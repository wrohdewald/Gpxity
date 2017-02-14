#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxmove.Activity`
"""

import io
from math import asin, sqrt, degrees
import datetime


import gpxpy
from gpxpy.gpx import GPX, GPXTrack, GPXTrackSegment

from .backend import Storage


__all__ = ['Activity']


class Activity:

    """Represents an activity.

    Args:
        storage (Storage): The Storage where this Activity is _loaded from. If
            it was constructed in memory, storage is None.
        gpx (GPX): Initial content. At least one of storage or gpx must be None.

    Attributes:
        legal_what (tuple(str)): The legal values for :attr:`~Activity.what`. The first one is used
            as default value.
        storage_ids (dict(Storage, str)): Defines an id for this activity in a storage. An
            activity can be in several storages (like after
            :meth:`Storage.save <gpxmove.backend.Storage.save()>`), and every
            storage has its own scheme for unique ids.
        source_storage (Storage): The initial storage where Activity is loaded from.
            Is None if we constructed a new Activity in memory.

    Todo:
        strictly separate special keywords like what and public from general
        keywords: property keywords should not return them and not accept them.

    """

    class DuplicateKeyword(Exception):
        """All our special keywords like Status:* or What:* may only appear once in gpx.keywords"""
        pass


    legal_what = (
        'Cycling', 'Running', 'Mountain biking', 'Indoor cycling', 'Sailing', 'Walking', 'Hiking',
        'Swimming', 'Driving', 'Off road driving', 'Motor racing', 'Motorcycling', 'Enduro',
        'Skiing', 'Cross country skiing', 'Canoeing', 'Kayaking', 'Sea kayaking', 'Stand up paddle boarding',
        'Rowing', 'Windsurfing', 'Kiteboarding', 'Orienteering', 'Mountaineering', 'Skating',
        'Skateboarding', 'Horse riding', 'Hang gliding', 'Gliding', 'Flying', 'Snowboarding',
        'Paragliding', 'Hot air ballooning', 'Nordic walking', 'Snowshoeing', 'Jet skiing', 'Powerboating',
        'Miscellaneous')

    def __init__(self, storage, id_in_storage=None, gpx=None):
        if storage is not None:
            assert gpx is None
        if gpx is not None:
            assert storage is None
        super(Activity, self).__init__()
        self.storage_ids = dict()
        self.__gpx = gpx or GPX()
        self.loading = False
        self._loaded = gpx is not None
        self.source_storage = storage
        if id_in_storage:
            self.add_to_storage(storage, id_in_storage)

    @property
    def time(self) ->datetime.datetime:
        """datetime.datetime: start time of activity.
        If gpx.time is undefined, use the first time from track points."""
        if not self.__gpx.time:
            self.__gpx.time = self.__gpx.get_time_bounds()[0]
        return self.__gpx.time

    @time.setter
    def time(self, value: datetime.datetime):
        if value != self.time:
            self.__gpx.time = value

    def adjust_time(self):
        """set gpx.time to the time of the first trackpoint.
        We must do this for mapmytracks because it does
        not support uploading the time, it computes the time
        from the first trackpoint. We want to be synchronous."""
        self._load_full()
        self.__gpx.time = self.__gpx.get_time_bounds()[0]

    @property
    def title(self) -> str:
        """str: The title. Internally stored in gpx.title, but every storage
            may actually store this differently. But this is transparent to the user.
        """
        return self.__gpx.name

    @title.setter
    def title(self, value: str):
        if value != self.__gpx.name:
            self.__gpx.name = value
            for storage in self.storage_ids:
                storage.change_title(self)

    @property
    def description(self) ->str:
        """str: The description. Internally stored in gpx.description, but every storage
            may actually store this differently. But this is transparent to the user.
        """
        return self.__gpx.description

    @description.setter
    def description(self, value: str):
        if value != self.__gpx.description:
            self.__gpx.description = value
            for storage in self.storage_ids:
                storage.change_description(self)

    @property
    def what(self) ->str:
        """str: What is this activity doing?
        Returns:
            The current value or the default value (see `legal_what`)
        """
        return self._get_what_from_keywords() or Activity.legal_what[0]

    def _get_what_from_keywords(self) ->str:
        """no default value here"""
        found = list()
        for keyword in self.keywords:
            if keyword.startswith('What:'):
                value = keyword.split(':')[1]
                if value in Activity.legal_what:
                    found.append(value)
        if len(found) > 1:
            raise Activity.DuplicateKeyword('What:' + ','.join(found))
        if found:
            return found[0]

    @what.setter
    def what(self, value: str):
        if value != self._get_what_from_keywords():
            if value not in Activity.legal_what and value is not None:
                raise Exception('What {} is not known'.format(value))
            for _ in self.keywords:
                if _.startswith('What:'):
                    self.remove_keyword(_)
            self.add_keyword('What:{}'.format(value))
            for storage in self.storage_ids:
                storage.change_what(self)

    def point_count(self) ->int:
        """
        Returns:
          total count over all tracks and segments"""
        self._load_full()
        result = 0
        for track in self.__gpx.tracks:
            for segment in track.segments:
                result += len(segment.points)
        return result

    def add_to_storage(self, storage: Storage, id_in_storage: str) ->None:
        """makes activity known in storage, does not yet save/upload"""
        assert isinstance(id_in_storage, str)
        self.storage_ids[storage] = id_in_storage
        storage.activities.append(self)
        if self.source_storage is None:
            # newly constructed in memory
            self.source_storage = storage

    def _load_full(self) ->None:
        """load the full track from source_storage if not yet loaded."""
        if self.source_storage and not self._loaded and not self.loading:
            self.source_storage.load_full(self)

    def add_points(self, points) ->None:
        """adds points to last segment in the last track. If no track
        is allocated yet, do so. This only adds to this Activity instance.
        If you want to update the storage, first do this and then
        storage.update(activity).

        Args:
            points (list(GPXTrackPoint): The points to be added
            upload: If False, only add to this Activity instance.
                If True, also add in the storage if the storage supports
                this action. If it does not, raise NotImplemented.
        """
        if self.__gpx.tracks:
            # make sure the same points are not added twice
            assert points != self.__gpx.tracks[-1].segments[-1][-len(points):]
        self._load_full()
        if not self.__gpx.tracks:
            self.__gpx.tracks.append(GPXTrack())
            self.__gpx.tracks[0].segments.append(GPXTrackSegment())
        self.__gpx.tracks[-1].segments[-1].points.extend(points)

    def parse(self, infile):
        """parse GPX.
        public, title, description and what may already be set, and the may
        be redefined by infile.
        public will be or-ed from both sources and "what" will be overridden
        by infile values, if present.

        Args:
            infile: may be a file descriptor or str
        """
        assert self.loading
        old_gpx = self.__gpx
        old_keywords = self.keywords
        old_what = self.what
        old_public = self.public
        if isinstance(infile, str):
            self.__gpx = gpxpy.parse(io.StringIO(infile))
        else:
            self.__gpx = gpxpy.parse(infile)
        for keyword in old_keywords:
            if keyword.startswith('What:') or keyword == 'public':
                continue
            if keyword not in self.keywords:
                self.add_keyword(keyword)
        self.public = self.public or old_public
        if not self._get_what_from_keywords():
            self.what = old_what
        if old_gpx.name and not self.__gpx.name:
            self.__gpx.name = old_gpx.name
        if old_gpx.description and not self.__gpx.description:
            self.__gpx.description = old_gpx.description
        self._loaded = True

    def to_xml(self):
        """Produce exactly one line per trackpoint for easier editing
        (like removal of unwanted points).
        """
        self._load_full()
        result = self.__gpx.to_xml()
        result = result.replace('</trkpt><', '</trkpt>\n<')
        result = result.replace('<link ></link>', '')   # and remove those empty <link> tags
        result = result.replace('\n</trkpt>', '</trkpt>')
        result = result.replace('\n\n', '\n')
        return result

    @property
    def public(self):
        """
        bool: True if :literal:`Status:public` in self.keywords.
            Is this a private activity (can only be seen by the account holder) or
            is it public?
        """
        return 'Status:public' in self.keywords

    @public.setter
    def public(self, value):
        """stores this flag as keyword 'public'"""
        if value:
            self.add_keyword('Status:public')
        else:
            self.remove_keyword('Status:public')

    @property
    def tracks(self):
        """
        Returns:
            the list of all gpx tracks, readonly
        """
        self._load_full()
        return self.__gpx.tracks

    def last_time(self) ->datetime.datetime:
        """
        Returns:
            the last timestamp we received so far"""
        self._load_full()
        return self.__gpx.get_time_bounds().end_time

    @property
    def keywords(self):
        """list(str): represent them as a list - in GPX they are comma separated.
            Content is whatever you want. Because the GPX format does not have attributes
            for everything used by all backends, we encode some of the backend arguments
            in keywords. Example for mapmytracks: keywords = 'Status:public, What:Cycling'.
            You can set those special attributes manually with add_keyword() and remove_keyword()
            but the preferred way is to use the corresponding properties like what or public."""
        self._load_full()
        if self.__gpx.keywords:
            return list(x.strip() for x in self.__gpx.keywords.split(','))
        else:
            return list()

    @keywords.setter
    def keywords(self, value):
        """replace all keywords with a new list.

        Args:
            value (list(str)): a list of keywords

        Todo:
            ensure our special keywords are unique
        """
        self.__gpx.keywords = ', '.join(value)

    def add_keyword(self, value: str) ->None:
        """adds to the comma separated keywords. Special logic for our special
        keywords like Status:public or What:Cycling.

        Args:
            value: the keyword
        """
        self._load_full()
        have_keywords = self.keywords
        if value == 'Status:public' and 'Status:public' in have_keywords:
            return
        if value.startswith('What:'):
            if self._get_what_from_keywords():
                raise Activity.DuplicateKeyword('What:{}, {}'.format(
                    self._get_what_from_keywords(), value.split(':')[1]))
        if value not in have_keywords:
            if self.__gpx.keywords:
                self.__gpx.keywords += ', {}'.format(value)
            else:
                self.__gpx.keywords = value

    def remove_keyword(self, value: str):
        """removes from the keywords.

        Args:
            value: the keyword to be removed
        """
        self._load_full()
        self.__gpx.keywords = ', '.join(x for x in self.keywords if x != value)

    def __repr__(self):
        parts = [','.join(sorted(set(self.storage_ids.values())))]
        if self.__gpx:
            parts.append(self.what)
            if self.__gpx.name:
                parts.append(self.__gpx.name)
            if self.__gpx.get_time_bounds()[0]:
                parts.append('{}-{}'.format(*self.__gpx.get_time_bounds()))
            parts.append('{} points'.format(self.point_count()))
            if self.angle():
                parts.append('angle={}'.format(self.angle()))
        return 'Activity({})'.format(' '.join(parts))

    def __str__(self):
        return self.__repr__()

    def key(self) ->str:
        """for speed optimized equality checks, not granted to be exact

        Returns:
            a string with selected attributes in printable form
        """
        self._load_full()
        return 'title:{} description:{} keywords:{} hash:{} angle:{} points:{}'.format(
            self.title, self.description,
            ','.join(self.keywords), self.__hash__(), self.angle(), self.point_count())

    def __hash__(self) ->int:
        """does not  have to be unique. Using the time of the last point"""
        self._load_full()
        if not self.__gpx.tracks:
            return 0
        last_time = self.__gpx.tracks[-1].segments[-1].points[-1].time
        return int(last_time.timestamp())

    def angle(self) ->float:
        """For me, the earth is flat.

        Returns:
            the angle in degrees 0..360 between start and end.
        """
        self._load_full()
        if not self.__gpx.tracks:
            return None
        first_point = self.__gpx.tracks[0].segments[0].points[0]
        last_point = self.__gpx.tracks[-1].segments[-1].points[-1]
        delta_lat = first_point.latitude - last_point.latitude
        delta_long = first_point.longitude - last_point.longitude
        norm_lat = delta_lat / 90.0
        norm_long = delta_long / 180.0
        try:
            result = int(degrees(asin(norm_long / sqrt(norm_lat**2 + norm_long **2))))
        except ZeroDivisionError:
            return 0
        if norm_lat >= 0.0:
            return (360.0 + result) % 360.0
        else:
            return 180.0 - result

    def all_points(self):
        """
        First, this fully loads the activity if not yet done.

        Yields:
            GPXTrackPoint: all points in all tracks and segments
        """
        self._load_full()
        for track in self.__gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    yield point

    def points_equal(self, other, verbose=False) ->bool:
        """
        First, this fully loads the activity if not yet done.

        Returns:
            True if both have identical points. All points of all tracks and segments are combined.
        """
        self._load_full()
        if self.point_count() != other.point_count():
            if verbose:
                print('Activities {} and {} have different # of points'.format(self, other))
            return False
        if self.angle() != other.angle():
            if verbose:
                print('Activities {} and {} have different angle'.format(self, other))
            return False
        for idx, (point1, point2) in enumerate(zip(self.all_points(), other.all_points())):
            # GPXTrackPoint has no __eq__ and no working hash()
            # those are only the most important attributes:
            if point1.longitude != point2.longitude:
                if verbose:
                    print('{} and {}: Points #{} have different longitude: {}, {}'.format(
                        self, other, idx, point1, point2))
                return False
            if point1.latitude != point2.latitude:
                if verbose:
                    print('{} and {}: Points #{} have different latitude: {}, {}'.format(
                        self, other, idx, point1, point2))
                return False
            if point1.elevation != point2.elevation:
                if verbose:
                    print('{} and {}: Points #{} have different elevation: {}, {}'.format(
                        self, other, idx, point1, point2))
                return False
        return True
