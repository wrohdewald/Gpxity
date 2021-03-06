#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This implements :class:`gpxity.openrunner.Openrunner` for https://www.openrunner.com."""

# pylint: disable=protected-access

from html.parser import HTMLParser
import datetime
from collections import defaultdict

import logging

import requests
from gpxpy import gpx as mod_gpx


from .. import Backend
from ..gpx import Gpx

GPXTrackPoint = mod_gpx.GPXTrackPoint

if False:  # pylint: disable=using-constant-test
    try:
        import http.client as http_client
    except ImportError:
        # Python 2
        import httplib as http_client
    http_client.HTTPConnection.debuglevel = 1

__all__ = ['Openrunner']


class OpenrunnerRawTrack:

    """raw data from the gpies html page."""

    # pylint: disable=too-few-public-methods
    def __init__(self):
        """See class docstring."""
        self.track_id = None
        self.title = None
        self.time = None
        self.distance = None
        self.category = None


class ParseOpenrunnerCategories(HTMLParser):  # pylint: disable=abstract-method

    """Parse the legal values for category from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseOpenrunnerCategories, self).__init__()
        self.result_names = ['Other']
        self.result_ids = [2]
        self.current_tag = None
        self.seeing_list = False

    def feed(self, data):
        """get data."""
        self.seeing_list = False
        super(ParseOpenrunnerCategories, self).feed(data)

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        self.current_tag = tag
        attributes = defaultdict(str)
        for key, value in attrs:
            attributes[key] = value
        if tag == 'select' and attributes['id'] == 'search_activity':
            self.seeing_list = True
        if self.seeing_list and tag == 'option':
            if attributes['value'] != '':
                self.result_ids.append(int(attributes['value']))

    def handle_endtag(self, tag):
        """handle end of gpxfile list."""
        if tag == 'select':
            self.seeing_list = False

    def handle_data(self, data):
        """data from the parser."""
        if self.seeing_list:
            data = data.strip()
            if not data:
                return
            if self.current_tag == 'option':
                if data != 'Select an activity':
                    self.result_names.append(data)


class ParseOpenrunnerSubscription(HTMLParser):  # pylint: disable=abstract-method

    """Parse the current subscription from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseOpenrunnerSubscription, self).__init__()
        self.category = None
        self.seeing_card_title = False
        self.current_card_title = None
        self.result = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        attributes = dict(attrs)
        self.seeing_card_title = False
        if attributes.get('class') == 'card-title':
            self.seeing_card_title = True
            self.current_card_title = None

    def handle_data(self, data):
        """Handle data."""
        data = data.strip()
        if data == '':
            return
        if self.seeing_card_title:
            self.current_card_title = data
        if data == 'Subscription in progress':
            self.result = self.current_card_title


class ParseOpenrunnerActivity(HTMLParser):  # pylint: disable=abstract-method

    """Parse the category value for a gpxfile from html."""

    def __init__(self):
        """See class docstring."""
        super(ParseOpenrunnerActivity, self).__init__()
        self.current_tag = None
        self.category = None

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        self.current_tag = tag
        attributes = defaultdict(str)  # TODO: class MyHTMLParser with attributes getter
        for key, value in attrs:
            attributes[key] = value
        attributes = dict(attrs)
        if tag == 'input' and attributes['name'] == 'trackTypes' and 'checked' in attributes:
            self.category = attributes['id']


class ParseOpenrunnerList(HTMLParser):  # pylint: disable=abstract-method

    """get some attributes available only on the web page.

    Of course, this is highly unreliable. Just use what we can get."""

    def __init__(self):
        """See class docstring."""
        super(ParseOpenrunnerList, self).__init__()
        self.result = dict()
        self.result['gpxfiles'] = list()
        self.gpxfile = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False

    def feed(self, data):
        """get data."""
        self.gpxfile = None
        self.column = 0
        self.current_tag = None
        self.seeing_list = False
        self.after_list = False
        self.seeing_a = False
        super(ParseOpenrunnerList, self).feed(data)

    def handle_starttag(self, tag, attrs):
        """starttag from the parser."""
        self.current_tag = tag
        attributes = defaultdict(str)
        for key, value in attrs:
            attributes[key] = value
        if tag == 'tbody':
            self.seeing_list = True
        if not self.seeing_list:
            return
        if tag == 'tr':
            self.gpxfile = OpenrunnerRawTrack()
            self.column = 0
            self.seeing_a = False
        elif tag == 'td':
            self.column += 1
        elif self.after_list and tag == 'a':
            self.seeing_a = True
            value = attributes['value'].strip()

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
        if self.seeing_list:
            if self.column == 2:
                self.gpxfile.track_id = data
            elif self.column == 3:
                if self.current_tag == 'h6' and self.gpxfile.title is None:
                    self.gpxfile.title = data
            elif self.column == 4:
                self.gpxfile.category = data
            elif self.column == 7:
                self.gpxfile.distance = float(data)
            elif self.column == 10:
                self.gpxfile.time = datetime.datetime.strptime(data, '%d-%m-%Y').replace(tzinfo=datetime.timezone.utc)
                self.result['gpxfiles'].append(self.gpxfile)


class Openrunner(Backend):

    """The implementation for openrunner.com.

    The gpxfile ident is the ID given by openrunner.

    Searching arbitrary gpxfiles is not supported. Openrunner only looks at the
    gpxfiles of a specific user.

    Args:
        account (:class:`~gpxity.accounts.Account`): The account to be used.
            Alternatively a dict can be passed to build an ad hoc :class:`~gpxity.accounts.Account`
            instance.

    """

    # pylint: disable=abstract-method

    max_field_sizes = {'keywords': 200}

    _default_description = 'None yet. Let everyone know how you got on.'

    point_precision = 5

    supported_categories = (
        'Cycling - Road',
        'Canoe-Kayak',
        'Cycling - Gravel',
        'Cycling - MTB',
        'Cycling - Touring',
        'Footbiking',
        'Hiking',
        'Horse riding',
        'Longboard',
        'Nordic walking',
        'River navigation',
        'Rollerblading',
        'Running - Trail',
        'Running - Urban Trail',
        'Running- Road',
        'Skiing - Backcountry',
        'Skiing - Crosscountry',
        'Skiing - Rollerskiing',
        'Skiing - Touring',
        'Snowshoeing',
        'Stand Up Paddle',
        'Swimming',
        'Swimrun',
        'Walking',
        'Other'
    )

    _category_decoding = {
        'Canoe-Kayak': 'Canoeing',
        'Footbiking': 'Cycling - Foot',
        'Longboard': 'Miscellaneous',
        'Other': 'Miscellaneous',
        'River navigation': 'Miscellaneous',
        'Rollerblading': 'Skating - Inline',
        'Running - Trail': 'Running',
        'Running - Urban Trail': 'Running',
        'Running- Road': 'Running - Road',
        'Skiing - Rollerskiing': 'Skiing - Roller',
        'Stand Up Paddle': 'Stand up paddle boarding',
        'Swimrun': 'Swimming',
    }

    # translate internal names to Openrunner names
    _category_encoding = {
        'Cabriolet': 'Other',
        'Canoeing': 'Canoe-Kayak',
        'Coach': 'Other',
        'Crossskating': 'Other',
        'Cycling': 'Cycling - Road',
        'Cycling - Foot': 'Footbiking',
        'Cycling - Hand': 'Cycling - Road',
        'Cycling - Indoor': 'Other',
        'Driving': 'Other',
        'Enduro': 'Other',
        'Flying': 'Other',
        'Geocaching': 'Other',
        'Gliding': 'Other',
        'Hang gliding': 'Other',
        'Hiking - Speed': 'Hiking',
        'Hot air ballooning': 'Other',
        'Jet skiing': 'Other',
        'Kayaking': 'Canoe-Kayak',
        'Kiteboarding': 'Other',
        'Miscellaneous': 'Other',
        'Motor racing': 'Other',
        'Motorcycling': 'Other',
        'Motorhome': 'Other',
        'Mountaineering': 'Other',
        'Nordic walking': 'Other',
        'Off road driving': 'Other',
        'Orienteering': 'Other',
        'Pack animal trekking': 'Horse riding',
        'Paragliding': 'Other',
        'Pedelec': 'Other',
        'Powerboating': 'River navigation',
        'Rowing': 'River navigation',
        'Running': 'Running- Road',
        'Running - Road': 'Running- Road',
        'Sailing': 'Other',
        'Sea kayaking': 'Canoe-Kayak',
        'Sightseeing': 'Other',
        'Skateboarding': 'Other',
        'Skating': 'Other',
        'Skating - Inline': 'Rollerblading',
        'Skiing': 'Skiing - Touring',
        'Skiing - Alpine': 'Other',
        'Skiing - Nordic': 'Skiing - Backcountry',
        'Skiing - Touring': 'Skiing - Backcountry',
        'Snowboarding': 'Other',
        'Snowshoeing': 'Other',
        'Stand up paddle boarding': 'Stand Up Paddle',
        'Train': 'Other',
        'Wheelchair': 'Other',
        'Windsurfing': 'Other',
        'Wintersports': 'Other',
    }

    # translate Openrunner names to Openrunner numbers
    _legal_categories_numbers = {
        'Canoe-Kayak': 18,
        'Cycling - Gravel': 20,
        'Cycling - MTB': 3,
        'Cycling - Road': 1,
        'Cycling - Touring': 11,
        'Footbiking': 13,
        'Hiking': 9,
        'Horse riding': 4,
        'Longboard': 25,
        'Nordic walking': 12,
        'Other': 2,
        'River navigation': 8,
        'Rollerblading': 5,
        'Running - Trail': 10,
        'Running - Urban Trail': 19,
        'Running- Road': 21,
        'Skiing - Backcountry': 14,
        'Skiing - Crosscountry': 15,
        'Skiing - Rollerskiing': 16,
        'Skiing - Touring': 22,
        'Snowshoeing': 17,
        'Stand Up Paddle': 24,
        'Swimming': 6,
        'Swimrun': 23,
        'Walking': 7,
    }

    assert set(_legal_categories_numbers.keys()) == set(supported_categories)

    default_url = 'https://www.openrunner.com'

    @staticmethod
    def __encode_number(nbr) -> str:
        """Encode a single unsigned number.

        Returns: the encoded string

        """
        result = ''
        while nbr >= 32:
            result += chr(95 + (nbr & 31))
            nbr >>= 5
        result += chr(63 + nbr)
        return result

    @classmethod
    def __encode_signed_number(cls, nbr) ->str:
        """Encode a single signed number.

        Returns: The encoded string

        """
        tmp = nbr << 1
        if nbr < 0:
            tmp = ~tmp
        return cls.__encode_number(tmp)

    @classmethod
    def _encode_points(cls, points) ->str:
        """Encode a list of points.

        Returns: the encoded string

        """
        result = ''
        prev_lat = 0
        prev_lon = 0
        for point in points:
            lat = round(point.latitude * 100000)
            lon = round(point.longitude * 100000)
            delta_lat = lat - prev_lat
            delta_lon = lon - prev_lon
            prev_lat = lat
            prev_lon = lon
            result += cls.__encode_signed_number(delta_lat)
            result += cls.__encode_signed_number(delta_lon)
        return result

    @staticmethod
    def _decode_points(input_str) ->list:
        """Decode str into a list of points.

        Returns: list(GPXTrackPoint)

        """
        def decode_number():
            """Decode a single number."""
            nonlocal input_str
            result = 0
            shift = 0
            while True:
                ord_value = ord(input_str[0]) - 63
                result |= (31 & ord_value) << shift
                input_str = input_str[1:]
                if ord_value < 32:
                    break
                shift += 5
            if 1 & result:
                return ~(result >> 1)
            return result >> 1

        def blow_up(nbr):
            return round(0.00001 * nbr, 5)
        result = list()
        latitude = longitude = 0
        while input_str:
            latitude += decode_number()
            longitude += decode_number()
            result.append(GPXTrackPoint(latitude=blow_up(latitude), longitude=blow_up(longitude)))
        return result

    def _download_legal_categories(self):
        """Needed only for unittest.

        Returns: list(str)
            all legal values for category.

        """
        response = self.__get(action='route/search/page')
        category_parser = ParseOpenrunnerCategories()
        category_parser.feed(response.text)
        return sorted(category_parser.result_names)

    @property
    def subscription(self) ->str:
        """Get the subscription model.

        Returns: The name of the subscription.

        """
        if self._cached_subscription is None:
            parser = ParseOpenrunnerSubscription()
            parser.feed(self.__get(action='user/mysubscription').text)
            if parser.result == 'Standard':
                self._cached_subscription = 'free'
            else:
                self._cached_subscription = 'full'
            self.logger.debug('%s: subscription: %s', self.account, self._cached_subscription)
        return self._cached_subscription

    @property
    def session(self):
        """The requests.Session for this backend. Only initialized once.

        Returns:
            The session

        """
        ident = str(self)
        if ident not in self._session:
            if not self.account.username:
                raise self.BackendException('{}: Needs authentication data'.format(self.url))
            self._session[ident] = requests.Session()
            if self.account.password:
                data = {
                    'language': 'en',
                    'login': self.account.username,
                    'password': self.account.password,
                }
                self._session[ident].response = self._session[ident].post(
                    '{}/user/login'.format(self.url),
                    data=data, timeout=self.timeout)
                self._check_response(self._session_response, data)
        if self._session_response is None:
            self.logger.info('Openrunner.session got no _session_response')
        return self._session[ident]

    @property
    def _session_response(self):
        """The last response received.

        Returns: The response

        """
        # TODO: also in GPSIES
        ident = str(self)
        if ident in self._session:
            if hasattr(self._session[ident], 'response'):
                return self._session[ident].response
        return None

    def __http_post(self, post_type, action: str, data=None):
        """Common code for HTTP POST.

        Returns: the response

        """
        if data is None:
            data = dict()
        data['_'] = int(datetime.datetime.now().timestamp())
        full_url = '{}/{}'.format(self.url, action)
        self.session  # because headers needs accessToken  pylint: disable=pointless-statement
        headers = {'X-Language': 'en'}
        if self._session_response:
            headers['Authorization'] = 'Bearer {}'.format(self._session_response.json()['user']['accessToken'])
            method = getattr(self.session, post_type)
        else:
            method = getattr(requests, post_type)
        response = method(full_url, data=data, headers=headers, timeout=self.timeout)
        self._check_response(response, data)
        return response

    def __get(self, action: str, data=None):
        """common code for a GET within the session.

        Returns: the response

        """
        return self.__http_post("get", action, data)

    def __post(self, action: str, data):
        """common code for a POST within the session.

        Returns: the response

        """
        return self.__http_post("post", action, data)

    def __delete(self, action: str, data):
        """common code for a POST within the session.

        Returns:
            the response

        """
        return self.__http_post("delete", action, data)

    @classmethod
    def decode_category(cls, value: str) ->str:
        """Translate the value from Openrunner into internal one.

        Returns:
            The decoded name

        """
        try:
            return super(Openrunner, cls).decode_category(value)
        except Exception:
            if value == 'Autre':  # TODO: Should not happen
                logging.error("Openrunner said Autre")
                return 'Miscellaneous'
            reverse_nbr = dict(zip(cls._legal_categories_numbers.values(), cls._legal_categories_numbers.keys()))
            try:
                if int(value) in reverse_nbr:
                    return cls.decode_category(reverse_nbr[int(value)])
            except ValueError:
                pass
            raise cls.BackendException('Openrunner gave us an unknown gpxfile type {}'.format(value))

    def _list(self):
        """get all gpxfiles for this user."""
        if self.account.password:
            response = self.__get(action='user/myroute')
        else:
            response = self.__get(action='route/findby?author={}'.format(self._get_author()))
        page_parser = ParseOpenrunnerList()
        page_parser.feed(response.text)
        for raw_data in page_parser.result['gpxfiles']:
            gpxfile = self._found_gpxfile(raw_data.track_id, Gpx())
            gpxfile.gpx.is_complete = False
            gpxfile.title = raw_data.title
            gpxfile.time = raw_data.time
            if raw_data.distance:
                gpxfile.distance = raw_data.distance
            if raw_data.category:
                gpxfile.category = self.decode_category(raw_data.category)

    def _read(self, gpxfile):
        """Get the entire gpxfile."""
        response = self.__get(action='route/{}'.format(gpxfile.id_in_backend))
        route = response.json()['route']
        points = self._decode_points(route['shape']['full_encoded'])
        gpx = Gpx()
        gpx.add_points(points)
        gpx.name = route['name']
        gpx.description = route['description']
        gpx.keywords = route['keyword']
        gpxfile.gpx = gpx
        # the date format seems to depend on the language. fr would be %d-%m-%Y
        gpxfile.time = datetime.datetime.strptime(
            route['updatedDate'], '%Y/%m/%d').replace(tzinfo=datetime.timezone.utc)
        gpxfile.public = not route['private']
        gpxfile.category = self.decode_category(route['activity'])

    def _check_response(self, response, data):
        """are there error messages?."""
        if response.status_code != 200:
            if 'route_activity_id_foreign' in response.text:
                raise self.BackendException('Category id is illegal: {}'.format(data))
            if 'route.keyword may not be greater' in response.text:
                raise self.BackendException('Keywords too long: {}'.format(data))
            if 'Unauthorized' in response.text:
                raise self.BackendException('{}: Needs authentication data'.format(self.url))
            raise self.BackendException(response.text)

    def _write_all(self, gpxfile) ->str:
        """save full gpx gpxfile at Openrunner.

        Returns:
            The new id_in_backend

        """
        points = list(gpxfile.points())
        data = {
            'route[activity]': self._legal_categories_numbers[self.encode_category(gpxfile.category)],
            'route[description]': gpxfile.description,
            'route[elevation][sampleEncoded]': self._encode_points(points),
            'route[elevation][sampleIntervalInMeter]': gpxfile.distance / len(points),
            'route[end][lat]': points[-1].latitude,
            'route[end][lng]': points[-1].longitude,
            'route[is_private]': 0 if gpxfile.public else 1,
            'route[is_tested]': 1,
            'route[keyword]': ', '.join(gpxfile.keywords),
            'route[labelColor]': '#ffffff',
            'route[lengthInMeter]': min(gpxfile.distance, 1200) * 1000,  # TODO: unittest: is max length still 1200km?
            'route[name]': gpxfile.title,
            'route[official]': 0,
            'route[shape][pointShapeEncoded]': '',
            'route[shape][pointShapeReducedEncoded]': self._encode_points(points[:20]),
            'route[shape][pointWaypointEncoded]': self._encode_points(points),
            'route[shape][pointWaypointType]': 'A' * len(points),
            'route[shape][showMilestone]': 1,
            'route[shape][strokeColor]': "#b71c0c",
            'route[shape][strokeOpacity]': 0.8,
            'route[shape][strokeWidth]': 5,
            'route[source]': 'openrunner-web',
            'route[start][lat]': points[0].latitude,
            'route[start][lng]': points[0].longitude,
            'route[surface]': 0,
            'route[terrain]': 0,
            'route[waymark]': 0,
        }
        response = self.__post(action='route', data=data)
        json = response.json()
        new_ident = str(json['id'])
        if not new_ident:
            raise self.BackendException('No id found in response')
        gpxfile.id_in_backend = new_ident
        return new_ident

    def _remove_ident(self, ident: str):
        """remove on the server."""
        self.__delete(action='route', data={'routeIds[0]': ident})

    def detach(self):
        """also close session."""
        super(Openrunner, self).detach()
        if self.session:
            self.session.close()
