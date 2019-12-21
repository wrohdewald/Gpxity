#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.gpx`."""

from math import asin, sqrt, degrees
import datetime
import logging

from lxml import etree

# This code would speed up parsing GPX by about 30%. When doing
# that, GPX will only return str instead of datetime for times.
#
# import gpxpy.gpxfield as mod_gpxfield
# mod_gpxfield.TIME_TYPE=None

from gpxpy import gpx as mod_gpx
from gpxpy import parse as gpxpy_parse
from gpxpy.geo import length as gpx_length, Location
from gpxpy.geo import simplify_polyline

import geocoder
from geocoder.location import Location as Geocoder_location

from .util import repr_timespan, uniq, positions_equal

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXTrackPoint = mod_gpx.GPXTrackPoint
GPXWaypoint = mod_gpx.GPXWaypoint
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException

# see https://github.com/tkrajina/gpxpy/issues/150
Location.__hash__ = lambda x: int(x.latitude * 1000) + int(x.longitude * 1000) + int(x.elevation * 10)  # noqa


__all__ = ['Gpx']


class Gpx(GPX):

    """Wrapper around class GPX from gpxpy.

    Attributes:
        undefined_str_marker: A new Gpx() gets this value for all str attributes
            relevant for Gpxity. This lets :class:`~gpxity.gpxfile.GpxFile` know if
            the wanted value is already known (by loading the list of tracks
            in the backend) or if the full gpxfile needs to be read.
        real_keywords: As decoded from keywords
        is_complete: False while we hold only metadata for the gpxfile. __init__ sets it to True,
            callers loading only metadata must switch it to False and back to True when the full data is loaded.
        default_country: This is automatically set when the Gpx is part
            of a concrete Backend. Used for location names: the default country name
            will not be added. This values comes from Account.country.

        category: As decoded from keywords, no translation done
        public: Decoded from keywords
        ids: Decoded from keywords

    The user may either update keywords or keywords_only/category/public/ids.
    :meth:`encode` and :meth:`decode` synchronize them.

    Gpx.parse() sets both groups.

    """

    # pylint: disable=too-many-instance-attributes

    undefined_str = '__UXNXDXEXFXIXNXEXD__'
    undefined_date = datetime.datetime(year=1970, month=1, day=3, hour=1, tzinfo=datetime.timezone.utc)
    _seg_wpt_prefix = 'Trk/Seg '

    def __init__(self):
        """Put 'undefined' markers into all fields of relevance for gpxity."""
        super(Gpx, self).__init__()
        self.name = Gpx.undefined_str
        self.description = Gpx.undefined_str
        self.keywords = Gpx.undefined_str
        self.time = Gpx.undefined_date
        self.__cached_speed = None
        self.default_country = None

        self.real_keywords = list()
        self.category = Gpx.undefined_str
        self.public = Gpx.undefined_str
        self.ids = list()
        self.is_complete = True

    def clone(self):
        """Clone.

        Returns: Gpx

        """
        result = super(Gpx, self).clone()
        result.default_country = self.default_country
        result.real_keywords = self.real_keywords[:]
        result.category = self.category
        result.public = self.public
        result.ids = self.ids[:]
        result.is_complete = self.is_complete
        return result

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
        if self.get_track_points_no():
            first_point = next(self.points())
            if first_point.time:
                self.time = first_point.time
        if self.is_complete:
            if self.name == Gpx.undefined_str:
                self.name = ''
            if self.description == Gpx.undefined_str:
                self.description = ''

    def decode(self):
        """Extract real_keywords, category, public,ids from keywords."""
        self.__cached_speed = None
        self.__update_segment_waypoints()
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
            result = next(self.points()).time
            if result:
                assert result.tzinfo, 'first point time has no tzinfo:{}'.format(result)
        except StopIteration:
            result = self.time
            if result:
                assert result.tzinfo, 'gpx.time has no tzinfo:{}'.format(result)
        return result

    @property
    def distance(self) ->float:
        """For me, the earth is flat.

        Returns:
            the distance in km, rounded to m. 0.0 if not computable.  # TODO: needs unittest

        """
        return round(gpx_length(list(self.points())) / 1000, 3)

    def add_points(self, points):
        """Just add points. Silently ignore points which are allready in this Gpx."""
        if points:
            if not self.tracks:
                self.tracks.append(GPXTrack())
                self.tracks[0].segments.append(GPXTrackSegment())
            self.tracks[-1].segments[-1].points.extend(points)

    @classmethod
    def parse(cls, indata, is_complete: bool = True):
        """Parse xml data.

        Args:
            indata: may be a file descriptor or str
            is_complete: indata holds the entire gpxfile info, not just metadata

        Returns: Gpx()

        """
        result = Gpx()
        result.is_complete = is_complete
        if hasattr(indata, 'read'):
            indata = indata.read()
        if indata:
            # gpxpy.gpx has no classmethod constructor. This should be simpler.
            try:
                gpx = gpxpy_parse(indata)
            except GPXXMLSyntaxException as exc:
                logging.error('GPX Syntax error in %s: %s', indata, exc)
                raise
            for _ in gpx.__slots__:
                setattr(result, _, getattr(gpx, _))
            result.workaround_for_gpxpy_issue_140()
            result.decode()
            if result.name is None:
                result.name = ''
            if result.description is None:
                result.description = ''
        result._add_missing_tzinfo()  # pylint: disable=protected-access
        return result

    def _add_missing_tzinfo(self):
        """Add missing tzinfo to all times.

        Gpxpy does not always set it but python3.7.3 disallows mixing times with and without tzinfo.

        """
        if self.time:
            if not self.time.tzinfo:
                self.time = self.time.replace(tzinfo=datetime.timezone.utc)
        for _ in self.points():
            if _.time:
                if not _.time.tzinfo:
                    _.time = _.time.replace(tzinfo=datetime.timezone.utc)

    def workaround_for_gpxpy_issue_140(self):
        """Remove empty gpx extension elements.

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
        assert self.is_complete, 'Not complete: {}'.format(str(self))
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
        result = result.replace('>\n        <name>', '><name>')
        result = result.replace('\n\n', '\n')

        # Mapsource cannot parse <bounds ... ></bounds> but that is what to_xml creates
        # we want <bounds ... />
        result = result.replace('>\n    </bounds>', ' />')

        if not result.endswith('\n'):
            result += '\n'
        return result

    @property
    def last_time(self) ->datetime.datetime:
        """The last time we received.

        Returns:

            The last time we received so far. If none, return None."""
        _ = self.last_point()
        if _ and _.time:
            assert _.time.tzinfo, _
        return _.time if _ else None

    def speed(self, points=None) ->float:
        """Speed over the entire time in km/h or 0.0.

        Args: If points is None, all are used

        Returns:
            The speed

        """
        if points is None:
            if self.__cached_speed is None:
                self.__cached_speed = self.speed(self.point_list())
            return self.__cached_speed
        time_range = (self.first_time, self.last_time)
        if time_range[0] is None or time_range[1] is None:
            return 0.0
        duration = time_range[1] - time_range[0]
        seconds = duration.days * 24 * 3600 + duration.seconds
        if seconds:
            return round(gpx_length(self.point_list()) / seconds * 3.6, 3)
        return 0.0

    def moving_speed(self) ->float:
        """Speed for time in motion in km/h.

        Returns:
            The moving speed

        """
        if self.get_track_points_no() < 20:
            # this is a magic number from gpxpy: segment too small to compute speed
            return self.speed()
        bounds = self.get_moving_data()
        if bounds.moving_time:
            return round(bounds.moving_distance / bounds.moving_time * 3.6, 3)
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
        return 'Track({})'.format(' '.join(parts))

    def __str__(self) ->str:
        """The str.

        Returns: same as __repr__

        """
        return self.__repr__()

    def angle(self, first_point=None, last_point=None, precision=None) ->float:
        """For me, the earth is flat.

        Args:
            first_point: if None, first point of Gpx
            last_point: if None, last point of Gpx
            precision: After comma digits. Default is  6.

        Returns:
            the angle in degrees 0..360 between start and end.
            If we have no two points, return 0

        """
        if first_point is None:
            try:
                first_point = next(self.points())
            except StopIteration:
                return 0
        if last_point is None:
            last_point = self.last_point()
            if last_point is None:
                return 0
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
        if self.time:
            self.time += delta

    def points_hash(self) -> float:
        """A hash that is hopefully different for every possible Gpx().

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
            logging.debug('Pointcount %s != %s', self.get_track_points_no(), other.get_track_points_no())
            return False
        for _, (point1, point2) in enumerate(zip(self.points(), other.points())):
            if not positions_equal(point1, point2, digits):
                logging.debug('Point #%s: %s != %s', _, point1, point2)
                return False
        return True

    def index(self, other, digits=4):
        """Check if this gpx contains other track.

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

    def split_segment_after(self, track_idx, segment_idx, point_idx):
        """Split segment after point.

        Args:
            track_idx: Track index
            segment_idx: Segment index
            point_idx: Point index

        """
        track = self.tracks[track_idx]
        if point_idx not in (0, len(track.segments[segment_idx].points) - 1):
            new_segments = track.segments[:segment_idx + 1]
            new_segments.append(GPXTrackSegment())
            new_segments[-1].points = new_segments[-2].points[point_idx + 1:]
            new_segments[-2].points = new_segments[-2].points[:point_idx + 1]
            new_segments.extend(track.segments[segment_idx + 1:])
            track.segments = new_segments

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
                    if needs_break:
                        if len(new_segment.points) == 1:
                            needs_break = False
                        elif point.distance_2d(prev_point) > 50:
                            needs_break = False
                    if needs_break:
                        result = True
                        new_segments.append(new_segment)
                        new_segment = GPXTrackSegment()
                    new_segment.points.append(point)
                new_segments.append(new_segment)
            new_gpxfile = GPXTrack()
            new_gpxfile.segments.extend(new_segments)
            new_tracks.append(new_gpxfile)
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

    def locate_point(self, track=0, segment=0, point=0):  # noqa
        """Determine name of place for point.

        Saves that in point.name for caching.

        Args:
            track, segment, point: Indices into the list

        track or point may also be a real GPXTrackPoint.

        Returns: tuple(name, located)
            name is the name of the location
            located is True if locating was needed, False if we had it cached

        """
        # pylint: disable=too-many-branches
        if isinstance(track, GPXTrackPoint):
            point = track
        if not isinstance(point, GPXTrackPoint):
            point = self.tracks[track].segments[segment].points[point]
        result = not point.name
        if result:
            # point.name = 'dummy'  # for faster testing
            # return point.name, True
            parts = []
            _ = Geocoder_location([point.latitude, point.longitude])
            place = geocoder.get(location=_, provider='osm', method='reverse')
            if place.raw is None:
                point.name = 'Water'
                return point.name, True
            fields = dict()
            for _ in ('city', 'town', 'village', 'hamlet'):
                if hasattr(place, _):
                    value = getattr(place, _)
                    if value:
                        fields[_] = value
            if 'address' in place.raw:
                fields.update(place.raw['address'])
            name = None
            prefer = ['town', 'suburb', 'village', 'hamlet', 'town', 'city', 'school']
            for _ in prefer:
                if _ in fields:
                    name = fields[_]
                    break
            if not name:
                name = place.address
            if name:
                parts.append(name)
            if not self.default_country or place.country.lower() != self.default_country.lower():
                parts.append(place.country or place.country_code)
            try:
                point.name = ','.join(parts)
            except TypeError:
                logging.error(
                    'Parsing geo info: %r country=%r(default %r) -> %r',
                    place.raw, place.country, self.default_country, parts)
                raise
        return point.name, result

    @staticmethod
    def _wpt_equal(left, right):
        """Compare two waypoints.

        Returns: True if identical

        """
        return (
            left.latitude == right.latitude and  # noqa
            left.longitude == right.longitude and  # noqa
            left.elevation == right.elevation and  # noqa
            left.time == right.time and  # noqa
            left.name == right.name and  # noqa
            left.symbol == right.symbol and  # noqa
            left.description == right.description and  # noqa
            left.type == right.type
        )

    def has_waypoint_at(self, location):
        """Check if we have a waypoint there.

        Returns: the waypoint or None

        """
        for wpt in self.waypoints:
            if wpt.latitude == location.latitude and wpt.longitude == location.longitude:
                return True
        return False

    def __update_segment_waypoints(self):
        """If the track has such waypoints, update them.

        See :meth:`add_segment_waypoints`

        Returns: True if a change happened

        """
        if any(x.name.startswith(self._seg_wpt_prefix) for x in self.waypoints):
            return self.add_segment_waypoints()
        return False

    def add_segment_waypoints(self, at_end: bool = True):
        """Every segment start gets a waypoint.

        The name looks like :literal:`Trk/Seg 2/4 Mainz-Wiesbaden`.
        Existing such waypoints are removed if the no longer belong
        to a segment start.

        For the involved points (first and last of each segment) see
        :meth:`locate_point`.

        Returns: True if a change happened

        """

        def make_wp(trk_idx, seg_idx, point, typename):
            """Make waypoint for start or end of segment.points

            Returns: GPXWaypoint

            """
            self.locate_point(point)
            debug_info = list()
            if hasattr(point, 'speed_after'):
                debug_info.append('speed:{}'.format(point.speed_after))
            if hasattr(point, 'turn'):
                debug_info.append('turn:{}'.format(point.turn))
            name = '{}{}/{} {}{}'.format(
                self._seg_wpt_prefix, trk_idx + 1, seg_idx + 1,
                ','.join(debug_info),
                point.name)
            return GPXWaypoint(
                latitude=point.latitude, longitude=point.longitude,
                elevation=point.elevation, time=point.time, name=name,
                symbol='Waypoint', type=typename)

        old_seg_wp = [x for x in self.waypoints if x.name.startswith(self._seg_wpt_prefix)]
        new_seg_wp = list()
        for trk_idx, trk in enumerate(self.tracks):
            for seg_idx, seg in enumerate(trk.segments):
                new_seg_wp.append(make_wp(trk_idx, seg_idx, seg.points[0], 'Startpunkt'))
                if at_end:
                    new_seg_wp.append(make_wp(trk_idx, seg_idx, seg.points[-1], 'Endpunkt'))
        if (len(old_seg_wp) != len(new_seg_wp)
                or any(not self._wpt_equal(old_seg_wp[x], new_seg_wp[x]) for x in range(len(old_seg_wp)))):  # noqa
            self.waypoints = [
                x for x in self.waypoints
                if hasattr(x, 'name') and not x.name.startswith(self._seg_wpt_prefix)]
            self.waypoints.extend(new_seg_wp)
            return True
        return False

    def __trackfieldnames(self):
        """The names of track fields.

        Returns: a list

        """
        if self.version == '1.1':
            fields = GPXTrack.gpx_11_fields
        else:
            fields = GPXTrack.gpx_10_fields
        return [x.name for x in fields if not isinstance(x, str) and x.name != 'segments']

    def __losing_metadata_when_joining_tracks(self):
        """Check if metadata would be lost.

        Returns: list()

        """
        losing = list()
        for name in self.__trackfieldnames():
            seen = list()
            for _ in self.tracks:
                if name == 'extensions':
                    # pylint: disable=c-extension-no-member
                    value = '///'.join(etree.tostring(x, pretty_print=False).decode('utf-8') for x in _.extensions)
                    value = value.replace('\n', '').replace('>        <', '><')
                else:
                    value = getattr(_, name)
                if value:
                    seen.append(value)
            if len(set(seen)) > 1:
                for _ in seen[1:]:
                    losing.append('{}: {}'.format(name, _))
        return losing

    def join_tracks(self, force=False):
        """Join all tracks to a single track.

        Differring metadata will not be combined.
        If metadata will be lost, it is printed and nothing is done unless force is True

        Args: force if True, join even if metadata is lost

        Returns: list()
            A list with text strings about lost metadata

        """
        losing = self.__losing_metadata_when_joining_tracks()
        if not losing or force:
            track0 = self.tracks[0]
            for other in self.tracks[1:]:
                track0.segments.extend(other.segments)
                for name in self.__trackfieldnames():
                    value0 = getattr(track0, name)
                    value1 = getattr(other, name)
                    if not value0 and value1:
                        setattr(track0, name, value1)
            self.tracks = [track0]
        return losing

    def __make_point_times_unique(self, points):
        """Yield all points. If two adjacent points have the same time, add 1 second to the second one."""
        prev = points[0]
        yield points[0]
        for point in points[1:]:
            if prev.time == point.time:
                point.time += datetime.timedelta(seconds=1)
                self.dupchanged = True  # pylint:disable=attribute-defined-outside-init
            yield point
            prev = point

    def remove_duplicate_points(self):
        """Uniquify adjacent points if both have the same time and same position.

        Treats each segment separately.

        Returns: True if changes happened.

        """
        self.dupchanged = False  # pylint:disable=attribute-defined-outside-init
        try:
            for track in self.tracks:
                for segment in track.segments:
                    segment.points = list(self.__make_point_times_unique(segment.points))
            return self.dupchanged
        finally:
            delattr(self, 'dupchanged')
        logging.error('Unknown error in Gpx.remove_duplicate_points')

    @staticmethod
    def _window(points, size=3):
        """Generate tuples with size elements.

        Returns: A list of tuples

        """
        idx = 0
        while len(points) >= idx + size:
            yield points[idx:idx + size]
            idx += 1

    def point_index_by_id(self, wanted):
        """Locate point by id.

        Returns: (track_idx, seg_idx, point_idx) or None

        """
        for track_idx, track in enumerate(self.tracks):
            for seg_idx, segment in enumerate(track.segments):
                for point_idx, point in enumerate(segment.points):
                    if id(wanted) == id(point):
                        return track_idx, seg_idx, point_idx
        assert False
        return None

    def __prepare_point_data(self):
        """Prepare point data needed for untangle()."""  # noqa
        def turn(first, middle, last):
            """The change of direction at middle point in abs(degrees): 0..180.

            Since this is done to find points within the same ball, identical positions
            should return a big degree. Both big turns and identical positions are parts of a ball.

            formula 2 at https://en.wikipedia.org/wiki/Law_of_cosines#Applications is problematic.

            Returns: 0..180
            """

            length_a = first.distance_2d(middle)
            if round(length_a) < 5:
                return 100
            length_b = middle.distance_2d(last)
            if round(length_b) < 5:
                return 100
            angle1 = self.angle(first, middle)
            angle2 = self.angle(middle, last)
            return abs(round(((angle1 - angle2) + 180) % 360 - 180))

        self.all_points = self.point_list()  # pylint:disable=attribute-defined-outside-init
        self.all_points[0].turn = 0
        self.all_points[-1].turn = 0
        for idx in range(0, len(self.all_points) - 2):
            self.all_points[idx + 1].turn = turn(*self.all_points[idx:idx + 3])
        for idx in range(0, len(self.all_points) - 1):
            first = self.all_points[idx]
            second = self.all_points[idx + 1]
            if not first.time or not second.time:
                timediff = datetime.timedelta(milliseconds=1)  # simulate high speed, so those points are kept
            else:
                timediff = second.time - first.time
                if not timediff:
                    raise Exception('{} has two adjacent points with identical time {}'.format(self, first.time))
            first.time_after = timediff
            second.time_before = timediff
            way = first.distance_2d(second)
            first.way_after = way
            second.way_before = way
            first.speed_after = round(way / timediff.total_seconds() * 3.6, 2)  # km/h
            second.speed_before = first.speed_after
        for src, dst in ((1, 0), (-2, -1)):
            self.all_points[dst].way_before = self.all_points[src].way_before
            self.all_points[dst].way_after = self.all_points[src].way_before
            self.all_points[dst].time_before = self.all_points[src].time_before
            self.all_points[dst].time_after = self.all_points[src].time_before
            self.all_points[dst].speed_before = self.all_points[src].speed_before
            self.all_points[dst].speed_after = self.all_points[src].speed_before
        for point in self.all_points:
            point.weight = round(point.speed_after * 5 - point.turn, 2)

    def __remove_single_points(self, force):
        """Remove a point if.

        - there are time gaps of at least avg * 5 before and after
        - way before and after is both < 50m
        Returns: A list of messages

        """
        result = list()
        avg_time = sum(
            (x.time_after for x in self.all_points[:-1]),
            datetime.timedelta()) / (len(self.all_points) - 1)
        remove_points = list()
        time_limit = avg_time * 5
        # for first, middle, after in self._window(self.all_points):
        for middle in self.all_points:  # TODO: TESTEN
            if middle.time is None or middle.time_before is None or middle.time_after is None:
                continue
            if (middle.time_before > time_limit and middle.time_after > time_limit):
                if middle.turn > 30 and middle.way_after < 50 and middle.way_before < 50:
                    remove_points.append(middle)

        for remove_point in reversed(remove_points):
            self.locate_point(remove_point)
            result.append(
                'removing point {} {} time before/after {}/{}'.format(
                    remove_point, remove_point.name,
                    remove_point.time_before, remove_point.time_after))
            track_idx, seg_idx, point_idx = self.point_index_by_id(remove_point)
            if force:
                # split segment after point to be removed
                self.split_segment_after(track_idx, seg_idx, point_idx)
                del self.tracks[track_idx].segments[seg_idx].points[point_idx]
        # remove empty segments
        if force:
            for track in self.tracks:
                track.segments = [x for x in track.segments if x.points]
        return result

    def untangle(self, force=False):
        """Locate stops and clean away its local erratic movements.

        Returns:A list of strings describing what happens/would happen

        """
        self.__prepare_point_data()
        self.all_points = self.point_list()  # pylint:disable=attribute-defined-outside-init
        try:
            return self.__remove_single_points(force)
        finally:
            if force:
                self.add_segment_waypoints(at_end=True)
            for _ in self.all_points:
                if logging.getLogger().level == logging.DEBUG:
                    _.name = '{} turn={} speed_after={} weight={}'.format(
                        _.name or '', _.turn, _.speed_after, _.weight)
                delattr(_, 'turn')
                delattr(_, 'way_before')
                delattr(_, 'way_after')
                delattr(_, 'time_before')
                delattr(_, 'time_after')
                delattr(_, 'speed_before')
                delattr(_, 'speed_after')
                delattr(_, 'weight')
            delattr(self, 'all_points')

    def clear_segments(self):
        """For each track, combine all segments into one."""
        for track in self.tracks:
            for segment in track.segments[1:]:
                track.segments[0].points.extend(segment.points)
            track.segments = track.segments[:1]

    def simplify(self, max_distance=None):
        """Just like gpxpy does. But if we get a strin gending with 'p', reduce to that point number."""
        try:
            max_distance = float(max_distance)
            super(Gpx, self).simplify(max_distance)
        except ValueError:
            for trk_idx, track in enumerate(self.tracks):
                for seg_idx, segment in enumerate(track.segments):
                    points = segment.points
                    _ = 0.5
                    while len(points) > int(max_distance[:-1]):
                        _ *= 1.1
                        points = simplify_polyline(segment.points[:], max_distance=_)
                    if _ > 0.5:
                        logging.info('Trk/Seg %s/%s: maximal deviation is %.02f meters, reduced from %s to %s points',
                                     trk_idx, seg_idx, _, len(segment.points), len(points))
                    segment.points = points

    def revert_direction(self):
        """Revert the direction of the track. Reverts track/segment order and points within."""
        for _ in self.points():
            if not _.time:
                # TODO: generalize
                raise Exception('revert_direction: All points must have a time')
        self.tracks = list(reversed(self.tracks))
        for track in self.tracks:
            track.segments = list(reversed(track.segments))
            for segment in track.segments:
                old_point_times = [x.time for x in segment.points]
                segment.points = list(reversed(segment.points))
                seglen = len(segment.points)

                # switch start and end time
                _ = segment.points[0].time
                segment.points[0].time = segment.points[-1].time
                segment.points[-1].time = _

                # calculate intermediate time
                for idx, point in enumerate(segment.points[1:-1]):
                    print('idx:', idx)
                    time1 = old_point_times[seglen-idx-2]
                    time2 = old_point_times[seglen-idx-1]
                    timedelta = time2 - time1
                    point.time = segment.points[idx].time + timedelta
