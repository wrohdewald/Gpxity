#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.MMT` for http://www.mapmytracks.com

There are some problems with the server running at mapmytracks.com:
    * it is not possible to change an existing track - if the track changes, the
      track must be re-uploaded and gets a new track id This invalididates
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
    * downloading tracks with that abi is very slow and hangs forever for big tracks
      (at least this was so in Feb 2017, maybe have to test again occasionally).
    * not all parts of MMT data are supported like images (not interesting for me,
      at least not now).

"""

from xml.etree import ElementTree
import html
from html.parser import HTMLParser
import datetime
from collections import defaultdict

import requests

from .. import Backend, Track
from ..version import VERSION


__all__ = ['MMT']

def _convert_time(raw_time) ->datetime.datetime:
    """MMT uses Linux timestamps. Converts that into datetime

    Args:
        raw_time (int): The linux timestamp from the MMT server
    """
    return datetime.datetime.utcfromtimestamp(float(raw_time))


class ParseMMTCategories(HTMLParser): # pylint: disable=abstract-method

    """Parse the legal values for category from html"""

    def __init__(self):
        super(ParseMMTCategories, self).__init__()
        self.seeing_tracks = False
        self.result = ['Cycling'] # The default value

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        # pylint: disable=too-many-branches
        attributes = dict(attrs)
        if tag == 'select' and attributes['name'] == 'activity':
            self.seeing_tracks = True
        if self.seeing_tracks and tag == 'option':
            _ = attributes['value']
            if _ not in self.result:
                self.result.append(_)

    def handle_endtag(self, tag):
        if self.seeing_tracks and tag == 'select':
            self.seeing_tracks = False


class ParseMMTTrack(HTMLParser): # pylint: disable=abstract-method

    """get some attributes available only on the web page. Of course,
    this is highly unreliable. Just use what we can get."""

    result = dict()

    def __init__(self):
        super(ParseMMTTrack, self).__init__()
        self.seeing_category = False
        self.seeing_title = False
        self.seeing_description = False
        self.seeing_status = False
        self.seeing_tag = None
        self.result['mid'] = None
        self.result['title'] = None
        self.result['description'] = None
        self.result['category'] = None
        self.result['category_from_title'] = None
        self.result['category_3'] = None
        self.result['public'] = None
        self.result['tags'] = dict() # key: name, value: id

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        # pylint: disable=too-many-branches
        self.seeing_title = False
        self.seeing_description = False
        self.seeing_category = False
        self.seeing_status = False
        self.seeing_tag = None
        attributes = defaultdict(str)
        for key, value in attrs:
            attributes[key] = value
        if tag == 'input':
            value = attributes['value'].strip()
            if (attributes['id'] == 'activity_type' and attributes['type'] == 'hidden'
                    and attributes['name'] == 'activity_type' and value):
                self.result['category_3'] = value
            elif (attributes['id'] == 'mid' and attributes['type'] == 'hidden'
                  and attributes['name'] == 'mid'and value):
                self.result['mid'] = value
        elif tag == 'div' and attributes['class'] == 'panel' and 'data-activity' in attributes:
            self.result['category'] = attributes['data-activity']
        elif tag == 'span' and attributes['class'] == 'privacy-status':
            self.seeing_status = True
        elif tag == 'title':
            self.seeing_category = True
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
        if self.seeing_category:
            try:
                _ = data.split('|')[1].split('@')[0].strip()
                self.result['category_from_title'] = ' '.join(_.split(' ')[:-2])
            except BaseException:
                print('cannot parse', data)
                self.result['category_from_title'] = ''
        if self.seeing_status:
            self.result['public'] = data.strip() != 'Only you can see this activity'
        if self.seeing_tag:
            self.result['tags'][data.strip()] = self.seeing_tag


class MMTRawTrack:

    """raw data from mapmytracks.get_tracks"""

    # pylint: disable=too-few-public-methods
    def __init__(self, xml):
        self.track_id = xml.find('id').text
        self.title = html.unescape(xml.find('title').text)
        self.time = _convert_time(xml.find('date').text)
        self.category = html.unescape(xml.find('activity_type').text)
        self.distance = float(xml.find('distance').text)


class MMT(Backend):
    """The implementation for MapMyTracks.
    The track ident is the number given by MapMyTracks.

    MMT knows tags. We map :attr:`Track.keywords <gpxity.Track.keywords>` to MMT tags. MMT will
    change keywords: It converts the first character to upper case. See
    :attr:`Track.keywords <gpxity.Track.keywords>` for how Gpxity handles this.

    Args:
        url (str): The Url of the server. Default is http://mapmytracks.com
        auth (tuple(str, str)): Username and password
        cleanup (bool): If True, :meth:`~gpxity.Backend.destroy` will remove all tracks in the
            user account.
         timeout: If None, there are no timeouts: Gpxity waits forever. For legal values
            see http://docs.python-requests.org/en/master/user/advanced/#timeouts
    """

    # pylint: disable=abstract-method

   #  skip_test = True

    _default_description = 'None yet. Let everyone know how you got on.'

    _legal_categories = list()

    _category_encoding = {
        'Pedelec': 'Cycling',
        'Crossskating': 'Skating',
        'Handcycle': 'Cycling',
        'Motorhome': 'Driving',
        'Cabriolet': 'Driving',
        'Coach': 'Miscellaneous',
        'Pack animal trekking': 'Hiking',
        'Train': 'Miscellaneous',
        'Stand up paddle boarding': 'SUP boarding',
    }

    default_url = 'http://www.mapmytracks.com'

    def __init__(self, url=None, auth=None, cleanup=False, debug=False, timeout=None):
        if url is None:
            url = self.default_url
        super(MMT, self).__init__(url, auth, cleanup, debug, timeout)
        self.__mid = -1 # member id at MMT for auth
        self.__session = None
        self.__tag_ids = dict()  # key: tag name, value: tag id in MMT. It seems that MMT
            # has a lookup table and never deletes there. So a given tag will always get
            # the same ID. We use this fact.
            # MMT internally capitalizes tags but displays them lowercase.
        self._last_response = None # only used for debugging
        self._current_lifetrack = None

    @property
    def legal_categories(self):
        """
        Returns: list(str)
            all legal values for category."""
        if not self._legal_categories:
            response = self.session.post('{}/profile/upload/manual'.format(self.url), timeout=self.timeout)
            category_parser = ParseMMTCategories()
            category_parser.feed(response.text)
            self._legal_categories.extend(category_parser.result)
        return self._legal_categories

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

    def decode_category(self, value: str) ->str:
        """Translate the value from MMT into internal one.
        Since gpxity once decided to use MMT definitions for tracks, this should mostly be 1:1 here."""
        if value not in Track.legal_categories:
            raise self.BackendException('MMT gave us an unknown category={}'.format(value))
        return value

    def encode_category(self, value: str) ->str:
        """Translate internal value into MMT value"""
        if value in self.legal_categories:
            return value
        if value not in self._category_encoding:
            raise self.BackendException('MMT has no equivalent for {}'.format(value))
        return self._category_encoding[value]

    @property
    def mid(self):
        """the member id on MMT belonging to auth"""
        if self.__mid == -1:
            response = self.session.get(self.url)
            page_parser = ParseMMTTrack()
            page_parser.feed(response.text)
            self.__mid = page_parser.result['mid']
            self.__tag_ids.update(page_parser.result['tags'])
            self._check_tag_ids()
        return self.__mid

    @staticmethod
    def _encode_keyword(value):
        """mimics the changes MMT applies to tags"""
        return ' '.join(x.capitalize() for x in value.split())

    def _check_tag_ids(self):
        """Assert that all tags conform to what MMT likes"""
        for _ in self.__tag_ids:
            assert _[0].upper() == _[0], self.__tag_ids

    def _found_tag_id(self, tag, id_):
        """We just learned about a new tag id. They never change for a given string."""
        self.__tag_ids[self._encode_keyword(tag)] = id_
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
            return None
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

    def _write_attribute(self, track, attribute):
        """change an attribute directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        attr_value = getattr(track, attribute)
        if attribute == 'description' and attr_value == self._default_description:
            attr_value = ''
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>update_{attr}</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<{attr}>{value}</{attr}></message>'.format(
                attr=attribute,
                eid=track.id_in_backend,
                usrid=self.auth[0],
                value=attr_value,
                uid=self.session.cookies['exp_uniqueid'])
        self.__post(with_session=True, url='assets/php/interface.php', data=data, expect='success')

    def _write_title(self, track):
        """changes title on remote server"""
        self._write_attribute(track, 'title')

    def _write_description(self, track):
        """changes description on remote server"""
        self._write_attribute(track, 'description')

    def _write_public(self, track):
        """changes public/private on remote server"""
        self.__post(
            with_session=True, url='user-embeds/statuschange-track', expect='access granted',
            mid=self.mid, tid=track.id_in_backend,
            hash=self.session.cookies['exp_uniqueid'],
            status=1 if track.public else 2)
            # what a strange answer

    def _write_category(self, track):
        """change category directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        self.__post(
            with_session=True, url='handler/change_activity', expect='ok',
            eid=track.id_in_backend, activity=self.encode_category(track.category))

    def _current_keywords(self, track):
        """Read all current keywords (MMT tags).

        Returns:
            A sorted unique list"""
        page_scan = self._scan_track_page(track)
        return list(sorted(set(page_scan['tags'])))

    def _write_keywords(self, track):
        """Sync track keywords to MMT tags."""
        current_tags = self._current_keywords(track)
        new_tags = set(self._encode_keyword(x) for x in track.keywords)
        # This should really only remove unwanted tags and only add missing tags,
        # like #for remove_tag in current_tags-new_tags, for new_tag in new_tags-current_tags
        # but that does not work, see __remove_one_keyword
        for remove_tag in current_tags:
            self.__remove_one_keyword(track, remove_tag)
        self._write_add_keywords(track, ','.join(new_tags))

    def _write_add_keywords(self, track, value):
        """Add keyword as MMT tag. MMT allows adding several at once, comma separated,
        and we allow this too. But do not expect this to work with all backends."""
        if not value:
            return
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>add_tag</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<tagnames>{value}</tagnames></message>'.format(
                eid=track.id_in_backend,
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
                'MMT does not like some of your keywords: mmt ids={} your keywords={}  mmt tags={}'.format(
                    ids, values, tags))
        for key, id_ in zip(values, ids):
            self._found_tag_id(key, id_)

    def _write_remove_keyword(self, track, value):
        """Remove an MTT tag. This is flawed, see __remove_one_keyword, so
        we rewrite all keywords instead.
        """
        for remove_tag in track.keywords:
            self.__remove_one_keyword(track, remove_tag)
        # sort for reproducibility in tests
        self._write_add_keywords(track, ','.join(sorted(self._encode_keyword(x) for x in track.keywords)))

    def __remove_one_keyword(self, track, value):
        """Here I have a problem. This seems to do exactly what happens in a
        browser but MMT always removes the wrong tag. However it always
        **does** remove a tag, so we can still use this: Repeat calling it until
        all tags are gone and then redefine all wanted tags.
        Sadly, MMT never returns anything for this POST."""
        value = self._encode_keyword(value)
        if value not in self.__tag_ids:
            self.__tag_ids.update(self._scan_track_page(track)['tags'])
            self._check_tag_ids()
            if value not in self.__tag_ids:
                raise self.BackendException('{}: Cannot remove keyword {}, reason: not known'.format(self.url, value))
        self.__post(
            with_session=True, url='handler/delete-tag.php',
            tag_id=self.__tag_ids[value], entry_id=track.id_in_backend)

    def get_time(self) ->datetime.datetime:
        """get MMT server time"""
        return _convert_time(self.__post(request='get_time').find('server_time').text)

    def _yield_tracks(self):
        """get all tracks for this user."""

        while True:
            old_len = self.real_len()
            response = self.__post(
                request='get_activities', author=self.auth[0],
                offset=old_len)
            chunk = response.find('activities')
            if not chunk:
                return
            for _ in chunk:
                raw_data = MMTRawTrack(_)
                track = self._found_track(raw_data.track_id)
                # pylint: disable=protected-access
                track._header_data['title'] = raw_data.title
                track._header_data['category'] = self.decode_category(raw_data.category)
                track._header_data['time'] = raw_data.time
                track._header_data['distance'] = raw_data.distance
                yield track
            assert self.real_len() > old_len

    def _scan_track_page(self, track):
        """The MMT api does not deliver all attributes we want.
        This gets some more by scanning the web page and
        returns it in page_parser.result"""
        response = self.session.get('{}/explore/activity/{}'.format(
            self.url, track.id_in_backend))
        page_parser = ParseMMTTrack()
        page_parser.feed(response.text)
        return page_parser.result

    def _use_webpage_results(self, track):
        """if the title has not been set, get_activities says something like "Track 2016-09-04 ..."
            while the home page says "Cycling activity". We prefer the value from the home page
            and silently ignore this inconsistency.
         """
        page_scan = self._scan_track_page(track)
        if page_scan['title']:
            track.title = page_scan['title']
        if page_scan['description']:
            _ = page_scan['description']
            if _ == self._default_description:
                _ = ''
            track.description = _
        if page_scan['tags']:
            track.keywords = page_scan['tags'].keys()
        # MMT sends different values of the current track type, hopefully category_3 is always the
        # correct one.
        if page_scan['category_3']:
            track.category = self.decode_category(page_scan['category_3'])
        if page_scan['public'] is not None:
            track.public = page_scan['public']

    def _read_all(self, track):
        """get the entire track"""
        session = self.session
        if session is None:
            # https access not implemented for TrackMMT
            return
        response = session.get('{}/assets/php/gpx.php?tid={}&mid={}&uid={}'.format(
            self.url, track.id_in_backend, self.mid, self.session.cookies['exp_uniqueid']))
            # some tracks download only a few points if mid/uid are not given, but I
            # have not been able to write a unittest triggering that ...
        track.parse(response.text)
        # but this does not give us track type and other things,
        # get them from the web page.
        self._use_webpage_results(track)

    def _remove_ident(self, ident: str):
        """remove on the server"""
        self.__post(
            with_session=True, url='handler/delete_track', expect='access granted',
            tid=ident, hash=self.session.cookies['exp_uniqueid'])

    def _write_all(self, track) ->str:
        """save full gpx track on the MMT server.
        We must upload the title separately.

        Returns:
            The new id_in_backend
        """
        if not track.gpx.get_track_points_no():
            raise self.BackendException('MMT does not accept a track without trackpoints:{}'.format(track))
        response = self.__post(
            request='upload_activity', gpx_file=track.to_xml(),
            status='public' if track.public else 'private',
            description=track.description, activity=self.encode_category(track.category))
        new_ident = response.find('id').text
        if not new_ident:
            raise self.BackendException('No id found in response')
        old_ident = track.id_in_backend
        track.id_in_backend = new_ident
        # the caller will do the above too, never mind
        if '_write_title' in self.supported:
            self._write_title(track)
        # MMT can add several keywords at once
        if track.keywords and '_write_add_keywords' in self.supported:
            self._write_add_keywords(track, ','.join(self._encode_keyword(x) for x in track.keywords))
        if old_ident:
            self._remove_ident(old_ident)
        track.id_in_backend = new_ident
        return new_ident

    @staticmethod
    def __formatted_lifetrack_points(points):
        """formats points for life tracking"""
        _ = list()
        for point in points:
            _.append('{} {} {} {}'.format(
                point.latitude,
                point.longitude,
                point.elevation if point.elevation is not None else 0,
                point.time.timestamp()))
        return ' '.join(_)

    def _lifetrack(self, track, points):
        """Supports only one track per account. We ensure that only
        one track is tracked by this backend instance, you have to
        make sure there are no other processes interfering. The MMT
        API does not help you with that.

        points are not yet added to track."
        """
        if points is None:
            if self._current_lifetrack:
                self.__post(request='stop_activity')
                self._current_lifetrack = None
            return
        if not self._current_lifetrack:
            result = self.__post(
                request='start_activity',
                title=track.title,
                privacy='public' if track.public else 'private',
                activity=self.encode_category(track.category),
                points=self.__formatted_lifetrack_points(track.points()),
                source='Gpxity',
                version=VERSION,
                # tags='TODO',
                unique_token='{}'.format(id(track)))
            if result.find('type').text != 'activity_started':
                raise self.BackendException('activity_started failed')
            track.id_in_backend = result.find('activity_id').text
            self._current_lifetrack = track
        if track != self._current_lifetrack:
            raise self.BackendException('MMT._lifetrack() got wrong track')
        self.__post(
            request='update_activity', activity_id=track.id_in_backend,
            points=self.__formatted_lifetrack_points(points))

    def destroy(self):
        """also close session"""
        super(MMT, self).destroy()
        if self.session:
            self.session.close()

MMT._define_support() # pylint: disable=protected-access
