# -*- coding: utf-8 -*-


# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""Tests for gpxity.backends."""

import unittest
import importlib
import os
import io
import datetime
import time
import random
from inspect import getmembers, isclass, getmro
from pkgutil import get_data
import tempfile
from contextlib import contextmanager
from subprocess import Popen

import gpxpy
from gpxpy.gpx import GPXTrackPoint

from ...track import Track
from ...backend import Backend
from ...auth import Authenticate
from .. import GPSIES

# pylint: disable=attribute-defined-outside-init

__all__ = ['BasicTest']

from .. import Directory


class BasicTest(unittest.TestCase):

    """define some helpers.

    Attributes:
        all_backend_classes: a list of all backend implementations

    """

    all_backend_classes = None

    def setUp(self):  # noqa
        """define test specific Directory.prefix."""
        Authenticate.path = os.path.join(os.path.dirname(__file__), 'test_auth_cfg')
        print('auth file now is', Authenticate.path)
        self.start_time = datetime.datetime.now()
        self.unicode_string1 = 'unicode szlig: ß'
        self.unicode_string2 = 'something japanese:の諸問題'
        Directory.prefix = 'gpxity.' + '.'.join(self.id().split('.')[-2:])
        path = tempfile.mkdtemp(prefix=Directory.prefix)

        if not os.path.exists(path):
            os.mkdir(path)

    def tearDown(self):  # noqa
        """Check if there are still /tmp/gpxitytest.* directories."""
        must_be_empty = tempfile.mkdtemp(prefix=Directory.prefix)
        os.rmdir(must_be_empty)
        timedelta = datetime.datetime.now() - self.start_time
        print('{} seconds '.format(timedelta.seconds), end='', flush=True)

    @staticmethod
    def _get_gpx_from_test_file(name: str):
        """get data from a predefined gpx file.

        name is without .gpx

        Returns:=
            A GPX object

        """
        gpx_test_file = os.path.join(os.path.dirname(__file__), '{}.gpx'.format(name))
        if not os.path.exists(gpx_test_file):
            raise Exception('MMTTests needs a GPX file named {}.gpx for testing in {}'.format(
                name, os.getcwd()))
        return gpxpy.parse(io.StringIO(get_data(__package__, '{}.gpx'.format(name)).decode('utf-8')))

    @classmethod
    def create_test_track(
            cls, count: int = 1, idx: int = 0, category: str = None, public: bool = False,
            start_time=None, end_time=None):
        """create a :class:`~gpxity.Track`.

        It starts off with **test.gpx** and appends a
        last track point, it also changes the time stamp of the last point.
        This is done using **count** and **idx**: The last point is set such that
        looking at the tracks, they all go in a different direction clockwise, with an angle
        in degrees of :literal:`360 * idx / count`.

        Args:
            count: See above. Using 1 as default if not given.
            idx: See above. Using 0 as default if not given.
            category: The wanted value for the track.
                Default: if count == len(:attr:`Track.legal_categories <gpxity.Track.legal_categories>`),
                the default value will be legal_categories[idx].
                Otherwise a random value will be applied.
            public: should the tracks be public or private?
            start_time: If given, assign it to the first point and adjust all following times
            end_time: explicit time for the last point. If None: See above.

        Returns:
            (~gpxity.Track): A new track not bound to a backend

        """
        if BasicTest.all_backend_classes is None:
            BasicTest.all_backend_classes = BasicTest._find_backend_classes()
        gpx = cls._get_gpx_from_test_file('test')
        if start_time is not None:
            _ = start_time - gpx.tracks[0].segments[0].points[0].time
            gpx.adjust_time(_)
        last_points = gpx.tracks[-1].segments[-1].points
        if end_time is None:
            end_time = last_points[-1].time + datetime.timedelta(hours=10, seconds=idx)
        new_point = GPXTrackPoint(
            latitude=last_points[-1].latitude, longitude=last_points[-1].longitude + 0.001, time=end_time)
        _ = gpxpy.geo.LocationDelta(distance=1000, angle=360 * idx / count)
        new_point.move(_)
        last_points.append(new_point)

        # now set all times such that they are in order with this track and do not overlap
        # with other test tracks
        duration = new_point.time - gpx.tracks[0].segments[0].points[0].time + datetime.timedelta(seconds=10)
        for point in gpx.walk(only_points=True):
            point.time += duration * idx

        result = Track(gpx=gpx)
        result.title = 'Random GPX # {}'.format(idx)
        result.description = 'Description to {}'.format(gpx.name)
        if category:
            result.category = category
        elif count == len(Track.legal_categories):
            result.category = Track.legal_categories[idx]
        else:
            result.category = random.choice(Track.legal_categories)
        result.public = public
        return result

    @staticmethod
    def _random_datetime():
        """random datetime between now() - 10 days and now().

        Returns:
            A random datetime

        """
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=10)
        delta = end - start
        int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
        random_second = random.randrange(int_delta)
        return start + datetime.timedelta(seconds=random_second)

    @staticmethod
    def _random_keywords(count=100):
        """A set of random keywords, but always the same.

        We do not want to generate too many tag ids for MMT.

        Returns:
            A set of random keywords

        """
        state = random.getstate()
        try:
            random.seed(1)
            basis = 'abcdefghijklmnopqrstuvwxyz'
            basis += basis.upper()
            basis += '/-_+.% $"|\\'
            result = set()
            while len(result) < count:
                _ = ''.join(random.choice(basis) for x in range(4))
                result.add(_.strip())
            return result
        finally:
            random.setstate(state)

    @classmethod
    def _random_points(cls, count=100):
        """Get some random points.

        Returns:
            A list with count points

        """
        result = list()
        start_time = cls._random_datetime()
        for _ in range(count):
            point = GPXTrackPoint(
                latitude=random.uniform(0.0, 90.0),
                longitude=random.uniform(0.0, 180.0), elevation=_,
                time=start_time + datetime.timedelta(seconds=10 * _))
            result.append(point)
        return result

    def assertSameTracks(self, backend1, backend2, with_category=True):  # noqa pylint: disable=invalid-name
        """both backends must hold identical tracks."""
        self.maxDiff = None  # pylint: disable=invalid-name
        if backend1 != backend2:
            with_last_time = not (isinstance(backend1, GPSIES) or isinstance(backend2, GPSIES))
            keys1 = sorted(x.key(with_category, with_last_time) for x in backend1)
            keys2 = sorted(x.key(with_category, with_last_time) for x in backend2)
            self.assertEqual(keys1, keys2)

    def assertEqualTracks(self, track1, track2, xml: bool = False, with_category: bool = True):  # noqa pylint: disable=invalid-name
        """both tracks must be identical. We test more than necessary for better test coverage.

        Args:

            xml: if True, also compare to_xml()"""
        self.maxDiff = None

        # GPSIES: when uploading tracks. GPSIES sometimes assigns new times to all points,
        # starting at 2010-01-01 00:00. Until I find the reason, ignore point times for comparison.
        with_last_time = not (isinstance(track1.backend, GPSIES) or isinstance(track2.backend, GPSIES))

        self.assertEqual(track1.key(with_category, with_last_time), track2.key(with_category, with_last_time))
        self.assertTrue(track1.points_equal(track2))
        if xml:
            self.assertEqual(track1.gpx.to_xml(), track2.gpx.to_xml())

    def assertNotEqualTracks(self, track1, track2, with_category: bool = True):  # noqa pylint: disable=invalid-name
        """both tracks must be different. We test more than necessary for better test coverage."""
        self.assertNotEqual(track1.key(with_category), track2.key(with_category))
        self.assertFalse(track1.points_equal(track2))
        self.assertNotEqual(track1.gpx.to_xml(), track2.gpx.to_xml())

    def assertTrackFileContains(self, track, string):  # noqa pylint: disable=invalid-name
        """Assert that string is in the physical file. Works only for Directory backend."""
        with open(track.backend.gpx_path(track.id_in_backend)) as trackfile:
            data = trackfile.read()
        self.assertIn(string, data)

    def setup_backend(  # pylint: disable=too-many-arguments
            self, cls_, username: str = None, url: str = None, count: int = 0,
            cleanup: bool = True, clear_first: bool = True, category: str = None,
            public: bool = False, debug: bool = False):
        """set up an instance of a backend with count tracks.

        If count == len(:attr:`Track.legal_categories <gpxity.Track.legal_categories>`),
        the list of tracks will always be identical. For an example
        see :meth:`TestBackends.test_all_category <gpxity.backends.test.test_backends.TestBackends.test_all_category>`.

        Args:
            cls_ (Backend): the class of the backend to be created
            username: use this to for a specific accout name. Default is 'gpxitytest'
            url: for the backend
            count: how many random tracks should be inserted?
            cleanup: If True, remove all tracks when done. Passed to the backend.
            clear_first: if True, first remove all existing tracks
            public: should the tracks be public or private?

        Returns:
            the prepared Backend

        """

        result = cls_(url, auth=username or 'gpxitytest', cleanup=cleanup, debug=debug)
        if clear_first:
            result.remove_all()
        if count:
            # if count == 0, skip this. Needed for write-only backends like Mailer.
            while count > len(result):
                track = self.create_test_track(count, len(result), category=category, public=public)
                result.add(track)
            self.assertGreaterEqual(len(result), count)
            if clear_first:
                self.assertEqual(len(result), count)
        return result

    @staticmethod
    @contextmanager
    def lifetrackserver(directory, servername, port):
        """Start and ends a server for lifetrack testing."""
        cmdline = 'mmtserver --debug --servername {} --port {} --directory {}'.format(
            servername, port, directory)
        process = Popen(cmdline.split())
        try:
            time.sleep(1)  # give the server time to start
            yield
        finally:
            process.kill()

    @contextmanager
    def temp_backend(self, cls_, url=None, count=0,  # pylint: disable=too-many-arguments
                     cleanup=True, clear_first=True, category=None,
                     public: bool = False, debug: bool = False, username=None):
        """Just like setup_backend but usable as a context manager. which will call destroy() when done."""
        tmp_backend = self.setup_backend(cls_, username, url, count, cleanup, clear_first, category, public, debug)
        try:
            yield tmp_backend
        finally:
            tmp_backend.destroy()

    @staticmethod
    def clone_backend(backend):
        """return a clone of backend."""
        return backend.__class__(backend.url, backend.auth)

    @staticmethod
    def _find_backend_classes(with_skip: bool = False):
        """Find all backend classes. Those will be tested.

        Args:
            with_skip: if True, also finds those with skip_test=False

        Returns:
            A list of backend classes

        """
        backends_directory = __file__
        while not backends_directory.endswith('backends'):
            backends_directory = os.path.dirname(backends_directory)
        if not os.path.exists(backends_directory):
            raise Exception('we are not where we should be')
        result = list()
        mod_names = os.listdir(backends_directory)
        for mod in mod_names:
            if not mod.endswith('.py'):
                continue
            mod = mod.replace('.py', '')
            if mod == '__init__':
                continue
            try:
                imported = importlib.__import__(mod, globals(), locals(), level=2)
                for name, cls in getmembers(imported, isclass):
                    if name in imported.__all__ and Backend in getmro(cls)[1:]:
                        # isinstance and is do not work here
                        if with_skip or not cls.skip_test:
                            result.append(cls)
            except ImportError:
                pass
        # sort because we want things reproducibly
        return sorted(set(result), key=lambda x: x.__class__.__name__)
