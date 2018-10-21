#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.track.Track`."""

# pylint: disable=protected-access

from math import asin, sqrt, degrees
import datetime
from contextlib import contextmanager
from functools import total_ordering
import weakref
from copy import deepcopy
import logging

# This code would speed up parsing GPX by about 30%. When doing
# that, GPX will only return str instead of datetime for times.
#
# import gpxpy.gpxfield as mod_gpxfield
# mod_gpxfield.TIME_TYPE=None

# pylint: disable=too-many-lines

from gpxpy import gpx as mod_gpx
from gpxpy import parse as gpxpy_parse
from gpxpy.geo import length as gpx_length, Location
from gpxpy.geo import simplify_polyline

from .util import repr_timespan, uniq, positions_equal

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException

# see https://github.com/tkrajina/gpxpy/issues/150
Location.__hash__ = lambda x: int(x.latitude * 1000) + int(x.longitude * 1000) + int(x.elevation * 10)  # noqa


__all__ = ['Track', 'Fences']


class Fences:  # pylint: disable=too-few-public-methods

    """
    Defines circles.

    Args:
        config_str: The string from auth.cfg

    Attributes:
        center (GPXTrackPoint): The center
        radius (meter): The radius in meters

    """

    def __init__(self, config_str: str):
        """init."""
        self.circles = list()
        if config_str is not None:
            for fence in config_str.split(' '):
                parts = fence.split('/')
                if len(parts) != 3:
                    raise Exception('fence needs 3 parts')
                try:
                    parts = [x.strip() for x in parts]
                    center = Location(float(parts[0]), float(parts[1]))
                    radius = float(parts[2])
                except Exception:
                    raise Exception('Fence definition is wrong: {}'.format(fence))
                circle = (center, radius)
                self.circles.append(circle)

    def outside(self, point) ->bool:
        """Determine if point is outside of all fences.

        Returns: True or False.

        """
        return all(point.distance_2d(x[0]) > x[1] for x in self.circles)


@total_ordering
class Track:  # pylint: disable=too-many-public-methods

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

    The data will only be loaded from the backend when it is needed. Some backends
    might support loading some attributes separately, but for now, we always load
    everything as soon as anything is needed.

    Args:
        gpx (GPX): Initial content. To be used if you create a new Track from scratch without
            loading it from some backend.

    Attributes:
        legal_categories (tuple(str)): The legal values for :attr:`~Track.category`. The first one is used
            as default value. This is a mostly a superset of the values for the different backends.
            Every backend maps from its internal values into those when reading and maps them
            back when writing. Since not all backends support all values defined here and since
            some backends may define more values than we know, information may get lost when
            converting, even if you copy a track between two backends of the same type.

    """

    # pylint: disable = too-many-instance-attributes,too-many-public-methods

    class CannotMerge(Exception):
        """Is raised if  Track.merge() fails."""

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
        """See class docstring."""
        self.__dirty = list()
        self._batch_changes = False
        self.__category = self.legal_categories[0]
        self.__public = False
        self._ids = list()
        self.__id_in_backend = None
        self.__backend = None
        self._loaded = False
        self._header_data = dict()  # only for internal use because we clear data on _full_load()
        self.__gpx = gpx or GPX()
        self.__backend = None
        self.__cached_distance = None
        self._similarity_others = weakref.WeakValueDictionary()
        self._similarities = dict()
        self.__without_fences = None  # used by context manager "fenced()"
        if gpx:
            self._decode_keywords(self.__gpx.keywords)
            self._round_points(self.points())
            self._loaded = True

    @property
    def backend(self):
        """The backend this track lives in. If the track was constructed in memory, backend is None.

        This is a read-only property. It is set with :meth:`Backend.add <gpxity.backend.Backend.add>`.

        It is not possible to decouple a track from its backend, use :meth:`clone()`.

        Returns:
            The backend

        """
        return self.__backend
        # :attr:`Track.id_in_backend <gpxity.track.Track.id_in_backend>`.

    @property
    def id_in_backend(self) ->str:
        """Every backend has its own scheme for unique track ids.

        Some backends may change the id if the track data changes.

        Returns:
            the id in the backend

        """
        return self.__id_in_backend

    @id_in_backend.setter
    def id_in_backend(self, value: str) ->None:
        """Change the id in the backend. Currently supported only by Directory.

        Args:
            value: The new value

        """
        if value is not None:
            if not isinstance(value, str):
                raise Exception('{}: id_in_backend must be str'.format(value))
            if '/' in value:
                raise Exception('{}: / not allowed in id_in_backend'.format(value))
        if self.__id_in_backend == value:
            return
        if self.__id_in_backend:
            self._ids.insert(0, (str(self.backend), self.__id_in_backend))
        if self.__is_decoupled:
            # internal use
            self.__id_in_backend = value
        else:
            if not self.__id_in_backend:
                raise Exception('Cannot set id_in_backend for yet unsaved track {}'.format(self))
            if not value:
                raise Exception('Cannot remove id_in_backend for saved track {}'.format(self))
            with self._decouple():
                self.backend._change_id(self, value)

    def _set_backend(self, value):
        """To be used only by backend implementations."""
        assert self.__is_decoupled
        old_backend = self.__backend
        self.__backend = value
        if self.__gpx.keywords:
            if old_backend is None or old_backend.__class__ != value.__class__:
                # encode keywords for the new backend
                # TODO: unittest
                self.change_keywords(self.__gpx.keywords)

    def rewrite(self) ->None:
        """Call this after you directly manipulated  :attr:`gpx`."""
        self._load_full()
        self._dirty = 'gpx'

    @property
    def _dirty(self) ->list:
        """
        Check if  the track is in sync with the backend.

        Setting :attr:`_dirty` will directly write the changed data into the backend.

        :attr:`_dirty` can receive an arbitrary string like 'title'. If the backend
        has a method _write_title, that one will be called. Otherwise the
        entire track will be written by the backend.

        Returns:
            list: The names of the attributes currently marked as dirty.

        """
        return self.__dirty

    @_dirty.setter
    def _dirty(self, value):
        """See dirty.getter."""
        if not isinstance(value, str):
            raise Exception('_dirty only receives str')
        if value in self._header_data:
            del self._header_data[value]
        if not self.__is_decoupled:
            if value == 'gpx':
                if self.__without_fences is not None:
                    raise Exception(
                        '{}: You may not modify gpx while being in the context manager "fenced()"'.format(self))
                self._uncache_gpx()
            self.__dirty.append(value)
            if not self._batch_changes:
                self._rewrite()

    def _uncache_gpx(self):
        """gpx has changed: clear caches."""
        self.__cached_distance = None
        for other in self._similarity_others.values():
            del other._similarity_others[id(self)]
            # TODO: unittest where other does not exist anymore
            del other._similarities[id(self)]
        self._similarity_others = weakref.WeakValueDictionary()
        self._similarities = dict()

    def _clear_dirty(self):
        """To be used by the backend when saving."""
        self.__dirty = list()

    def clone(self):
        """Create a new track with the same content but without backend.

        Returns:
            ~gpxity.track.Track: the new track

        """
        self.__resolve_header_data()
        result = Track(gpx=self.gpx.clone())
        result.category = self.category
        result.public = self.public
        result._ids = deepcopy(self._ids)
        if self.backend is not None:
            result._ids.insert(0, (str(self.backend), self.__id_in_backend))
        return result

    def _rewrite(self):
        """Rewrite all changes in the associated backend.

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
        if 'write' not in self.backend.supported:
            # TODO: unittest
            raise Exception('Rewriting {}: "write" is not supported'.format(self))
        if not self.__is_decoupled and not self._batch_changes:
            with self._decouple():
                self.backend._rewrite(self, self.__dirty)
            self._clear_dirty()

    def remove(self):
        """Remove this track in the associated backend.

        If the track is not coupled with a backend, raise an Exception.

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
        if 'time' in self._header_data:
            return self._header_data['time']
        self._load_full()
        try:
            return next(self.points()).time
        except StopIteration:
            pass

    @property
    def title(self) -> str:
        """str: The title.

        Returns:
            the title

        """
        if 'title' in self._header_data:
            return self._header_data['title']
        self._load_full()
        return self.__gpx.name or ''

    @title.setter
    def title(self, value: str):
        """see getter."""
        if value != self.__gpx.name:
            self._load_full()
            self.__gpx.name = value
            self._dirty = 'title'

    @property
    def description(self) ->str:
        """str: The description.

        Returns:
            The description

        """
        if 'description' in self._header_data:
            return self._header_data['description']
        self._load_full()
        return self.__gpx.description or ''

    @description.setter
    def description(self, value: str):
        """see getter."""
        if value != self.__gpx.description:
            self._load_full()
            self.__gpx.description = value
            self._dirty = 'description'

    @contextmanager
    def fenced(self, fences):
        """Suppress points in fences."""
        if self.__without_fences is not None:
            raise Exception('fenced() is already active')
        self.__without_fences = self.__gpx
        try:
            if fences:
                for track in self.__gpx.tracks:
                    for segment in track.segments:
                        segment.points = [x for x in segment.points if fences.outside(x)]
                self.__gpx.waypoints = [x for x in self.gpx.waypoints if fences.outside(x)]
            self._uncache_gpx()
            yield
        finally:
            self.__gpx = self.__without_fences
            self._uncache_gpx()
            self.__without_fences = None

    @contextmanager
    def _decouple(self):
        """Context manager: disable automic synchronization with the backend.

        In that state, automatic writes of changes into
        the backend are disabled, and if you access attributes which
        would normally trigger a full load from the backend, they will not.
        (The latter is used by __str__ and __repr__).

        """
        from_backend = self.__backend
        prev_value = from_backend._decoupled if from_backend is not None else None
        if from_backend is not None:
            from_backend._decoupled = True
        try:
            yield
        finally:
            if from_backend is not None:
                from_backend._decoupled = prev_value

    @property
    def __is_decoupled(self):
        """True if we are currently decoupled from the backend.

        In that state, changes to Track are not written to the backend and
        the track is not marked dirty.

        Returns:
            True if we are decoupled

        """
        if self.backend is None:
            return True
        return self.backend._decoupled

    @contextmanager
    def batch_changes(self):
        """Context manager: disable the direct update in the backend and saves the entire track when done.

        This may or may not make things faster. Directory and GPSIES profits from this, MMT maybe.

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
        """str: What is this track doing? If we have no current value, return the default.

        The value is automatically translated between our internal value and
        the value used by the backend. This happens when reading from
        or writing to the backend.
        Returns:
            The current value or the default value (see :attr:`legal_categories`)

        """
        if not self._loaded and 'category' in self._header_data:
            return self._header_data['category']
        self._load_full()
        return self.__category

    @category.setter
    def category(self, value: str):
        """see getter."""
        if value is None:
            value = self.legal_categories[0]
        if value != self.__category:
            if value not in self.legal_categories:
                raise Exception('Category {} is not known'.format(value))
            self._load_full()
            self.__category = value
            self._dirty = 'category'

    def _load_full(self) ->None:
        """Load the full track from source_backend if not yet loaded."""
        if (self.backend is not None and self.id_in_backend and not self._loaded
                and not self.__is_decoupled and 'scan' in self.backend.supported):  # noqa
            self.backend._read_all_decoupled(self)
            self._loaded = True
        if not self.__is_decoupled:
            self.__resolve_header_data()

    def __resolve_header_data(self):
        """Put header data into gpx and clear them."""
        with self._decouple():
            pairs = [(x[0], x[1]) for x in self._header_data.items()]
            for key, value in pairs:
                if key in ('title', 'description', 'category', 'public', 'keywords'):
                    setattr(self, key, value)
                elif key in ('time', 'distance'):
                    pass
                elif key == 'ids':
                    self._ids = value
                else:
                    raise Exception('Unhandled header_data: {}/{}'.format(key, value))
            self._header_data.clear()

    def add_points(self, points) ->None:
        """Add points to last segment in the last track.

        If no track is allocated yet and points is not an empty list, allocates a track.

        Args:
            points (list(GPXTrackPoint): The points to be added

        """
        if points:
            self._add_points(points)
            self._dirty = 'gpx'

    def _add_points(self, points):
        """Just add without setting dirty."""
        if points:
            if self.__gpx.tracks:
                # make sure the same points are not added twice
                _ = self.__gpx.tracks[-1].segments[-1]
                assert points != _.points[-len(points):]
            self._load_full()
            if not self.__gpx.tracks:
                self.__gpx.tracks.append(GPXTrack())
                self.__gpx.tracks[0].segments.append(GPXTrackSegment())
            self._round_points(points)
            self.__gpx.tracks[-1].segments[-1].points.extend(points)

    def _decode_keywords(self, data, into_header_data: bool = False):  # noqa
        """'self.keywords' is 1:1 as parsed from xml.

        Here we extract our special keywords Category: and Status:

        Args:
            into_header_data: if False, set the real track fields.
                If True, save everything in self._header_data.

        """
        # pylint: disable=too-many-branches
        gpx_keywords = list()
        ids = list()
        if isinstance(data, str):
            data = [x.strip() for x in data.split(', ')]
        if data is not None:
            for keyword in data:
                _ = [x.strip() for x in keyword.split(':')]
                what = _[0]
                value = ':'.join(_[1:])
                if into_header_data:
                    if what == 'Category':
                        self._header_data['category'] = value
                    elif what == 'Status':
                        self._header_data['public'] = value == 'public'
                    elif what == 'Id':
                        _ = value.split('/')
                        backend_name = '/'.join(_[:-1])
                        if backend_name == '':
                            backend_name = '.'
                        ids.append((backend_name, _[-1]))
                    else:
                        gpx_keywords.append(keyword)
                else:
                    if what == 'Category':
                        self.category = value
                    elif what == 'Status':
                        self.public = value == 'public'
                    elif what == 'Id':
                        _ = value.split('/')
                        backend_name = '/'.join(_[:-1])
                        if backend_name == '':
                            backend_name = '.'
                        ids.append((backend_name, _[-1]))
                    else:
                        gpx_keywords.append(keyword)
        gpx_keywords = [x[1:] if x.startswith('-') else x for x in gpx_keywords]
        if into_header_data:
            self._header_data['keywords'] = sorted(gpx_keywords)
            self._header_data['ids'] = ids
        else:
            if 'keywords' in self._header_data:
                del self._header_data['keywords']
            self.__gpx.keywords = ', '.join(sorted(gpx_keywords))
            if 'ids' in self._header_data:
                del self._header_data['ids']
            self._ids = ids

    def _encode_keywords(self) ->str:
        """Add our special keywords Category and Status.

        Returns:
            The full list of keywords as one str

        """
        result = self.keywords
        result.append('Category:{}'.format(self.category))
        result.append('Status:{}'.format('public' if self.public else 'private'))
        for _ in self.ids:
            # TODO: encode the , to something else
            result.append('Id:{}/{}'.format(*_))
        return ', '.join(result)

    def parse(self, indata):
        """Parse GPX.

        :attr:`title`, :attr:`description` and :attr:`category` from indata have precedence over the current values.
        :attr:`public` will be or-ed
        :attr:`keywords` will stay unchanged if indata has none, otherwise be replaced from indata

        Args:
            indata: may be a file descriptor or str

        """
        assert self.__is_decoupled
        if hasattr(indata, 'read'):
            indata = indata.read()
        if not indata:
            # ignore empty file
            return
        with self._decouple():
            old_title = self.title
            old_description = self.description
            old_public = self.public
            try:
                self.__gpx = gpxpy_parse(indata)
            except GPXXMLSyntaxException as exc:
                self.backend.logger.error(
                    '%s: Track %s has illegal GPX XML: %s', self.backend, self.id_in_backend, exc)
                raise
            if self.__gpx.keywords:
                self._decode_keywords(self.__gpx.keywords)
            self.public = self.__public or old_public
            if old_title and not self.__gpx.name:
                self.__gpx.name = old_title
            if old_description and not self.__gpx.description:
                self.__gpx.description = old_description
            self._round_points(self.points())
        self._header_data = dict()
        self._loaded = True
        self.__workaround_for_gpxpy_issue_140()

    def __workaround_for_gpxpy_issue_140(self):
        """Remove empty track extension elements.

        Maybe we have to do that for other extension elements too.
        But I hope gpxity can soon enough depend on a fixed stable
        version of gpxpy.

        """
        for track in self.gpx.tracks:
            track.extensions = [x for x in track.extensions if len(x) or x.text is not None]

    @staticmethod
    def _round_points(points):
        """Round points to 6 decimal digits because some backends may cut last digits.

        Gpsies truncates to 7 digits. The points are rounded in place!

        Args:
            points (list(GPXTrackPoint): The points to be rounded

        """
        for _ in points:
            _.longitude = round(_.longitude, 6)
            _.latitude = round(_.latitude, 6)

    def to_xml(self) ->str:
        """Produce exactly one line per trackpoint for easier editing (like removal of unwanted points).

        Returns:

            The xml string."""
        self._load_full()
        old_keywords = self.__gpx.keywords
        try:
            self.__gpx.keywords = self._encode_keywords()

            result = self.__gpx.to_xml()
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
        finally:
            self.__gpx.keywords = old_keywords
        return result

    @property
    def public(self):
        """
        bool: Is this a private track (can only be seen by the account holder) or is it public?.

            Default value is False

        Returns:
            True if track is public, False if it is private

        """
        if 'public' in self._header_data:
            return self._header_data['public']
        self._load_full()
        return self.__public

    @public.setter
    def public(self, value):
        """Store this flag as keyword 'public'."""
        if value != self.__public:
            self._load_full()
            self.__public = value
            self._dirty = 'public'

    @property
    def gpx(self) ->GPX:
        """
        Direct access to the GPX object.

        If you use it to change its content, remember to call :meth:`rewrite` afterwards.

        Returns:
            the GPX object

        """
        self._load_full()
        return self.__gpx

    @property
    def last_time(self) ->datetime.datetime:
        """The last time we received.

        Returns:

            The last time we received so far. If none, return None."""
        self._load_full()
        try:
            return self.__gpx.tracks[-1].segments[-1].points[-1].time
        except IndexError:
            pass

    @property
    def keywords(self):
        """list(str): represent them as a sorted list - in GPX they are comma separated.

            Content is whatever you want.

            Because the GPX format does not have attributes for everything used by all backends,
            we encode some of the backend arguments in keywords.

            Example for mapmytracks: keywords = 'Status:public, Category:Cycling'.

            However this is transparent for you. When parsing theGPX file, those are removed
            from keywords, and the are re-added in when exporting in :meth:`to_xml`. So
            :attr:`Track.keywords` will never show those special values.

            Some backends may change keywords. :class:`~gpxity.backends.mmt.MMT` converts the
            first character into upper case and will return it like that. Gpxity will not try to hide such
            problems. So if you save a track in :class:`~gpxity.backends.mmt.MMT`, its keywords
            will change. But they will not change if you copy from :class:`~gpxity.backends.mmt.MMT`
            to :class:`~gpxity.backends.directory.Directory` - so if you copy from DirectoryA
            to :class:`~gpxity.backends.mmt.MMT` to DirectoryB, the keywords in
            DirectoryA and DirectoryB will not be identical, for example "berlin" in DirectoryA but
            "Berlin" in DirectoryB.

        """
        if 'keywords' in self._header_data:
            # TODO: unittest checking that keywords is always a deep copy
            return self._header_data['keywords'][:]
        self._load_full()
        if self.__gpx.keywords:
            return list(sorted(x.strip() for x in self.__gpx.keywords.split(',')))
        return list()

    @keywords.setter
    def keywords(self, values):
        """Replace all keywords.

        Args:
            Either single str with one or more keywords, separated by commas
                or an iterable of keywords. The new keywords. Must not have duplicates.

        """
        self.change_keywords(values, replace=True)

    @staticmethod
    def _check_keyword(keyword):
        """Must not be one of our internally used codes."""
        internal = (('Category', 'category'), ('Status', 'public'), ('Id', 'ids'))
        for internal_kw, attr in internal:
            if keyword.startswith(internal_kw + ':'):
                raise Exception('Do not use {} directly, use Track.{}'.format(internal_kw, attr))
        if ',' in keyword:
            raise Exception('No comma allowed within a keyword')

    def __prepare_keywords(self, values):
        """Common introductory code for change_keywords.

        The values may be preceded with a '-' which will be preserved in the result._ids

        Args:
            values: Either single str with one or more keywords, separated by commas
                or an iterable of keywords.

        Returns:
            A set of legal keywords as expected by the backend.

        """
        if isinstance(values, str):
            lst = [x.strip() for x in values.split(',')]
        else:
            lst = list(values)
        pairs = list()
        for _ in lst:
            if _.startswith('-'):
                pairs.append((False, _[1:]))
            else:
                pairs.append((True, _))
        for _ in pairs:
            self._check_keyword(_[1])
        if self.backend is not None:
            pairs = [(x[0], self.backend._encode_keyword(x[1])) for x in pairs]
        adding = {x[1] for x in pairs if x[0]}
        removing = {x[1] for x in pairs if not x[0]}
        return adding, removing

    def change_keywords(self, values, replace=False, dry_run=False):
        """Change keywords.

        Duplicate keywords are silently ignored.
        A keyword may not contain a comma.
        Keywords with a preceding '-' are removed, the others are added.
        Raise an Exception if a keyword is both added and removed.

        Args:
            values: Either a single str with one or more keywords, separated by commas
                or an iterable of keywords
            replace: if True, replace current keywords with the new ones. Ignores keywords
                preceded with a '-'.
            dry_run: if True, only return the new keywords but do not make that change

        Returns:
            The new keywords

        """
        self._load_full()
        have = {*self.keywords}
        add, remove = self.__prepare_keywords(values)
        if add & remove:
            raise Exception('Cannot both add and remove keywords {}'.format(add & remove))

        if replace:
            remove = have - add
        else:
            add -= have
            remove &= have

        new = (have | add) - remove
        if not dry_run and new != have:
            self.__gpx.keywords = ', '.join(sorted(new))
            with self.batch_changes():
                if add:
                    self._dirty = 'add_keywords:{}'.format(', '.join(add))
                if remove:
                    self._dirty = 'remove_keywords:{}'.format(', '.join(remove))
        assert sorted(new) == self.keywords, (
            'change_keywords failed. Expected: {}, got: {}'.format(sorted(new), self.keywords))
        return sorted(new)

    def speed(self) ->float:
        """Speed over the entire time in km/h or 0.0.

        Returns:
            The speed

        """
        time_range = (self.time, self.last_time)
        if time_range[0] is None or time_range[1] is None:
            return 0.0
        duration = time_range[1] - time_range[0]
        seconds = duration.days * 24 * 3600 + duration.seconds
        if seconds:
            return self.distance() / seconds * 3600
        return 0.0

    def moving_speed(self) ->float:
        """Speed for time in motion in km/h.

        Returns:
            The moving speed

        """
        bounds = self.gpx.get_moving_data()
        if bounds.moving_time:
            return bounds.moving_distance / bounds.moving_time * 3.6
        return 0.0

    def warnings(self):
        """Return a list of strings with easy to find problems."""
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

    def __repr__(self) ->str:
        """The repr.

        Returns:
            the repr str

        """
        with self._decouple():
            # this should not automatically load the entire track
            parts = []
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
                if 'distance' in self._header_data:
                    parts.append('{:4.2f}km'.format(self._header_data['distance']))
                elif self.gpx.get_track_points_no() or self._loaded:
                    parts.append('{} points'.format(self.gpx.get_track_points_no()))
            return '{}({})'.format(str(self), ' '.join(parts))

    def __str__(self) ->str:
        """The str.

        Returns:
            a unique full identifier

        """

        if self.backend is None:
            return 'unsaved: "{}" time={} id={}'.format(self.title or 'untitled', self.time, id(self))
        ident = self.id_in_backend or 'unsaved'
        if str(self.backend) == '.':
            # current directory
            return ident
        return '{}/{}'.format(self.backend, ident)

    def key(self, with_category: bool = True, with_last_time: bool = True) ->str:
        """For speed optimized equality checks, not granted to be exact, but sufficiently safe IMHO.

        Args:
            with_category: If False, do not use self.category. Needed for comparing
                tracks for equality like in unittests because values can change
                and information can get lost while copying between different
                backends
            with_last_time: If False, do not use self.last_time.

        Returns:
            a string with selected attributes in printable form.

        """
        self._load_full()
        return 'title:{} description:{} keywords:{} category:{}: public:{} last_time:{} angle:{} points:{}'.format(
            self.title, self.description,
            ','.join(self.keywords), self.category if with_category else '',
            self.public, self.last_time if with_last_time else '',
            self.angle(), self.gpx.get_track_points_no())

    def __eq__(self, other) ->bool:
        """equal.

        Returns:
            result

        """
        if self is other:
            return True
        return self.key() == other.key()

    def __lt__(self, other) ->bool:
        """less than.

        Returns:
            result

        """
        return self.key() < other.key()

    def distance(self) ->float:
        """For me, the earth is flat.

        Returns:
            the distance in km, rounded to m

        """
        if 'distance' in self._header_data:
            return self._header_data['distance']
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
            result = degrees(asin(norm_long / sqrt(norm_lat**2 + norm_long ** 2)))
        except ZeroDivisionError:
            return 0
        if norm_lat >= 0.0:
            return (360.0 + result) % 360.0
        return 180.0 - result

    def segments(self):
        """
        A generator over all segments.

        Yields:
            GPXTrackSegment: all segments in all tracks

        """
        self._load_full()
        for track in self.__gpx.tracks:
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
        """Return the last point of the track."""
        # TODO: unittest for track without __gpx or without points
        return self.__gpx.tracks[-1].segments[-1].points[-1]

    def adjust_time(self, delta):
        """Add a timedelta to all times.

        gpxpy.gpx.adjust_time does the same but it ignores waypoints.
        A newer gpxpy.py has a new bool arg for adjust_time which
        also adjusts waypoints on request but I do not want to check versions.

        """
        self.gpx.adjust_time(delta)
        for wpt in self.gpx.waypoints:
            wpt.time += delta
        self._dirty = 'gpx'

    def points_hash(self) -> float:
        """A hash that is hopefully different for every possible track.

        It is built using the combination of all points.

        Returns:
            The hash

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
            _ = point.time
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
        if self.gpx.get_track_points_no() != other.gpx.get_track_points_no():
            return False
        for _, (point1, point2) in enumerate(zip(self.points(), other.points())):
            if not positions_equal(point1, point2, digits):
                return False
        return True

    def index(self, other, digits=4):
        """Check if this track contains other track.gpx.

        This only works if all values for latitude and longitude are
        nearly identical.

        Useful if one of the tracks had geofencing applied.

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
    def overlapping_times(tracks):
        """Find tracks with overlapping times.

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
        """Try to check if track has the default title given by a backend.

        Returns:

            True if so"""
        # the title of MMT might have been copied into another backend:
        if not self.title:
            return True
        if self.title == '{} track'.format(self.category):
            return True
        if all(x in '0123456789 :-_' for x in self.title):
            return True
        return False

    def __merge_metadata(self, other, dry_run):
        """Merge metadata from other.

        Used only by self.merge.

        Returns:
            a list of verbosity messages

        """
        msg = list()
        if not other._has_default_title() and self._has_default_title():
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
                other, other.category, self, self.category))
        kw_src = set(other.keywords)
        kw_dst = set(self.keywords)
        if kw_src - kw_dst:
            msg.append('New keywords: {}'.format(','.join(kw_src - kw_dst)))
            if not dry_run:
                self.keywords = kw_src | kw_dst
        return msg

    def can_merge(self, other, partial_tracks: bool = False):
        """Check if self and other are mergeable.

        args:
            other: The other Track
            partial_tracks: If True, they are mergeable if one of them contains
                the other one.

        Returns: (int, str)
            int is either None or the starting index of the shorter track in the longer track
            str is either None or a string explaing why this is not mergeable

        """
        if str(self) == str(other):
            return None, 'Cannot merge identical tracks {}'.format(self)

        if partial_tracks:
            other_in_self = self.index(other)
            if other_in_self is not None:
                return other_in_self, None
            self_in_other = other.index(self)
            if self_in_other is not None:
                return self_in_other, None
        elif self.points_equal(other):
            return 0, None
        return None, (
            'Cannot merge {} with {} points into {} with {} points'.format(
                other, other.gpx.get_track_points_no(),
                self, self.gpx.get_track_points_no()))

    def merge(  # noqa pylint: disable=unused-argument
            self, other, remove: bool = False, dry_run: bool = False, copy: bool = False,
            partial_tracks: bool = False) ->list:
        """Merge other track into this one. The track points must be identical.

        If merging is not possible, raise Track.CannotMerge.

        If either is public, the result is public.
        If self.title seems like a default and other.title does not, use other.title
        Combine description and keywords.

        Args:
            other (:class:`~gpxity.track.Track`): The track to be merged
            remove: After merging succeeded, remove other
            dry_run: if True, do not really apply the merge
            copy: This argument is ignored. It is only here to give Track.merge() and Backend.merge()
                the same interface.
            partial_tracks: merges other track
                if either track is part of the other one

        Returns: list(str)
            Messages about what has been done.

        """
        assert isinstance(other, Track)
        msg = []
        shorter_at, _ = self.can_merge(other, partial_tracks)
        if shorter_at is None:
            raise Track.CannotMerge(_)
        with self.batch_changes():
            if other.gpx.get_track_points_no() > self.gpx.get_track_points_no():
                if not dry_run:
                    self.gpx.tracks = deepcopy(other.gpx.tracks)
                    self.rewrite()
                msg.append('{} got entire gpx.tracks from {}'.format(self, other))
            msg.extend(self.__merge_metadata(other, dry_run))
            changed_point_times = 0
            self_points = self.point_list()[shorter_at:]
            for self_point, other_point in zip(self_points, other.points()):
                # TODO: unittest with shorter track
                if not self_point.time:
                    if not dry_run:
                        self_point.time = other_point.time
                    changed_point_times += 1
            if changed_point_times:
                if not dry_run:
                    self.rewrite()
                msg.append('Copied times for {} out of {} points'.format(
                    changed_point_times, self.gpx.get_track_points_no()))
        if msg:
            msg = ['     ' + x for x in msg]
            msg.insert(0, 'merge{} {!r}'.format(' and remove' if remove else '', other))
            msg.insert(1, '{}  into {!r}'.format(' ' * len(' and remove') if remove else '', self))
        if remove:
            if len(msg) <= 2:
                msg.append(
                    'remove duplicate {!r}: It was identical with {!r}'.format(other, self))
            if not dry_run:
                other.remove()
        return msg

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

    def fix(self, orux: bool = False, jumps: bool = False):
        """Fix bugs. This may fix them or produce more bugs.

        Please backup your track before doing this.

        Args:
            orux: Older Oruxmaps switched the day back by one
                day after exactly 24 hours.
            jumps: Whenever the time jumps back or more than 30
            minutes into the future, split the segment at that point.

        Returns:
            A list of message strings, usable for verbose output.

            """
        self._load_full()
        if orux:
            self.__fix_orux()
        if jumps:
            self.__fix_jumps()
        return []

    def __fix_jumps(self):  # noqa pylint: disable=too-many-branches
        """Split segments at jumps.

        Whenever the time jumps back or more than 30
        minutes into the future or the distance exceeds 5km,

        split the segment at that point."""
        did_break = False
        new_tracks = list()
        for track in self.gpx.tracks:
            new_segments = list()
            for segment in track.segments:
                if not segment.points:
                    did_break = True  # sort of - but also needs a rewrite
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
                    elif point.time - prev_point.time > datetime.timedelta(minutes=30):
                        needs_break = True
                    elif point.time < prev_point.time:
                        needs_break = True
                    elif point.distance_2d(prev_point) > 5000:
                        needs_break = True
                    if needs_break:
                        did_break = True
                        new_segments.append(new_segment)
                        new_segment = GPXTrackSegment()
                    new_segment.points.append(point)
                new_segments.append(new_segment)
            new_track = GPXTrack()
            new_track.segments.extend(new_segments)
            new_tracks.append(new_track)
        if did_break:
            self.gpx.tracks = new_tracks
            self._dirty = 'gpx'

    def __fix_orux(self):
        """Try to fix Oruxmaps problems.

        1. the 24h bugs

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
        """Return a float 0..1: 1 is identity."""

        def simple(track):
            """Simplified track"""
            return [(round(x.latitude, 3), round(x.longitude, 3))
                    for x in simplify_polyline(list(track.points()), max_distance=50)]

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
            other._similarity_others[id(self)] = self
            other._similarities[id(self)] = result
        return self._similarities[id(other)]

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

    @property
    def ids(self):
        """Return ids for all backends where this track has already been.

        This is a list of pairs. pair[0] is the name of the backend, pair[1] is the track id within.
        You can modify it but your changes will never be saved.
        They are sorted by ascending age.
        Only the 5 youngest are kept.
        If the same filename appears in more than one directory, keep only the youngest.

        Returns: list( (str, str))
            a list of tuple pairs with str(backend) and id_in_backend

        """
        if 'ids' in self._header_data:
            result = self._header_data['ids']
        else:
            self._load_full()
            result = self._ids
        return self.__clean_ids(result)

    @staticmethod
    def __clean_ids(original):
        """Remove redundancies and old ids.append.

        1. if the same id_in_backend is in several directories, keep only the first one
        2. keep only 5

        Returns: The cleaned list if ids

        """
        result = list()
        seen = set()
        for _ in original:
            is_dir = ':' not in _[0]
            if is_dir:
                if _[1] not in seen:
                    seen.add(_[1])
                    result.append(_)
            else:
                result.append(_)
        return result[:5]

    def split(self):
        """Create separate tracks for every track/segment."""
        backend = self.backend
        self.remove()
        try:
            for segment in self.segments():
                track = self.clone()
                gpx_track = GPXTrack()
                gpx_track.segments.append(segment)
                track.gpx.tracks = [gpx_track]
                backend.add(track)
        except BaseException as exc:
            logging.error('split:%s', exc)
            backend.add(self)
