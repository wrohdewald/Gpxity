#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.mmt.MMT` for http://www.mapmytracks.com.

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

# pylint: disable=protected-access

# TODO: logout

from xml.etree import ElementTree
import html
from html.parser import HTMLParser
import datetime
import calendar
from collections import defaultdict
import requests

from .. import Backend, Track
from ..version import VERSION


__all__ = ['MMT']


def _convert_time(raw_time) ->datetime.datetime:
    """MMT uses Linux timestamps. Converts that into datetime.

    Args:
        raw_time (int): The linux timestamp from the MMT server

    Returns:
        The datetime

    """
    return datetime.datetime.utcfromtimestamp(float(raw_time))


class ParseMMTCategories(HTMLParser):  # pylint: disable=abstract-method

    """Parse the legal values for category from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseMMTCategories, self).__init__()
        self.seeing_category = False
        self.result = ['Cycling']  # The default value

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        # pylint: disable=too-many-branches
        attributes = dict(attrs)
        self.seeing_category = (
            tag == 'input' and 'name' in attributes and attributes['name'].startswith('add-activity'))

    def handle_data(self, data):
        """handle the data."""
        if self.seeing_category:
            _ = data.strip()
            if _ not in self.result:
                self.result.append(_)
            self.seeing_category = False


class ParseMMTTrack(HTMLParser):  # pylint: disable=abstract-method

    """get some attributes available only on the web page.

    Of course, this is highly unreliable. Just use what we can get."""

    result = dict()

    def __init__(self, backend):
        """See class docstring."""
        super(ParseMMTTrack, self).__init__()
        self.backend = backend
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
        self.result['tags'] = dict()  # key: name, value: id

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
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
                    and attributes['name'] == 'activity_type' and value):  # noqa
                self.result['category_3'] = value
            elif (attributes['id'] == 'mid' and attributes['type'] == 'hidden'
                  and attributes['name'] == 'mid'and value):  # noqa
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
        elif tag == 'a' and attributes['class'] == 'tag-link' and attributes['rel'] == 'tag':
            assert attributes['id'].startswith('tag-')
            self.seeing_tag = attributes['id'].split('-')[2]

    def handle_data(self, data):
        """data from the parser."""
        if not data.strip():
            return
        if self.seeing_title:
            self.result['title'] = data.strip()
        if self.seeing_description:
            self.result['description'] = html.unescape(data.strip())
        if self.seeing_category:
            try:
                _ = data.split('|')[1].split('@')[0].strip()
                self.result['category_from_title'] = ' '.join(_.split(' ')[:-2])
            except BaseException:
                self.backend.logger.warning('%s: Cannot parse %s', self.backend, data)
                self.result['category_from_title'] = ''
        if self.seeing_status:
            self.result['public'] = data.strip() != 'Only you can see this activity'
        if self.seeing_tag:
            self.result['tags'][data.strip()] = self.seeing_tag


class MMTRawTrack:

    """raw data from mapmytracks.get_tracks."""

    # pylint: disable=too-few-public-methods
    def __init__(self, xml):
        """See class docstring."""
        self.track_id = xml.find('id').text
        self.title = html.unescape(xml.find('title').text)
        self.time = _convert_time(xml.find('date').text)
        self.category = html.unescape(xml.find('activity_type').text)
        self.distance = float(xml.find('distance').text)


class MMT(Backend):

    """The implementation for MapMyTracks.

    The track ident is the number given by MapMyTracks.

    MMT knows tags. We map :attr:`Track.keywords <gpxity.track.Track.keywords>` to MMT tags. MMT will
    change keywords: It converts the first character to upper case. See
    :attr:`Track.keywords <gpxity.track.Track.keywords>` for how Gpxity handles this.

    Args:
        url (str): The Url of the server. Default is http://mapmytracks.com
        auth (tuple(str, str)): Username and password
        cleanup (bool): If True, :meth:`~gpxity.backend.Backend.destroy` will remove all tracks in the
            user account.
         timeout: If None, there are no timeouts: Gpxity waits forever. For legal values
            see http://docs.python-requests.org/en/master/user/advanced/#timeouts

    """

    # pylint: disable=abstract-method

    _default_description = 'None yet. Let everyone know how you got on.'

    legal_categories = (
        'Cycling', 'Running', 'Mountain biking', 'Sailing', 'Walking', 'Hiking',
        'Driving', 'Off road driving', 'Motor racing', 'Motorcycling', 'Enduro',
        'Skiing', 'Cross country skiing', 'Canoeing', 'Kayaking', 'Sea kayaking',
        'SUP boarding', 'Rowing', 'Swimming', 'Windsurfing', 'Orienteering',
        'Mountaineering', 'Skating', 'Horse riding', 'Hang gliding', 'Hand cycling',
        'Gliding', 'Flying', 'Kiteboarding', 'Snowboarding', 'Paragliding',
        'Hot air ballooning', 'Nordic walking', 'Miscellaneous', 'Skateboarding',
        'Snowshoeing', 'Jet skiing', 'Powerboating', 'Wheelchair', 'Indoor cycling')

    _category_encoding = {
        'Cabriolet': 'Driving',
        'Coach': 'Miscellaneous',
        'Crossskating': 'Skating',
        'Handcycle': 'Cycling',
        'Motorhome': 'Driving',
        'Pack animal trekking': 'Hiking',
        'Pedelec': 'Cycling',
        'Stand up paddle boarding': 'SUP boarding',
        'Train': 'Miscellaneous',
    }

    default_url = 'http://www.mapmytracks.com'

    # MMT only accepts one simultaneous lifetracker per login. We make sure
    # that at least this process does not try to run several at once.
    # This check is now too strict: We forbid multiple lifetrackers even if
    # every MMT account only gets one.
    _current_lifetrack = None

    def __init__(self, url=None, auth=None, cleanup=False, timeout=None):
        """See class docstring."""
        if url is None:
            url = self.default_url
        super(MMT, self).__init__(url, auth, cleanup, timeout)
        self.__mid = -1  # member id at MMT for auth
        self.__is_free_account = None
        self.__tag_ids = dict()  # key: tag name, value: tag id in MMT. It seems that MMT
        # has a lookup table and never deletes there. So a given tag will always get
        # the same ID. We use this fact.
        # MMT internally capitalizes tags but displays them lowercase.
        self._last_response = None  # only used for debugging
        self.https_url = self.url.replace('http:', 'https:')

    def _download_legal_categories(self):
        """Needed only for unittest.

        Returns: list(str)
            all legal values for category.

        """
        response = requests.get(self.url + '/explore/wall', timeout=self.timeout)
        category_parser = ParseMMTCategories()
        category_parser.feed(response.text)
        return sorted(category_parser.result)

    @property
    def session(self):
        """The requests.Session for this backend. Only initialized once.

        Returns:
                The session

        """
        ident = str(self)
        if ident not in self._session:
            self._session[ident] = requests.Session()
            # I have no idea what ACT=9 does but it seems to be needed
            payload = {'username': self.config.username, 'password': self.config.password, 'ACT': '9'}
            login_url = '{}/login'.format(self.https_url)
            response = self._session[ident].post(
                login_url, data=payload, timeout=self.timeout)
            if 'You are now logged in.' not in response.text:
                raise self.BackendException('Login as {} / {} failed, I got {}'.format(
                    self.config.username, self.config.password, response.text))
            cookies = requests.utils.dict_from_cookiejar(self._session[ident].cookies)
            self._session[ident].cookies = requests.utils.cookiejar_from_dict(cookies)
        return self._session[ident]

    def decode_category(self, value: str) ->str:
        """Translate the value from MMT into internal one.

        Since gpxity once decided to use MMT definitions for tracks, this should mostly be 1:1 here.

        Returns:
            the decoded value

        """
        if value not in Track.legal_categories:
            raise self.BackendException('MMT gave us an unknown category={}'.format(value))
        return value

    def encode_category(self, value: str) ->str:
        """Translate internal value into MMT value.

        Returns:
            the translated value

        """
        if value in self.legal_categories:
            return value
        if value not in self._category_encoding:
            raise self.BackendException('MMT has no equivalent for {}'.format(value))
        return self._category_encoding[value]

    @property
    def mid(self):
        """the member id on MMT belonging to auth.

        Returns:
            The mid

        """
        if self.__mid == -1:
            self._parse_homepage()
        return self.__mid

    @property
    def is_free_account(self):
        """Return True if the current account is not PLUS enabled."""
        if self.__is_free_account is None:
            self._parse_homepage()
        return self.__is_free_account

    def _parse_homepage(self):
        """Get some interesting values from the home page."""
        response = self.session.get(self.url)
        self.__is_free_account = 'href="/plus">Upgrade to PLUS' in response.text
        page_parser = ParseMMTTrack(self)
        page_parser.feed(response.text)
        self.__mid = page_parser.result['mid']
        self.__tag_ids.update(page_parser.result['tags'])
        self._check_tag_ids()

    @staticmethod
    def _encode_keyword(value):
        """mimic the changes MMT applies to tags.

        Returns:
            The changed keywords

        """
        return ' '.join(x.capitalize() for x in value.split())

    def _check_tag_ids(self):
        """Assert that all tags conform to what MMT likes."""
        for _ in self.__tag_ids:
            assert _[0].upper() == _[0], self.__tag_ids

    def _found_tag_id(self, tag, id_):
        """We just learned about a new tag id. They never change for a given string."""
        self.__tag_ids[tag] = id_
        self._check_tag_ids()

    def __post(  # noqa
            self, with_session: bool = False, url: str = None, data: str = None, expect: str = None, **kwargs) ->str:
        """Helper for the real function with some error handling.

        Args:
            with_session: If given, use self.session. Otherwise, use basic auth.
            url:  Will be appended to self.url. Default is api/. For the basic url, pass an empty  string.
            data: should be xml and will be encoded. May be None.
            expect: If given, raise an error if this string is not part of the server answer.
            kwargs: a dict for post(). May be None. data and kwargs must not both be passed.

        Returns:
            the result

        """
        full_url = self.url + '/' + (url if url else '')
        headers = {'DNT': '1'}  # do not track
        if not self.config.username or not self.config.password:
            raise self.BackendException('{}: Needs authentication data'.format(self.url))
        if data:
            data = data.encode('ascii', 'xmlcharrefreplace')
        else:
            data = kwargs
        try:
            if with_session:
                response = self.session.post(
                    full_url, data=data, headers=headers, timeout=self.timeout)
            else:
                response = requests.post(
                    full_url, data=data, headers=headers,
                    auth=(self.config.username, self.config.password), timeout=self.timeout)
        except requests.exceptions.ReadTimeout:
            self.logger.error('%s: timeout for %s', self, data)
            raise
        self._last_response = response  # for debugging
        if response.status_code != requests.codes.ok:  # pylint: disable=no-member
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
        """we got status_code != ok."""
        try:
            result.raise_for_status()
        except BaseException as exc:
            if isinstance(data, str) and 'request' in data:
                _ = data['request']
            else:
                _ = data
            raise cls.BackendException('{}: {} {} {}'.format(exc, url, _, result.text))

    def _write_attribute(self, track, attribute):
        """change an attribute directly on mapmytracks.

        Note that we specify iso-8859-1 but use utf-8. If we correctly specify utf-8 in

        the xml encoding, mapmytracks.com aborts our connection."""
        attr_value = getattr(track, attribute)
        if attribute == 'description' and attr_value == self._default_description:
            attr_value = ''
        # MMT returns 500 Server Error if we set the title to an empty string
        if attribute == 'title' and not attr_value:
            attr_value = 'no title'
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>update_{attr}</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<{attr}>{value}</{attr}></message>'.format(
                attr=attribute,
                eid=track.id_in_backend,
                usrid=self.config.username,
                value=attr_value,
                uid=self.session.cookies['exp_uniqueid'])
        self.__post(with_session=True, url='assets/php/interface.php', data=data, expect='success')

    def _write_title(self, track):
        """change title on remote server."""
        self._write_attribute(track, 'title')

    def _write_description(self, track):
        """change description on remote server."""
        self._write_attribute(track, 'description')

    def _write_public(self, track):
        """change public/private on remote server."""
        self.__post(
            with_session=True, url='user-embeds/statuschange-track', expect='access granted',
            mid=self.mid, tid=track.id_in_backend,
            hash=self.session.cookies['exp_uniqueid'],
            status=1 if track.public else 2)
        # what a strange answer

    def _write_category(self, track):
        """change category directly on mapmytracks.

        Note that we specify iso-8859-1 but use utf-8. If we correctly specify utf-8 in

        the xml encoding, mapmytracks.com aborts our connection."""
        self.__post(
            with_session=True, url='handler/change_activity', expect='ok',
            eid=track.id_in_backend, activity=self.encode_category(track.category))

    def _current_tags(self, track):
        """Return all current MMT tags.

        Returns:

            A sorted unique list"""
        page_scan = self._scan_track_page(track)
        return list(sorted(set(page_scan['tags'])))

    def _write_add_keywords(self, track, values):
        """Add keyword as MMT tag.

        MMT allows adding several at once, comma separated,

        and we allow this too. But do not expect this to work with all backends."""
        if not values:
            return
        values = ','.join(sorted(values.split(',')))
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>add_tag</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<tagnames>{value}</tagnames></message>'.format(
                eid=track.id_in_backend,
                usrid=self.config.username,
                value=values,
                uid=self.session.cookies['exp_uniqueid'])
        text = self.__post(with_session=True, url='assets/php/interface.php', data=data, expect='success')
        values = [x.strip() for x in values.split(',')]
        ids = (text.find('ids').text or '').split(',')
        tags = (text.find('tags').text or '').split(',')
        if values != tags or len(ids) != len(values):
            if values != tags:
                raise self.BackendException(
                    '{}: _write_add_keywords({}): MMT does not like some of your keywords: mmt tags={}'.format(
                        track, ','.join(values), ','.join(tags)))
            if len(ids) != len(values):
                raise self.BackendException(
                    '{}: _write_add_keywords({}): MMT does not like some of your keywords: mmt ids={}'.format(
                        track, ','.join(values), ','.join(ids)))
        for tag, id_ in zip(values, ids):
            self._found_tag_id(tag, id_)

    def _write_remove_keywords(self, track, values):
        """Remove keywords from track."""
        # with Track.batch_changes() active, track.keywords is already in the future
        # state after all batched changes have been applied, but we need the current
        # state. Ask MMT.
        current = self._get_current_keywords(track)
        wanted = set(current) - {x.strip() for x in values.split(',')}
        if True:  # pylint: disable=using-constant-test
            # First remove all keywords and then re-add the still wanted ones. This works!
            # Because even if MMT does not remove the correct keyword, it always does
            # remove one of them.
            for value in current:
                self._remove_single_keyword(track, value)
            self._write_add_keywords(track, ','.join(wanted))
        else:
            # Specifically remove unwanted keywords. This does not work, MMT does not
            # always remove the correct keyword. No idea why.
            for value in values.split(','):
                if value in current:
                    self._remove_single_keyword(track, value)

    def _remove_single_keyword(self, track, value):
        """Remove a specific keyword from track. Does not work correctly, see above."""
        tag = value.strip()
        if tag not in self.__tag_ids:
            self.__tag_ids.update(self._scan_track_page(track)['tags'])
            self._check_tag_ids()
            if tag not in self.__tag_ids:
                raise self.BackendException(
                    '{}: Cannot remove tag {}, MMT does not have an id'.format(track, tag))
        if tag in self.__tag_ids:
            self.__post(
                with_session=True, url='handler/delete-tag.php',
                tag_id=self.__tag_ids[tag], entry_id=track.id_in_backend)

    def get_time(self) ->datetime.datetime:
        """get MMT server time.

        Returns:
            The server time

        """
        return _convert_time(self.__post(request='get_time').find('server_time').text)

    def _load_track_headers(self):
        """get all tracks for this user."""

        while True:
            old_len = self.real_len()
            response = self.__post(
                request='get_activities', author=self.config.username,
                offset=old_len)
            chunk = response.find('activities')
            if not chunk:
                return
            self.logger.debug('got chunk %s %s', type(chunk), chunk)
            for _ in chunk:
                raw_data = MMTRawTrack(_)
                track = self._found_track(raw_data.track_id)
                track._header_data['title'] = raw_data.title
                track._header_data['category'] = self.decode_category(raw_data.category)
                track._header_data['time'] = raw_data.time
                track._header_data['distance'] = raw_data.distance
            assert self.real_len() > old_len

    def _scan_track_page(self, track):
        """The MMT api does not deliver all attributes we want.
        This gets some more by scanning the web page and
        returns it in page_parser.result"""
        response = self.session.get('{}/explore/activity/{}'.format(
            self.url, track.id_in_backend))
        page_parser = ParseMMTTrack(self)
        page_parser.feed(response.text)
        return page_parser.result

    def _get_current_keywords(self, track):
        """Ask MMT for current keywords, return them as a list."""
        page_scan = self._scan_track_page(track)
        if page_scan['tags']:
            return sorted(page_scan['tags'].keys())
        return list()

    def _use_webpage_results(self, track):
        """Get things directly.

        if the title has not been set, get_activities says something like "Track 2016-09-04 ..."
            while the home page says "Cycling activity". We prefer the value from the home page
            and silently ignore this inconsistency.

         """
        page_scan = self._scan_track_page(track)
        if page_scan['title']:
            track.title = page_scan['title']
        if page_scan['description']:
            _ = html.unescape(page_scan['description'])
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
        """get the entire track."""
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
        """remove on the server."""
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
        if 'write_title' in self.supported:
            self._write_title(track)
        # MMT can add several keywords at once
        if track.keywords and 'write_add_keywords' in self.supported:
            self._write_add_keywords(track, ', '.join(track.keywords))
        if old_ident:
            self._remove_ident(old_ident)
        track.id_in_backend = new_ident
        self.logger.debug('%s fully written', track)
        return new_ident

    @staticmethod
    def __formatted_lifetrack_points(points) ->str:
        """format points for life tracking.

        Returns:
            The formatted points

        """
        _ = list()
        for point in points:
            _.append('{} {} {} {}'.format(
                point.latitude,
                point.longitude,
                point.elevation if point.elevation is not None else 0,
                calendar.timegm(point.time.utctimetuple())))
        return ' '.join(_)

    def _lifetrack_start(self, track, points) ->str:
        """Start a new lifetrack with initial points.

        Returns:
            new_ident: New track id

        """
        if self.is_free_account:
            raise Exception('Your free MMT account does not allow lifetracking')
        if MMT._current_lifetrack is not None:
            raise Exception('start: MMT only accepts one simultaneous lifetracker per username')
        MMT._current_lifetrack = track
        result = self.__post(
            request='start_activity',
            title=track.title,
            privacy='public' if track.public else 'private',
            activity=self.encode_category(track.category),
            points=self.__formatted_lifetrack_points(points),
            source='Gpxity',
            version=VERSION,
            expect='activity_started',
            # tags='TODO',
            unique_token='{}'.format(id(track)))
        result = result.find('activity_id').text
        self.logger.error('%s: lifetracking started', self)
        return result

    def _lifetrack_update(self, track, points):
        """Update a lifetrack with points.

        Args:
            track: The lifetrack
            points: The new points

        """
        if MMT._current_lifetrack != track:
            raise Exception('update: MMT only accepts one simultaneous lifetracker per username')
        self.__post(
            request='update_activity', activity_id=track.id_in_backend,
            points=self.__formatted_lifetrack_points(points),
            expect='activity_updated')

    def _lifetrack_end(self, track):
        """End a lifetrack.

        Args:
            track: The lifetrack

        """
        if MMT._current_lifetrack != track:
            raise Exception('end: MMT only accepts one simultaneous lifetracker per username')
        self.__post(request='stop_activity')
        MMT._current_lifetrack = None

    def destroy(self):
        """also close session."""
        # TODO: session/destroy are quite similar between MMT and GPSIES
        super(MMT, self).destroy()
        ident = str(self)
        if ident in self._session:
            self._session[ident].close()

    @classmethod
    def is_disabled(cls) ->bool:
        """For now, it is disabled. Access stopped working.

        Returns:
            True if disabled

        """
        return cls.__name__ == 'MMT' or super(MMT, cls).is_disabled()
