#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Activity`
"""

from math import asin, sqrt, degrees
import datetime
from contextlib import contextmanager
from functools import total_ordering

from .util import repr_timespan

# This code would speed up parsing GPX by about 30%. When doing
# that, GPX will only return str instead of datetime for times.
#
# import gpxpy.gpxfield as mod_gpxfield
# mod_gpxfield.TIME_TYPE=None

from gpxpy import gpx as mod_gpx
from gpxpy import parse as gpxpy_parse
from gpxpy.geo import length as gpx_length

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException


__all__ = ['Activity']


@total_ordering
class Activity:

    """Represents an activity.

    An activity is essentially a GPX file. If a backend supports attributes not directly
    supported by the GPX format like the MapMyTracks activity type, they will
    transparently be encodeded in existing GPX fields like keywords, see :attr:`keywords`.

    The GPX part is done by https://github.com/tkrajina/gpxpy.

    If an activity is assigned to a backend, all changes will by default be written directly to the backend.
    Some backends are able to change only one attribute with little time overhead, others always have
    to rewrite the entire activity.

    However you can use the context manager :meth:`batch_changes`. This holds back updating the backend until
    leaving the context.

    If you manipulate the gpx directly, this goes unnoticed. Use :meth:`rewrite` when done.

    Not all backends support everything, you could get the exception NotImplementedError.

    Some backends are able to change only one attribute with little time overhead, others always have
    to rewrite the entire activity.


    Args:
        gpx (GPX): Initial content. To be used if you create a new Activity from scratch without
            loading it from some backend.

    The data will only be loaded from the backend when it is needed. Some backends
    might support loading some attributes separately, but for now, we always load
    everything as soon as anything is needed.

    Attributes:
        legal_whats (tuple(str)): The legal values for :attr:`~Activity.what`. The first one is used
            as default value. This is a mostly a superset of the values for the different backends.
            Every backend maps from its internal values into those when reading and maps them
            back when writing. Since not all backends support all values defined here and since
            some backends may define more values than we know, information may get lost when
            converting, even if you copy an activity between two backends of the same type.

        header_data (dict): The backend may only deliver some general information about
            activities, the full data will only be loaded when needed. This general information
            can help avoiding having to load the full data. The backend will fill header_data
            if it can. The backends are free to put additional info here. MMT does this for
            time, title, what and distance. You are not supposed to change header_data.
    """

    # pylint: disable = too-many-instance-attributes

    legal_whats = (
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
        self.__what = self.legal_whats[0]
        self.__public = False
        self.__id_in_backend = None
        self.__backend = None
        self._loaded = False
        self.header_data = dict()
        self.__gpx = gpx or GPX()
        self.__backend = None
        if gpx:
            self._parse_keywords()
            self._round_points(self.points())

    @property
    def backend(self):
        """The backend this activity lives in. If the activity was constructed in memory, backend is None.

        This is a read-only property. It is set with :meth:`Backend.add <gpxity.Backend.add>`.

        It is not possible to decouple an activity from its backend, use :meth:`clone()`.
        """
        return self.__backend
        # :attr:`Activity.id_in_backend <gpxity.Activity.id_in_backend>`.

    @property
    def id_in_backend(self) ->str:
        """Every backend has its own scheme for unique activity ids. Some
        backends may change the id if the activity data changes.
        """
        return self.__id_in_backend

    def _set_id_in_backend(self, value: str) ->None:
        """To be used only by backend implementations.

        Args:
            value: The new value
        """
        if value is not None and not isinstance(value, str):
            raise Exception('{}: id_in_backend must be str'.format(value))
        self.__id_in_backend = value
 #       if self.backend is not None and not self.backend._has_item(value): # pylint:disable=protected-access
    #         # do not say self in backend because that would do a full load of self.
       #     self.backend.append(self)

    def _set_backend(self, value):
        """To be used only by backend implementations"""
        assert self.__is_decoupled
        self.__backend = value

    def rewrite(self) ->None:
        """Call this after you directly manipulated  :attr:`gpx`"""
        self._dirty = 'gpx'

    @property
    def _dirty(self) ->set:
        """
        Is the activity in sync with the backend?

        Setting :attr:`_dirty` will directly write the changed data into the backend.

        :attr:`_dirty` can receive an arbitrary string like 'title'. If the backend
        has a method _write_title, that one will be called. Otherwise the
        entire activity will be written by the backend.

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
            if not self._batch_changes:
                self._rewrite()

    def _clear_dirty(self):
        """To be used by the backend when saving"""
        self.__dirty = set()

    def clone(self):
        """Creates a new activity with the same content but without backend.

        Returns:
            ~gpxity.Activity: the new activity
        """
        result = Activity(gpx=self.gpx.clone())
        result.what = self.what
        result.public = self.public
        result._set_id_in_backend(self.id_in_backend)  # pylint: disable=protected-access
        return result

    def _rewrite(self):
        """Rewrites all changes in the associated backend.

        If any of those conditions is met, do nothing:

        - we are currently loading from backend: Avoid recursion
        - batch_changes is active
        - we have no backend

        Otherwise the backend will save this activity.
        """
        if self.backend is None:
            self._clear_dirty()
        if not self.__dirty:
            return
        if not self.__is_decoupled and not self._batch_changes:
            self.backend._rewrite(self, self.__dirty)  # pylint: disable=protected-access
            self._clear_dirty()

    def remove(self):
        """Removes this activity in the associated backend. If the activity
        is not coupled with a backend, raise an Exception.
        """
        if self.backend is None:
            raise Exception('{}: Removing needs a backend'.format(self))
        self.backend.remove(self.id_in_backend)

    @property
    def time(self) ->datetime.datetime:
        """datetime.datetime: start time of activity.
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
            self._dirty = 'title'

    @property
    def description(self) ->str:
        """str: The description.
        """
        self._load_full()
        return self.__gpx.description or ''

    @description.setter
    def description(self, value: str):
        if value != self.description:
            self.__gpx.description = value
            self._dirty = 'description'

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
        state, changes to Activity are not written to the backend and
        the activity is not marked dirty.
        """
        if self.backend is None:
            return True
        return self.backend._decoupled  # pylint: disable=protected-access

    @contextmanager
    def batch_changes(self):
        """This context manager disables  the direct update in the backend
        and saves the entire activity when done. This may or may not make
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
    def what(self) ->str:
        """str: What is this activity doing? If we have no current value,
        return the default.

        The value is automatically translated between our internal value and
        the value used by the backend. This happens when reading from
        or writing to the backend.
        Returns:
            The current value or the default value (see :attr:`legal_whats`)
        """
        if not self._loaded and 'what' in self.header_data:
            return self.header_data['what']
        self._load_full()
        return self.__what

    @what.setter
    def what(self, value: str):
        if value is None:
            value = self.legal_whats[0]
        if value != self.what:
            if value not in self.legal_whats:
                raise Exception('What {} is not known'.format(value))
            self.__what = value
            self._dirty = 'what'

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

    def track(self, backend=None, points=None) ->None:
        """Life tracking.

        If this activity belongs to a backend supporting
        life tracking:

        * **points** is None: Stop life tracking
        * if life tracking is not active, start it and send all points already known in this \
            activity. The backend may change :attr:`id_in_backend`.
        * if life tracking was already active, just send the new points.

        MMT supports simultaneous life tracking for only
        one activity per account, others may support more.

        For backends not supporting life tracking, the points are
        simply added.

        Args:
            backend: The backend which should track this Activity. Only pass this
              when you start tracking.
            points (list(GPXTrackPoint): The points to be added
        """
        if self.backend is not None and backend is not None:
            raise Exception('track(): Activity must not have a backend yet')
        if backend is not None:
            self.__backend = backend
        if self.backend is None:
            raise Exception('track(): backend unknown')
        # pylint: disable=no-member
        if 'track' in self.backend.supported:
            self._round_points(points)
            self.backend._track(self, points) # pylint: disable=protected-access
        else:
            self.add_points(points)

    def _parse_keywords(self):
        """self.keywords is 1:1 as parsed from xml. Here we extract
        our special keywords What: and Status:"""
        new_keywords = list()
        for keyword in self.keywords:
            if keyword.startswith('What:'):
                self.what = keyword.split(':')[1]
            elif keyword.startswith('Status:'):
                self.public = keyword.split(':')[1] == 'public'
            else:
                new_keywords.append(keyword)
        self.keywords = new_keywords

    def parse(self, indata):
        """Parses GPX.

        :attr:`title`, :attr:`description` and :attr:`what` from indata have precedence over the current values.
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
                print('{}: Activity {} has illegal GPX XML: {}'.format(
                    self.backend, self.id_in_backend, exc))
                raise
            self._parse_keywords()
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
        new_keywords.append('What:{}'.format(self.what))
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
        bool: Is this a private activity (can only be seen by the account holder) or
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

            Example for mapmytracks: keywords = 'Status:public, What:Cycling'.

            However this is transparent for you. When parsing theGPX file, those are removed
            from keywords, and the are re-added in when exporting in :meth:`to_xml`. So
            :attr:`Activity.keywords` will never show those special values.

            Some backends may change keywords. :class:`~gpxity.MMT` converts the
            first character into upper case and will return it like that. Gpxity will not try to hide such
            problems. So if you save an activity in :class:`~gpxity.MMT`, its keywords
            will change. But they will not change if you copy from :class:`~gpxity.MMT`
            to :class:`~gpxity.Directory` - so if you copy from DirectoryA
            to :class:`~gpxity.MMT` to DirectoryB, the keywords in
            DirectoryA and DirectoryB will not be identical, for example "berlin" in DirectoryA but
            "Berlin" in DirectoryB.
        """
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
                # add_keyword ensures we do not get unwanted things like What:
                self.add_keyword(keyword)
            self.__dirty = set()
            self._dirty = 'keywords'

    @staticmethod
    def _check_keyword(keyword):
        """Must not be What: or Status:"""
        if keyword.startswith('What:'):
            raise Exception('Do not use this directly,  use Activity.what')
        if keyword.startswith('Status:'):
            raise Exception('Do not use this directly,  use Activity.public')
        if ',' in keyword:
            raise Exception('No comma allowed within a keyword')

    def add_keyword(self, value: str) ->None:
        """Adds to the comma separated keywords. Duplicate keywords are not allowed.
        A keyword may not contain a comma.

        Args:
            value: the keyword
        """
        self._check_keyword(value)
        self._load_full()
        if value in self.keywords:
            raise Exception('Keywords may not be duplicate: {}'.format(value))
        if self.__gpx.keywords:
            self.__gpx.keywords += ', {}'.format(value)
        else:
            self.__gpx.keywords = value
        self._dirty = 'add_keyword:{}'.format(value)

    def remove_keyword(self, value: str) ->None:
        """Removes from the keywords.

        Args:
            value: the keyword to be removed
        """
        self._check_keyword(value)
        self._load_full()
        self.__gpx.keywords = ', '.join(x for x in self.keywords if x != value)
        self._dirty = 'remove_keyword:{}'.format(value)

    def __repr__(self):
        with self._decouple():
            # this should not automatically load the entire activity
            parts = []
            if self.id_in_backend is not None:
                parts.append('id:{}'.format(self.id_in_backend))
            parts.append('public' if self.public else 'private')
            if self.__gpx:
                parts.append(self.what)
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
            return 'Activity({})'.format(' '.join(parts))

    def __str__(self):
        return self.__repr__()

    def identifier(self) ->str:
        """The full identifier with backend name and id_in_backend.
        As used for gpxdo.
        """
        if self.backend is None:
            return 'nobackend'
        return self.backend._activity_identifier(self)

    def key(self, with_what: bool = True) ->str:
        """For speed optimized equality checks, not granted to be exact, but
        sufficiently safe IMHO.

        Args:
            with_what: If False, do not use self.what. Needed for comparing
                activities for equality like in unittests because values can change
                and information can get lost while copying between different
                backends

        Returns:
            a string with selected attributes in printable form.
        """
        self._load_full()
        return 'title:{} description:{} keywords:{} what:{}: public:{} last_time:{} angle:{} points:{}'.format(
            self.title, self.description,
            ','.join(self.keywords), self.what if with_what else '', self.public, self.last_time,
            self.angle(), self.gpx.get_track_points_no())

    def __eq__(self, other):
        if self is other:
            return True
        return self.key() == other.key()

    def __lt__(self, other):
        return self.key() < other.key()

    def length(self) ->float:
        """For me, the earth is flat.

        Returns:
            the length in km
        """
        return round(gpx_length(list(self.points())) / 1000, 3)

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
        last_point = self.__gpx.tracks[-1].segments[-1].points[-1]
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
            True if both activities have identical points.

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
    def overlapping_times(activities):
        """"
        Yields:
            groups of activities with overlapping times. Sorted by time.

        This may be very slow for many long activities.
        """
        previous = None
        group = list()  # Activity is  mutable, so a set is no possible
        for current in sorted(activities, key=lambda x: x.time):
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
        """Try to check if activity has the default title given by a backend."""
        # the title of MMT might have been copied into another backend:
        if not self.title:
            return True
        if self.title == '{} activity'.format(self.what):
            return True
        if  all(x in '0123456789 :-_' for x in self.title):
            return True
        return False


    def merge(self, other) ->list:
        """Merge other activity into this one. The track points must be identical.
        If either is public, the result is public.
        If self.title seems like a default and other.title does not, use other.title
        Combine description and keywords.

        Args:
            other (:class:`~gpxity.Activity`): The activity to be merged
        Returns: list(str)
            Messages about what has been done
        """
        if self.points_hash() != other.points_hash():
            raise Exception('Cannot merge, points are different: {} into {}'.format(other, self))
        msg = list()
        with self.batch_changes():
            if not other._has_default_title() and self._has_default_title():  # pylint: disable=protected-access
                msg.append('Title: {} -> {}'.format(self.title, other.title))
                self.title = other.title
            if other.description != self.description:
                msg.append('Additional description: {}'.format(
                    other.description))
                self.description += '\n'
                self.description += other.description
            if other.public and not self.public:
                msg.append('Visibility: private -> public')
                self.public = True
            if other.what != self.what:
                msg.append('What: other={} wins over self={}'.format(other.what, self.what))
            kw_src = set(other.keywords)
            kw_dst = set(self.keywords)
            if kw_src - kw_dst:
                msg.append('New keywords: {}'.format(','.join(kw_src - kw_dst)))
                self.keywords = kw_src | kw_dst
        return msg
