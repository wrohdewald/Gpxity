#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.track.GpxFile`."""

# pylint: disable=protected-access

import datetime
from functools import total_ordering
from contextlib import contextmanager
import weakref
from copy import deepcopy
import logging

# pylint: disable=too-many-lines

from gpxpy import gpx as mod_gpx
from gpxpy.geo import simplify_polyline

from .gpx import Gpx
from .backend_base import BackendBase
from .util import repr_timespan

GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException


__all__ = ['GpxFile']


@total_ordering
class GpxFile:  # pylint: disable=too-many-public-methods

    """Represents a file with Gpx data.

    If a :class:`~gpxity.backend.Backend` supports attributes not directly
    supported by the GPX format like the MapMyTracks track type, they will
    transparently be encodeded in existing GPX fields like keywords, see :attr:`keywords`.

    If a :class:`~gpxity.backend.Backend` (like :class:`~gpxity.backends.wptrackserver.WPTrackserver`)
    does not support keywords, the will transparently be encoded in the description.

    The GPX part is done by https://github.com/tkrajina/gpxpy.

    If a gpxfile is assigned to a backend, all changes will by default be written directly to the backend.
    Some backends are able to change only one attribute with little time overhead, others always have
    to rewrite the entire gpxfile.

    You can use the context manager :meth:`batch_changes`. This holds back updating the backend until
    leaving the context.

    If you manipulate the gpx directly, this goes unnoticed to the updating mechanism. Use :meth:`rewrite` when done.

    Not all backends support everything, you could get the exception NotImplementedError.

    The data will only be loaded from the backend when it is needed. Backends have two ways
    of loading data: Either load a list of gpxfiles or load all information about a specific gpxfile. Often
    loading the list of gpxfiles gives us some attributes for free, so listing
    those gpxfiles may be much faster if you do not want everything listed.

    Absolutely all attributes (like :attr:`title`, :attr:`distance`) are encoded in :attr:`gpx`.
    However you can always assign values to them even if :attr:`gpx` is None. As soon
    as :attr:`gpx` is given, it will be updated.

    All points are always rounded to 6 decimal digits when they are added to the track.
    However some backends may support less than 6 decimals. You can query Backend.point_precision.

    Args:
        gpx (Gpx): Initial content. Can be used if you create a new GpxFile from scratch without
            loading it from some backend.

    Attributes:
        categories (tuple(str)): The legal values for :attr:`~GpxFile.category`. The first one is used
            as default value. This is a superset of the values for the different backends.
            Every backend maps from its internal values into those when reading and maps them
            back when writing. Since not all backends support all values defined here and since
            some backends may define more values than we know, information may get lost when
            converting.

    """

    # pylint: disable = too-many-instance-attributes,too-many-public-methods

    class CannotMerge(Exception):
        """Is raised if :meth:`GpxFile.merge() <gpxity.track.GpxFile.merge>` fails."""

    categories = (
        'Cycling', 'Cycling - Road', 'Cycling - Gravel', 'Cycling - MTB', 'Cycling - Indoor', 'Cycling - Hand',
        'Cycling - Touring', 'Cycling - Foot',
        'Running', 'Running - Trail', 'Running - Urban Trail', 'Running - Road',
        'Sailing', 'Walking', 'Hiking', 'Hiking - Speed',
        'Swimming', 'Driving', 'Off road driving', 'Motor racing', 'Motorcycling', 'Enduro',
        'Skiing', 'Skiing - Touring', 'Skiing - Backcountry', 'Skiing - Crosscountry', 'Skiing - Nordic',
        'Skiing - Alpine', 'Skiing - Roller',
        'Canoeing', 'Kayaking', 'Sea kayaking', 'Stand up paddle boarding',
        'Rowing', 'Windsurfing', 'Kiteboarding', 'Orienteering', 'Mountaineering', 'Skating',
        'Skateboarding', 'Horse riding', 'Hang gliding', 'Gliding', 'Flying', 'Snowboarding',
        'Paragliding', 'Hot air ballooning', 'Nordic walking', 'Snowshoeing', 'Jet skiing', 'Powerboating',
        'Swimrun',
        'Pedelec', 'Crossskating', 'Motorhome', 'Cabriolet', 'Coach',
        'Pack animal trekking', 'Train', 'Wheelchair', 'Sightseeing', 'Geocaching', 'Longboard',
        'River navigation',
        'Skating - Inline',
        'Wintersports',
        'Miscellaneous')

    _obsolete_categories = {
        'Mountain biking': 'Cycling - MTB',
    }

    def __init__(self, gpx=None):
        """See class docstring."""
        if gpx is None:
            gpx = Gpx()
        assert isinstance(gpx, Gpx)
        self.__dirty = list()
        self._batch_changes = False
        self.__ids = list()  # TODO: remove
        self.__id_in_backend = None
        self.__backend = None
        self.__gpx = None
        self.__backend = None
        self.__cached_time = None
        self.__cached_distance = None

        # __header_cache holds all attributes that are set while gpx is None.
        # After gpx is given, if an attribute is not set in gpx, remove it from __header_cache
        # and write it into gpx. Do that for all values from __header_cache before writing
        # to the backend.
        self.__header_cache = dict()

        self._similarity_others = weakref.WeakValueDictionary()
        self._similarities = dict()
        self.__without_fences = None  # used by context manager "fenced()"
        self.gpx = gpx

    def __decode_gpx(self):
        """Extract attributes from gpx.

        This is done whenever gpx changes.

        We have 3 groups of attributes depending on how often
        they are needed an how expensive their computation is,
        in ascending order:

        1. always read from and write to gpx. Examples: title, description
        2. cache now. Examples: category ??? Wirklich???? Oder nur 1. und 3.?
        3. lazy: compute and cache only when needed. Examples: distance, time
            Those are set to None here.

        If an attribute is changed, the full gpxfile is always loaded first.

        """
        self.__gpx.decode()

        # lazy attributes:
        self.__cached_distance = None
        self.__cached_time = None
        self._clear_similarity_cache()

    def __encode_gpx(self):
        """Put values into gpx. See __decode_gpx."""
        self.__gpx.encode()
        if self.backend is not None:
            self.__gpx.category = self.backend.encode_category(self.__gpx.category)

    @property
    def backend(self):
        """The backend this gpxfile lives in. If the gpxfile was constructed in memory, backend is None.

        This is a read-only property. It is set with :meth:`Backend.add <gpxity.backend.Backend.add>`.

        It is not possible to decouple a gpxfile from its backend, use :meth:`clone()`.

        Returns:
            The backend

        """
        return self.__backend
        # :attr:`GpxFile.id_in_backend <gpxity.gpxfile.GpxFile.id_in_backend>`.

    @property
    def id_in_backend(self) ->str:
        """Every backend has its own scheme for unique ids.

        Some backends may change this if the gpxfile data changes.

        Some backends support assigning a new value. Those are
        currently :class:`~gpxity.backends.directory.Directory` and
        :class:`~gpxity.backends.wptrackserver.WPTrackserver`.
        The others will raise NotImplementedError.

        See also :meth:`Backend.add() <gpxity.backend.Backend.add>`.


        Returns:
            the id in the backend

        """
        return self.__id_in_backend

    @id_in_backend.setter
    def id_in_backend(self, value: str) ->None:
        """Change the id in the backend.

        Illegal changes raise ValueError.

        Args:
            value: The new value

        """
        BackendBase._check_id_legal(value)
        if self.__backend:
            self.__backend._check_id_legal(value)
        if self.__id_in_backend == value:
            return
        if self.__id_in_backend:
            self.__ids.insert(0, str(self))
        if self.__is_decoupled:
            # internal use
            self.__id_in_backend = value
        else:
            if not self.__id_in_backend:
                raise ValueError('Cannot set id_in_backend for yet unsaved gpxfile {}'.format(self))
            if not value:
                raise ValueError('Cannot remove id_in_backend for saved gpxfile {}'.format(self))
            with self._decouple():
                self.backend._change_ident(self, value)

    def _set_backend(self, value):
        """To be used only by backend implementations."""
        assert self.__is_decoupled
        if self.__backend:
            self.__backend._check_id_legal(self.id_in_backend)
        old_backend = self.__backend
        self.__backend = value
        if self.__gpx.keywords:
            if old_backend is None or old_backend.__class__ != value.__class__:
                # encode keywords for the new backend
                # TODO: unittest
                self.__gpx.encode()
                self.change_keywords(self.__gpx.real_keywords)

    def rewrite(self) ->None:
        """Call this after you directly manipulated  :attr:`gpx`."""
        if not self.__gpx.is_complete:
            raise Exception('GpxFile.rewrite: The gpxfile must already be loaded fully')
        self._dirty = 'gpx'

    @property
    def _dirty(self) ->list:
        """
        Check if  the gpxfile is in sync with the backend.

        Setting :attr:`_dirty` will directly write the changed data into the backend.

        :attr:`_dirty` can receive an arbitrary string like 'title'. If the backend
        has a method _write_title, that one will be called. Otherwise the
        entire gpxfile will be written by the backend.

        Returns:
            list: The names of the attributes currently marked as dirty.

        """
        return self.__dirty

    @_dirty.setter
    def _dirty(self, value):
        """See dirty.getter."""
        if not isinstance(value, str):
            raise Exception('_dirty only receives str')
        if value == 'gpx':
            if self.__without_fences is not None:
                raise Exception(
                    '{}: You may not modify gpx while being in the context manager "fenced()"'.format(self))
            self.__decode_gpx()
        if not self.__is_decoupled:
            self.__dirty.append(value)
            if not self._batch_changes:
                self._rewrite()

    def _clear_similarity_cache(self):
        """Clear similarities cache, also in the other similar gpxfiles."""
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
        """Create a new gpxfile with the same content but without backend.

        Returns:
            ~gpxity.gpxfile.GpxFile: the new gpxfile

        """
        self._load_full()
        result = GpxFile(gpx=self.gpx.clone())
        if self.backend is not None:
            result.__ids.insert(0, str(self))
        return result

    def _rewrite(self):
        """Rewrite all changes in the associated backend.

        If any of those conditions is met, do nothing:

        - we are currently loading from backend: Avoid recursion
        - batch_changes is active
        - we have no backend

        Otherwise the backend will save this gpxfile.

        """
        if 'gpx' in self.__dirty:
            self.__decode_gpx()
        if self.backend is None:
            self._clear_dirty()
        if not self.__dirty:
            return
        if 'write' not in self.backend.supported:
            # TODO: unittest
            raise Exception('Rewriting {}: "write" is not supported'.format(self))
        if not self.__is_decoupled and not self._batch_changes:
            with self._decouple():
                old_gpx_keywords = self.__gpx.keywords
                try:
                    self.__encode_gpx()
                    self.backend._rewrite(self, self.__dirty)
                finally:
                    self.__gpx.keywords = old_gpx_keywords
            self._clear_dirty()

    def remove(self):
        """Remove this gpxfile in the associated backend.

        If the gpxfile is not coupled with a backend, raise an Exception.

        """
        if self.backend is None:
            raise Exception('{}: Removing needs a backend'.format(self))
        self.backend.remove(self.id_in_backend)

    @property
    def first_time(self) ->datetime.datetime:
        """datetime.datetime: start time of gpxfile.

        For a simpler implementation of backends, notably :class:`~gpxity.backends.mmt.MMT`
        we ignore gpx.time. Instead we return the time of the earliest track point.
        Only if there is no track point, return gpx.time. If that is unknown
        too, return None.

        For the same reason time is readonly.

        We assume that the first point comes first in time and the last
        point comes last in time. In other words, points should be ordered
        by their time.

        """
        if self.__cached_time is None:
            self.__cached_time = self.__gpx.first_time
            if self.__cached_time is None:
                self.__cached_time = self.gpx.first_time
        return self.__cached_time

    @property
    def distance(self) ->float:
        """For me, the earth is flat.

        This property can only be set while the full gpxfile has not yet
        been loaded. The setter is used by the backends when scanning for all gpxfiles.

        Returns:
            the distance in km, rounded to m. 0.0 if not computable.

        """
        if self.__cached_distance is None:
            self.__cached_distance = self.gpx.distance
        return self.__cached_distance

    @distance.setter
    def distance(self, value):
        """The setter."""
        if self.__gpx.is_complete:
            raise Exception('Setting GpxFile.distance is only allowed while the full gpxfile has not yet been loaded')
        self.__cached_distance = value

    @property
    def title(self) -> str:
        """str: The title.

        Returns:
            the title

        """
        if self.__gpx.name == Gpx.undefined_str:
            self._load_full()
            if self.__gpx.name == Gpx.undefined_str:
                self.__gpx.name = ''
        return self.__gpx.name

    @title.setter
    def title(self, value: str):
        """see getter."""
        if self.__gpx.name != value:
            self._load_full()
            self.__gpx.name = value
            self._dirty = 'title'

    @property
    def description(self) ->str:
        """str: The description.

        Returns:
            The description

        """
        if self.__gpx.description == Gpx.undefined_str:
            self._load_full()
            if self.__gpx.description == Gpx.undefined_str:
                self.__gpx.description = ''
        return self.__gpx.description

    @description.setter
    def description(self, value: str):
        """see getter."""
        if self.__gpx.description != value:
            self._load_full()
            self.__gpx.description = value
            self._dirty = 'description'

    @contextmanager
    def fenced(self, fences):
        """Suppress points in fences.

        While this context manager is running, suppressed points are
        not visible.

        """
        if not fences:
            yield
            return

        if self.__without_fences is not None:
            raise Exception('fenced() is already active')
        self.__without_fences = self.__gpx
        try:
            for track in self.__gpx.tracks:
                for segment in track.segments:
                    segment.points = [x for x in segment.points if fences.outside(x)]
            self.__gpx.waypoints = [x for x in self.__gpx.waypoints if fences.outside(x)]
            self._clear_similarity_cache()
            yield
        finally:
            self.__gpx = self.__without_fences
            self._clear_similarity_cache()
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

        In that state, changes to GpxFile are not written to the backend and
        the gpxfile is not marked dirty.

        Returns:
            True if we are decoupled

        """
        if self.backend is None:
            return True
        return self.backend._decoupled

    @contextmanager
    def batch_changes(self):
        """Context manager: disable the direct update in the backend and saves the entire gpxfile when done.

        This may or may not make things faster.
        :class:`~gpxity.backends.directory.Directory` and
        :class:`~gpxity.backends.gpsies.GPSIES` profits from this,
        :class:`~gpxity.backends.mmt.MMT` maybe.

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
        """str: What is this gpxfile doing? If we have no current value, return the default.

        The value is automatically translated between our internal value and
        the value used by the backend. This happens when reading from
        or writing to the backend. Here we return always the internal value.

        Returns:
            The current value or the default value (see :attr:`categories`)

        """
        if self.__gpx.category == Gpx.undefined_str:
            self._load_full()
        if self.__gpx.category == Gpx.undefined_str:
            return self.categories[0]
        if self.backend is None:
            return self.__gpx.category
        return self.backend.decode_category(self.__gpx.category)

    def __default_category(self) ->str:
        """The default for either an unsaved gpxfile or for the corresponding backend.

        Returns: The category

        """
        if self.backend is None:
            return self.categories[0]
        return self.backend.decode_category(self.backend.supported_categories[0])

    @category.setter
    def category(self, value: str):
        """see getter."""
        if value is None:
            value = self.__default_category()
        if value not in self.categories:
            raise Exception('Category {} is not known'.format(value))
        if value != self.__gpx.category:
            self._load_full()
            self.__gpx.category = value
            self.__encode_gpx()
            self._dirty = 'category'

    def _load_full(self):
        """Load the full gpxfile from source_backend if not yet loaded and if not decoupled.

        The backend may
         -  add values to self.__gpx
         -  replace self.__gpx, see gpx.setter

         The backend is allowed and expected to replace already known values. This may
         happen
         - if the backend has a mistake and returns different values in the list of the gpxfile
           and in the full downloaded gpxfile
         - if somebody else changed the gpxfile in the backend meanwhile

        Returns: True for success

        """
        if (self.backend is not None and self.id_in_backend and not self.__gpx.is_complete
                and not self.__is_decoupled and 'scan' in self.backend.supported):  # noqa
            self.backend._read_all_decoupled(self)

    def add_points(self, points) ->None:
        """Round and add points to last segment in the last gpxfile.

        If no track is allocated yet and points is not an empty list, allocates a track.

        Args:
            points (list(GPXTrackPoint): The points to be added

        """
        if points:
            self._round_points(points)
            self.gpx.add_points(points)
            self._dirty = 'gpx'

    def __decode_category(self, value) -> str:
        """Helper for _decode_keywords.

        Returns:
            A value out of GpxFile.categories

        """
        return self.backend.decode_category(value) if self.backend is not None else value

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

    def xml(self) ->str:
        """Produce exactly one line per trackpoint for easier editing (like removal of unwanted points).

        Returns: The xml string.

        """
        self._load_full()
        if self.__is_decoupled:
            # if Backend._write_all() calls this, everything is already encoded in __gpx
            self.__encode_gpx()   # TODO: should not be necessary
        return self.__gpx.xml()

    @property
    def public(self):
        """
        bool: Is this a private gpxfile (can only be seen by the account holder) or is it public?.

            Default value is False

        Returns:
            True if gpxfile is public, False if it is private

        """
        if self.__gpx.keywords == Gpx.undefined_str:
            self._load_full()
        if self.__gpx.public == Gpx.undefined_str:
            return False
        return self.__gpx.public

    @public.setter
    def public(self, value):
        """Store this flag as keyword 'public'."""
        if value not in (True, False):
            raise ValueError('public must be True or False, I got {}'.format(value))
        if value != self.__gpx.public:
            self._load_full()
            self.__gpx.public = value
            self.__gpx.encode()
            self._dirty = 'public'

    @property
    def gpx(self) ->Gpx:
        """
        Direct access to the Gpx object.

        If you use it to change its content
        * remember to call :meth:`rewrite` afterwards.
        * Since everything is stored in Gpx, all attributes like
        :attr:`description`, ;attr:`public` ... will change too.

        Returns:
            the Gpx object

        """
        self._load_full()
        return self.__gpx

    @gpx.setter
    def gpx(self, value):
        """Assign new gpx."""
        self.__gpx = value
        self._clear_similarity_cache()
        if self.__is_decoupled:
            self.__decode_gpx()
        else:
            self.__encode_gpx()
        self._round_points(self.points())

    @property
    def last_time(self) ->datetime.datetime:
        """The last time we received.

        Returns:
            The last time we received so far. If none, return None.

        """
        return self.gpx.last_time

    @property
    def keywords(self):
        """list(str): represent them as a sorted list - in GPX they are comma separated.

            Content is whatever you want.

            Because the GPX format does not have attributes for everything used by all backends,
            we encode some of the backend arguments in keywords.

            Example for mapmytracks: keywords = 'Status:public, Category:Cycling'.

            Gpxity expects keywords to be separated by ",". When writing them Gpxity
            uses ", " (with a space after the comma) as separator.

            However this is transparent for you. When parsing theGPX file, those are removed
            from keywords, and the are re-added in when exporting in :meth:`xml`. So
            :attr:`GpxFile.keywords` will never show those special values.

            Some backends may change keywords. :class:`~gpxity.backends.mmt.MMT` converts the
            first character into upper case and will return it like that. Gpxity will not try to hide such
            problems. So if you save a gpxfile in :class:`~gpxity.backends.mmt.MMT`, its keywords
            will change. But they will not change if you copy from :class:`~gpxity.backends.mmt.MMT`
            to :class:`~gpxity.backends.directory.Directory` - so if you copy from DirectoryA
            to :class:`~gpxity.backends.mmt.MMT` to DirectoryB, the keywords in
            DirectoryA and DirectoryB will not be identical, for example "berlin" in DirectoryA but
            "Berlin" in DirectoryB.

        """
        return self.gpx.real_keywords

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
                raise Exception('Do not use {} directly, use GpxFile.{}'.format(internal_kw, attr))
        if ',' in keyword:
            raise Exception('No comma allowed within a keyword')

    def __prepare_keywords(self, values):
        """Common introductory code for change_keywords.

        The values may be preceded with a '-' which will be preserved in the result.__ids

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
        new = sorted((have | add) - remove)
        if not dry_run and self.keywords != new:
            self.__gpx.real_keywords = new
            with self.batch_changes():
                if remove:
                    self._dirty = 'remove_keywords{}{}'.format(BackendBase._dirty_separator, ', '.join(remove))
                if add:
                    self._dirty = 'add_keywords{}{}'.format(BackendBase._dirty_separator, ', '.join(add))
        assert new == self.keywords, (
            'change_keywords failed. Expected: {}, got: {}'.format(new, self.keywords))
        return new

    def speed(self) ->float:
        """Speed over the entire time in km/h or 0.0.

        Returns:
            The speed

        """
        return self.gpx.speed()

    def moving_speed(self) ->float:
        """Speed for time in motion in km/h.

        Returns:
            The moving speed

        """
        return self.gpx.moving_speed()

    def warnings(self):
        """Return a list of strings with easy to find problems."""
        result = list()
        if self.last_time:
            speed = self.speed()
            moving_speed = self.moving_speed()
            if speed > moving_speed:
                result.append('Speed {:.3f} must not be above Moving speed {:.3f}'.format(
                    speed, moving_speed))
            expected_speeds = {
                'Cycling - MTB': ((3, 50), (5, 50)),
                'Cycling - Road': ((3, 60), (10, 60)),
            }
            expected_speed = expected_speeds.get(self.category)
            if expected_speed:
                template = None
                if speed < expected_speed[0][0]:
                    template = 'Speed {speed:.3f} is very low'
                elif speed > expected_speed[0][1]:
                    template = 'Speed {speed:.3f} is very high'
                elif moving_speed < expected_speed[1][0]:
                    template = 'Moving speed {moving_speed:.3f} is very low'
                elif moving_speed > expected_speed[1][1]:
                    template = 'Moving speed {moving_speed:.3f} is very high'
                if template:
                    result.append(template.format(speed=speed, moving_speed=moving_speed))
        return result

    def __repr__(self) ->str:
        """The repr.

        Returns:
            the repr str

        """
        with self._decouple():
            # this should not automatically load the entire gpxfile
            parts = []
            parts.append('public' if self.public else 'private')
            if self.__gpx:
                parts.append(self.category)
                if self.keywords:
                    parts.append(','.join(self.keywords))
                if self.title:
                    parts.append(self.title)
                if self.first_time and self.last_time:
                    parts.append(repr_timespan(self.first_time, self.last_time))
                elif self.first_time:
                    parts.append(str(self.first_time))
                if self.distance:
                    parts.append('{:4.2f}km'.format(self.distance))
            return '{}({})'.format(str(self), ' '.join(parts))

    @staticmethod
    def identifier(backend, ident: str) ->str:
        """The full identifier for a gpxfile.

        Since we may want to do this without instantiating a gpxfile,
        this must be staticmethod or classmethod.

        str(gpxfile) uses this. However if a gpxfile has no id_in_backend,
        str(gpxfile will create one using title, time, id(gpxfile).

        Args:
            backend: May be :class:`~gpxity.backend.Backend` or :class:`~gpxity.accounts.Account`
            ident: id_in_backend

        Returns:
            the full identifier.

        """
        if isinstance(backend, BackendBase):
            account = backend.account
        else:
            account = backend
        if account is None:
            return 'unsaved: "{}"'.format(ident)
        if not ident:
            ident = 'no id_in_backend'
        return str(account) + ident

    def __str__(self) ->str:
        """The str.

        Returns:
            a unique full identifier

        """
        ident = self.id_in_backend
        if not ident:
            ident = '"{}" time={} id={}'.format(self.title or 'untitled', self.first_time, id(self))
        return self.identifier(self.backend, ident)

    def key(self, with_category: bool = True, with_last_time: bool = True, precision=None) ->str:
        """For speed optimized equality checks, not granted to be exact, but sufficiently safe IMHO.

        Args:
            with_category: If False, do not use self.category. Needed for comparing
                gpxfiles for equality like in unittests because values can change
                and information can get lost while copying between different
                backends
            with_last_time: If False, do not use self.last_time.
            precision: For latitude/longitude. After comma digits. Default is as defined by backend or 6.

        Returns:
            a string with selected attributes in printable form.

        """
        self._load_full()
        return 'title:{} description:{} keywords:{} category:{}: public:{} last_time:{} angle:{} points:{}'.format(
            self.title, self.description,
            ','.join(self.keywords).lower(), self.category if with_category else '',
            self.public, self.last_time if with_last_time else '',
            self.angle(precision=precision), self.gpx.get_track_points_no())

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

    def angle(self, first_point=None, last_point=None, precision=None) ->float:
        """For me, the earth is flat.

        Args:
            first_point: if None, first point of GpxFile
            last_point: if None, last point of GpxFile
            precision: After comma digits. Default is as defined by backend or 6.

        Returns:
            the angle in degrees 0..360 between start and end.
            If we have no two points, return 0

        """
        return self.gpx.angle(first_point=first_point, last_point=last_point, precision=precision)

    def segments(self):
        """
        A generator over all segments.

        Yields:
            GPXTrackSegment: all segments in all tracks

        """
        for _ in self.gpx.segments():
            yield _

    def points(self):
        """
        A generator over all points.

        Yields:
            GPXTrackPoint: all points in all tracks and segments

        """
        for _ in self.gpx.points():
            yield _

    def point_list(self):
        """A flat list with all points.

        Returns:
            The list

        """
        return sum((x.points for x in self.segments()), [])

    def last_point(self):
        """Return the last point of the track. None if none."""
        # TODO: unittest for track without __gpx or without points
        return self.gpx.last_point()

    def adjust_time(self, delta):
        """Add a timedelta to all times."""
        self.gpx.adjust_time(delta)
        self._dirty = 'gpx'

    def points_hash(self) -> float:
        """A hash that is hopefully different for every possible track.

        It is built using the combination of all points.

        Returns:
            The hash

        """
        return self.gpx.points_hash()

    def points_equal(self, other, digits=4) ->bool:
        """
        Compare points for same position.

        Args:
            digits: Number of after comma digits to compare

        Returns:
            True if both gpxfiles have identical points.

        All points of all gpxfiles and segments are combined. Elevations are ignored.

        """
        return self.gpx.points_equal(other.gpx, digits)

    def index(self, other, digits=4):
        """Check if this gpxfile contains other gpxfile.

        This only works if all values for latitude and longitude are
        nearly identical.

        Useful if one of the gpxfiles had geofencing applied.

        Args:
            digits: How many after point digits are used

        Returns:
            None or the starting index for other.points in self.points

        """
        return self.gpx.index(other.gpx, digits)

    @staticmethod
    def overlapping_times(gpxfiles):
        """Find gpxfiles with overlapping times.

        Yields:
            groups of gpxfiles with overlapping times. Sorted by time.

        This may be very slow for many long gpxfiles.

        """
        previous = None
        group = list()  # GpxFile is  mutable, so a set is no possible
        for current in sorted(gpxfiles, key=lambda x: x.first_time):
            if previous and current.first_time <= previous.last_time:
                if previous not in group:
                    group.append(previous)
                group.append(current)
            else:
                if group:
                    yield sorted(group, key=lambda x: x.first_time)
                    group = list()
            previous = current
        if group:
            yield sorted(group, key=lambda x: x.first_time)

    def _has_default_title(self) ->bool:
        """Try to check if gpxfile has the default title given by a backend.

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
        # ids are diffent. keywords are sorted, ids is fifo
        new_ids = self.__clean_ids(self.ids + other.ids)
        if new_ids != self.ids:
            msg.append('New Ids: {}'.format(','.join(set(new_ids) - set(self.ids))))
            if not dry_run:
                self.ids = new_ids
        return msg

    def can_merge(self, other, partial_tracks: bool = False):
        """Check if self and other are mergeable.

        args:
            other: The other GpxFile
            partial_tracks: If True, they are mergeable if one of them contains
                the other one.

        Returns: (int, str)
            int is either None or the starting index of the shorter gpxfile in the longer gpxfile
            str is either None or a string explaing why this is not mergeable

        """
        if str(self) == str(other):
            return None, 'Cannot merge identical gpxfiles {}'.format(self)

        if (other.gpx.get_track_points_no()) == 0 and other.gpx.waypoints:
            # mergable
            return 0, None

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

    def __merge_waypoints(self, other, dry_run) ->list:
        """Merge waypoints from other with differing positions.

        Returns: list(str)
            Messages about what has been done.

        """
        # TODO: unittest
        def have(wpt):
            """True if we already have this waypoint."""
            return (wpt.latitude, wpt.longitude) in [(x.latitude, x.longitude) for x in new_wpts]
        merged_count = 0
        new_wpts = self.gpx.waypoints[:]
        for other_wpt in other.gpx.waypoints:
            if not have(other_wpt):
                new_wpts.append(other_wpt)
                if not dry_run:
                    self.gpx.waypoints.append(other_wpt)
                    self.rewrite()
                merged_count += 1
        if merged_count > 0:
            return ['{} got {} waypoints from {}'.format(self, merged_count, other)]
        return []

    def __merge_gpxfiles(self, other, dry_run, shorter_at) ->list:
        """Merge gpxfiles from other.

        Returns: list(str)
            Messages about what has been done.

        """
        msg = []
        if other.gpx.get_track_points_no() > self.gpx.get_track_points_no():
            if not dry_run:
                self.gpx.tracks = deepcopy(other.gpx.tracks)
                self.rewrite()
            msg.append('{} got entire gpx.tracks from {}'.format(self, other))
        changed_point_times = 0
        self_points = self.point_list()[shorter_at:]
        for self_point, other_point in zip(self_points, other.points()):
            # TODO: unittest with shorter gpxfile
            if not self_point.time:
                if not dry_run:
                    self_point.time = other_point.time
                changed_point_times += 1
        if changed_point_times:
            if not dry_run:
                self.rewrite()
            msg.append('Copied times for {} out of {} points'.format(
                changed_point_times, self.gpx.get_track_points_no()))
        return msg

    def merge(  # noqa pylint: disable=unused-argument
            self, other, remove: bool = False, dry_run: bool = False, copy: bool = False,
            partial_tracks: bool = False) ->list:
        """Merge other gpxfile into this one.

        Either the track points must be identical or the other gpxfile
        may only contain waypoints.

        If merging is not possible, raise GpxFile.CannotMerge.

        If either is public, the result is public.
        If self.title seems like a default and other.title does not, use other.title
        Combine description and keywords.
        Merge waypoints as defined by _merge_waypoints().

        Args:
            other (:class:`~gpxity.gpxfile.GpxFile`): The gpxfile to be merged
            remove: After merging succeeded, remove other
            dry_run: if True, do not really apply the merge
            copy: This argument is ignored. It is only here to give
                :meth:`GpxFile.merge() <gpxity.gpxfile.GpxFile.merge>`
                and :meth:`Backend.merge() <gpxity.backend.Backend.merge>` the same interface.
            partial_tracks: merges other gpxfile
                if either gpxfile is part of the other one

        Returns: list(str)
            Messages about what has been done.

        """
        assert isinstance(other, GpxFile)
        msg = []
        shorter_at, _ = self.can_merge(other, partial_tracks)
        if shorter_at is None:
            raise GpxFile.CannotMerge(_)
        with self.batch_changes():
            msg.extend(self.__merge_gpxfiles(other, dry_run, shorter_at))
            msg.extend(self.__merge_waypoints(other, dry_run))
            msg.extend(self.__merge_metadata(other, dry_run))
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

    def fix_orux(self):
        """Older Oruxmaps switched the day back by one day after exactly 24 hours.

        Try fixing that.

        Please backup your gpxfile before doing this.

        Returns: A list with messages. Currently nothing.

        """
        if self.gpx.fix_orux():
            self._dirty = 'gpx'
        return []

    def split_at_stops(self, minutes):
        """Split where things happen.

        Whenever the time jumps back or more than X
        minutes into the future, split the segment at that point.

        minutes: Shortest possible stop for splitting

        Returns:
            A list of message strings, usable for verbose output.

        """
        if self.gpx.fix_jumps(minutes=minutes):
            self._dirty = 'gpx'

    def __similarity_to(self, other):
        """Return a float 0..1: 1 is identity."""

        def simple(gpxfile):
            """Simplified gpxfile"""
            return [(round(x.latitude, 3), round(x.longitude, 3))
                    for x in simplify_polyline(list(gpxfile.points()), max_distance=50)]

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

    def similarity(self, others):
        """Return a float 0..1: 1 is identity.

        The highest value for others is returned."""

        if isinstance(others, GpxFile):
            others = [others]
        return max(self.__similarity_to(x) for x in others)

    def time_offset(self, other):
        """If time and last_time have the same offset between both gpxfiles, return that time difference.
        Otherwise return None."""
        return self.gpx.time_offset(other.gpx)

    @property
    def ids(self):
        """Return ids for all backends where this gpxfile has already been.

        You can modify it but your changes will only be saved if and when
        the entire gpxfile is saved.

        They are sorted by ascending age.
        Only the 5 youngest are kept.
        If the same id_in_backend appears in more than one directory, keep only the youngest.

        Returns: list( (str))
            a list of gpxfile ids

        """
        if self.__gpx.keywords == Gpx.undefined_str:
            self._load_full()
        return self.__clean_ids(self.__gpx.ids)

    @ids.setter
    def ids(self, value):
        """Setter for ids."""
        cleaned = self.__clean_ids(value)
        if cleaned != self.__gpx.ids:
            self._load_full()
            self.__gpx.ids = cleaned
            self.__gpx.encode()

    @staticmethod
    def __clean_ids(original):
        """Remove redundancies and old ids.append.

        1. if the same id_in_backend is in several directories, keep only the first one
        2. keep only 5

        Returns: The cleaned list if ids

        """
        result = list()
        seen_url = set()
        seen_id = set()
        for orig_id in original:
            if orig_id in seen_id:
                continue
            seen_id.add(orig_id)
            try:
                acc, _ = BackendBase.parse_objectname(orig_id)
            except KeyError:
                continue
            if acc.backend == 'Directory':
                if acc.url not in seen_url:
                    seen_url.add(acc.url)
                    result.append(orig_id)
            else:
                result.append(orig_id)
        result = result[:5]
        if result != original:
            logging.debug('ids: %s -> %s', original, result)
        return result

    def split_segments(self):
        """Create separate gpxfiles for every track/segment."""
        backend = self.backend
        clone = self.clone()
        self.remove()
        try:
            for segment in clone.segments():
                gpxfile = self.clone()
                gpx_track = GPXTrack()
                gpx_track.segments.append(segment)
                gpxfile.gpx.tracks = [gpx_track]
                backend.add(gpxfile)
        except BaseException as exc:
            logging.error('split:%s', exc)
            backend.add(clone)

    def locate_point(self, track=0, segment=0, point=0) ->str:
        """Determine name of place for point.

        Saves that in point.name for caching. If backend.account.country is given,
        add the country name only if it is different.

        Args:
            track, segment, point: Indices into the respective arrays
            default_country: suppress this one in the result

        Returns: A string

        """
        country = self.backend.account.country if self.backend is not None else None
        result, located = self.gpx.locate_point(track, segment, point, default_country=country)
        if located:
            if self.backend is not None:
                self.rewrite()
        return result

    def add_locations(self, segments=False):
        """Call locate_point for the first point.

        Args: segments: Also do that for the first point of each segment.

        """
        self.locate_point()
        if segments:
            for track_idx, gpx_track in enumerate(self.gpx.tracks):
                for seg_idx, _ in enumerate(gpx_track.segments):
                    self.locate_point(track=track_idx, segment=seg_idx)

    def add_segment_waypoints(self):
        """Every segment start gets a waypoint.

        The name looks like :literal:`Trk/Seg 2/4 Mainz-Wiesbaden`.
        Existing such waypoints are removed if the no longer belong
        to a segment start.

        For the involved points (first and last of each segment) see
        :meth:`locate_point`.

        """
        if self.gpx.add_segment_waypoints():
            self._dirty = 'gpx'

    def join_tracks(self, force=False):
        """Join all tracks to a single track.

        Metadata from all but the first track is thrown away.
        If metadata will be lost, it is printed and nothing is done unless force is True

        Args: force if True, join even if metadata is lost

        Returns: list()
            A list with text strings about lost metadata

        """

        result = self.gpx.join_tracks(force)
        if result:
            result = ['  ' + x for x in result]
            if force:
                msg = 'Joining tracks in {trk} lost metadata from joined tracks:'
            else:
                msg = 'Joining tracks in {trk} would lose metadata from joined tracks, use the force option:'
            result.insert(0, msg.format(trk=self))
        if not result or force:
            self.rewrite()
        return result
