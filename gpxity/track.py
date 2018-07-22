#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Track`
"""

from math import asin, sqrt, degrees
import datetime
from contextlib import contextmanager
from functools import total_ordering
import weakref

# This code would speed up parsing GPX by about 30%. When doing
# that, GPX will only return str instead of datetime for times.
#
# import gpxpy.gpxfield as mod_gpxfield
# mod_gpxfield.TIME_TYPE=None

from gpxpy import gpx as mod_gpx
from gpxpy import parse as gpxpy_parse
from gpxpy.geo import length as gpx_length
from gpxpy.geo import simplify_polyline

from .util import repr_timespan, uniq

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException


__all__ = ['Track']


@total_ordering
class Track:

    """Represents a track.

    An track is essentially a GPX file. If a backend supports attributes not directly
    supported by the GPX format like the MapMyTracks track type, they will
    transparently be encodeded in existing GPX fields like keywords, see :attr:`keywords`.

    The GPX part is done by https://github.com/tkrajina/gpxpy.

    If a track is assigned to a backend, all changes will by default be written directly to the backend.
    Some backends are able to change only one attribute with little time overhead, others always have
    to rewrite the entire track.

    However you can use the context manager :meth:`batch_changes`. This holds back updating the backend until
    leaving the context.

    If you manipulate the gpx directly, this goes unnoticed. Use :meth:`rewrite` when done.

    Not all backends support everything, you could get the exception NotImplementedError.

    Some backends are able to change only one attribute with little time overhead, others always have
    to rewrite the entire track.

    All points are always rounded to  6 decimal digits when they are added to the
    track.

    Args:
        gpx (GPX): Initial content. To be used if you create a new Track from scratch without
            loading it from some backend.

    The data will only be loaded from the backend when it is needed. Some backends
    might support loading some attributes separately, but for now, we always load
    everything as soon as anything is needed.

    Attributes:
        legal_categories (tuple(str)): The legal values for :attr:`~Track.category`. The first one is used
            as default value. This is a mostly a superset of the values for the different backends.
            Every backend maps from its internal values into those when reading and maps them
            back when writing. Since not all backends support all values defined here and since
            some backends may define more values than we know, information may get lost when
            converting, even if you copy a track between two backends of the same type.

        header_data (dict): The backend may only deliver some general information about
            tracks, the full data will only be loaded when needed. This general information
            can help avoiding having to load the full data. The backend will fill header_data
            if it can. The backends are free to put additional info here. MMT does this for
            time, title, category and distance. You are not supposed to change header_data.
    """

    # pylint: disable = too-many-instance-attributes

    legal_categories = (
        # values from MMT
        'Cycling', 'Running', 'Mountain biking', 'Indoor cycling', 'Sailing', 'Walking', 'Hiking',
        'Swimming', 'Driving', 'Off road driving', 'Motor racing', 'Motorcycling', 'Enduro',
        'Skiing', 'Cross country skiing', 'Canoeing', 'Kayaking', 'Sea kayaking', 'Stand up paddle boarding',
        'Rowing', 'Windsurfing', 'Kiteboarding', 'Orienteering', 'Mountaineering', 'Skating',
        'Skateboarding', 'Horse riding', 'Hang gliding', 'Gliding', 'Flying', 'Snowboarding',
        'Paragliding', 'Hot air ballooning', 'Nordic walking', 'Snowshoeing', 'Jet skiing', 'Powerboating',
        # values from GPSIES
        'Pedelec', 'Crossskating', 'Handcycle', 'Motorhome', 'Cabriolet', 'Coach',
        'Pack animal trekking', 'Train',
        'Miscellaneous')

    def __init__(self, gpx=None):
        self.__dirty = set()
        self._batch_changes = False
        self.__category = self.legal_categories[0]
        self.__public = False
        self.__id_in_backend = None
        self.__backend = None
        self._loaded = False
        self.header_data = dict()
        self.__gpx = gpx or GPX()
        self.__backend = None
        self.__cached_distance = None
        self._similarity_others = weakref.WeakValueDictionary()
        self._similarities = dict()
        if gpx:
            self._parse_keywords()
            self._round_points(self.points())

    @property
    def backend(self):
        """The backend this track lives in. If the track was constructed in memory, backend is None.

        This is a read-only property. It is set with :meth:`Backend.add <gpxity.Backend.add>`.

        It is not possible to decouple a track from its backend, use :meth:`clone()`.
        """
        return self.__backend
        # :attr:`Track.id_in_backend <gpxity.Track.id_in_backend>`.

    @property
    def id_in_backend(self) ->str:
        """Every backend has its own scheme for unique track ids. Some
        backends may change the id if the track data changes.
        """
        return self.__id_in_backend

    @id_in_backend.setter
    def id_in_backend(self, value: str) ->None:
        """Changes the id in the backend. Currently supported
        only by Directory.

        Args:
            value: The new value
        """
        if value is not None and not isinstance(value, str):
            raise Exception('{}: id_in_backend must be str'.format(value))
        if self.__id_in_backend == value:
            return
        if self.__is_decoupled:
            # internal use
            self.__id_in_backend = value
        else:
            if not self.__id_in_backend:
                raise Exception('Cannot set id_in_backend for yet unsaved track {}'.format(self))
            if not value:
                raise Exception('Cannot remove id_in_backend for saved track {}'.format(self))
            with self._decouple():
                self.backend._change_id(self, value)  # pylint: disable=protected-access

    def _set_backend(self, value):
        """To be used only by backend implementations"""
        assert self.__is_decoupled
        self.__backend = value

    def rewrite(self) ->None:
        """Call this after you directly manipulated  :attr:`gpx`"""
        self._load_full()
        self._dirty = 'gpx'

    @property
    def _dirty(self) ->set:
        """
        Is the track in sync with the backend?

        Setting :attr:`_dirty` will directly write the changed data into the backend.

        :attr:`_dirty` can receive an arbitrary string like 'title'. If the backend
        has a method _write_title, that one will be called. Otherwise the
        entire track will be written by the backend.

        Returns:
            set: The names of the attributes currently marked as dirty.
        """
        return self.__dirty

    @_dirty.setter
    def _dirty(self, value):
        if not isinstance(value, str):
            raise Exception('_dirty only receives str')
        if not self.__is_decoupled:
            self.__dirty.add(value)
            if value == 'gpx':
                for key in 'time', 'distance':
                    if key in self.header_data:
                        del self.header_data[key]
                self.__cached_distance = None
                for other in self._similarity_others.values():
                    del other._similarity_others[id(self)] # pylint: disable=protected-access
                    # TODO: unittest where other does not exist anymore
                    del other._similarities[id(self)]  # pylint: disable=protected-access
                self._similarity_others = weakref.WeakValueDictionary()
                self._similarities = dict()
            if not self._batch_changes:
                self._rewrite()

    def _clear_dirty(self):
        """To be used by the backend when saving"""
        self.__dirty = set()

    def clone(self):
        """Creates a new track with the same content but without backend.

        Returns:
            ~gpxity.Track: the new track
        """
        result = Track(gpx=self.gpx.clone())
        result.category = self.category
        result.public = self.public
        return result

    def _rewrite(self):
        """Rewrites all changes in the associated backend.

        If any of those conditions is met, do nothing:

        - we are currently loading from backend: Avoid recursion
        - batch_changes is active
        - we have no backend

        Otherwise the backend will save this track.
        """
        if self.backend is None:
            self._clear_dirty()
        if not self.__dirty:
            return
        if not self.__is_decoupled and not self._batch_changes:
            with self._decouple():
                self.backend._rewrite(self, self.__dirty)  # pylint: disable=protected-access
            self._clear_dirty()

    def remove(self):
        """Removes this track in the associated backend. If the track
        is not coupled with a backend, raise an Exception.
        """
        if self.backend is None:
            raise Exception('{}: Removing needs a backend'.format(self))
        self.backend.remove(self.id_in_backend)

    @property
    def time(self) ->datetime.datetime:
        """datetime.datetime: start time of track.
        For a simpler implementation of backends, notably MMT, we ignore
        gpx.time. Instead we return the time of the earliest track point.
        Only if there is no track point, return gpx.time. If that is unknown
        too, return None.

        For the same reason time is readonly.

        We assume that the first point comes first in time and the last
        point comes last in time. In other words, points should be ordered
        by their time.
        """
        if not self._loaded and 'time' in self.header_data:
            return self.header_data['time']
        self._load_full()
        try:
            return next(self.points()).time
        except StopIteration:
            pass

    @property
    def title(self) -> str:
        """str: The title.
        """
        if not self._loaded and 'title' in self.header_data:
            return self.header_data['title']
        self._load_full()
        return self.__gpx.name

    @title.setter
    def title(self, value: str):
        if value != self.title:
            self.__gpx.name = value
            self.__update_header_data('title', value)
            self._dirty = 'title'

    @property
    def description(self) ->str:
        """str: The description.
        """
        if not self._loaded and 'description' in self.header_data:
            return self.header_data['description']
        self._load_full()
        return self.__gpx.description or ''

    @description.setter
    def description(self, value: str):
        if value != self.description:
            self.__gpx.description = value
            self.__update_header_data('description', value)
            self._dirty = 'description'

    def __update_header_data(self, key, value):
        """Setters should call this if they change a content value.
        Needed in case the setter was called with self._loaded=False."""
        # TODO: needs tests like gpxdo set --title='Poreč lokal' mmt:wolfgang61/2231133
        # for all fields used by header_data
        if key in self.header_data:
            self.header_data[key] = value

    @contextmanager
    def _decouple(self):
        """This context manager disables automic synchronization with
        the backend. In that state, automatic writes of changes into
        the backend are disabled, and if you access attributes which
        would normally trigger a full load from the backend, they will not.
        (The latter is used by __str__ and __repr__).
        """
        # pylint: disable=protected-access
        had_backend = self.__backend is not None
        prev_value = self.__backend._decoupled if had_backend else False
        if had_backend:
            self.__backend._decoupled = True
        try:
            yield
        finally:
            if had_backend and self.__backend is not None:
                self.__backend._decoupled = prev_value

    @property
    def __is_decoupled(self):
        """True if we are currently decoupled from the backend. In that
        state, changes to Track are not written to the backend and
        the track is not marked dirty.
        """
        if self.backend is None:
            return True
        return self.backend._decoupled  # pylint: disable=protected-access

    @contextmanager
    def batch_changes(self):
        """This context manager disables  the direct update in the backend
        and saves the entire track when done. This may or may not make
        things faster. Directory and GPSIES profits from this, MMT maybe.
        """
        prev_batch_changes = self._batch_changes
        self._batch_changes = True
        try:
            yield
        finally:
            self._batch_changes = prev_batch_changes
            self._rewrite()

    @property
    def category(self) ->str:
        """str: What is this track doing? If we have no current value,
        return the default.

        The value is automatically translated between our internal value and
        the value used by the backend. This happens when reading from
        or writing to the backend.
        Returns:
            The current value or the default value (see :attr:`legal_categories`)
        """
        if not self._loaded and 'category' in self.header_data:
            return self.header_data['category']
        self._load_full()
        return self.__category

    @category.setter
    def category(self, value: str):
        if value is None:
            value = self.legal_categories[0]
        if value != self.category:
            if value not in self.legal_categories:
                raise Exception('Category {} is not known'.format(value))
            self.__category = value
            self.__update_header_data('category', value)
            self._dirty = 'category'

    def _load_full(self) ->None:
        """Loads the full track from source_backend if not yet loaded."""
        if self.backend is not None and self.id_in_backend and not self._loaded and not self.__is_decoupled:
            self.backend._read_all_decoupled(self) # pylint: disable=protected-access, no-member
            self._loaded = True

    def add_points(self, points) ->None:
        """Adds points to last segment in the last track. If no track
        is allocated yet and points is not an empty list, allocates
        a track.

        Args:
            points (list(GPXTrackPoint): The points to be added
        """
        if points:
            if self.__gpx.tracks:
                # make sure the same points are not added twice
                assert points != self.__gpx.tracks[-1].segments[-1].points[-len(points):]
            self._load_full()
            if not self.__gpx.tracks:
                self.__gpx.tracks.append(GPXTrack())
                self.__gpx.tracks[0].segments.append(GPXTrackSegment())
            self._round_points(points)
            self.__gpx.tracks[-1].segments[-1].points.extend(points)
            self._dirty = 'gpx'

    def lifetrack(self, backend=None, points=None) ->None:
        """Life tracking.

        When starting lifetracking, the track must have no points yet
        and must not yet be assigned to a backend.

        Some backends may have a separate interface for life tracking like MMT.
        Others may simply watch an activity and notice if it gets more points.
        This is fully transparent, usage of lifetrack is always identical.

        Args:
            backend: The backend which should lifetrack this Track. Only pass this
              when you start tracking. The backend may change :attr:`id_in_backend`.
            points (list(GPXTrackPoint): The points to be added.
                If None: Stop life tracking.
        """
        if self.backend is not None and backend is not None:
            raise Exception('lifetrack(): Track must not have a backend yet')
        if self.backend is None and self.__gpx.tracks:
            raise Exception('lifetrack(): Track must be empty')
        if backend is not None:
            self.backend.add(self)
        if self.backend is None:
            raise Exception('lifetrack(): backend unknown')
        # pylint: disable=no-member
        if 'track' in self.backend.supported:
            self._round_points(points)
            self.backend._lifetrack(self, points) # pylint: disable=protected-access
        else:
            self.add_points(points)

    def _parse_keywords(self):
        """self.keywords is 1:1 as parsed from xml. Here we extract
        our special keywords Category: and Status:"""
        new_keywords = list()
        for keyword in self.keywords:
            if keyword.startswith('Category:'):
                self.category = keyword.split(':')[1]
            elif keyword.startswith('Status:'):
                self.public = keyword.split(':')[1] == 'public'
            else:
                new_keywords.append(keyword)
        self.keywords = new_keywords

    def parse(self, indata):
        """Parses GPX.

        :attr:`title`, :attr:`description` and :attr:`category` from indata have precedence over the current values.
        :attr:`public` will be or-ed

        Args:
            indata: may be a file descriptor or str
        """
        if hasattr(indata, 'read'):
            indata = indata.read()
        if not indata:
            # ignore empty file
            return
        with self._decouple():
            old_gpx = self.__gpx
            old_public = self.public
            try:
                self.__gpx = gpxpy_parse(indata)
            except GPXXMLSyntaxException as exc:
                print('{}: Track {} has illegal GPX XML: {}'.format(
                    self.backend, self.id_in_backend, exc))
                raise
            if 'keywords' in self.header_data:
                del self.header_data['keywords']
            self._parse_keywords()
            if 'public' in self.header_data:
                del self.header_data['public']
            self.public = self.public or old_public
            if old_gpx.name and not self.__gpx.name:
                self.__gpx.name = old_gpx.name
            if old_gpx.description and not self.__gpx.description:
                self.__gpx.description = old_gpx.description
            self._round_points(self.points())
        self._loaded = True

    @staticmethod
    def _round_points(points):
        """Rounds points to 6 decimal digits because some backends may
        cut last digits. Gpsies truncates to 7 digits. The points are rounded
        in place!

        Args:
            points (list(GPXTrackPoint): The points to be rounded
        """
        for _ in points:
            _.longitude = round(_.longitude, 6)
            _.latitude = round(_.latitude, 6)

    def to_xml(self) ->str:
        """Produces exactly one line per trackpoint for easier editing
        (like removal of unwanted points).
        """
        self._load_full()
        new_keywords = self.keywords
        new_keywords.append('Category:{}'.format(self.category))
        new_keywords.append('Status:{}'.format('public' if self.public else 'private'))
        old_keywords = self.__gpx.keywords
        try:
            self.__gpx.keywords = ', '.join(new_keywords)

            result = self.__gpx.to_xml()
            result = result.replace('</trkpt><', '</trkpt>\n<')
            result = result.replace('<copyright ></copyright>', '')   # gpxviewer does not accept such illegal xml
            result = result.replace('<link ></link>', '')
            result = result.replace('<author>\n</author>\n', '')
            result = result.replace('\n</trkpt>', '</trkpt>')
            result = result.replace('>\n<ele>', '><ele>')
            result = result.replace('>\n<time>', '><time>')
            result = result.replace('</ele>\n<time>', '</ele><time>')
            result = result.replace('.0</ele>', '</ele>') # this could differ depending on the source
            result = result.replace('\n\n', '\n')
            if not result.endswith('\n'):
                result += '\n'
        finally:
            self.__gpx.keywords = old_keywords
        return result

    @property
    def public(self):
        """
        bool: Is this a private track (can only be seen by the account holder) or
            is it public? Default value is False
        """
        if not self._loaded and 'public' in self.header_data:
            return self.header_data['public']
        self._load_full()
        return self.__public

    @public.setter
    def public(self, value):
        """Stores this flag as keyword 'public'."""
        if value != self.public:
            self.__public = value
            self.__update_header_data('public', value)
            self._dirty = 'public'

    @property
    def gpx(self) ->GPX:
        """
        Direct access to the GPX object. If you use it to change its content,
        remember to call :meth:`rewrite` afterwards.

        Returns:
            the GPX object
        """
        self._load_full()
        return self.__gpx

    @property
    def last_time(self) ->datetime.datetime:
        """datetime.datetime:
        the last time we received so far.
        If none, return None."""
        self._load_full()
        try:
            return self.__gpx.tracks[-1].segments[-1].points[-1].time
        except IndexError:
            pass

    @property
    def keywords(self):
        """list(str): represents them as a sorted list - in GPX they are comma separated.
            Content is whatever you want.

            Because the GPX format does not have attributes for everything used by all backends,
            we encode some of the backend arguments in keywords.

            Example for mapmytracks: keywords = 'Status:public, Category:Cycling'.

            However this is transparent for you. When parsing theGPX file, those are removed
            from keywords, and the are re-added in when exporting in :meth:`to_xml`. So
            :attr:`Track.keywords` will never show those special values.

            Some backends may change keywords. :class:`~gpxity.MMT` converts the
            first character into upper case and will return it like that. Gpxity will not try to hide such
            problems. So if you save a track in :class:`~gpxity.MMT`, its keywords
            will change. But they will not change if you copy from :class:`~gpxity.MMT`
            to :class:`~gpxity.Directory` - so if you copy from DirectoryA
            to :class:`~gpxity.MMT` to DirectoryB, the keywords in
            DirectoryA and DirectoryB will not be identical, for example "berlin" in DirectoryA but
            "Berlin" in DirectoryB.
        """
        if not self._loaded and 'keywords' in self.header_data:
            return self.header_data['keywords']
        self._load_full()
        if self.__gpx.keywords:
            return list(sorted(x.strip() for x in self.__gpx.keywords.split(',')))
        return list()

    @keywords.setter
    def keywords(self, value):
        """Replaces all keywords.

        Args:
            value (iterable(str)): the new keywords. Must not have duplicates.
        """
        self._load_full()
        with self.batch_changes():
            self.__gpx.keywords = ''
            for keyword in sorted(value):
                # add_keyword ensures we do not get unwanted things like Category:
                self.add_keyword(keyword)
            self.__dirty = set()
            if 'keywords' in self.header_data:
                del self.header_data['keywords']
            self._dirty = 'keywords'

    @staticmethod
    def _check_keyword(keyword):
        """Must not be Category: or Status:"""
        if keyword.startswith('Category:'):
            raise Exception('Do not use this directly,  use Track.category')
        if keyword.startswith('Status:'):
            raise Exception('Do not use this directly,  use Track.public')
        if ',' in keyword:
            raise Exception('No comma allowed within a keyword')

    def add_keyword(self, value: str) ->None:
        """Adds to the comma separated keywords. Duplicate keywords are silently ignored.
        A keyword may not contain a comma.

        Args:
            value: the keyword
        """
        self._check_keyword(value)
        self._load_full()
        if value not in self.keywords:
            if self.__gpx.keywords:
                self.__gpx.keywords += ', {}'.format(value)
            else:
                self.__gpx.keywords = value
            if 'keywords' in self.header_data:
                del self.header_data['keywords']
            self._dirty = 'add_keyword:{}'.format(value)

    def remove_keyword(self, value: str) ->None:
        """Removes from the keywords.

        Args:
            value: the keyword to be removed
        """
        self._check_keyword(value)
        self._load_full()
        self.__gpx.keywords = ', '.join(x for x in self.keywords if x != value)
        if 'keywords' in self.header_data:
            del self.header_data['keywords']
        self._dirty = 'remove_keyword:{}'.format(value)

    def speed(self):
        """Speed over the entire time in km/h or 0.0"""
        time_range = (self.time, self.last_time)
        if time_range[0] is None or time_range[1] is None:
            return 0.0
        duration = time_range[1] - time_range[0]
        seconds = duration.days * 24 * 3600 + duration.seconds
        if seconds:
            return self.distance() / seconds * 3600
        return 0.0

    def moving_speed(self):
        """Speed for time in motion in km/h"""
        bounds = self.gpx.get_moving_data()
        if bounds.moving_time:
            return bounds.moving_distance / bounds.moving_time * 3.6
        return 0.0

    def warnings(self):
        """Returns a list of strings with easy to find problems."""
        result = list()
        if self.speed() > self.moving_speed():
            result.append('Speed {:.3f} must not be above Moving speed {:.3f}'.format(
                self.speed(), self.moving_speed()))
        if self.category == 'Cycling':
            if not 3 <= self.speed() <= 60:
                result.append('Speed {:.3f} is out of expected range 3..60'.format(self.speed()))
            if not 10 <= self.moving_speed() <= 50:
                result.append('Moving speed {:.3f} is out of expected range 10..50'.format(self.moving_speed()))
        if self.category == 'Mountain biking':
            if not 3 <= self.speed() <= 50:
                result.append('Speed {:.3f} is out of expected range 3..50'.format(self.speed()))
            if not 10 <= self.moving_speed() <= 40:
                result.append('Moving speed {:.3f} is out of expected range 10..40'.format(self.moving_speed()))
        return result

    def __repr__(self):
        with self._decouple():
            # this should not automatically load the entire track
            parts = []
            if self.id_in_backend is not None:
                parts.append('id:{}'.format(self.id_in_backend))
            parts.append('public' if self.public else 'private')
            if self.__gpx:
                parts.append(self.category)
                if self.keywords:
                    parts.append(','.join(self.keywords))
                if self.title:
                    parts.append(self.title)
                if self.time and self.last_time:
                    parts.append(repr_timespan(self.time, self.last_time))
                elif self.time:
                    parts.append(str(self.time))
                if 'distance' in self.header_data:
                    parts.append('{:4.2f}km'.format(self.header_data['distance']))
                else:
                    parts.append('{} points'.format(self.gpx.get_track_points_no()))
            return 'Track({})'.format(' '.join(parts))

    def __str__(self):
        return self.__repr__()

    def identifier(self, long: bool = False) ->str:
        """The full identifier with backend name and id_in_backend.
        As used for gpxdo.

        Args:
            long: If True, give more info
        """
        long_info = ' "{}" from {}'.format(self.title, self.time) if long else ''
        return '{}{}{}'.format(
            self.backend.identifier() if self.backend else '',
            self.id_in_backend if self.id_in_backend else ' unsaved ',
            long_info)

    def key(self, with_category: bool = True) ->str:
        """For speed optimized equality checks, not granted to be exact, but
        sufficiently safe IMHO.

        Args:
            with_category: If False, do not use self.category. Needed for comparing
                tracks for equality like in unittests because values can change
                and information can get lost while copying between different
                backends

        Returns:
            a string with selected attributes in printable form.
        """
        self._load_full()
        return 'title:{} description:{} keywords:{} category:{}: public:{} last_time:{} angle:{} points:{}'.format(
            self.title, self.description,
            ','.join(self.keywords), self.category if with_category else '', self.public, self.last_time,
            self.angle(), self.gpx.get_track_points_no())

    def __eq__(self, other):
        if self is other:
            return True
        return self.key() == other.key()

    def __lt__(self, other):
        return self.key() < other.key()

    def distance(self) ->float:
        """For me, the earth is flat.

        Returns:
            the distance in km, rounded to m
        """
        if 'distance' in self.header_data:
            return self.header_data['distance']
        if self.__cached_distance is None:
            self.__cached_distance = round(gpx_length(list(self.points())) / 1000, 3)
        return self.__cached_distance

    def angle(self) ->float:
        """For me, the earth is flat.

        Returns:
            the angle in degrees 0..360 between start and end.
            If we have no track, return 0
        """
        try:
            first_point = next(self.points())
        except StopIteration:
            return 0
        last_point = self.last_point()
        delta_lat = round(first_point.latitude, 6) - round(last_point.latitude, 6)
        delta_long = round(first_point.longitude, 6) - round(last_point.longitude, 6)
        norm_lat = delta_lat / 90.0
        norm_long = delta_long / 180.0
        try:
            result = degrees(asin(norm_long / sqrt(norm_lat**2 + norm_long **2)))
        except ZeroDivisionError:
            return 0
        if norm_lat >= 0.0:
            return (360.0 + result) % 360.0
        return 180.0 - result

    def segments(self):
        """
        Yields:
            GPXTrackSegment: all segments in all tracks
        """
        self._load_full()
        for track in self.__gpx.tracks:
            for segment in track.segments:
                yield segment

    def points(self):
        """
        Yields:
            GPXTrackPoint: all points in all tracks and segments
        """
        for segment in self.segments():
            for point in segment.points:
                yield point

    def last_point(self):
        """Returns the last point of the track."""
        # TODO: unittest for track without __gpx or without points
        return self.__gpx.tracks[-1].segments[-1].points[-1]

    def adjust_time(self, delta):
        """Adds a timedelta to all times.
        gpxpy.gpx.adjust_time does the same but it ignores waypoints.
        """
        self.gpx.adjust_time(delta)
        for wpt in self.gpx.waypoints:
            wpt.time += delta
        self._dirty = 'gpx'

    def points_hash(self) -> float:
        """A hash that is hopefully different for every possible track.
        It is built using the combination of all points.
        """
        self._load_full()
        result = 1.0
        for point in self.points():
            if point.longitude:
                result *= point.longitude
            if point.latitude:
                result *= point.latitude
            if point.elevation:
                result *= point.elevation
            result %= 1e20
        return result

    def points_equal(self, other) ->bool:
        """
        Returns:
            True if both tracks have identical points.

        All points of all tracks and segments are combined. Elevations are ignored.
        """
        # We do not use points_hash because we want to abort as soon as we know
        # they are different.
        self._load_full()
        if self.gpx.get_track_points_no() != other.gpx.get_track_points_no():
            return False
        if self.angle() != other.angle():
            return False
        for _, (point1, point2) in enumerate(zip(self.points(), other.points())):
            # GPXTrackPoint has no __eq__ and no working hash()
            # those are only the most important attributes:
            if point1.longitude != point2.longitude:
                return False
            if point1.latitude != point2.latitude:
                return False
        return True

    @staticmethod
    def overlapping_times(tracks):
        """"
        Yields:
            groups of tracks with overlapping times. Sorted by time.

        This may be very slow for many long tracks.
        """
        previous = None
        group = list()  # Track is  mutable, so a set is no possible
        for current in sorted(tracks, key=lambda x: x.time):
            if previous and current.time <= previous.last_time:
                if previous not in group:
                    group.append(previous)
                group.append(current)
            else:
                if group:
                    yield sorted(group, key=lambda x: x.time)
                    group = list()
            previous = current
        if group:
            yield sorted(group, key=lambda x: x.time)

    def _has_default_title(self) ->bool:
        """Try to check if track has the default title given by a backend."""
        # the title of MMT might have been copied into another backend:
        if not self.title:
            return True
        if self.title == '{} track'.format(self.category):
            return True
        if  all(x in '0123456789 :-_' for x in self.title):
            return True
        return False


    def merge(self, other, remove: bool = False, dry_run: bool = False, copy: bool = False) ->list:  # pylint: disable=unused-argument
        """Merge other track into this one. The track points must be identical.
        If either is public, the result is public.
        If self.title seems like a default and other.title does not, use other.title
        Combine description and keywords.

        Args:
            other (:class:`~gpxity.Track`): The track to be merged
            remove: After merging succeeded, remove other
            dry_run: if True, do not really apply the merge
            copy: This argument is ignored. It is only here to give Track.merge() and Backend.merge()
                the same interface.
        Returns: list(str)
            Messages about category has been done
        """
        # pylint: disable=too-many-branches
        if self.points_hash() != other.points_hash():
            raise Exception('Cannot merge, points are different: {} into {}'.format(other, self))
        msg = list()
        with self.batch_changes():
            if not other._has_default_title() and self._has_default_title():  # pylint: disable=protected-access
                msg.append('Title: {} -> {}'.format(self.title, other.title))
                if not dry_run:
                    self.title = other.title
            if other.description and other.description != self.description:
                msg.append('Additional description: {}'.format(
                    other.description))
                if not dry_run:
                    self.description += '\n'
                    self.description += other.description
            if other.public and not self.public:
                msg.append('Visibility: private -> public')
                if not dry_run:
                    self.public = True
            if other.category != self.category:
                msg.append('Category: {}={} wins over {}={}'.format(
                    other.identifier(), other.category, self.identifier(), self.category))
            kw_src = set(other.keywords)
            kw_dst = set(self.keywords)
            if kw_src - kw_dst:
                msg.append('New keywords: {}'.format(','.join(kw_src - kw_dst)))
                if not dry_run:
                    self.keywords = kw_src | kw_dst
            changed_point_times = 0
            for self_point, other_point in zip(self.points(), other.points()):
                if not self_point.time:
                    if not dry_run:
                        self_point.time = other_point.time
                    changed_point_times += 1
            if changed_point_times:
                if not dry_run:
                    self._dirty = 'gpx'
                msg.append('Copied times for {} out of {} points'.format(
                    changed_point_times, self.gpx.get_track_points_no()))
            if msg:
                msg = list('     ' + x for x in msg)
                msg.insert(0, 'Merged{} {}'.format(
                    ' and removed' if remove else '', other.identifier(long=True)))
                msg.insert(1, '{}  into {}'.format(
                    ' ' * len(' and removed') if remove else '', self.identifier(long=True)))
            if remove:
                if len(msg) <= 2:
                    msg.append('Removed duplicate {}'.format(other.identifier(long=True)))
                if not dry_run:
                    other.remove()
        return msg

    @staticmethod
    def __time_diff(last_point, point):
        """Returns difference in seconds, ignoring the date."""
        result = abs(last_point.hhmmss - point.hhmmss)
        if result > 33200: # seconds in 12 hours
            result = 86400 - result
        return result

    @staticmethod
    def __point_is_near(last_point, point, delta_meter):
        """Returns True if distance < delta_meter"""
        return abs(last_point.distance_2d(point)) < delta_meter

    def fix(self, orux24: bool = False):
        """Fix bugs. This may fix them or produce more bugs.
        Please backup your track before doing this.

        Args:
            orux24: Older Oruxmaps switched the day back by one
                day after exactly 24 hours.

        Returns:
            A list of message strings, usable for verbose output.
            """
        if orux24:
            self.__fix_orux24()
        return []

    def __fix_orux24(self):
        """Try to fix Oruxmaps 24hour bug."""
        all_points = list(uniq(self.points()))
        for _ in all_points:
            _.hhmmss = _.time.hour * 3600.0 + _.time.minute * 60 + _.time.second + _.time.microsecond / 1000000
        new_points = list([all_points.pop(0)])
        while all_points:
            last_point = new_points[-1]
            near_points = list(x for x in all_points if self.__point_is_near(last_point, x, 10000))
            if not near_points:
                near_points = all_points[:]
            nearest = min(near_points, key=lambda x: Track.__time_diff(last_point, x))
            new_points.append(nearest)
            all_points.remove(nearest)

        day_offset = 0
        point1 = None
        for point in new_points:
            if point1 is None:
                point1 = point
            else:
                point2 = point
                if point1.time - point2.time > datetime.timedelta(days=day_offset, hours=23):
                    day_offset += 1
                if day_offset:
                    point2.time += datetime.timedelta(days=day_offset)
                point1 = point2

        segment = GPXTrackSegment()
        segment.points.extend(new_points)

        self.__gpx.tracks = list()
        self.__gpx.tracks.append(GPXTrack())
        self.__gpx.tracks[0].segments.append(segment)
        self._dirty = 'gpx'

    def similarity(self, other):
        """Returns a float 0..1: 1 is identity."""

        def simple(track):
            """Simplified track"""
            return list((round(x.latitude, 3), round(x.longitude, 3))
                        for x in simplify_polyline(list(track.points()), max_distance=50))

        if id(other) not in self._similarity_others:
            simple1 = simple(self)
            simple2 = simple(other)
            max_len = max([len(simple1), len(simple2)])
            similar_length = 1.0 - abs(len(simple1) - len(simple2)) / max_len
            set1 = set(simple1)
            set2 = set(simple2)
            min_len = min([len(set1), len(set2)])
            similar_points = len(set1 & set2) / min_len
            result = similar_length * similar_points
            self._similarity_others[id(other)] = other
            self._similarities[id(other)] = result
            other._similarity_others[id(self)] = self  # pylint: disable=protected-access
            other._similarities[id(self)] = result  # pylint: disable=protected-access
        return self._similarities[id(other)]
