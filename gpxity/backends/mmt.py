#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.MMT` for http://www.mapmytracks.com

There are some problems with the server running at mapmytracks.com:
    * it is not possible to change an existing activity - if the track changes, the
      activity must be re-uploaded and gets a new activity id This invalididates
      references held by other backend instances (maybe on other clients).
      But I could imagine that most similar services have this problem too.
    * does not support GPX very well beyond track data. One problem is that
      it does not support gpx.time, it ignores it in uploads and uses the time
      of the earliest trackpoint. To be consistent, Gpxity follows that for now
      and does not respect gpx.time either.
    * there is an official description of an API at https://github.com/MapMyTracks
      but this does not implement everything needed. For the missing parts we
      simulate what a web browser would do, see :meth:`MMT._read_all` and
      :meth:`MMT._write_attribute`. Of course that could fail if MMT changes its site.
      Which is true for the api itself, it can and does get incompatible changes at
      any time without notice to users or deprecation periods.
    * downloading activities with that abi is very slow and hangs forever for big activities
      (at least this was so in Feb 2017, maybe have to test again occasionally).
    * not all parts of MMT data are supported like images (not interesting for me,
      at least not now).

"""

from xml.etree import ElementTree
import html
from html.parser import HTMLParser
import datetime
from collections import defaultdict
from contextlib import contextmanager

import requests

from .. import Backend, Activity
from ..util import VERSION


__all__ = ['MMT']

def _convert_time(raw_time) ->datetime.datetime:
    """MMT uses Linux timestamps. Converts that into datetime

    Args:
        raw_time (int): The linux timestamp from the MMT server
    """
    return datetime.datetime.utcfromtimestamp(float(raw_time))


class ParseMMTWhats(HTMLParser): # pylint: disable=abstract-method

    """Parse the legal values for what from html"""

    def __init__(self):
        super(ParseMMTWhats, self).__init__()
        self.seeing_activities = False
        self.result = ['Cycling'] # The default value

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        # pylint: disable=too-many-branches
        attributes = dict(attrs)
        if tag == 'select' and attributes['name'] == 'activity':
            self.seeing_activities = True
        if self.seeing_activities and tag == 'option':
            _ = attributes['value']
            if _ not in self.result:
                self.result.append(_)

    def handle_endtag(self, tag):
        if self.seeing_activities and tag == 'select':
            self.seeing_activities = False


class ParseMMTActivity(HTMLParser): # pylint: disable=abstract-method

    """get some attributes available only on the web page. Of course,
    this is highly unreliable. Just use what we can get."""

    result = dict()

    def __init__(self):
        super(ParseMMTActivity, self).__init__()
        self.seeing_what = False
        self.seeing_title = False
        self.seeing_description = False
        self.seeing_status = False
        self.seeing_tag = None
        self.result['mid'] = None
        self.result['title'] = None
        self.result['description'] = None
        self.result['what'] = None
        self.result['what_from_title'] = None
        self.result['what_3'] = None
        self.result['public'] = None
        self.result['tags'] = dict() # key: name, value: id

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        # pylint: disable=too-many-branches
        self.seeing_title = False
        self.seeing_description = False
        self.seeing_what = False
        self.seeing_status = False
        self.seeing_tag = None
        attributes = defaultdict(str)
        for key, value in attrs:
            attributes[key] = value
        if tag == 'input':
            value = attributes['value'].strip()
            if (attributes['id'] == 'activity_type' and attributes['type'] == 'hidden'
                    and attributes['name'] == 'activity_type' and value):
                self.result['what_3'] = value
            elif (attributes['id'] == 'mid' and attributes['type'] == 'hidden'
                  and attributes['name'] == 'mid'and value):
                self.result['mid'] = value
        elif tag == 'div' and attributes['class'] == 'panel' and 'data-activity' in attributes:
            self.result['what'] = attributes['data-activity']
        elif tag == 'span' and attributes['class'] == 'privacy-status':
            self.seeing_status = True
        elif tag == 'title':
            self.seeing_what = True
        elif tag == 'h2' and attributes['id'] == 'track-title':
            self.seeing_title = True
        elif tag == 'p' and attributes['id'] == 'track-desc':
            self.seeing_description = True
        elif tag == 'a' and attributes['class'] == 'tag-link' and  attributes['rel'] == 'tag':
            assert attributes['id'].startswith('tag-')
            self.seeing_tag = attributes['id'].split('-')[2]

    def handle_data(self, data):
        """data from the parser"""
        if not data.strip():
            return
        if self.seeing_title:
            self.result['title'] = data.strip()
        if self.seeing_description:
            self.result['description'] = data.strip()
        if self.seeing_what:
            try:
                _ = data.split('|')[1].split('@')[0].strip()
                self.result['what_from_title'] = ' '.join(_.split(' ')[:-2])
            except BaseException:
                print('cannot parse', data)
                self.result['what_from_title'] = ''
        if self.seeing_status:
            self.result['public'] = data.strip() != 'Only you can see this activity'
        if self.seeing_tag:
            self.result['tags'][data.strip()] = self.seeing_tag


class MMTRawActivity:

    """raw data from mapmytracks.get_activities"""

    # pylint: disable=too-few-public-methods
    def __init__(self, xml):
        self.activity_id = xml.find('id').text
        self.title = html.unescape(xml.find('title').text)
        self.time = _convert_time(xml.find('date').text)
        self.what = html.unescape(xml.find('activity_type').text)
        self.distance = float(xml.find('distance').text)


class MMT(Backend):
    """The implementation for MapMyTracks.
    The activity ident is the number given by MapMyTracks.

    MMT knows tags. We map :attr:`Activity.keywords <gpxity.Activity.keywords>` to MMT tags. MMT will
    change keywords: It converts the first character to upper case. See
    :attr:`Activity.keywords <gpxity.Activity.keywords>` for how Gpxity handles this.

    Args:
        url (str): The Url of the server. Default is http://mapmytracks.com
        auth (tuple(str, str)): Username and password
        cleanup (bool): If True, :meth:`~gpxity.Backend.destroy` will remove all activities in the
            user account.
         timeout: If None, there are no timeouts: Gpxity waits forever. For legal values
            see http://docs.python-requests.org/en/master/user/advanced/#timeouts
    """

    # pylint: disable=abstract-method

   #  skip_test = True

    _default_description = 'None yet. Let everyone know how you got on.'

    _legal_whats = list()

    _what_encoding = {
        'Pedelec': 'Cycling',
        'Crossskating': 'Skating',
        'Handcycle': 'Cycling',
        'Motorhome': 'Driving',
        'Cabriolet': 'Driving',
        'Coach': 'Miscellaneous',
        'Pack animal trekking': 'Hiking',
        'Train': 'Miscellaneous'
    }

    def __init__(self, url=None, auth=None, cleanup=False, debug=False, timeout=None):
        if url is None:
            url = 'http://www.mapmytracks.com'
        super(MMT, self).__init__(url, auth, cleanup, debug, timeout)
        self.__mid = -1 # member id at MMT for auth
        self.__session = None
        self.__tag_ids = dict()  # key: tag name, value: tag id in MMT. It seems that MMT
            # has a lookup table and never deletes there. So a given tag will always get
            # the same ID. We use this fact.
            # MMT internally capitalizes tags but displays them lowercase.
        self._last_response = None # only used for debugging
        self._tracking_activity = None
        self.__overriding_ident = None

    @property
    def legal_whats(self):
        """
        Returns: list(str)
            all legal values for what."""
        if not self._legal_whats:
            response = self.session.post('{}/profile/upload/manual'.format(self.url), timeout=self.timeout)
            whats_parser = ParseMMTWhats()
            whats_parser.feed(response.text)
            self._legal_whats.extend(whats_parser.result)
        return self._legal_whats

    @property
    def session(self):
        """The requests.Session for this backend. Only initialized once."""
        if self.__session is None:
            if not self.auth:
                raise self.BackendException('{}: Needs authentication data'.format(self.url))
            self.__session = requests.Session()
            # I have no idea what ACT=9 does but it seems to be needed
            payload = {'username': self.auth[0], 'password': self.auth[1], 'ACT':'9'}
            base_url = self.url.replace('http:', 'https:')
            login_url = '{}/login'.format(base_url)
            response = self.__session.post(login_url, data=payload, timeout=self.timeout)
            if not 'You are now logged in.' in response.text:
                raise self.BackendException('Login as {} failed'.format(self.auth[0]))
        return self.__session

    def decode_what(self, value: str) ->str:
        """Translate the value from MMT into internal one.
        Since gpxity once decided to use MMT definitions for activities, this should mostly be 1:1 here."""
        if value not in Activity.legal_whats:
            raise self.BackendException('MMT gave us an unknown what={}'.format(value))
        return value

    def encode_what(self, value: str) ->str:
        """Translate internal value into MMT value"""
        if value in self.legal_whats:
            return value
        if value not in self._what_encoding:
            raise self.BackendException('MMT has no equivalent for {}'.format(value))
        return self._what_encoding[value]

    @property
    def mid(self):
        """the member id on MMT belonging to auth"""
        if self.__mid == -1:
            response = self.session.get(self.url)
            page_parser = ParseMMTActivity()
            page_parser.feed(response.text)
            self.__mid = page_parser.result['mid']
            self.__tag_ids.update(page_parser.result['tags'])
            self._check_tag_ids()
        return self.__mid

    @staticmethod
    def _kw_to_tag(value):
        """mimics the changes MMT applies to tags"""
        return value[0].upper() + value[1:]

    def _check_tag_ids(self):
        """Assert that all tags conform to what MMT likes"""
        for _ in self.__tag_ids:
            assert _[0].upper() == _[0], self.__tag_ids

    def _found_tag_id(self, tag, id_):
        """We just learned about a new tag id. They never change for a given string."""
        self.__tag_ids[self._kw_to_tag(tag)] = id_
        self._check_tag_ids()

    def __post(self, with_session: bool = False, url: str = None, data: str = None, expect: str = None, **kwargs):
        """Helper for the real function with some error handling.

        Args:
            with_session: If given, use self.session. Otherwise, use basic auth.
            url:  Will be appended to self.url. Default is api/. For the basic url, pass an empty  string.
            data: should be xml and will be encoded. May be None.
            expect: If given, raise an error if this string is not part of the server answer.
            kwargs: a dict for post(). May be None. data and kwargs must not both be passed.
        """
        if url is None:
            url = 'api/'
        full_url = self.url + url
        headers = {'DNT': '1'} # do not track
        if data:
            data = data.encode('ascii', 'xmlcharrefreplace')
        else:
            data = kwargs
        try:
            if with_session:
                response = self.session.post(full_url, data=data, headers=headers, timeout=self.timeout)
            else:
                response = requests.post(full_url, data=data, headers=headers, auth=self.auth, timeout=self.timeout)
        except requests.exceptions.ReadTimeout:
            print('timeout for', data)
            raise
        self._last_response = response # for debugging
        if response.status_code != requests.codes.ok: # pylint: disable=no-member
            self.__handle_post_error(full_url, data, response)
            return
        result = response.text
        if (result == 'access denied') or (expect and expect not in result):
            raise self.BackendException('{}: expected {} in {}'.format(data, expect, result))
        if result.startswith('<?xml'):
            try:
                result = ElementTree.fromstring(result)
            except ElementTree.ParseError:
                raise self.BackendException('POST {} has parse error: {}'.format(data, response.text))
            result_type = result.find('type')
            if result_type is not None and result_type.text == 'error':
                reason = result.find('reason').text if result.find('reason') else 'no reason given'
                raise self.BackendException('{}: {}'.format(data, reason))
        return result

    @classmethod
    def __handle_post_error(cls, url, data, result):
        """we got status_code != ok"""
        try:
            result.raise_for_status()
        except BaseException as exc:
            if 'request' in data:
                _ = data['request']
            else:
                _ = data
            raise cls.BackendException('{}: {} {} {}'.format(exc, url, _, result.text))

    def _write_attribute(self, activity, attribute):
        """change an attribute directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        attr_value = getattr(activity, attribute)
        if attribute == 'description' and attr_value == self._default_description:
            attr_value = ''
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>update_{attr}</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<{attr}>{value}</{attr}></message>'.format(
                attr=attribute,
                eid=self.__overriding_ident or activity.id_in_backend,
                usrid=self.auth[0],
                value=attr_value,
                uid=self.session.cookies['exp_uniqueid'])
        self.__post(with_session=True, url='assets/php/interface.php', data=data, expect='success')

    def _write_title(self, activity):
        """changes title on remote server"""
        self._write_attribute(activity, 'title')

    def _write_description(self, activity):
        """changes description on remote server"""
        self._write_attribute(activity, 'description')

    def _write_public(self, activity):
        """changes public/private on remote server"""
        self.__post(
            with_session=True, url='user-embeds/statuschange-track', expect='access granted',
            mid=self.mid, tid=self.__overriding_ident or activity.id_in_backend,
            hash=self.session.cookies['exp_uniqueid'],
            status=1 if activity.public else 2)
            # what a strange answer

    def _write_what(self, activity):
        """change what directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        self.__post(
            with_session=True, url='handler/change_activity', expect='ok',
            eid=self.__overriding_ident or activity.id_in_backend, activity=self.encode_what(activity.what))

    def _current_keywords(self, activity):
        """Read all current keywords (MMT tags).

        Returns:
            A sorted unique list"""
        page_scan = self._scan_activity_page(activity)
        return list(sorted(set(page_scan['tags'])))

    def _write_keywords(self, activity):
        """Sync activity keywords to MMT tags."""
        current_tags = self._current_keywords(activity)
        new_tags = set(self._kw_to_tag(x) for x in activity.keywords)
        # This should really only remove unwanted tags and only add missing tags,
        # like #for remove_tag in current_tags-new_tags, for new_tag in new_tags-current_tags
        # but that does not work, see __remove_one_keyword
        for remove_tag in current_tags:
            self.__remove_one_keyword(activity, remove_tag)
        self._write_add_keyword(activity, ','.join(new_tags))

    def _write_add_keyword(self, activity, value):
        """Add keyword as MMT tag. MMT allows adding several at once, comma separated,
        and we allow this too. But do not expect this to work with all backends."""
        if not value:
            return
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>add_tag</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<tagnames>{value}</tagnames></message>'.format(
                eid=self.__overriding_ident or activity.id_in_backend,
                usrid=self.auth[0],
                value=value,
                uid=self.session.cookies['exp_uniqueid'])
        text = self.__post(with_session=True, url='assets/php/interface.php', data=data, expect='success')
        # unclear: when do we get id and/or tag? One answer was
        # <tags>B2</tags><ids>232325,16069</ids>
        # for the request <tagnames>B2,Berlin</tagnames>
        ids = (text.find('ids').text or '').split(',')
        values = value.split(',')
        tags = (text.find('tags').text or '').split(',')
        if values != tags or len(ids) != len(values):
            raise self.BackendException(
                'MMT gives us strange tag values: ids={} values={} tags={}'.format(ids, values, tags))
        for key, id_ in zip(values, ids):
            self._found_tag_id(key, id_)

    def _write_remove_keyword(self, activity, value):
        """Remove an MTT tag. This is flawed, see __remove_one_keyword, so
        we rewrite all keywords instead.
        """
        # Our list of keywords may not be current, reload it
   #     activity.keywords = set(self._current_keywords(activity)) - set([value])
        # activity.keywords is assumed to be current (see Activity.remove_keyword())
        for remove_tag in activity.keywords:
            self.__remove_one_keyword(activity, remove_tag)
        self.__remove_one_keyword(activity, value)
        # sort for reproducibility in tests
        self._write_add_keyword(activity, ','.join(sorted(activity.keywords)))

    def __remove_one_keyword(self, activity, value):
        """Here I have a problem. This seems to do exactly what happens in a
        browser but MMT always removes the wrong tag. However it always
        **does** remove a tag, so we can still use this: Repeat calling it until
        all tags are gone and then redefine all wanted tags.
        Sadly, MMT never returns anything for this POST."""
        value = self._kw_to_tag(value)
        if value not in self.__tag_ids:
            self.__tag_ids.update(self._scan_activity_page(activity)['tags'])
            self._check_tag_ids()
            if value not in self.__tag_ids:
                raise self.BackendException('{}: Cannot remove keyword {}, reason: not known'.format(self.url, value))
        self.__post(
            with_session=True, url='handler/delete-tag.php',
            tag_id=self.__tag_ids[value], entry_id=self.__overriding_ident or activity.id_in_backend)

    def get_time(self) ->datetime.datetime:
        """get MMT server time"""
        return _convert_time(self.__post(request='get_time').find('server_time').text)

    def _yield_activities(self):
        """get all activities for this user. If we do not use the generator
        created by yield_activity, unittest fails. Why?"""

        while True:
            old_len = self.real_len()
            response = self.__post(
                request='get_activities', author=self.auth[0],
                offset=old_len)
            chunk = response.find('activities')
            if not chunk:
                return
            for _ in chunk:
                raw_data = MMTRawActivity(_)
                activity = self._found_activity(raw_data.activity_id)
                activity.header_data['title'] = raw_data.title
                activity.header_data['what'] = self.decode_what(raw_data.what)
                activity.header_data['time'] = raw_data.time
                activity.header_data['distance'] = raw_data.distance
                yield activity
            assert self.real_len() > old_len

    def _scan_activity_page(self, activity):
        """The MMT api does not deliver all attributes we want.
        This gets some more by scanning the web page and
        returns it in page_parser.result"""
        response = self.session.get('{}/explore/activity/{}'.format(
            self.url, activity.id_in_backend))
        page_parser = ParseMMTActivity()
        page_parser.feed(response.text)
        return page_parser.result

    def _use_webpage_results(self, activity):
        """if the title has not been set, get_activities says something like "Activity 2016-09-04 ..."
            while the home page says "Cycling activity". We prefer the value from the home page
            and silently ignore this inconsistency.
         """
        page_scan = self._scan_activity_page(activity)
        if page_scan['title']:
            activity.title = page_scan['title']
        if page_scan['description']:
            _ = page_scan['description']
            if _ == self._default_description:
                _ = ''
            activity.description = _
        if page_scan['tags']:
            activity.keywords = page_scan['tags'].keys()
        # MMT sends different values of the current activity type, hopefully what_3 is always the
        # correct one.
        if page_scan['what_3']:
            activity.what = self.decode_what(page_scan['what_3'])
        if page_scan['public'] is not None:
            activity.public = page_scan['public']

    def _read_all(self, activity):
        """get the entire activity"""
        session = self.session
        if session is None:
            # https access not implemented for TrackMMT
            return
        response = session.get('{}/assets/php/gpx.php?tid={}&mid={}&uid={}'.format(
            self.url, activity.id_in_backend, self.mid, self.session.cookies['exp_uniqueid']))
            # some activities download only a few points if mid/uid are not given, but I
            # have not been able to write a unittest triggering that ...
        activity.parse(response.text)
        # but this does not give us activity type and other things,
        # get them from the web page.
        self._use_webpage_results(activity)

    def _remove_activity(self, activity):
        """remove on the server"""
        self.__post(
            with_session=True, url='handler/delete_track', expect='access granted',
            tid=activity.id_in_backend, hash=self.session.cookies['exp_uniqueid'])

    @contextmanager
    def override_ident(self, ident: str):
        """Temporarily override the activity ident. While this is active,
        only the one activity meant must be used."""
        try:
            self.__overriding_ident = ident
            yield
        finally:
            self.__overriding_ident = None

    def _write_all(self, activity) ->str:
        """save full gpx track on the MMT server.
        We must upload the title separately.

        Returns:
            The new id_in_backend
        """
        result = None
        if not activity.gpx.get_track_points_no():
            raise self.BackendException('MMT does not accept an activity without trackpoints:{}'.format(activity))
        response = self.__post(
            request='upload_activity', gpx_file=activity.to_xml(),
            status='public' if activity.public else 'private',
            description=activity.description, activity=self.encode_what(activity.what))
        result = response.find('id').text
        with self.override_ident(result):
            if '_write_title' in self.supported:
                self._write_title(activity)
            # MMT can add several keywords at once
            if activity.keywords and '_write_add_keyword' in self.supported:
                self._write_add_keyword(activity, ','.join(activity.keywords))
        return result

    @staticmethod
    def __track_points(points):
        """formats points for life tracking"""
        _ = list()
        for point in points:
            _.append('{} {} {} {}'.format(
                point.latitude,
                point.longitude,
                point.elevation if point.elevation is not None else 0,
                point.time.timestamp()))
        return ' '.join(_)

    def _track(self, activity, points):
        """Supports only one activity per account. We ensure that only
        one activity is tracked by this backend instance, you have to
        make sure there are no other processes interfering. The MMT
        API does not help you with that.

        points are not yet added to activity."
        """
        if points is None:
            if self._tracking_activity:
                self.__post(request='stop_activity')
                self._tracking_activity = None
            return
        if not self._tracking_activity:
            result = self.__post(
                request='start_activity',
                title=activity.title,
                privacy='public' if activity.public else 'private',
                activity=self.encode_what(activity.what),
                points=self.__track_points(activity.points()),
                source='Gpxity',
                version=VERSION,
                # tags='TODO',
                unique_token='{}'.format(id(activity)))
            if result.find('type').text != 'activity_started':
                raise self.BackendException('activity_started failed')
            activity.id_in_backend = result.find('activity_id').text
            self._tracking_activity = activity
            self.append(activity)
        if activity != self._tracking_activity:
            raise self.BackendException('MMT._track() got wrong activity')
        self.__post(
            request='update_activity', activity_id=activity.id_in_backend,
            points=self.__track_points(points))

    def destroy(self):
        """also close session"""
        super(MMT, self).destroy()
        if self.session:
            self.session.close()

MMT._define_support() # pylint: disable=protected-access
