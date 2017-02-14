#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxmove.backends.MMTClientStorage`
"""


from xml.etree import ElementTree
from html.parser import HTMLParser
import datetime

import requests

from gpxpy.gpx import GPXTrackPoint

from .. import Storage, Activity


__all__ = ['MMTClientStorage']



class MMTSession:
    """Helps execute commands while logged in"""
    # pylint: disable=too-few-public-methods

    def __init__(self, storage):
        self.session = requests.Session()
        # I have no idea what ACT=9 does but it seems to be needed
        payload = {'username': storage.auth[0], 'password': storage.auth[1], 'ACT':'9'}
        base_url = storage.base_url().replace('http:', 'https:')
        login_url = '{}/login'.format(base_url)
        response = self.session.post(login_url, data=payload)
        if not 'You are now logged in.' in response.text:
            raise requests.exceptions.HTTPError()

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, trback):
        self.session.close()


class ParseMMTActivity(HTMLParser): # pylint: disable=abstract-method

    """get some attributes available only on the web page. Of course,
    this is highly unreliable. Just use what we can get."""

    result = dict()

    def __init__(self):
        super(ParseMMTActivity, self).__init__()
        self.seeing_what = False
        self.seeing_title = False
        self.seeing_description = False
        self.result['title'] = None
        self.result['description'] = None
        self.result['legal_whats'] = list()
        self.result['what'] = None
        self.result['what_from_title'] = None
        self.result['what_3'] = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        self.seeing_title = False
        self.seeing_description = False
        self.seeing_what = False
        if tag == 'input' and len(attrs) == 4:
            if attrs[0] == ('id', 'activity_type'):
                if attrs[1] == ('type', 'hidden'):
                    if attrs[2] == ('name', 'activity_type'):
                        if attrs[3][0] == 'value':
                            value = attrs[3][1].strip()
                            self.result['what_3'] = value
            if attrs[0] == ('type', 'radio') and attrs[1] == ('class', 'activity_type'):
                value = attrs[3][1].strip()
                self.result['legal_whats'].append(value)
        elif tag == 'div' and attrs and attrs[0] == ('class', 'panel') and attrs[1][0] == 'data-activity':
            # sometime this says Miscellaneous instead of the correct value like Swimming
            self.result['what'] = attrs[1][1]
        elif tag == 'title':
            self.seeing_what = True
        elif tag == 'h2' and attrs and attrs[0] == ('id', 'track-title'):
            self.seeing_title = True
        elif tag == 'p' and attrs and attrs[0] == ('id', 'track-desc'):
            self.seeing_description = True

    def handle_data(self, data):
        """data from the parser"""
        if self.seeing_title and data.strip():
            self.result['title'] = data.strip()
        if self.seeing_description and data.strip():
            self.result['description'] = data.strip()
        if self.seeing_what and data.strip():
            try:
                _ = data.split('|')[1].split('@')[0].strip()
                self.result['what_from_title'] = ' '.join(_.split(' ')[:-2])
            except BaseException:
                print('cannot parse', data)
                self.result['what_from_title'] = ''


class MMTRawActivity:

    """raw data from mapmytracks.get_activities"""

    # pylint: disable=too-few-public-methods
    def __init__(self, xml):
        self.activity_id = xml.find('id').text
        self.title = xml.find('title').text
        self.time = MMTClientStorage.convert_time(xml.find('date').text)
        self.what = xml.find('activity_type').text


class MMTClientStorage(Storage):
    """The implementation for MapMyTracks.
    The activity ident is the number given by MapMYTracks.
    cleanup: if True, remove storage in __exit__ and in destroy()

    Mapping GPX 1.1  - Activity attribute -  mapmytracks:
    name                    title                           title
    desc                    description                 description
    time                    time                               date
    keywords            public, what   status, what
    """

    def __init__(self, url=None, auth=None, cleanup=True):
        if url is None:
            url = 'http://www.mapmytracks.com/api'
        super(MMTClientStorage, self).__init__(url, auth, cleanup)
        self.remote_known_whats = None

    def __post(self, request, session=None, **kwargs):
        """helper for the real function"""
        data = kwargs.copy()
        data['request'] = request
        result = (session or requests).post(self.url, data=data, auth=self.auth, timeout=(5, 300))
        try:
            result.content.decode(result.encoding)
        except  UnicodeDecodeError:
            # As of February 2017, the xml always says it is encoded as utf-8 but it is not!
            # It looks like iso8859-1
            result.encoding = result.apparent_encoding
        if result.status_code != requests.codes.ok: # pylint: disable=no-member
            self.__handle_post_error(request, result)
            return
        try:
            result = ElementTree.fromstring(result.text)
        except ElementTree.ParseError:
            print('POST {} has parse error: {}'.format(request, result.text))
            raise
        assert result.text != 'error' # should have raise_for_status
        result_type = result.find('type')
        if result_type is not None and result_type.text == 'error':
            raise requests.exceptions.HTTPError(result.find('reason').text)
        return result

    def __handle_post_error(self, request, result):
        """we got status_code != ok"""
        try:
            result.raise_for_status()
        except BaseException as exc:
            raise type(exc)('{}: {} {} {}'.format(exc, self.url, request, result.text))


    def _change_attribute(self, activity, attribute):
        """change an attribute directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        if activity.loading:
            return
        with MMTSession(self) as session:
            url = self.base_url() + '/assets/php/interface.php'
            data = '<?xml version="1.0" encoding="ISO-8859-1"?>' \
                '<message><nature>update_{}</nature><eid>{}</eid>' \
                '<usr>{}</usr><uid>{}</uid>' \
                '<title>{}</title></message>'.format(
                    attribute,
                    activity.storage_ids[self], self.auth[0],
                    session.cookies['exp_uniqueid'], getattr(activity, attribute)).encode('utf-8')
            response = session.post(url, data=data)
            if 'success' not in response.text:
                raise requests.exceptions.HTTPError()

    def change_title(self, activity):
        """changes title on remote server"""
        self._change_attribute(activity, 'title')

    def change_description(self, activity):
        """changes description on remote server"""
        self._change_attribute(activity, 'description')

    def change_what(self, activity):
        """change what directly on mapmytracks. Note that we specify iso-8859-1 but
        use utf-8. If we correctly specify utf-8 in the xml encoding, mapmytracks.com
        aborts our connection."""
        if activity.loading:
            return
        with MMTSession(self) as session:
            url = self.base_url() + '/handler/change_activity'
            data = {'eid': activity.storage_ids[self], 'activity': activity.what}
            response = session.post(url, data=data)
            if 'ok' not in response.text:
                raise requests.exceptions.HTTPError()

    def get_time(self):
        """get MMT server time as a Linux timestamp"""
        return int(self.__post('get_time').find('server_time').text)

    def _yield_activities(self):
        """get all activities for this user. If we do not use the generator
        created by yield_activity, unittest fails. Why?"""

        self.activities.clear()

        with MMTSession(self) as session:
            while True:
                response = self.__post(
                    'get_activities', author=self.auth[0],
                    offset=len(self.activities), session=session)
                chunk = response.find('activities')
                if not chunk:
                    return
                for _ in chunk:
                    raw_data = MMTRawActivity(_)
                    activity = Activity(self, raw_data.activity_id)
                    activity.loading = True
                    try:
                        activity.title = raw_data.title
                        activity.time = raw_data.time
                        activity.what = raw_data.what
                    finally:
                        activity.loading = False
                    yield activity

    def __import_xml(self, activity, xml):
        """imports points and other data. Currently unused and unusable
        see __load_points_with_api."""
        xml_points = xml.find('points')
        min_when = 100000000000000
        max_when = 0
        if xml_points is not None and xml_points.text:
            for raw_point in xml_points.text.split(' '):
                when, latitude, longitude, elevation = raw_point.split(',')
                min_when = min(min_when, int(when))
                max_when = max(max_when, int(when))
                when = self.convert_time(when)
                activity.add_points([
                    GPXTrackPoint(
                        latitude, longitude,
                        elevation=elevation,
                        time=when)])
        complete_tag = xml.find('complete')
        if complete_tag:
            activity.complete = complete_tag.text == 'Yes'
        print('import chunk: when in range', min_when, max_when)
        return max_when

    def base_url(self):
        """the url without subdirectories"""
        return self.url.replace('/api/', '')

    def load_full(self, activity):
        """get the entire activity"""
        activity.loading = True
        try:
            with MMTSession(self) as session:
                response = session.get('{}/assets/php/gpx.php?tid={}'.format(
                    self.base_url(), activity.storage_ids[self]))
                activity.parse(response.text)
                # but this does not give us activity type and other things.
                response = session.get('{}/explore/activity/{}'.format(
                    self.base_url(), activity.storage_ids[self]))
                page_parser = ParseMMTActivity()
                page_parser.feed(response.text)
                # if the title has not been set, get_activities says something like "Activity 2016-09-04 ..."
                # while the home page says "Cycling activity". We prefer the value from the home page
                # and silently ignore this inconsistency.
                if self.remote_known_whats is None:
                    self.remote_known_whats = page_parser.result['legal_whats']
                if page_parser.result['title']:
                    activity.title = page_parser.result['title']
                if page_parser.result['description']:
                    activity.description = page_parser.result['description']
                # MMT sends different values of the current activity type, hopefully what_3 is always the
                # correct one.
                if page_parser.result['what_3']:
                    activity.what = page_parser.result['what_3']
        finally:
            activity.loading = False

    def __load_points_with_api(self, activity):
        """"First, it only imported 100 points starting at from_time. Now (Feb 2017), it always imports
        the full track but hangs forever for very large tracks."""
        old_from_time = -1
        from_time = 0
        while from_time != old_from_time:
            chunk = self.__post('get_activity', activity_id=activity.storage_ids[self], from_time=from_time, timeout=5)
            old_from_time = from_time
            from_time = self.__import_xml(activity, chunk)
            if from_time == 0:
                # this activity has no trackpoints!
                break
        if not activity.point_count():
            raise Exception('{} from {} is empty'.format(
                activity, self))
        activity.loaded = True

    def _remove_activity_in_storage(self, activity):
        """remove on the server"""
        act_id = activity.storage_ids[self]
        response = self.__post('delete_activity', activity_id=act_id)
        type_xml = response.find('type')
        if type_xml is None or type_xml.text != 'activity_deleted':
            raise Exception('{}: Could not delete activity {}: {}'.format(self, activity, response.text))

    def save(self, activity):
        """save full gpx track on the MMT server.
        We must upload the title separately.
        Because we cannot upload the time, we set the activity time to the time
        of the first trackpoint."""

        activity.adjust_time()
        status = 'public' if activity.public else 'private'
        response = self.__post(
            'upload_activity', gpx_file=activity.to_xml(),
            status=status, description=activity.description, activity=activity.what)
        new_id = response.find('id').text
        activity.add_to_storage(self, new_id)
        self.change_title(activity)

    def destroy(self):
        """We do not want to remove the account on mapmytracks!"""
        if self.cleanup:
            self.remove_all()

    def update(self, activity, points):
        """append points in the storage. activity already has them.
        points are GPXTrackPoint"""
        activity.add_points(points)
        self.__post(
            'update_activity', activity_id=activity.storage_ids[self],
            points=points)

    @staticmethod
    def convert_time(raw_time):
        """MMT uses Linux timestamps. Converts that into datetime"""
        return datetime.datetime.utcfromtimestamp(int(raw_time))
