#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.gpsies.GPSIES` for https://www.gpsies.com.

so ginge das mit dem API-Key: https://github.com/telemaxx/gpsiesreader/blob/master/gpsies3.py

"""

# pylint: disable=protected-access

from html.parser import HTMLParser
import datetime
import time
from collections import defaultdict

import requests

from .. import Backend, Track

__all__ = ['GPSIES']


class GPSIESRawTrack:

    """raw data from the gpies html page."""

    # pylint: disable=too-few-public-methods
    def __init__(self):
        """See class docstring."""
        self.track_id = None
        self.title = None
        self.time = None
        self.distance = None
        self.public = True


class ParseGPSIESCategories(HTMLParser):  # pylint: disable=abstract-method

    """Parse the legal values for category from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseGPSIESCategories, self).__init__()
        self.result = list(['biking'])

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes':
            _ = attributes['id']
            if _ not in self.result:
                self.result.append(_)


class ParseGPIESEditPage(HTMLParser):  # pylint: disable=abstract-method

    """Parse the category value for a track from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseGPIESEditPage, self).__init__()
        self.category = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes' and 'checked' in attributes:
            self.category = attributes['id']


class ParseGPSIESList(HTMLParser):  # pylint: disable=abstract-method

    """get some attributes available only on the web page.

    Of course, this is highly unreliable. Just use what we can get."""

    def __init__(self):
        """See class docstring."""
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
        """get data."""
        self.track = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False
        self.seeing_warning = False
        super(ParseGPSIESList, self).feed(data)

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
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
        """handle end of track list."""
        if tag == 'tbody':
            self.seeing_list = False
            self.after_list = True

    def handle_data(self, data):
        """data from the parser."""
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

    GPSIES does not support keywords. If you upload a track with keywords,
    they will silently be ignored.

    Args:
        url (str): The Url of the server. Default is https://gpsies.com
        auth (tuple(str, str)): Username and password
        cleanup (bool): If True, :meth:`~gpxity.backend.Backend.destroy` will remove all tracks in the
            user account.
        timeout: If None, there are no timeouts: Gpxity waits forever. For legal values
            see http://docs.python-requests.org/en/master/user/advanced/#timeouts

    """

    # pylint: disable=abstract-method

    _default_description = 'None yet. Let everyone know how you got on.'

    legal_categories = (
        'biking', 'trekking', 'walking', 'jogging', 'climbing', 'racingbike', 'mountainbiking',
        'pedelec', 'skating', 'crossskating', 'handcycle', 'motorbiking', 'motocross', 'motorhome',
        'cabriolet', 'car', 'riding', 'coach', 'packAnimalTrekking', 'swimming', 'canoeing', 'sailing',
        'boating', 'motorboat', 'skiingNordic', 'skiingAlpine', 'skiingRandonnee', 'snowshoe',
        'wintersports', 'flying', 'train', 'sightseeing', 'geocaching', 'miscellaneous')

    _category_decoding = {
        'biking': 'Cycling',
        'boating': 'Rowing',
        'car': 'Driving',
        'climbing': 'Mountaineering',
        'geocaching': 'Miscellaneous',
        'jogging': 'Running',
        'motocross': 'Enduro',
        'motorbiking': 'Motorcycling',
        'motorboat': 'Powerboating',
        'mountainbiking': 'Mountain biking',
        'packAnimalTrekking': 'Pack animal trekking',
        'racingbike': 'Cycling',
        'riding': 'Horse riding',
        'sightseeing': 'Miscellaneous',
        'skiingAlpine': 'Skiing',
        'skiingNordic': 'Cross country skiing',
        'skiingRandonnee': 'Skiing',
        'snowshoe': 'Snowshoeing',
        'trekking': 'Hiking',
        'wintersports': 'Miscellaneous',
    }

    _category_encoding = {
        'Cross country skiing': 'skiingNordic',
        'Cycling': 'biking',
        'Driving': 'car',
        'Enduro': 'motocross',
        'Gliding': 'flying',
        'Hang gliding': 'flying',
        'Hiking': 'trekking',
        'Horse riding': 'riding',
        'Hot air ballooning': 'flying',
        'Indoor cycling': 'biking',
        'Jet skiing': 'motorboat',
        'Kayaking': 'boating',
        'Kiteboarding': 'sailing',
        'Motor racing': 'motorbiking',
        'Motorcycling': 'motorbiking',
        'Mountain biking': 'mountainbiking',
        'Mountaineering': 'climbing',
        'Nordic walking': 'walking',
        'Off road driving': 'car',
        'Orienteering': 'jogging',
        'Pack animal trekking': 'packAnimalTrekking',
        'Paragliding': 'flying',
        'Powerboating': 'motorboat',
        'Rowing': 'boating',
        'Running': 'jogging',
        'Sea kayaking': 'boating',
        'Skateboarding': 'skating',
        'Skiing': 'skiingAlpine',
        'Snowboarding': 'wintersports',
        'Snowshoeing': 'snowshoe',
        'Stand up paddle boarding': 'boating',
        'Windsurfing': 'sailing',
    }

    default_url = 'https://www.gpsies.com'

    def __init__(self, url=None, auth=None, cleanup=False, timeout=None):
        """See class docstring."""
        if url is None:
            url = self.default_url
        super(GPSIES, self).__init__(url, auth, cleanup, timeout)
        self.session_response = None

    def _download_legal_categories(self):
        """Needed only for unittest.

        Returns: list(str)
            all legal values for category.

        """
        response = requests.post('{}?trackList.do'.format(self.url), timeout=self.timeout)
        category_parser = ParseGPSIESCategories()
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
            if not self.config.username or not self.config.password:
                raise self.BackendException('{}: Needs authentication data'.format(self.url))
            self._session[ident] = requests.Session()
            data = {'username': self.config.username, 'password': self.config.password}
            self.session_response = self._session[ident].post(
                '{}/loginLayer.do?language=en'.format(self.url),
                data=data, timeout=self.timeout)
            self._check_response(self.session_response)
            cookies = requests.utils.dict_from_cookiejar(self._session[ident].cookies)
            cookies['cookieconsent_dismissed'] = 'yes'
            self._session[ident].cookies = requests.utils.cookiejar_from_dict(cookies)
        return self._session[ident]

    def __post(self, action: str, data, files=None, track=None):
        """common code for a POST within the session.

        Returns:
            the response

        """
        for key in data:
            data[key] = self._html_encode(data[key])
        if data.get('fileDescription'):
            data['fileDescription'] = '<p>{}</p>'.format(data['fileDescription'])
        response = self.session.post('{}/{}.do'.format(self.url, action), data=data, files=files, timeout=self.timeout)
        self._check_response(response, track)
        return response

    def decode_category(self, value: str) ->str:
        """Translate the value from Gpsies into internal one.

        Returns:
            The decoded name

        """
        if value.capitalize() in Track.legal_categories:
            return value.capitalize()
        if value not in self._category_decoding:
            raise self.BackendException('Gpsies gave us an unknown track type {}'.format(value))
        return self._category_decoding[value]

    def encode_category(self, value: str) ->str:
        """Translate internal value into Gpsies value.

        Returns:
            The encoded name

        """
        if value in self.legal_categories:
            return value
        if value.lower() in self.legal_categories:
            return value.lower()
        if value not in self._category_encoding:
            raise self.BackendException('Gpsies has no equivalent for {}'.format(value))
        return self._category_encoding[value]

    def _write_category(self, track):
        """change category on gpsies."""
        self._edit(track)

    def _write_description(self, track):
        """change description on gpsies."""
        self._edit(track)

    def _write_title(self, track):
        """change title on gpsies."""
        self._edit(track)

    def _write_public(self, track):
        """change public on gpsies."""
        self._edit(track)

    def _edit(self, track):
        """edit directly on gpsies."""
        assert track.id_in_backend
        data = {
            'edit': '',
            'fileDescription': track.description,
            'fileId': track.id_in_backend,
            'filename': track.title,
            'status': '1' if track.public else '3',
            'trackTypes': self.encode_category(track.category),
            'websiteUrl': ''}

        # in about 1 out of 10 cases this update does not work.
        # Doing that on the website with firefox shows the same problem.
        # So reload and compare until both are identical.
        copy = track.clone()
        copy.id_in_backend = track.id_in_backend
        ctr = 0
        while True:
            self.__post('editTrack', data, track=track)
            self._read_all(copy)
            if track.description != copy.description:
                msg = 'description: {} -> {}'.format(copy.description, track.description)
            elif track.title != copy.title:
                msg = 'title: {} -> {}'.format(copy.title, track.title)
            elif track.public != copy.public:
                msg = 'public: {} -> {}'.format(copy.public, track.public)
            elif self.encode_category(track.category) != self.encode_category(copy.category):
                msg = 'category: {}/{} -> {}/{}'.format(
                    copy.category, self.encode_category(copy.category),
                    track.category, self.encode_category(track.category))
            else:
                return
            ctr += 1
            time.sleep(1)
            if ctr > 50:
                raise Backend.BackendException(
                    'GPSIES: _edit fails to change track {}: {}'.format(track, msg))
            time.sleep(2)

    def _load_track_headers(self):
        """get all tracks for this user."""

        data = {'username': self.config.username}
        response = self.__post('trackList', data=data)
        page_parser = ParseGPSIESList()
        page_parser.feed(response.text)
        hrefs = []
        for line in response.text.split('\n'):
            if 'pagination' in line:
                hrefs = [x for x in line.split(' ') if x.startswith('href')]
        for href in hrefs[2:-2]:
            href = href[1:-1]  # remove apostrophes
            parts = ''.join(href.split('?')[1:])
            parts = parts.split('&amp;')
            data = dict(x.split('=') for x in parts)  # noqa
            response = self.__post('userList', data=data)
            page_parser.feed(response.text)
        for raw_data in page_parser.result['tracks']:
            track = self._found_track(raw_data.track_id)
            track._header_data['title'] = raw_data.title
            track._header_data['time'] = raw_data.time
            if raw_data.distance:
                track._header_data['distance'] = raw_data.distance
            track._header_data['public'] = raw_data.public
            if str(self) not in self._session:  # anonymous, no login
                track.public = True

    def _read_category(self, track):
        """I found no way to download all attributes in one go."""
        data = {'fileId': track.id_in_backend}
        response = self.__post('editTrack', data, track=track)
        page_parser = ParseGPIESEditPage()
        page_parser.feed(response.text)
        track.category = self.decode_category(page_parser.category)

    def _read_all(self, track):
        """get the entire track. For gpies, we only need the gpx file."""
        data = {'fileId': track.id_in_backend, 'keepOriginalTimestamps': 'true'}
        response = self.__post('download', data=data, track=track)
        track.parse(response.text)
        # in Track, the results of a full load override _header_data
        if 'public' in track._header_data:
            # _header_data is empty if this is a new track we just wrote
            _ = track._header_data['public']
            del track._header_data['public']
            track.public = _
        self._read_category(track)

    def _check_response(self, response, track=None):
        """are there error messages?."""
        trk_str = '{}: '.format(track) if track is not None else ''
        if response.status_code != 200:
            raise self.BackendException(response.text)
        if 'alert-danger' in response.text:
            _ = response.text.split('alert-danger">')[1].split('</div>')[0].strip()
            if '<li>' in _:
                _ = _.split('<li>')[1].split('</li>')[0]
            raise self.BackendException(trk_str + _)
        if 'alert-warning' in response.text:
            _ = response.text.split('alert-warning">')[1].split('<')[0].strip()
            ignore_messages = (
                'This track is deleted and only shown by a direct URL call.',
                'Track is not public, can be seen only by me',
                'GPSies is my hobby website and is funded by advertising'
            )
            if not any(x in _ for x in ignore_messages):
                self.logger.warning(trk_str + _)

    def _remove_ident(self, ident: str):
        """remove on the server."""
        data = {
            'delete': '',
            'fileDescription': 'n/a',
            'fileId': ident,
            'filename': 'n/a',
            'status': '1',
            'trackTypes': 'racingbike',
            'websiteUrl': ''}
        self.__post('editTrack', data=data)

    def _write_all(self, track) ->str:
        """save full gpx track on the GPSIES server.

        Returns:
            The new id_in_backend

        """
        files = {'formFile': (
            '{}.gpx'.format(self._html_encode(track.title)), track.to_xml(), 'application/gpx+xml')}
        data = {
            'fileDescription': track.description,
            'filename': track.title,
            'status': '1' if track.public else '3',
            'trackClassification': 'withoutClassification',
            'trackSimplification': '0',
            'trackTypes': self.encode_category(track.category),
            'uploadButton': ''}
        response = self.__post('upload', files=files, data=data, track=track)
        if 'Created' not in response.text:
            # not created
            raise self.BackendException('{}: {}'.format(track, response.text))
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
        """also close session."""
        super(GPSIES, self).destroy()
        if self.session:
            self.session.close()

    @classmethod
    def _define_support(cls):
        """GPSIES special case."""
        super(GPSIES, cls)._define_support()
        cls.supported.remove('keywords')
