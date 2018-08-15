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

from .. import Backend, Track

__all__ = ['GPSIES']

class GPSIESRawTrack:

    """raw data from the gpies html page"""

    # pylint: disable=too-few-public-methods
    def __init__(self):
        self.track_id = None
        self.title = None
        self.time = None
        self.distance = None
        self.public = True

class ParseGPSIESCategories(HTMLParser): # pylint: disable=abstract-method

    """Parse the legal values for category from html"""

    def __init__(self):
        super(ParseGPSIESCategories, self).__init__()
        self.result = list(['biking'])

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes':
            _ = attributes['id']
            if _ not in self.result:
                self.result.append(_)


class ParseGPIESEditPage(HTMLParser): # pylint: disable=abstract-method

    """Parse the category value for a track from html"""

    def __init__(self):
        super(ParseGPIESEditPage, self).__init__()
        self.category = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser"""
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes' and 'checked' in attributes:
            self.category = attributes['id']


class ParseGPSIESList(HTMLParser): # pylint: disable=abstract-method

    """get some attributes available only on the web page. Of course,
    this is highly unreliable. Just use what we can get."""

    def __init__(self):
        super(ParseGPSIESList, self).__init__()
        self.result = dict()
        self.result['tracks'] = list()
        self.track = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False
        self.seeing_warning = False

    def feed(self, data):
        self.track = None
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
            self.track = GPSIESRawTrack()
            self.column = 0
            self.seeing_a = False
        elif tag == 'td':
            self.column += 1
        elif self.after_list and tag == 'a':
            self.seeing_a = True
            value = attributes['value'].strip()
        elif tag == 'a' and 'href' in attributes and self.track.track_id is None:
            self.track.track_id = attributes['href'].split('fileId=')[1]
        elif tag == 'img' and self.track and 'lock.png' in attributes['src']:
            self.track.public = False

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
                if self.current_tag == 'i' and self.track.title is None:
                    self.track.title = data
            elif self.column == 4:
                if data.endswith('km'):
                    self.track.distance = float(data.replace(' km', '').replace(',', ''))
            elif self.column == 5:
                self.track.time = datetime.datetime.strptime(data, '%m/%d/%y')
                self.result['tracks'].append(self.track)


class GPSIES(Backend):
    """The implementation for gpsies.com.
    The track ident is the fileId given by gpsies.

    Searching arbitrary tracks is not supported. GPSIES only looks at the
    tracks of a specific user.

    Args:
        url (str): The Url of the server. Default is https://gpsies.com
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

    _category_decoding = {
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
        'skiingNordic': 'Cross country skiing',
        'skiingAlpine': 'Skiing',
        'skiingRandonnee': 'Skiing',
        'snowshoe': 'Snowshoeing',
        'wintersports': 'Miscellaneous',
        'sightseeing': 'Miscellaneous',
        'geocaching': 'Miscellaneous'
    }

    _category_encoding = {
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

    default_url = 'https://www.gpsies.com'

    def __init__(self, url=None, auth=None, cleanup=False, debug=False, timeout=None):
        if url is None:
            url = self.default_url
        super(GPSIES, self).__init__(url, auth, cleanup, debug, timeout)
        self.__session = None
        self.session_response = None

    @property
    def legal_categories(self):
        """
        Returns: list(str)
            all legal values for category."""
        if not self._legal_categories:
            response = requests.post('{}?trackList.do'.format(self.url), timeout=self.timeout)
            category_parser = ParseGPSIESCategories()
            category_parser.feed(response.text)
            self._legal_categories.extend(category_parser.result)
        return self._legal_categories

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

    def decode_category(self, value: str) ->str:
        """Translate the value from Gpsies into internal one."""
        if value.capitalize() in Track.legal_categories:
            return value.capitalize()
        if value not in self._category_decoding:
            raise self.BackendException('Gpsies gave us an unknown track type {}'.format(value))
        return self._category_decoding[value]

    def encode_category(self, value: str) ->str:
        """Translate internal value into Gpsies value"""
        if value in self.legal_categories:
            return value
        if value.lower() in self.legal_categories:
            return value.lower()
        if value not in self._category_encoding:
            raise self.BackendException('Gpsies has no equivalent for {}'.format(value))
        return self._category_encoding[value]

    def _write_category(self, track):
        """change category on gpsies"""
        self._edit(track)

    def _write_description(self, track):
        """change description on gpsies"""
        self._edit(track)

    def _write_title(self, track):
        """change title on gpsies"""
        self._edit(track)

    def _write_public(self, track):
        """change public on gpsies"""
        self._edit(track)

    def _edit(self, track):
        """edit directly on gpsies."""
        self._current_track = track
        assert track.id_in_backend
        data = {
            'edit':'',
            'fileId': track.id_in_backend,
            'fileDescription': track.description,
            'filename': track.title,
            'status': '1' if track.public else '3',
            'trackTypes': self.encode_category(track.category),
            'websiteUrl':''}

        # in about 1 out of 10 cases this update does not work.
        # Doing that on the website with firefox shows the same problem.
        # So reload and compare until both are identical.
        copy = track.clone()
        copy.id_in_backend = track.id_in_backend
        ctr = 0
        while True:
            self.__post('editTrack', data)
            self._read_all(copy)
            if track == copy:
                return
            ctr += 1
            if not ctr % 10:
                print('GPSIES._edit: {} tries'.format(ctr))
                if ctr > 50:
                    raise Backend.BackendException('GPSIES: _edit fails to change track {}'.format(track))

    def _yield_tracks(self):
        """get all tracks for this user."""

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
        for raw_data in page_parser.result['tracks']:
            # pylint: disable=protected-access
            track = self._found_track(raw_data.track_id)
            track._header_data['title'] = raw_data.title
            track._header_data['time'] = raw_data.time
            if raw_data.distance:
                track._header_data['distance'] = raw_data.distance
            track._header_data['public'] = raw_data.public
            if self.__session is None: # anonymous, no login
                track.public = True
            yield track

    def _read_category(self, track):
        """I found no way to download all attributes in one go"""
        self._current_track = track
        data = {'fileId': track.id_in_backend}
        response = self.__post('editTrack', data)
        page_parser = ParseGPIESEditPage()
        page_parser.feed(response.text)
        track.category = self.decode_category(page_parser.category)

    def _read_all(self, track):
        """get the entire track. For gpies, we only need the gpx file"""
        self._current_track = track
        data = {'fileId': track.id_in_backend, 'keepOriginalTimestamps': 'true'}
        response = self.__post('download', data=data)
        track.parse(response.text)
        # in Track, the results of a full load override _header_data
        # pylint: disable=protected-access
        if 'public' in track._header_data:
            # _header_data is empty if this is a new track we just wrote
            _ = track._header_data['public']
            del track._header_data['public']
            track.public = _
        self._read_category(track)

    def _check_response(self, response):
        """are there error messages?"""
        if response.status_code != 200:
            raise self.BackendException(response.text)
        if 'alert-danger' in response.text:
            _ = response.text.split('alert-danger">')[1].split('</div>')[0].strip()
            if '<li>' in _:
                _ = _.split('<li>')[1].split('</li>')[0]
            raise self.BackendException('{}: {}'.format(self._current_track, _))
        if 'alert-warning' in response.text:
            _ = response.text.split('alert-warning">')[1].split('<')[0].strip()
            ignore_messages = (
                'This track is deleted and only shown by a direct URL call.',
                'Track is not public, can be seen only by me',
                'GPSies is my hobby website and is funded by advertising'
                )
            if not any(x in _ for x in ignore_messages):
                print('WARNING', ':', self._current_track, _)

    def _remove_ident(self, ident: str):
        """remove on the server"""
        data = {
            'fileId': ident,
            'delete':'',
            'fileDescription':'n/a',
            'filename':'n/a',
            'status':'1',
            'trackTypes':'racingbike',
            'websiteUrl':''}
        self.__post('editTrack', data=data)

    def _write_all(self, track) ->str:
        """save full gpx track on the GPSIES server.

        Returns:
            The new id_in_backend
        """
        self._current_track = track
        files = {'formFile': (
            '{}.gpx'.format(self._html_encode(track.title)), track.to_xml(), 'application/gpx+xml')}
        data = {
            'filename': track.title,
            'status': '1' if track.public else '3',
            'fileDescription': track.description,
            'trackTypes': self.encode_category(track.category),
            'trackClassification':'withoutClassification',
            'trackSimplification': '0',
            'uploadButton':''}
        response = self.__post('upload', files=files, data=data)
        if 'Created' not in response.text:
            # not created
            raise self.BackendException('{}: {}'.format(self._current_track, response.text))
        new_ident = None
        for line in response.text.split('\n'):
            if 'fileId=' in line:
                new_ident = line.split('fileId=')[1].split('"')[0]
                break
        if not new_ident:
            raise self.BackendException('No fileId= found in response')
        if track.id_in_backend and track.id_in_backend != new_ident:
            self._remove_ident(track.id_in_backend)
        track.id_in_backend = new_ident
        return new_ident

    def destroy(self):
        """also close session"""
        super(GPSIES, self).destroy()
        if self.session:
            self.session.close()

GPSIES._define_support() # pylint: disable=protected-access
