#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
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

from .. import Backend
from ..gpx import Gpx

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

    def __str__(self):
        """Self speaking.

        Returns: str()

        """
        return '{} GPSIESRawTrack({}) title={} time={} distance={} public={}'.format(
            id(self), self.track_id, self.title, self.time, self.distance, self.public)

    def __repr__(self):
        """Self speaking.

        Returns: repr()

        """
        return self.__str__()


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

    """Parse the category value for a gpxfile from html."""

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
        self.result['gpxfiles'] = list()
        self.gpxfile = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False
        self.seeing_warning = False

    def feed(self, data):
        """get data."""
        self.gpxfile = None
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
            self.gpxfile = GPSIESRawTrack()
            self.column = 0
            self.seeing_a = False
        elif tag == 'td':
            self.column += 1
        elif self.after_list and tag == 'a':
            self.seeing_a = True
            value = attributes['value'].strip()
        elif tag == 'a' and 'href' in attributes and 'map.do?'in attributes['href'] and self.gpxfile.track_id is None:
            self.gpxfile.track_id = attributes['href'].split('fileId=')[1]
        elif tag == 'img' and self.gpxfile and 'lock.png' in attributes['src']:
            self.gpxfile.public = False

    def handle_endtag(self, tag):
        """handle end of gpxfile list."""
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
                if self.current_tag == 'i' and self.gpxfile.title is None:
                    self.gpxfile.title = data
            elif self.column == 4:
                if data.endswith('km'):
                    self.gpxfile.distance = float(data.replace(' km', '').replace(',', ''))
            elif self.column == 5:
                if self.gpxfile not in self.result['gpxfiles']:
                    data = data.replace('Last change:: ', '')  # gpsies has changed
                    self.gpxfile.time = datetime.datetime.strptime(data, '%m/%d/%y')
                    self.result['gpxfiles'].append(self.gpxfile)


class GPSIES(Backend):

    """The implementation for gpsies.com.

    The gpxfile ident is the fileId given by gpsies.

    Searching arbitrary gpxfiles is not supported. GPSIES only looks at the
    gpxfiles of a specific user.

    GPSIES does not support keywords. If you upload a gpxfile with keywords,
    they will silently be ignored.

    Args:
        account (:class:`~gpxity.accounts.Account`): The account to be used.
            Alternatively a dict can be passed to build an ad hoc :class:`~gpxity.accounts.Account`
            instance.

    """

    # pylint: disable=abstract-method

    _default_description = 'None yet. Let everyone know how you got on.'

    supported_categories = (
        'biking', 'trekking', 'walking', 'jogging', 'climbing', 'racingbike', 'mountainbiking',
        'pedelec', 'skating', 'crossskating', 'handcycle', 'motorbiking', 'motocross', 'motorhome',
        'cabriolet', 'car', 'riding', 'coach', 'packAnimalTrekking', 'swimming', 'canoeing', 'sailing',
        'boating', 'motorboat', 'skiingNordic', 'skiingAlpine', 'skiingRandonnee', 'snowshoe', 'trailrunning',
        'speedhiking', 'wintersports', 'flying', 'train', 'sightseeing', 'geocaching', 'miscellaneous')

    _category_decoding = {
        'biking': 'Cycling',
        'boating': 'Rowing',
        'car': 'Driving',
        'climbing': 'Mountaineering',
        'handcycle': 'Cycling - Hand',
        'jogging': 'Running',
        'motocross': 'Enduro',
        'motorbiking': 'Motorcycling',
        'motorboat': 'Powerboating',
        'mountainbiking': 'Cycling - MTB',
        'packAnimalTrekking': 'Pack animal trekking',
        'racingbike': 'Cycling - Road',
        'riding': 'Horse riding',
        'skiingAlpine': 'Skiing - Alpine',
        'skiingNordic': 'Skiing - Nordic',
        'skiingRandonnee': 'Skiing - Touring',
        'snowshoe': 'Snowshoeing',
        'speedhiking': 'Hiking - Speed',
        'trailrunning': 'Running - Trail',
        'trekking': 'Hiking',
        'wintersports': 'Wintersports',
    }

    _category_encoding = {
        'Cycling - Foot': 'biking',
        'Cycling - Gravel': 'biking',
        'Cycling - Hand': 'handcycle',
        'Cycling - Indoor': 'biking',
        'Cycling - Road': 'racingbike',
        'Cycling - Touring': 'biking',
        'Driving': 'car',
        'Enduro': 'motocross',
        'Gliding': 'flying',
        'Hang gliding': 'flying',
        'Hiking': 'trekking',
        'Horse riding': 'riding',
        'Hot air ballooning': 'flying',
        'Jet skiing': 'motorboat',
        'Kayaking': 'boating',
        'Kiteboarding': 'sailing',
        'Longboard': 'miscellaneous',
        'Motor racing': 'motorbiking',
        'Motorcycling': 'motorbiking',
        'Mountaineering': 'climbing',
        'Nordic walking': 'walking',
        'Off road driving': 'car',
        'Orienteering': 'jogging',
        'Pack animal trekking': 'packAnimalTrekking',
        'Paragliding': 'flying',
        'Powerboating': 'motorboat',
        'River navigation': 'miscellaneous',
        'Rowing': 'boating',
        'Running': 'jogging',
        'Running - Road': 'jogging',
        'Running - Urban Trail': 'jogging',
        'Sea kayaking': 'boating',
        'Skateboarding': 'skating',
        'Skating - Inline': 'skating',
        'Skiing': 'wintersports',
        'Skiing - Alpine': 'skiingAlpine',
        'Skiing - Backcountry': 'skiingRandonnee',
        'Skiing - Crosscountry': 'skiingRandonnee',
        'Skiing - Roller': 'miscellaneous',
        'Skiing - Touring': 'skiingRandonnee',
        'Snowboarding': 'wintersports',
        'Snowshoeing': 'snowshoe',
        'Stand up paddle boarding': 'boating',
        'Swimrun': 'miscellaneous',
        'Wheelchair': 'miscellaneous',
        'Windsurfing': 'sailing',
        'Wintersports': 'wintersports',
    }

    default_url = 'https://www.gpsies.com'

    def __init__(self, account):
        """See class docstring."""
        super(GPSIES, self).__init__(account)
        self._session_response = None

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
            author = self._get_author()
            if not self.account.password:
                raise self.BackendException('{}: Needs authentication data'.format(self.url))
            self._session[ident] = requests.Session()
            data = {'username': author, 'password': self.account.password}
            self._session_response = self._session[ident].post(
                '{}/loginLayer.do?language=en'.format(self.url),
                data=data, timeout=self.timeout)
            self._check_response(self._session_response)
            cookies = requests.utils.dict_from_cookiejar(self._session[ident].cookies)
            cookies['cookieconsent_dismissed'] = 'yes'
            self._session[ident].cookies = requests.utils.cookiejar_from_dict(cookies)
        return self._session[ident]

    def __post(self, action: str, data, files=None, gpxfile=None):
        """common code for a POST within the session.

        Returns:
            the response

        """
        for key in data:
            data[key] = self._html_encode(data[key])
        if data.get('fileDescription'):
            data['fileDescription'] = '<p>{}</p>'.format(data['fileDescription'])
        action_url = '{}/{}.do'.format(self.url, action)
        response = self.session.post(action_url, data=data, files=files, timeout=self.timeout)
        self._check_response(response, gpxfile)
        return response

    def _write_category(self, gpxfile):
        """change category on gpsies."""
        self._edit(gpxfile)

    def _write_description(self, gpxfile):
        """change description on gpsies."""
        self._edit(gpxfile)

    def _write_title(self, gpxfile):
        """change title on gpsies."""
        self._edit(gpxfile)

    def _write_public(self, gpxfile):
        """change public on gpsies."""
        self._edit(gpxfile)

    def _edit(self, gpxfile):
        """edit directly on gpsies."""
        assert gpxfile.id_in_backend
        data = {
            'edit': '',
            'fileDescription': gpxfile.description,
            'fileId': gpxfile.id_in_backend,
            'filename': gpxfile.title,
            'status': '1' if gpxfile.public else '3',
            'trackTypes': self.encode_category(gpxfile.category),
            'websiteUrl': ''}

        # in about 1 out of 10 cases this update does not work.
        # Doing that on the website with firefox shows the same problem.
        # So reload and compare until both are identical.
        copy = gpxfile.clone()
        copy.id_in_backend = gpxfile.id_in_backend
        ctr = 0
        while True:
            self.__post('editTrack', data, gpxfile=gpxfile)
            self._read_all(copy)
            if gpxfile.description != copy.description:
                msg = 'description: {} -> {}'.format(copy.description, gpxfile.description)
            elif gpxfile.title != copy.title:
                msg = 'title: {} -> {}'.format(copy.title, gpxfile.title)
            elif gpxfile.public != copy.public:
                msg = 'public: {} -> {}'.format(copy.public, gpxfile.public)
            elif self.encode_category(gpxfile.category) != self.encode_category(copy.category):
                msg = 'category: {}/{} -> {}/{}'.format(
                    copy.category, self.encode_category(copy.category),
                    gpxfile.category, self.encode_category(gpxfile.category))
            else:
                return
            ctr += 1
            time.sleep(1)
            if ctr > 50:
                raise Backend.BackendException(
                    'GPSIES: _edit fails to change gpxfile {}: {}'.format(gpxfile, msg))
            time.sleep(2)

    def _load_track_headers(self):
        """get all gpxfiles for this user."""
    #    return
        response = self.__post('trackList', data={'username': self._get_author()})
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
        for raw_data in page_parser.result['gpxfiles']:
            gpx = Gpx()
            gpx.name = raw_data.title
            gpx.time = raw_data.time
            public = raw_data.public
            if str(self) not in self._session:  # anonymous, no login
                public = True
            gpx.keywords = 'Status:{}, Category:{}'.format('public' if public else 'private', Gpx.undefined_str)
            gpxfile = self._found_track(raw_data.track_id, gpx)
            if raw_data.distance:
                gpxfile.distance = raw_data.distance

    def _read_category(self, gpxfile):
        """I found no way to download all attributes in one go."""
        data = {'fileId': gpxfile.id_in_backend}
        response = self.__post('editTrack', data, gpxfile=gpxfile)
        page_parser = ParseGPIESEditPage()
        page_parser.feed(response.text)
        gpxfile.category = self.decode_category(page_parser.category)

    def _read_all(self, gpxfile):
        """get the entire gpxfile. For gpies, we only need the gpx file."""
        data = {'fileId': gpxfile.id_in_backend, 'keepOriginalTimestamps': 'true'}
        response = self.__post('download', data=data, gpxfile=gpxfile)
        gpxfile.gpx = Gpx.parse(response.text)
        self._read_category(gpxfile)

    def _check_response(self, response, gpxfile=None):
        """are there error messages?."""
        trk_str = '{}: '.format(gpxfile) if gpxfile is not None else ''
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
                'This gpxfile is deleted and only shown by a direct URL call.',
                'GpxFile is not public, can be seen only by me',
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

    def _write_all(self, gpxfile) ->str:
        """save full gpx gpxfile on the GPSIES server.

        Returns:
            The new id_in_backend

        """
        files = {'formFile': (
            '{}.gpx'.format(self._html_encode(gpxfile.title)), gpxfile.xml(), 'application/gpx+xml')}
        data = {
            'fileDescription': gpxfile.description,
            'filename': gpxfile.title,
            'status': '1' if gpxfile.public else '3',
            'trackClassification': 'withoutClassification',
            'trackSimplification': '0',
            'trackTypes': self.encode_category(gpxfile.category),
            'uploadButton': ''}
        response = self.__post('upload', files=files, data=data, gpxfile=gpxfile)
        if 'Created' not in response.text:
            # not created
            raise self.BackendException('{}: {}'.format(gpxfile, response.text))
        new_ident = None
        for line in response.text.split('\n'):
            if 'fileId=' in line:
                new_ident = line.split('fileId=')[1].split('"')[0]
                break
        if not new_ident:
            raise self.BackendException('No fileId= found in response')
        if gpxfile.id_in_backend and gpxfile.id_in_backend != new_ident:
            self._remove_ident(gpxfile.id_in_backend)
        gpxfile.id_in_backend = new_ident
        return new_ident

    def detach(self):
        """also close session."""
        super(GPSIES, self).detach()
        if self.session:
            self.session.close()

    @classmethod
    def _define_support(cls):
        """GPSIES does not support keywords.

        TODO: encode them in the description.

        """
        super(GPSIES, cls)._define_support()
        cls.supported.remove('keywords')
