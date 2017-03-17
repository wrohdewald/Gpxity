#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.backends.MMT` for http://www.mapmytracks.com

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
    * not all parts of MMT data are supported like tags (would be nice to have.
      Download is implemented but no upload) or images (not interesting for me,
      at least not now).

"""

from xml.etree import ElementTree
from html.parser import HTMLParser
import datetime
from collections import defaultdict

import requests

from .. import Backend, Activity


__all__ = ['MMT']

def _convert_time(raw_time) ->datetime.datetime:
    """MMT uses Linux timestamps. Converts that into datetime

    Args:
        raw_time (int): The linux timestamp from the MMT server
    """
    return datetime.datetime.utcfromtimestamp(float(raw_time))


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
        self.result['mid'] = None
        self.result['title'] = None
        self.result['description'] = None
        self.result['legal_whats'] = list()
        self.result['what'] = None
        self.result['what_from_title'] = None
        self.result['what_3'] = None
        self.result['public'] = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        # pylint: disable=too-many-branches
        self.seeing_title = False
        self.seeing_description = False
        self.seeing_what = False
        self.seeing_status = False
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
            elif attributes['type'] == 'radio' and attributes['class'] == 'activity_type':
                self.result['legal_whats'].append(value)
        elif tag == 'div' and attributes['class'] == 'panel' and 'data-activity' in attributes:
            # TODO: still so? sometime this says Miscellaneous instead of the correct value like Swimming
            self.result['what'] = attributes['data-activity']
        elif tag == 'span' and attributes['class'] == 'privacy-status':
            self.seeing_status = True
        elif tag == 'title':
            self.seeing_what = True
        elif tag == 'h2' and attributes['id'] == 'track-title':
            self.seeing_title = True
        elif tag == 'p' and attributes['id'] == 'track-desc':
            self.seeing_description = True

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


class MMTRawActivity:

    """raw data from mapmytracks.get_activities"""

    # pylint: disable=too-few-public-methods
    def __init__(self, xml):
        self.activity_id = xml.find('id').text
        self.title = xml.find('title').text
        self.time = _convert_time(xml.find('date').text)
        self.what = xml.find('activity_type').text


class MMT(Backend):
    """The implementation for MapMyTracks.
    The activity ident is the number given by MapMyTracks.

    Args:
        url (str): The Url of the server. Default is http://mapmytracks.com
        auth (tuple(str, str)): Username and password
        cleanup (bool): If True, :meth:`~gpxity.backend.Backend.destroy` will remove all activities in the
            user account.
    """

    # pylint: disable=abstract-method

   #  skip_test = True

    _default_description = 'None yet. Let everyone know how you got on.'

    def __init__(self, url=None, auth=None, cleanup=True):
        if url is None:
            url = 'http://www.mapmytracks.com'
        super(MMT, self).__init__(url, auth, cleanup)
        self.remote_known_whats = None
        self.__mid = -1 # member id at MMT for auth
        self.__session = None
        self._last_response = None # only used for debugging

    @property
    def session(self):
        """The requests.Session for this backend. Only initialized once."""
        if self.__session is None:
            self.__session = requests.Session()
            # I have no idea what ACT=9 does but it seems to be needed
            payload = {'username': self.auth[0], 'password': self.auth[1], 'ACT':'9'}
            base_url = self.url.replace('http:', 'https:')
            login_url = '{}/login'.format(base_url)
            response = self.__session.post(login_url, data=payload)
            if not 'You are now logged in.' in response.text:
                raise requests.exceptions.HTTPError('Login as {} failed'.format(self.auth[0]))
        return self.__session

    @property
    def mid(self):
        """the member id on MMT belonging to auth"""
        if self.__mid == -1:
            response = self.session.get(self.url)
            page_parser = ParseMMTActivity()
            page_parser.feed(response.text)
            self.__mid = page_parser.result['mid']
        return self.__mid

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
                response = self.session.post(full_url, data=data, headers=headers, timeout=(5, 300))
            else:
                response = requests.post(full_url, data=data, headers=headers, auth=self.auth, timeout=(5, 300))
        except requests.exceptions.ReadTimeout:
            print('timeout for', data)
            raise
        self._last_response = response # for debugging
        if response.status_code != requests.codes.ok: # pylint: disable=no-member
            self.__handle_post_error(full_url, data, response)
            return
        result = response.text
        if expect and expect not in result:
            raise requests.exceptions.HTTPError('{}: expected {} in {}'.format(data, expect, result))
        if result.startswith('<?xml'):
            try:
                result = ElementTree.fromstring(result)
            except ElementTree.ParseError:
                print('POST {} has parse error: {}'.format(data, response.text))
                raise
            result_type = result.find('type')
            if result_type is not None and result_type.text == 'error':
                reason = result.find('reason').text if result.find('reason') else 'no reason given'
                raise requests.exceptions.HTTPError('{}: {}'.format(data, reason))
        return result

    @staticmethod
    def __handle_post_error(url, data, result):
        """we got status_code != ok"""
        try:
            result.raise_for_status()
        except BaseException as exc:
            if 'request' in data:
                _ = data['request']
            else:
                _ = data
            raise type(exc)('{}: {} {} {}'.format(exc, url, _, result.text))

    def _write_attribute(self, activity, attribute):
        """change an attribute directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        if activity.is_decoupled:
            return
        attr_value = getattr(activity, attribute)
        if attribute == 'description' and attr_value == self._default_description:
            attr_value = ''
        data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
            '<message><nature>update_{attr}</nature><eid>{eid}</eid>' \
            '<usr>{usrid}</usr><uid>{uid}</uid>' \
            '<{attr}>{value}</{attr}></message>'.format(
                attr=attribute,
                eid=activity.id_in_backend,
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
            mid=self.mid, tid=activity.id_in_backend, hash=self.session.cookies['exp_uniqueid'],
            status=1 if activity.public else 2)
            # what a strange answer

    def _write_what(self, activity):
        """change what directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        self.__post(
            with_session=True, url='handler/change_activity', expect='ok',
            eid=activity.id_in_backend, activity=activity.what)

    def get_time(self) ->datetime.datetime:
        """get MMT server time"""
        return _convert_time(self.__post(request='get_time').find('server_time').text)

    def _yield_activities(self):
        """get all activities for this user. If we do not use the generator
        created by yield_activity, unittest fails. Why?"""

        while True:
            old_len = len(self._activities)
            response = self.__post(
                request='get_activities', author=self.auth[0],
                offset=old_len)
            chunk = response.find('activities')
            if not chunk:
                return
            for _ in chunk:
                raw_data = MMTRawActivity(_)
                activity = Activity(self, raw_data.activity_id)
                with activity.decoupled():
                    activity.title = raw_data.title
                    activity.what = raw_data.what
                yield activity
            assert len(self._activities) > old_len

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
        if self.remote_known_whats is None:
            self.remote_known_whats = page_scan['legal_whats']
        with activity.decoupled():
            if page_scan['title']:
                activity.title = page_scan['title']
            if page_scan['description']:
                _ = page_scan['description']
                if _ == self._default_description:
                    _ = ''
                activity.description = _
            # MMT sends different values of the current activity type, hopefully what_3 is always the
            # correct one.
            if page_scan['what_3']:
                activity.what = page_scan['what_3']
            if page_scan['public'] is not None:
                activity.public = page_scan['public']

    def _read_all(self, activity):
        """get the entire activity"""
        response = self.session.get('{}/assets/php/gpx.php?tid={}&mid={}&uid={}'.format(
            self.url, activity.id_in_backend, self.mid, self.session.cookies['exp_uniqueid']))
            # some activities download only a few points if mid/uid are not given, but I
            # have not been able to write a unittest triggering that ...
        with activity.decoupled():
            activity.parse(response.text)
            # but this does not give us activity type and other things,
            # get them from the web page.
        self._use_webpage_results(activity)

    def _remove_activity_in_backend(self, activity):
        """remove on the server"""
        act_id = activity.id_in_backend
        response = self.__post(request='delete_activity', activity_id=act_id)
        type_xml = response.find('type')
        if type_xml is not None and type_xml.text == 'invalid_activity_id':
            # does not exist anymore, silently ignore this.
            return
        if type_xml is None or type_xml.text != 'activity_deleted':
            raise Exception('{}: Could not delete activity {}: {}'.format(self, activity, response.text))

    def _write_all(self, activity, ident: str = None):
        """save full gpx track on the MMT server.
        We must upload the title separately.
        Because we cannot upload the time, we set the activity time to the time
        of the first trackpoint."""

        if not activity.gpx.get_track_points_no():
            raise Exception('MMT does not accept an activity without trackpoints:{}'.format(activity))
        mmt_status = 'public' if activity.public else 'private'
        if activity.id_in_backend:
            # we cannot change an MMT activity in-place, we need to re-upload and then
            # remove the previous instance.
            self._remove_activity_in_backend(activity)
        response = self.__post(
            request='upload_activity', gpx_file=activity.to_xml(),
            status=mmt_status, description=activity.description, activity=activity.what)
        activity.id_in_backend = response.find('id').text
        self._write_title(activity)

    def update(self, activity, points):
        """append points in the backend. activity already has them.
        points are GPXTrackPoint"

        Todo:
            Doc is wrong, must rethink this.
        """
        activity.add_points(points)
        self.__post(
            request='update_activity', activity_id=activity.id_in_backend,
            points=points)

    def destroy(self):
        """also close session"""
        super(MMT, self).destroy()
        if self.session:
            self.session.close()

MMT._define_support() # pylint: disable=protected-access
