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


import gpxpy
from gpxpy.gpx import GPX, GPXTrack, GPXTrackSegment



__all__ = ['Activity']


class Activity:

    """Represents an activity.

    An activity is essentially a GPX file. If a backend supports attributes not directly
    supported by the GPX format like the MapMyTracks activity type, they will
    transparently be encodeded in existing GPX fields like keywords, see :attr:`keywords`.

    The GPX part is done by https://github.com/tkrajina/gpxpy.

    If an activity is assigned to a backend, all changes will by default be written directly to the backend.
    Some backends are able to change only one attribute with little time overhead, others always have
    to rewrite the entire activity.

    You can use the context manager :meth:`batch_changes`. This holds back updating the backend until
    the context is exiting.

    Not all backends support everything, you could get the exception NotImplementedError.


    Args:
        backend (Backend): The Backend where this Activity lives in. See :attr:`backend`.
        id_in_backend (str): The identifier of this activity in the backend. See :attr:`id_in_backend`.
        gpx (GPX): Initial content.

    At least one of **backend** or **gpx** must be None. If backend is None and this
    activity is later coupled with a backend, it is silently assumed that the activity did
    not yet exist in that backend. That makes a difference when loading data from
    the backend: If data is expected in the backend but not found, an exception is raised. If
    no data is expected, we do not try to load data.

    The data will only be loaded from the backend when it is needed. Some backends
    might support loading some attributes separately, but for now, we always load
    everything as soon as anything is needed.

    Attributes:
        legal_what (tuple(str)): The legal values for :attr:`~Activity.what`. The first one is used
            as default value.

            Currently those are the values as defined by mapmytracks.
            This should eventually become more flexible.
        id_in_backend (str): Every backend has its own scheme for unique activity ids. Some
            backends may change the id if the activity data changes.
    """

    # pylint: disable = too-many-instance-attributes

    legal_what = (
        'Cycling', 'Running', 'Mountain biking', 'Indoor cycling', 'Sailing', 'Walking', 'Hiking',
        'Swimming', 'Driving', 'Off road driving', 'Motor racing', 'Motorcycling', 'Enduro',
        'Skiing', 'Cross country skiing', 'Canoeing', 'Kayaking', 'Sea kayaking', 'Stand up paddle boarding',
        'Rowing', 'Windsurfing', 'Kiteboarding', 'Orienteering', 'Mountaineering', 'Skating',
        'Skateboarding', 'Horse riding', 'Hang gliding', 'Gliding', 'Flying', 'Snowboarding',
        'Paragliding', 'Hot air ballooning', 'Nordic walking', 'Snowshoeing', 'Jet skiing', 'Powerboating',
        'Miscellaneous')

    def __init__(self, backend=None, id_in_backend: str = None, gpx=None):
        self._loading = False
        self._loaded = backend is None or id_in_backend is None
        self.__dirty = set()
        self._batch_changes = False
        self.__what = self.legal_what[0]
        self.__public = False
        self.id_in_backend = id_in_backend
        self.__gpx = gpx or GPX()
        self.__backend = None
        if backend is not None:
            if gpx is not None:
                raise Exception('Cannot accept backend and gpx')
        self.__backend = backend
        if backend and self not in backend.activities:
            backend.activities.append(self)

    @property
    def backend(self):
        """The backend this activity lives in. If it was constructed in memory, backend is None.
        If you change it from None to a backend, this activity is automatically saved in that backend.

        It is not possible to decouple an activity from its backend, use :meth:`~gpxity.activity.Activity.clone()`.

        It is not possible to move the activity to a different backend by changing this.
        Use :meth:`Backend.save() <gpxity.backend.Backend.save()>` instead.
        """
        return self.__backend

    @backend.setter
    def backend(self, value):
        if value is not self.__backend:
            if value is None:
                raise Exception('You cannot decouple an activity from its backend. Use clone().')
            elif self.__backend is not None:
                raise Exception(
                    'You cannot assign the activity to a different backend this way. '
                    'Please use Backend.save(activity).')
            else:
                self._loaded = True
                self.__backend = value
                try:
                    self.__backend.save(self)
                except BaseException:
                    self.__backend = None
                    raise

    @property
    def dirty(self) ->bool:
        """
        Is the activity in sync with the backend?

        After directly manipulating :attr:`gpx`, set dirty to True.
        See also :meth:`~gpxity.activity.Activity.gpx`.

        Setting dirty to True will directly call :meth:`~gpxity.activity.Activity._save`.

        Setting dirty to False is not allowed.

        Returns:
            bool: True if the activity is not in sync with the backend. If no backend is
            associated, False stands for an empty activity.
        """
        return bool(self.__dirty)

    @dirty.setter
    def dirty(self, value):
        if not value:
            raise Exception('You may not set dirty to False. Instead use _save().')
        if self._loading:
            return

        if isinstance(value, bool):
            self.__dirty = set(['all'])
        else:
            self.__dirty.add(value)
        self._save()

    def clone(self):
        """Creates a new activity with the same content but without backend.

        Returns:
            the new activity
        """
        result = Activity(gpx=self.__gpx.clone())
        result.what = self.what
        result.public = self.public
        return result

    def _save(self):
        """Saves all changes in the associated backend.

        If any of those conditions is met, do nothing:

        - we are currently loading from backend: Avoid recursion
        - batch_changes is active
        - we have no backend

        Otherwise asks the backend to save this activity :meth:`Backend.save() <gpxity.backend.Backend.save>`.
        """
        if self.__dirty:
            if self.backend and not self._loading and not self._batch_changes:
                self.backend.save(self, self.__dirty) # pylint: disable=no-member
                self.__dirty = set()

    @property
    def time(self) ->datetime.datetime:
        """datetime.datetime: start time of activity.
        For a simpler implementation of backends, notably MMT, we ignore
        gpx.time. Instead we return the time of the earliest track point.
        Only if there is no track point, return gpx.time.

        For the same reason time is readonly.
        """
        return self.__gpx.get_time_bounds()[0] or self.__gpx.time

    @property
    def title(self) -> str:
        """str: The title.
        """
        self._load_full()
        return self.__gpx.name

    @title.setter
    def title(self, value: str):
        if value != self.title:
            self.__gpx.name = value
            self.dirty = 'title'

    @property
    def description(self) ->str:
        """str: The description.
        """
        self._load_full()
        return self.__gpx.description

    @contextmanager
    def loading(self):
        """This context manager marks the activity as being loaded. In
        that state, automatic writes of changes into the backend are
        disabled.

        You should never need this unless you write a new backend.
        """
        prev_loading = self._loading
        self._loading = True
        try:
            yield
        finally:
            self._loading = prev_loading

    @property
    def is_loading(self):
        """True if we are currently loading. See :meth:`loading`."""
        return self._loading

    @contextmanager
    def batch_changes(self):
        """This context manager disables  the direct update in the backend
        and saves the entire activity when done.
        """
        prev_batch_changes = self._batch_changes
        self._batch_changes = True
        try:
            yield
            self._save()
        finally:
            self._batch_changes = prev_batch_changes
            self._save()

    @description.setter
    def description(self, value: str):
        if value != self.description:
            self.__gpx.description = value
            self.dirty = 'description'

    @property
    def what(self) ->str:
        """str: What is this activity doing? If we have no current value,
        return the default.

        Returns:
            The current value or the default value (see :attr:`legal_what`)
        """
        self._load_full()
        return self.__what

    @what.setter
    def what(self, value: str):
        if value != self.what:
            if value not in Activity.legal_what and value is not None:
                raise Exception('What {} is not known'.format(value))
            self.__what = value if value else self.legal_what[0]
            self.dirty = 'what'

    def _load_full(self) ->None:
        """Loads the full track from source_backend if not yet loaded."""
        if self.backend and self.id_in_backend and not self._loaded and not self._loading:
            self.backend.load_full(self) # pylint: disable=no-member
            self._loaded = True

    def add_points(self, points) ->None:
        """Adds points to last segment in the last track. If no track
        is allocated yet, do so.

        UNFINISHED

        Args:
            points (list(GPXTrackPoint): The points to be added
        """
        if self.__gpx.tracks:
            # make sure the same points are not added twice
            assert points != self.__gpx.tracks[-1].segments[-1].points[-len(points):]
        self._load_full()
        if not self.__gpx.tracks:
            self.__gpx.tracks.append(GPXTrack())
            self.__gpx.tracks[0].segments.append(GPXTrackSegment())
        self.__gpx.tracks[-1].segments[-1].points.extend(points)

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
        with self.loading():
            old_gpx = self.__gpx
            old_public = self.public
            self.__gpx = gpxpy.parse(indata)
            self._parse_keywords()
            self.public = self.public or old_public
            if old_gpx.name and not self.__gpx.name:
                self.__gpx.name = old_gpx.name
            if old_gpx.description and not self.__gpx.description:
                self.__gpx.description = old_gpx.description
            self._loaded = True

    def to_xml(self) ->str:
        """Produces exactly one line per trackpoint for easier editing
        (like removal of unwanted points).
        """
        self._load_full()
        new_keywords = self.keywords
        new_keywords.append('What:{}'.format(self.what))
        if self.public:
            new_keywords.append('Status:public')
        old_keywords = self.__gpx.keywords
        try:
            self.__gpx.keywords = ', '.join(new_keywords)

            result = self.__gpx.to_xml()
            result = result.replace('</trkpt><', '</trkpt>\n<')
            result = result.replace('<link ></link>', '')   # and remove those empty <link> tags
            result = result.replace('\n</trkpt>', '</trkpt>')
            result = result.replace('\n\n', '\n')
        finally:
            self.__gpx.keywords = old_keywords
        return result

    @property
    def public(self):
        """
        bool: Is this a private activity (can only be seen by the account holder) or
            is it public?
        """
        self._load_full()
        return self.__public

    @public.setter
    def public(self, value):
        """Stores this flag as keyword 'public'."""
        if value != self.public:
            self.__public = value
            self.dirty = 'public'

    @property
    def gpx(self) ->GPX:
        """
        Direct access to the GPX object. If you use it to change its content,
        remember to set :attr:`dirty` to True afterwards.

        Returns:
            the GPX object
        """
        self._load_full()
        return self.__gpx

    def last_time(self) ->datetime.datetime:
        """
        Returns:
            the last timestamp we received so far."""
        self._load_full()
        return self.__gpx.get_time_bounds().end_time

    @property
    def keywords(self):
        """list(str): represents them as a list - in GPX they are comma separated.
            Content is whatever you want.

            Because the GPX format does not have attributes for everything used by all backends,
            we encode some of the backend arguments in keywords.

            Example for mapmytracks: keywords = 'Status:public, What:Cycling'.

            However this is transparent for you. When parsing theGPX file, those are removed
            from keywords, and the are re-added in when exporting in :meth:`to_xml`.
        """
        self._load_full()
        if self.__gpx.keywords:
            return list(x.strip() for x in self.__gpx.keywords.split(','))
        return list()

    @keywords.setter
    def keywords(self, value):
        """Replaces all keywords with a new list.

        Args:
            value (list(str)): a list of keywords
        """
        self._load_full()
        with self.batch_changes():
            self.__gpx.keywords = ''
            for keyword in value:
                # add_keyword ensures we do not get unwanted things like What:
                self.add_keyword(keyword)

    @staticmethod
    def _check_keyword(keyword):
        """Must not be What: or Status:"""
        if keyword.startswith('What:'):
            raise Exception('Do not use this directly,  use Activity.what')
        if keyword.startswith('Status:'):
            raise Exception('Do not use this directly,  use Activity.public')

    def add_keyword(self, value: str) ->None:
        """Adds to the comma separated keywords. Duplicate keywords are not allowed.

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
        self.dirty = 'keywords'

    def remove_keyword(self, value: str) ->None:
        """Removes from the keywords.

        Args:
            value: the keyword to be removed
        """
        self._check_keyword(value)
        self._load_full()
        self.__gpx.keywords = ', '.join(x for x in self.keywords if x != value)
        self.dirty = 'keywords'

    def __repr__(self):
        parts = []
        if self.backend:
            parts.append(repr(self.backend))
            parts.append('id:{}'.format(self.id_in_backend))
        if self.__gpx:
            parts.append(self.what)
            if self.__gpx.name:
                parts.append(self.__gpx.name)
            if self.__gpx.get_time_bounds()[0]:
                parts.append('{}-{}'.format(*self.__gpx.get_time_bounds()))
            parts.append('{} points'.format(self.gpx.get_track_points_no()))
            if self.angle():
                parts.append('angle={}'.format(self.angle()))
        return 'Activity({})'.format(' '.join(parts))

    def __str__(self):
        return self.__repr__()

    def key(self) ->str:
        """For speed optimized equality checks, not granted to be exact.

        Returns:
            a string with selected attributes in printable form.
        """
        self._load_full()
        return 'title:{} description:{} keywords:{} what:{}: public:{} last_time:{} angle:{} points:{}'.format(
            self.title, self.description,
            ','.join(self.keywords), self.what, self.public, self.last_time(),
            self.angle(), self.gpx.get_track_points_no())

    def angle(self) ->float:
        """For me, the earth is flat.

        Returns:
            the angle in degrees 0..360 between start and end.
            If we have no track, return 0
        """
        self._load_full()
        if not self.__gpx.tracks:
            return 0
        first_point = self.__gpx.tracks[0].segments[0].points[0]
        last_point = self.__gpx.tracks[-1].segments[-1].points[-1]
        delta_lat = first_point.latitude - last_point.latitude
        delta_long = first_point.longitude - last_point.longitude
        norm_lat = delta_lat / 90.0
        norm_long = delta_long / 180.0
        try:
            result = degrees(asin(norm_long / sqrt(norm_lat**2 + norm_long **2)))
        except ZeroDivisionError:
            return 0
        if norm_lat >= 0.0:
            return (360.0 + result) % 360.0
        return 180.0 - result

    def all_points(self):
        """
        Yields:
            GPXTrackPoint: all points in all tracks and segments
        """
        self._load_full()
        for track in self.__gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    yield point

    def points_equal(self, other) ->bool:
        """
        Returns:
            True if both activities have identical points.

        All points of all tracks and segments are combined.
        """
        self._load_full()
        if self.gpx.get_track_points_no() != other.gpx.get_track_points_no():
            return False
        if self.angle() != other.angle():
            return False
        for _, (point1, point2) in enumerate(zip(self.all_points(), other.all_points())):
            # GPXTrackPoint has no __eq__ and no working hash()
            # those are only the most important attributes:
            if point1.longitude != point2.longitude:
                return False
            if point1.latitude != point2.latitude:
                return False
            if point1.elevation != point2.elevation:
                return False
        return True
