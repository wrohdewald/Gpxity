#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.gpx`."""


from math import asin, sqrt, degrees
import datetime


# This code would speed up parsing GPX by about 30%. When doing
# that, GPX will only return str instead of datetime for times.
#
# import gpxpy.gpxfield as mod_gpxfield
# mod_gpxfield.TIME_TYPE=None

from gpxpy import gpx as mod_gpx
from gpxpy import parse as gpxpy_parse
from gpxpy.geo import length as gpx_length, Location

from .util import repr_timespan, uniq, positions_equal

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException

# see https://github.com/tkrajina/gpxpy/issues/150
Location.__hash__ = lambda x: int(x.latitude * 1000) + int(x.longitude * 1000) + int(x.elevation * 10)  # noqa


__all__ = ['Gpx']


class Gpx(GPX):

    """Wrapper around class GPX from gpxpy.

    Attributes:
        undefined_str_marker: A new Gpx() gets this value for all str attributes
            relevant for Gpxity. This lets :class:`~gpxity.track.Track` know if
            the wanted value is already known (by loading the list of tracks
            in the backend) or if the full track needs to be read.
        real_keywords: As decoded from keywords
        is_complete: False while we hold only metadata for the track.

        category: As decoded from keywords, no translation done
        public: Decoded from keywords
        ids: Decoded from keywords

    The user may either update keywords or keywords_only/category/public/ids.
    :meth:`encode` and :meth:`decode` synchronize them.

    Gpx.parse() sets both groups.

    """

    undefined_str = '__UXNXDXEXFXIXNXEXD__'
    undefined_date = datetime.datetime(year=1970, month=1, day=3, hour=1)

    def __init__(self):
        """Put 'undefined' markers into all fields of relevance for gpxity."""
        super(Gpx, self).__init__()
        self.name = Gpx.undefined_str
        self.description = Gpx.undefined_str
        self.keywords = Gpx.undefined_str
        self.time = Gpx.undefined_date

        self.real_keywords = list()
        self.category = Gpx.undefined_str
        self.public = Gpx.undefined_str
        self.ids = list()
        self.is_complete = False

    def encode(self):
        """Set keywords from real_keywords, category, public, ids."""
        all_kw = self.real_keywords[:]  # Make sure not to change the orignal
        if self.category != Gpx.undefined_str:
            all_kw.append('Category:{}'.format(self.category))
        all_kw.append('Status:{}'.format('public' if self.public is True else 'private'))
        for _ in self.ids:
            # TODO: encode the , to something else
            all_kw.append('Id:{}'.format(_))
        self.keywords = ', '.join(all_kw) or None

    def decode(self):
        """Extract real_keywords, category, public,ids from keywords."""
        if self.keywords is None:
            self.keywords = ''
        if self.keywords == Gpx.undefined_str:
            self.category = Gpx.undefined_str
            self.public = Gpx.undefined_str
            self.ids = list()
        else:
            data = [x.strip() for x in self.keywords.split(',')]
            if data == ['']:
                data = []
            real_keywords = list()
            ids = list()
            for keyword in data:
                _ = [x.strip() for x in keyword.split(':')]
                what = _[0]
                value = ':'.join(_[1:])
                if what == 'Category':
                    self.category = value
                elif what == 'Status':
                    self.public = value == 'public'
                elif what == 'Id':
                    ids.append(value)
                else:
                    real_keywords.append(keyword)
            self.ids = ids
            self.real_keywords = sorted(x[1:] if x.startswith('-') else x for x in real_keywords)

    @property
    def first_time(self) ->datetime.datetime:
        """datetime.datetime: start time of track.

        For a simpler implementation of backends, notably :class:`~gpxity.backends.mmt.MMT`
        we ignore gpx.time. Instead we return the time of the earliest track point.
        Only if there is no track point, return gpx.first_time. If that is unknown
        too, return None.

        For the same reason time is readonly.

        We assume that the first point comes first in time and the last
        point comes last in time. In other words, points should be ordered
        by their time.

        """
        try:
            return next(self.points()).time
        except StopIteration:
            return self.time

    @property
    def distance(self) ->float:
        """For me, the earth is flat.

        Returns:
            the distance in km, rounded to m. 0.0 if not computable.  # TODO: needs unittest

        """
        return round(gpx_length(list(self.points())) / 1000, 3)

    def add_points(self, points):
        """Just add points."""
        if points:
            if self.tracks:
                # make sure the same points are not added twice
                _ = self.tracks[-1].segments[-1]
                assert points != _.points[-len(points):]
            else:
                self.tracks.append(GPXTrack())
                self.tracks[0].segments.append(GPXTrackSegment())
            self.tracks[-1].segments[-1].points.extend(points)

    @classmethod
    def parse(cls, indata, is_complete: bool = True):
        """Parse xml data.

        Args:
            indata: may be a file descriptor or str
            is_complete: indata holds the entire track info, not just metadata

        Returns: Gpx()

        """
        result = Gpx()
        result.is_complete = is_complete
        if hasattr(indata, 'read'):
            indata = indata.read()
        if indata:
            # gpxpy.gpx has no classmethod constructor. This should be simpler.
            gpx = gpxpy_parse(indata)
            for _ in gpx.__slots__:
                setattr(result, _, getattr(gpx, _))
            result.workaround_for_gpxpy_issue_140()
            result.decode()
            if result.name is None:
                result.name = ''
            if result.description is None:
                result.description = ''
        return result

    def workaround_for_gpxpy_issue_140(self):
        """Remove empty track extension elements.

        Maybe we have to do that for other extension elements too.
        But I hope gpxity can soon enough depend on a fixed stable
        version of gpxpy.

        """
        for track in self.tracks:
            track.extensions = [x for x in track.extensions if len(x) or x.text is not None]

    def xml(self) ->str:
        """Produce exactly one line per trackpoint for easier editing (like removal of unwanted points).

        Returns: The xml string.

        """
        result = super(Gpx, self).to_xml()
        result = result.replace('</trkpt><', '</trkpt>\n<')
        result = result.replace('<copyright ></copyright>', '')   # gpxviewer does not accept such illegal xml
        result = result.replace('<link ></link>', '')
        result = result.replace('<author>\n</author>\n', '')
        result = result.replace('\n</trkpt>', '</trkpt>')
        result = result.replace('>\n<ele>', '><ele>')
        result = result.replace('>\n<time>', '><time>')
        result = result.replace('</ele>\n<time>', '</ele><time>')
        result = result.replace('.0</ele>', '</ele>')  # this could differ depending on the source
        # for newer gpxpy 1.3.3 which indents the xml:
        result = result.replace('\n      </trkpt>', '</trkpt>')
        result = result.replace('>\n        <ele>', '><ele>')
        result = result.replace('>\n        <time>', '><time>')
        result = result.replace('\n\n', '\n')
        if not result.endswith('\n'):
            result += '\n'
        return result

    @property
    def last_time(self) ->datetime.datetime:
        """The last time we received.

        Returns:

            The last time we received so far. If none, return None."""
        _ = self.last_point()
        return _.time if _ else None

    def speed(self) ->float:
        """Speed over the entire time in km/h or 0.0.

        Returns:
            The speed

        """
        time_range = (self.first_time, self.last_time)
        if time_range[0] is None or time_range[1] is None:
            return 0.0
        duration = time_range[1] - time_range[0]
        seconds = duration.days * 24 * 3600 + duration.seconds
        if seconds:
            return self.distance / seconds * 3600
        return 0.0

    def moving_speed(self) ->float:
        """Speed for time in motion in km/h.

        Returns:
            The moving speed

        """
        bounds = self.get_moving_data()
        if bounds.moving_time:
            return bounds.moving_distance / bounds.moving_time * 3.6
        return 0.0

    def __repr__(self) ->str:
        """The repr.

        Returns:
            the repr str

        """
        parts = []
        if self.keywords:
            parts.append(self.keywords)
        if self.name:
            parts.append(self.name)
        if self.first_time and self.last_time:
            parts.append(repr_timespan(self.first_time, self.last_time))
        elif self.first_time:
            parts.append(str(self.first_time))
        if self.distance:
            parts.append('{:4.2f}km'.format(self.distance))
        return '{}({})'.format(str(self), ' '.join(parts))

    def __str__(self) ->str:
        """The str.

        Returns: same as __repr__

        """
        return self.__repr__()

    def angle(self, precision=None) ->float:
        """For me, the earth is flat.

        Args:
            precision: After comma digits. Default is  6.

        Returns:
            the angle in degrees 0..360 between start and end.
            If we have no track, return 0

        """
        try:
            first_point = next(self.points())
        except StopIteration:
            return 0
        last_point = self.last_point()
        if precision is None:
            precision = 6
        delta_lat = round(first_point.latitude, precision) - round(last_point.latitude, precision)
        delta_long = round(first_point.longitude, precision) - round(last_point.longitude, precision)
        norm_lat = delta_lat / 90.0
        norm_long = delta_long / 180.0
        try:
            result = degrees(asin(norm_long / sqrt(norm_lat**2 + norm_long ** 2)))
            if norm_lat >= 0.0:
                result = (360.0 + result) % 360.0
            else:
                result = 180.0 - result
        except ZeroDivisionError:
            result = 0
        return result

    def segments(self):
        """
        A generator over all segments.

        Yields:
            GPXTrackSegment: all segments in all tracks

        """
        for track in self.tracks:
            for segment in track.segments:
                yield segment

    def points(self):
        """
        A generator over all points.

        Yields:
            GPXTrackPoint: all points in all tracks and segments

        """
        for segment in self.segments():
            for point in segment.points:
                yield point

    def point_list(self):
        """A flat list with all points.

        Returns:
            The list

        """
        return sum((x.points for x in self.segments()), [])

    def last_point(self):
        """Return the last point of the track. None if none."""
        # TODO: unittest for track without __gpx or without points
        try:
            return self.tracks[-1].segments[-1].points[-1]
        except IndexError:
            return None

    def adjust_time(self, delta):  # pylint: disable=arguments-differ
        """Add a timedelta to all times.

        gpxpy.gpx.adjust_time does the same but it ignores waypoints.
        A newer gpxpy.py has a new bool arg for adjust_time which
        also adjusts waypoints on request but I do not want to check versions.

        """
        super(Gpx, self).adjust_time(delta)
        for wpt in self.waypoints:
            wpt.time += delta
        self.time += delta

    def points_hash(self) -> float:
        """A hash that is hopefully different for every possible track.

        It is built using the combination of all points.

        Returns:
            The hash

        """
        result = 1.0
        for point in self.points():
            if point.longitude:
                result *= point.longitude
            if point.latitude:
                result *= point.latitude
            if point.elevation:
                result *= point.elevation
            _ = point.first_time
            if _:
                result *= (_.hour + 1)
                result *= (_.minute + 1)
                result *= (_.second + 1)
            result %= 1e20
        return result

    def points_equal(self, other, digits=4) ->bool:
        """
        Compare points for same position.

        Args:
            digits: Number of after comma digits to compare

        Returns:
            True if both tracks have identical points.

        All points of all tracks and segments are combined. Elevations are ignored.

        """
        # We do not use points_hash because we want to abort as soon as we know
        # they are different.
        if self.get_track_points_no() != other.get_track_points_no():
            return False
        for _, (point1, point2) in enumerate(zip(self.points(), other.points())):
            if not positions_equal(point1, point2, digits):
                return False
        return True

    def index(self, other, digits=4):
        """Check if this gpx contains other track gpx.

        This only works if all values for latitude and longitude are
        nearly identical.

        Useful if one of the gpx had geofencing applied.

        Args:
            digits: How many after point digits are used

        Returns:
            None or the starting index for other.points in self.points

        """
        self_points = self.point_list()
        other_points = other.point_list()
        for self_idx in range(len(self_points) - len(other_points) + 1):
            for other_idx, other_point in enumerate(other_points):
                if not positions_equal(self_points[self_idx + other_idx], other_point, digits):
                    break
            else:
                return self_idx
        return None

    @staticmethod
    def __time_diff(last_point, point):
        """Return difference in seconds, ignoring the date."""
        result = abs(last_point.hhmmss - point.hhmmss)
        if result > 33200:  # seconds in 12 hours
            result = 86400 - result
        return result

    @staticmethod
    def __point_is_near(last_point, point, delta_meter):
        """Return True if distance < delta_meter."""
        return abs(last_point.distance_2d(point)) < delta_meter

    def fix_jumps(self, minutes=30) ->bool:  # noqa pylint: disable=too-many-branches
        """Split segments at jumps.

        Whenever the time jumps back or more than X
        minutes into the future or the distance exceeds 5km,
        split the segment at that point.

        Returns: True if a split happened

        """
        result = False
        new_tracks = list()
        for track in self.tracks:
            new_segments = list()
            for segment in track.segments:
                if not segment.points:
                    result = True  # sort of - but also needs a rewrite
                    continue
                new_segment = GPXTrackSegment()
                new_segment.points.append(segment.points[0])
                for point in segment.points[1:]:
                    prev_point = new_segment.points[-1]
                    needs_break = False
                    if point.time is None and prev_point.time is not None:
                        needs_break = True
                    elif point.time is None and prev_point.time is None:
                        if point.distance_2d(prev_point) > 5000:
                            needs_break = True
                    elif point.time is not None and prev_point.time is None:
                        needs_break = True
                    elif point.time - prev_point.time > datetime.timedelta(minutes=minutes):
                        needs_break = True
                    elif point.time < prev_point.time:
                        needs_break = True
                    elif point.distance_2d(prev_point) > 5000:
                        needs_break = True
                    if needs_break:
                        result = True
                        new_segments.append(new_segment)
                        new_segment = GPXTrackSegment()
                    new_segment.points.append(point)
                new_segments.append(new_segment)
            new_track = GPXTrack()
            new_track.segments.extend(new_segments)
            new_tracks.append(new_track)
        if result:
            self.tracks = new_tracks
        return result

    def fix_orux(self) ->bool:
        """Try to fix Oruxmaps problems.

        1. the 24h bugs

        TODO: right now, result is always True even if nothing was done

        Returns: True if something changed.

        """
        all_points = list(uniq(self.points()))
        for _ in all_points:
            _.hhmmss = _.time.hour * 3600.0 + _.time.minute * 60
            _.hhmmss += _.time.second + _.time.microsecond / 1000000
        new_points = list([all_points.pop(0)])
        while all_points:
            last_point = new_points[-1]
            near_points = [x for x in all_points if self.__point_is_near(last_point, x, 10000)]
            if not near_points:
                near_points = all_points[:]
            nearest = min(near_points, key=lambda x: Gpx.__time_diff(last_point, x))
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

        self.tracks = list()
        self.tracks.append(GPXTrack())
        self.tracks[0].segments.append(segment)
        return True

    def time_offset(self, other):
        """If time and last_time have the same offset between both tracks, return that time difference.
        Otherwise return None."""
        def offset(point1, point2):
            """Returns the time delta if both points have a time."""
            if point1.time and point2.time:
                return point2.time - point1.time
            return None

        start_time_delta = offset(next(self.points()), next(other.points()))
        if start_time_delta:
            end_time_delta = offset(self.last_point(), other.last_point())
            if start_time_delta == end_time_delta:
                return start_time_delta
        return None
