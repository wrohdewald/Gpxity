#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpsies.GPSIES` for https://www.gpsies.com

so ginge das mit dem API-Key: https://github.com/telemaxx/gpsiesreader/blob/master/gpsies3.py

"""

from html.parser import HTMLParser
import datetime
from collections import defaultdict

import requests

from .. import Backend, Activity

__all__ = ['GPSIES']

class GPSIESRawActivity:

    """raw data from the gpies html page"""

    # pylint: disable=too-few-public-methods
    def __init__(self):
        self.activity_id = None
        self.title = None
        self.time = None
        self.distance = None
        self.public = True
        self.description = None

class ParseGPSIESWhats(HTMLParser): # pylint: disable=abstract-method

    """Parse the legal values for what from html"""

    def __init__(self):
        super(ParseGPSIESWhats, self).__init__()
        self.result = list(['biking'])

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes':
            _ = attributes['id']
            if _ not in self.result:
                self.result.append(_)


class ParseGPIESEditPage(HTMLParser): # pylint: disable=abstract-method

    """Parse the what value for an activity from html"""

    def __init__(self):
        super(ParseGPIESEditPage, self).__init__()
        self.what = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes' and 'checked' in attributes:
            self.what = attributes['id']


class ParseGPSIESList(HTMLParser): # pylint: disable=abstract-method

    """get some attributes available only on the web page. Of course,
    this is highly unreliable. Just use what we can get."""

    def __init__(self):
        super(ParseGPSIESList, self).__init__()
        self.result = dict()
        self.result['activities'] = list()
        self.activity = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False
        self.seeing_warning = False

    def feed(self, data):
        self.activity = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False
        self.seeing_warning = False
        super(ParseGPSIESList, self).feed(data)

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        self.current_tag = tag
        attributes = defaultdict(str)
        for key, value in attrs:
            attributes[key] = value
        if tag == 'div' and 'alert-warning' in attributes['class']:
            self.seeing_warning = True
        if tag == 'tbody':
            self.seeing_list = True
        if not self.seeing_list:
            return
        if tag == 'tr':
            self.activity = GPSIESRawActivity()
            self.column = 0
            self.seeing_a = False
        elif tag == 'td':
            self.column += 1
        elif self.after_list and tag == 'a':
            self.seeing_a = True
            value = attributes['value'].strip()
        elif tag == 'a' and 'href' in attributes and self.activity.activity_id is None:
            self.activity.activity_id = attributes['href'].split('fileId=')[1]
        elif tag == 'img' and self.activity and 'lock.png' in attributes['src']:
            self.activity.public = False

    def handle_endtag(self, tag):
        """handle end of track list"""
        if tag == 'tbody':
            self.seeing_list = False
            self.after_list = True


    def handle_data(self, data):
        """data from the parser"""
        data = data.strip()
        if not data:
            return
        if self.seeing_warning:
            raise GPSIES.BackendException(data)

        if self.seeing_list:
            if self.column == 3:
                if self.current_tag == 'i' and self.activity.title is None:
                    self.activity.title = data
            elif self.column == 4:
                if data.endswith('km'):
                    self.activity.distance = float(data.replace(' km', '').replace(',', ''))
            elif self.column == 5:
                self.activity.time = datetime.datetime.strptime(data, '%m/%d/%y')
                self.result['activities'].append(self.activity)


class GPSIES(Backend):
    """The implementation for gpsies.com.
    The activity ident is the fileId given by gpsies.

    Searching arbitrary tracks is not supported. GPSIES only looks at the
    tracks of a specific user.

    Args:
        url (str): The Url of the server. Default is https://gpsies.com
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

    _what_decoding = {
        'trekking': 'Hiking',
        'jogging': 'Running',
        'climbing': 'Mountaineering',
        'biking': 'Cycling',
        'racingbike': 'Cycling',
        'mountainbiking': 'Mountain biking',
        'motorbiking': 'Motorcycling',
        'motocross': 'Enduro',
        'car': 'Driving',
        'riding': 'Horse riding',
        'packAnimalTrekking': 'Pack animal trekking',
        'boating': 'Rowing',
        'motorboat': 'Powerboating',
        'skiingNordic': 'Cross contry skiing',
        'skiingAlpine': 'Skiing',
        'skiingRandonnee': 'Skiing',
        'snowshoe': 'Snowshoeing',
        'wintersports': 'Miscellaneous',
        'sightseeing': 'Miscellaneous',
        'geocaching': 'Miscellaneous'
    }

    _what_encoding = {
        'Cycling': 'biking',
        'Running': 'jogging',
        'Mountain biking': 'mountainbiking',
        'Indoor cycling': 'biking',
        'Hiking': 'trekking',
        'Driving': 'car',
        'Off road driving': 'car',
        'Motor racing': 'car',
        'Motorcycling': 'motorbiking',
        'Enduro': 'motocross',
        'Skiing': 'skiingAlpine',
        'Cross country skiing': 'skiingNordic',
        'Kayaking': 'boating',
        'Sea kayaking': 'boating',
        'Stand up paddle boarding': 'boating',
        'Rowing': 'boating',
        'Windsurfing': 'sailing',
        'Kiteboarding': 'sailing',
        'Orienteering': 'jogging',
        'Mountaineering': 'climbing',
        'Skateboarding': 'skating',
        'Horse riding': 'riding',
        'Hang gliding': 'flying',
        'Gliding': 'flying',
        'Snowboarding': 'wintersports',
        'Paragliding': 'flying',
        'Hot air ballooning': 'flying',
        'Nordic walking': 'walking',
        'Snowshoeing': 'snowshoe',
        'Jet skiing': 'motorboat',
        'Powerboating': 'motorboat',
        'Pack animal trekking': 'packAnimalTrekking'
    }

    def __init__(self, url=None, auth=None, cleanup=False, debug=False, timeout=None):
        if url is None:
            url = 'https://www.gpsies.com'
        super(GPSIES, self).__init__(url, auth, cleanup, debug, timeout)
        self.__session = None
        self.session_response = None

    @property
    def legal_whats(self):
        """
        Returns: list(str)
            all legal values for what."""
        if not self._legal_whats:
            response = requests.post('{}?trackList.do'.format(self.url), timeout=self.timeout)
            whats_parser = ParseGPSIESWhats()
            whats_parser.feed(response.text)
            self._legal_whats.extend(whats_parser.result)
        return self._legal_whats

    @property
    def session(self):
        """The requests.Session for this backend. Only initialized once."""
        if self.__session is None:
            if not self.auth:
                raise Exception('{}: Needs authentication data'.format(self.url))
            self.__session = requests.Session()
            data = {'username': self.auth[0], 'password': self.auth[1]}
            self.session_response = self.__session.post(
                '{}/loginLayer.do?language=en'.format(self.url),
                data=data, timeout=self.timeout)
            self._check_response(self.session_response)
        cookies = requests.utils.dict_from_cookiejar(self.__session.cookies)
        cookies['cookieconsent_dismissed'] = 'yes'
        self.__session.cookies = requests.utils.cookiejar_from_dict(cookies)
        return self.__session

    def __post(self, action: str, data, files=None):
        """common code for a POST within the session"""
        for key in data:
            data[key] = self._html_encode(data[key])
        if data.get('fileDescription'):
            data['fileDescription'] = '<p>{}</p>'.format(data['fileDescription'])
        response = self.session.post('{}/{}.do'.format(self.url, action), data=data, files=files, timeout=self.timeout)
        self._check_response(response)
        return response

    def decode_what(self, value: str) ->str:
        """Translate the value from Gpsies into internal one."""
        if value.capitalize() in Activity.legal_whats:
            return value.capitalize()
        if value not in self._what_decoding:
            raise self.BackendException('Gpsies gave us an unknown activity type {}'.format(value))
        return self._what_decoding[value]

    def encode_what(self, value: str) ->str:
        """Translate internal value into Gpsies value"""
        if value in self.legal_whats:
            return value
        if value.lower() in self.legal_whats:
            return value.lower()
        if value not in self._what_encoding:
            raise self.BackendException('Gpsies has no equivalent for {}'.format(value))
        return self._what_encoding[value]

    def _write_what(self, activity):
        """change what on gpsies"""
        self._edit(activity)

    def _write_description(self, activity):
        """change description on gpsies"""
        self._edit(activity)

    def _write_title(self, activity):
        """change title on gpsies"""
        self._edit(activity)

    def _write_public(self, activity):
        """change public on gpsies"""
        self._edit(activity)

    def _edit(self, activity):
        """edit directly on gpsies."""
        assert activity.id_in_backend
        data = {
            'edit':'',
            'fileId': activity.id_in_backend,
            'fileDescription': activity.description,
            'filename': activity.title,
            'status': '1' if activity.public else '3',
            'trackTypes': self.encode_what(activity.what),
            'websiteUrl':''}
        self.__post('editTrack', data)

    def _yield_activities(self):
        """get all activities for this user. If we do not use the generator
        created by yield_activity, unittest fails. Why?"""

        data = {'username': self.auth[0]}
        response = self.__post('trackList', data=data)
        page_parser = ParseGPSIESList()
        page_parser.feed(response.text)
        hrefs = []
        for line in response.text.split('\n'):
            if 'pagination' in line:
                hrefs = [x for x in line.split(' ') if x.startswith('href')]
        for href in hrefs[2:-2]:
            href = href[1:-1] # remove apostrophes
            parts = ''.join(href.split('?')[1:])
            parts = parts.split('&amp;')
            data = dict(x.split('=') for x in parts)
            response = self.__post('userList', data=data)
            page_parser.feed(response.text)
        for raw_data in page_parser.result['activities']:
            activity = self._found_activity(raw_data.activity_id)
            activity.header_data['title'] = raw_data.title
            activity.header_data['time'] = raw_data.time
            if raw_data.distance:
                activity.header_data['distance'] = raw_data.distance
            activity.header_data['public'] = raw_data.public
            if self.__session is None: # anonymous, no login
                activity.public = True
            yield activity

    def _read_what(self, activity):
        """I found no way to download all attributes in one go"""
        data = {'fileId': activity.id_in_backend}
        response = self.__post('editTrack', data)
        page_parser = ParseGPIESEditPage()
        page_parser.feed(response.text)
        activity.what = self.decode_what(page_parser.what)

    def _read_all(self, activity):
        """get the entire activity. For gpies, we only need the gpx file"""
        data = {'fileId': activity.id_in_backend, 'keepOriginalTimestamps': 'true'}
        response = self.__post('download', data=data)
        activity.parse(response.text)
        # in Activity, the results of a full load override header_data
        if 'public' in activity.header_data:
            # header_data is empty if this is a new activity we just wrote
            _ = activity.header_data['public']
            del activity.header_data['public']
            activity.public = _
        self._read_what(activity)

    def _check_response(self, response):
        """are there error messages?"""
        if response.status_code != 200:
            raise self.BackendException(response.text)
        if 'alert-danger' in response.text:
            _ = response.text.split('alert-danger">')[1].split('</div>')[0].strip()
            if '<li>' in _:
                _ = _.split('<li>')[1].split('</li>')[0]
            raise self.BackendException(_)
        if 'alert-warning' in response.text:
            _ = response.text.split('alert-warning">')[1].split('<')[0].strip()
            ignore_messages = (
                'This track is deleted and only shown by a direct URL call.',
                'Track is not public, can be seen only by me',
                'GPSies is my hobby website and is funded by advertising'
                )
            if not any(x in _ for x in ignore_messages):
                print('WARNING', ':', _)

    def _remove_activity(self, activity):
        """remove on the server"""
        data = {
            'fileId': activity.id_in_backend,
            'delete':'',
            'fileDescription':'n/a',
            'filename':'n/a',
            'status':'1',
            'trackTypes':'racingbike',
            'websiteUrl':''}
        self.__post('editTrack', data=data)

    def _write_all(self, activity) ->str:
        """save full gpx track on the GPSIES server.

        Returns:
            The new id_in_backend
        """
        files = {'formFile': (
            '{}.gpx'.format(self._html_encode(activity.title)), activity.to_xml(), 'application/gpx+xml')}
        data = {
            'filename': activity.title,
            'status': '1' if activity.public else '3',
            'fileDescription': activity.description,
            'trackTypes': self.encode_what(activity.what),
            'trackClassification':'withoutClassification',
            'trackSimplification': '0',
            'uploadButton':''}
        response = self.__post('upload', files=files, data=data)
        if 'Created' not in response.text:
            # not created
            raise self.BackendException(response.text)
        for line in response.text.split('\n'):
            if 'fileId=' in line:
                return line.split('fileId=')[1].split('"')[0]

    def destroy(self):
        """also close session"""
        super(GPSIES, self).destroy()
        if self.session:
            self.session.close()

GPSIES._define_support() # pylint: disable=protected-access
