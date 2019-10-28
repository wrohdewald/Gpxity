#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.mmt.MMT` for http://www.mapmytracks.com.

There are some problems with the server running at mapmytracks.com:
    * it is not possible to change an existing GpxFile - if the GpxFile changes, the
      GpxFile must be re-uploaded and gets a new id. This invalididates
      references held by other backend instances (maybe on other clients).
      But I could imagine that most similar services have this problem too.
    * does not support GPX very well beyond gpxfile data. One problem is that
      it does not support gpx.time, it ignores it in uploads and uses the time
      of the earliest trackpoint. To be consistent, Gpxity follows that for now
      and does not respect gpx.time either.
    * there is an official description of an API at https://github.com/MapMyTracks
      but this does not implement everything needed. For the missing parts we
      simulate what a web browser would do, see :meth:`MMT._read` and
      :meth:`MMT._write_attribute`. Of course that could fail if MMT changes its site.
      Which is true for the api itself, it can and does get incompatible changes at
      any time without notice to users or deprecation periods.
    * downloading gpxfiles with that abi is very slow and hangs forever for big gpxfiles
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

from .. import Backend
from ..gpx import Gpx
from ..version import VERSION


__all__ = ['MMT']


def _convert_time(raw_time) ->datetime.datetime:
    """MMT uses Linux timestamps. Converts that into datetime.

    Args:
        raw_time (int): The linux timestamp from the MMT server

    Returns:
        The datetime

    """
    return datetime.datetime.utcfromtimestamp(float(raw_time)).replace(tzinfo=datetime.timezone.utc)


class ParseMMTCategories(HTMLParser):  # pylint: disable=abstract-method

    """Parse the legal values for category from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseMMTCategories, self).__init__()
        self.seeing_category = False
        self.result = list()

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

    The gpxfile ident is the number given by MapMyTracks.

    MMT knows tags. We map :attr:`GpxFile.keywords <gpxity.gpxfile.GpxFile.keywords>` to MMT tags. MMT will
    change keywords: It converts the first character to upper case. See
    :attr:`GpxFile.keywords <gpxity.gpxfile.GpxFile.keywords>` for how Gpxity handles this.

    Args:
        account (:class:`~gpxity.accounts.Account`): The account to be used.
            Alternatively a dict can be passed to build an ad hoc :class:`~gpxity.accounts.Account`
            instance.

    """

    # pylint: disable=abstract-method

    _default_description = 'None yet. Let everyone know how you got on.'

    supported_categories = (
        'Cycling', 'Running', 'Mountain biking', 'Sailing', 'Walking', 'Hiking',
        'Driving', 'Off road driving', 'Motor racing', 'Motorcycling', 'Enduro',
        'Skiing', 'Cross country skiing', 'Canoeing', 'Kayaking', 'Sea kayaking',
        'SUP boarding', 'Rowing', 'Swimming', 'Windsurfing', 'Orienteering',
        'Mountaineering', 'Skating', 'Horse riding', 'Hang gliding', 'Hand cycling',
        'Gliding', 'Flying', 'Kiteboarding', 'Snowboarding', 'Paragliding',
        'Hot air ballooning', 'Nordic walking', 'Miscellaneous', 'Skateboarding',
        'Snowshoeing', 'Jet skiing', 'Powerboating', 'Wheelchair', 'Indoor cycling')

    _category_decoding = {
        'Cross country skiing': 'Skiing - Touring',
        'Hand cycling': 'Cycling - Hand',
        'Indoor cycling': 'Cycling - Indoor',
        'Mountain biking': 'Cycling - MTB',
        'SUP boarding': 'Stand up paddle boarding',
    }

    _category_encoding = {
        'Cabriolet': 'Driving',
        'Coach': 'Miscellaneous',
        'Crossskating': 'Skating',
        'Cycling - Foot': 'Cycling',
        'Cycling - Gravel': 'Cycling',
        'Cycling - Hand': 'Hand cycling',
        'Cycling - Road': 'Cycling',
        'Cycling - Touring': 'Cycling',
        'Geocaching': 'Miscellaneous',
        'Hiking - Speed': 'Hiking',
        'Longboard': 'Miscellaneous',
        'Motorhome': 'Driving',
        'Pack animal trekking': 'Hiking',
        'Pedelec': 'Cycling',
        'River navigation': 'Miscellaneous',
        'Running - Road': 'Miscellaneous',
        'Running - Trail': 'Miscellaneous',
        'Running - Urban Trail': 'Miscellaneous',
        'Sightseeing': 'Miscellaneous',
        'Skating - Inline': 'Skating',
        'Skiing - Alpine': 'Skiing',
        'Skiing - Backcountry': 'Cross country skiing',
        'Skiing - Crosscountry': 'Cross country skiing',
        'Skiing - Nordic': 'Cross country skiing',
        'Skiing - Roller': 'Skiing',
        'Stand up paddle boarding': 'SUP boarding',
        'Swimrun': 'Miscellaneous',
        'Train': 'Miscellaneous',
        'Wintersports': 'Skiing',
    }

    default_url = 'https://www.mapmytracks.com'

    # MMT only accepts one simultaneous lifetracker per login. We make sure
    # that at least this process does not try to run several at once.
    # This check is now too strict: We forbid multiple lifetrackers even if
    # every MMT account only gets one.
    _current_lifetrack = None

    def __init__(self, account):
        """See class docstring."""
        super(MMT, self).__init__(account)
        self.__mid = -1  # member id at MMT for authentication
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
        response = self.__get(url=self.url + '/explore/wall')
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
            author = self._get_author()
            self._session[ident] = requests.Session()
            # I have no idea what ACT=9 does but it seems to be needed
            payload = {'username': author, 'password': self.account.password, 'ACT': '9'}
            login_url = '{}/login'.format(self.https_url)
            headers = {'User-Agent': 'Gpxity'}  # see https://github.com/MapMyTracks/api/issues/26
            response = self._session[ident].post(
                login_url, data=payload, headers=headers, timeout=self.timeout)
            if 'You are now logged in.' not in response.text:
                raise self.BackendException('Login as {} / {} failed, I got {}'.format(
                    author, self.account.password, response.text))
            cookies = requests.utils.dict_from_cookiejar(self._session[ident].cookies)
            self._session[ident].cookies = requests.utils.cookiejar_from_dict(cookies)
        return self._session[ident]

    @property
    def mid(self):
        """the member id on MMT belonging to Account.

        Returns:
            The mid

        """
        if self.__mid == -1:
            self._parse_homepage()
        return self.__mid

    @property
    def subscription(self) ->str:
        """Return free or full.

        Returns: free or full

        """
        if self._cached_subscription is None:
            self._parse_homepage()
            self.logger.debug('%s: subscription: %s', self.account, self._cached_subscription)
            if self.subscription == 'free':
                self.supported = self.__class__.supported - set('private', )
        return self._cached_subscription

    def _parse_homepage(self):
        """Get some interesting values from the home page."""
        response = self.__get(with_session=True, url=self.url)
        if 'Get PLUS' in response.text:
            self._cached_subscription = 'free'
        else:
            self._cached_subscription = 'full'
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

    def __get(self, with_session: bool = False, url: str = None, headers=None):
        """Helper for the real function with some error handling.

        Sets User-Agent.

        Returns: response

        """
        if headers is None:
            headers = dict()
        headers['User-Agent'] = 'Gpxity'
        self.logger.debug('MMT.__get:%s url=%s', 'with session' if with_session else '', url)
        if with_session:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
        else:
            response = requests.get(url, headers=headers, timeout=self.timeout)
        return response

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
        # pylint: disable=too-many-branches

        full_url = self.url + '/' + (url if url else 'api/')
        headers = {'DNT': '1'}  # do not gpxfile
        headers['User-Agent'] = 'Gpxity'  # see https://github.com/MapMyTracks/api/issues/26
        if not self.account.username or not self.account.password:
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
                    auth=(self.account.username, self.account.password), timeout=self.timeout)
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
                _ = result.find('reason')
                if _ is not None:
                    reason = _.text
                else:
                    reason = 'no reason given'
                raise self.BackendException('{}: {}'.format(reason, data))
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

    def _write_attribute(self, gpxfile, attribute):
        """change an attribute directly on mapmytracks.

        Note that we specify iso-8859-1 but use utf-8. If we correctly specify utf-8 in

        the xml encoding, mapmytracks.com aborts our connection."""
        attr_value = getattr(gpxfile, attribute)
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
                eid=gpxfile.id_in_backend,
                usrid=self.account.username,
                value=attr_value,
                uid=self.session.cookies['exp_uniqueid'])
        self.__post(with_session=True, url='assets/php/interface.php', data=data, expect='success')

    def _write_title(self, gpxfile):
        """change title on remote server."""
        self._write_attribute(gpxfile, 'title')

    def _write_description(self, gpxfile):
        """change description on remote server."""
        self._write_attribute(gpxfile, 'description')

    def _write_public(self, gpxfile):
        """change public/private on remote server."""
        self.__post(
            with_session=True, url='user-embeds/statuschange-gpxfile', expect='access granted',
            mid=self.mid, tid=gpxfile.id_in_backend,
            hash=self.session.cookies['exp_uniqueid'],
            status=1 if gpxfile.public else 2)
        # what a strange answer

    def _write_category(self, gpxfile):
        """change category directly on mapmytracks.

        Note that we specify iso-8859-1 but use utf-8. If we correctly specify utf-8 in

        the xml encoding, mapmytracks.com aborts our connection."""
        self.__post(
            with_session=True, url='handler/change_activity', expect='ok',
            eid=gpxfile.id_in_backend, activity=self.encode_category(gpxfile.category))

    def _current_tags(self, gpxfile):
        """Return all current MMT tags.

        Returns:

            A sorted unique list"""
        page_scan = self._scan_track_page(gpxfile)
        return list(sorted(set(page_scan['tags'])))

    def _write_add_keywords(self, gpxfile, values):
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
                eid=gpxfile.id_in_backend,
                usrid=self.account.username,
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
                        gpxfile, ','.join(values), ','.join(tags)))
            if len(ids) != len(values):
                raise self.BackendException(
                    '{}: _write_add_keywords({}): MMT does not like some of your keywords: mmt ids={}'.format(
                        gpxfile, ','.join(values), ','.join(ids)))
        for tag, id_ in zip(values, ids):
            self._found_tag_id(tag, id_)

    def _write_remove_keywords(self, gpxfile, values):
        """Remove keywords from gpxfile."""
        # with GpxFile.batch_changes() active, gpxfile.keywords is already in the future
        # state after all batched changes have been applied, but we need the current
        # state. Ask MMT.
        current = self._get_current_keywords(gpxfile)
        wanted = set(current) - {x.strip() for x in values.split(',')}
        if True:  # pylint: disable=using-constant-test
            # First remove all keywords and then re-add the still wanted ones. This works!
            # Because even if MMT does not remove the correct keyword, it always does
            # remove one of them.
            for value in current:
                self._remove_single_keyword(gpxfile, value)
            self._write_add_keywords(gpxfile, ','.join(wanted))
        else:
            # Specifically remove unwanted keywords. This does not work, MMT does not
            # always remove the correct keyword. No idea why.
            for value in values.split(','):
                if value in current:
                    self._remove_single_keyword(gpxfile, value)

    def _remove_single_keyword(self, gpxfile, value):
        """Remove a specific keyword from gpxfile. Does not work correctly, see above."""
        tag = value.strip().capitalize()
        if tag not in self.__tag_ids:
            self.__tag_ids.update(self._scan_track_page(gpxfile)['tags'])
            self._check_tag_ids()
            if tag not in self.__tag_ids:
                raise self.BackendException(
                    '{}: Cannot remove tag {}, it is not one of {}'.format(
                        gpxfile, tag, self.__tag_ids))
        if tag in self.__tag_ids:
            self.__post(
                with_session=True, url='handler/delete-tag.php',
                tag_id=self.__tag_ids[tag], entry_id=gpxfile.id_in_backend)

    def get_time(self) ->datetime.datetime:
        """get MMT server time.

        Returns:
            The server time

        """
        return _convert_time(self.__post(request='get_time').find('server_time').text)

    def _list(self):
        """get all gpxfiles for this user."""
        while True:
            old_len = self.real_len()
            response = self.__post(
                request='get_activities', author=self._get_author(),
                offset=old_len)
            chunk = response.find('activities')
            if not chunk:
                return
            for _ in chunk:
                raw_data = MMTRawTrack(_)
                gpx = Gpx()
                gpx.is_complete = False
                gpx.name = raw_data.title
                gpx.time = raw_data.time
                gpxfile = self._found_gpxfile(raw_data.track_id, gpx)
                gpxfile.category = self.decode_category(raw_data.category)
                gpxfile.distance = raw_data.distance
            assert self.real_len() > old_len

    def _scan_track_page(self, gpxfile):
        """The MMT api does not deliver all attributes we want.
        This gets some more by scanning the web page and
        returns it in page_parser.result"""
        response = self.__get(
            with_session=True, url='{}/explore/activity/{}'.format(self.url, gpxfile.id_in_backend))
        page_parser = ParseMMTTrack(self)
        page_parser.feed(response.text)
        return page_parser.result

    def _get_current_keywords(self, gpxfile):
        """Ask MMT for current keywords, return them as a list."""
        page_scan = self._scan_track_page(gpxfile)
        if page_scan['tags']:
            return sorted(page_scan['tags'].keys())
        return list()

    def _use_webpage_results(self, gpxfile):
        """Get things directly.

        if the title has not been set, get_activities says something like "GpxFile 2016-09-04 ..."
            while the home page says "Cycling activity". We prefer the value from the home page
            and silently ignore this inconsistency.

         """
        page_scan = self._scan_track_page(gpxfile)
        if page_scan['title']:
            gpxfile.title = page_scan['title']
        if page_scan['description']:
            _ = html.unescape(page_scan['description'])
            if _ == self._default_description:
                _ = ''
            gpxfile.description = _
        if page_scan['tags']:
            gpxfile.keywords = page_scan['tags'].keys()
        # MMT sends different values of the current gpxfile type, hopefully category_3 is always the
        # correct one.
        if page_scan['category_3']:
            gpxfile.category = self.decode_category(page_scan['category_3'])
        if page_scan['public'] is not None:
            gpxfile.public = page_scan['public']

    def _read(self, gpxfile):
        """get the entire gpxfile."""
        session = self.session
        if session is None:
            # https access not implemented for TrackMMT
            return
        response = self.__get(with_session=True, url='{}/assets/php/gpx.php?tid={}&mid={}&uid={}'.format(
            self.url, gpxfile.id_in_backend, self.mid, self.session.cookies['exp_uniqueid']))
        # some gpxfiles download only a few points if mid/uid are not given, but I
        # have not been able to write a unittest triggering that ...
        gpxfile.gpx = Gpx.parse(response.text)
        # but this does not give us gpxfile type and other things,
        # get them from the web page.
        self._use_webpage_results(gpxfile)

    def _remove_ident(self, ident: str):
        """remove on the server."""
        self.__post(
            with_session=True, url='handler/delete_track', expect='access granted',
            tid=ident, hash=self.session.cookies['exp_uniqueid'])

    def _write_all(self, gpxfile) ->str:
        """save full gpx gpxfile on the MMT server.

        We must upload the title separately.

        Returns:
            The new id_in_backend

        """
        response = self.__post(
            request='upload_activity', gpx_file=gpxfile.xml(),
            status='public' if gpxfile.public else 'private',
            description=gpxfile.description, activity=self.encode_category(gpxfile.category))
        new_ident = response.find('id').text
        if not new_ident:
            raise self.BackendException('No id found in response')
        gpxfile.id_in_backend = new_ident
        # the caller will do the above too, never mind
        if 'write_title' in self.supported:
            self._write_title(gpxfile)
        # MMT can add several keywords at once
        if gpxfile.keywords and 'write_add_keywords' in self.supported:
            self._write_add_keywords(gpxfile, ', '.join(gpxfile.keywords))
        gpxfile.id_in_backend = new_ident
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

    def _lifetrack_start(self, gpxfile, points) ->str:
        """Start a new lifetrack with initial points.

        Returns:
            new_ident: New gpxfile id

        """
        if self.subscription == 'free':
            self.logger.info('Your free MMT account does not allow lifetracking, I will send the entire gpxfile')
            return super(MMT, self)._lifetrack_start(gpxfile, points)
        if MMT._current_lifetrack is not None:
            raise Exception('start: MMT only accepts one simultaneous lifetracker per username')
        MMT._current_lifetrack = gpxfile
        result = self.__post(
            request='start_activity',
            title=gpxfile.title,
            privacy='public' if gpxfile.public else 'private',
            activity=self.encode_category(gpxfile.category),
            points=self.__formatted_lifetrack_points(points),
            source='Gpxity',
            version=VERSION,
            expect='activity_started',
            # tags='TODO',
            unique_token='{}'.format(id(gpxfile)))
        result = result.find('activity_id').text
        self.logger.error('%s: lifetracking started', self)
        return result

    def _lifetrack_update(self, gpxfile, points):
        """Update a lifetrack with points.

        Args:
            gpxfile: The lifetrack
            points: The new points

        """
        if self.subscription == 'free':
            super(MMT, self)._lifetrack_update(gpxfile, points)
            return
        if MMT._current_lifetrack != gpxfile:
            raise Exception('lifetrack_update: MMT only accepts one simultaneous lifetracker per username')
        self.__post(
            request='update_activity', activity_id=gpxfile.id_in_backend,
            points=self.__formatted_lifetrack_points(points),
            expect='activity_updated')

    def _lifetrack_end(self, gpxfile):
        """End a lifetrack.

        Args:
            gpxfile: The lifetrack

        """
        if self.subscription == 'free':
            super(MMT, self)._lifetrack_end(gpxfile)
        else:
            if MMT._current_lifetrack != gpxfile:
                raise Exception('end: MMT only accepts one simultaneous lifetracker per username')
            self.__post(request='stop_activity')
            MMT._current_lifetrack = None

    def detach(self):
        """also close session."""
        # TODO: session/detach are quite similar between MMT and GPSIES
        super(MMT, self).detach()
        ident = str(self)
        if ident in self._session:
            self._session[ident].close()
