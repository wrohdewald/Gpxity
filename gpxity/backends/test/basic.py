# -*- coding: utf-8 -*-


# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Tests for gpxity.backends
"""

import unittest
import importlib
import os
import io
import datetime
import random
from inspect import getmembers, isclass, getmro
from pkgutil import get_data
import tempfile
from contextlib import contextmanager

import  gpxpy
from gpxpy.gpx import GPXTrackPoint

from ...activity import Activity
from ...backend import Backend

# pylint: disable=attribute-defined-outside-init

__all__ = ['BasicTest']

from .. import Directory

class BasicTest(unittest.TestCase):
    """define some helpers

    Attributes:
        all_backend_classes: a list of all backend implementations
    """

    all_backend_classes = None

 #   def __init__(self):
    #    super(BasicTest, self).__init__()

    def setUp(self):
        """defines test specific Directory.prefix"""
        self.start_time = datetime.datetime.now()
        self.unicode_string1 = 'unicode szlig: ß'
        self.unicode_string2 = 'something japanese:の諸問題'
        Directory.prefix = 'gpxity.' + '.'.join(self.id().split('.')[-2:])
        path = tempfile.mkdtemp(prefix=Directory.prefix)

        if not os.path.exists(path):
            os.mkdir(path)

    def tearDown(self):
        """Check if there are still /tmp/gpxitytest.* directories"""
        must_be_empty = tempfile.mkdtemp(prefix=Directory.prefix)
        os.rmdir(must_be_empty)
        timedelta = datetime.datetime.now() - self.start_time
        print('{} seconds '.format(timedelta.seconds), end='', flush=True)

    @staticmethod
    def _get_gpx_from_test_file(name: str):
        """gets data from a predefined gpx file.
        name is without .gpx"""
        gpx_test_file = os.path.join(os.path.dirname(__file__), '{}.gpx'.format(name))
        if not os.path.exists(gpx_test_file):
            raise Exception('MMTTests needs a GPX file named {}.gpx for testing in {}'.format(
                name, os.getcwd()))
        return gpxpy.parse(io.StringIO(get_data(__package__, '{}.gpx'.format(name)).decode('utf-8')))

    @classmethod
    def create_test_activity(
            cls, count: int = 1, idx: int = 0, what: str = None, public: bool = False,
            start_time=None, end_time=None):
        """creates an :class:`~gpxity.Activity`. It starts off with **test.gpx** and appends a
        last track point, it also changes the time stamp of the last point.
        This is done using **count** and **idx**: The last point is set such that
        looking at the tracks, they all go in a different direction clockwise, with an angle
        in degrees of :literal:`360 * idx / count`.

        Args:
            count: See above. Using 1 as default if not given.
            idx: See above. Using 0 as default if not given.
            what: The wanted value for the activity.
                Default: if count == len(:attr:`Activity.legal_whats <gpxity.Activity.legal_whats>`),
                the default value will be legal_whats[idx].
                Otherwise a random value will be applied.
            public: should the activities be public or private?
            start_time: If given, assign it to the first point and adjust all following times
            end_time: explicit time for the last point. If None: See above.

        Returns:
            (~gpxity.Activity): A new activity not bound to a backend
        """
        if BasicTest.all_backend_classes is None:
            BasicTest.all_backend_classes = BasicTest._find_backend_classes()
        gpx = cls._get_gpx_from_test_file('test')
        if start_time is not None:
            move_time = start_time - gpx.tracks[0].segments[0].points[0].time
            gpx.adjust_time(move_time)
        movement = gpxpy.geo.LocationDelta(distance=1000, angle=360 * idx / count)
        last_points = gpx.tracks[-1].segments[-1].points
        if end_time is None:
            end_time = last_points[-1].time + datetime.timedelta(hours=10, seconds=idx)
        new_point = GPXTrackPoint(
            latitude=last_points[-1].latitude, longitude=last_points[-1].longitude + 0.001, time=end_time)
        new_point.move(movement)
        gpx.tracks[-1].segments[-1].points.append(new_point)

        # now set all times such that they are in order with this activity and do not overlap
        # with other test activities
        duration = new_point.time - gpx.tracks[0].segments[0].points[0].time + datetime.timedelta(seconds=10)
        for point in gpx.walk(only_points=True):
            point.time += duration * idx

        result = Activity(gpx=gpx)
        result.title = 'Random GPX # {}'.format(idx)
        result.description = 'Description to {}'.format(gpx.name)
        if what:
            result.what = what
        elif count == len(Activity.legal_whats):
            result.what = Activity.legal_whats[idx]
        else:
            result.what = random.choice(Activity.legal_whats)
        result.public = public
        return result

    @staticmethod
    def _random_datetime():
        """random datetime between now() - 10 days and now()"""
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=10)
        delta = end - start
        int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
        random_second = random.randrange(int_delta)
        return start + datetime.timedelta(seconds=random_second)

    @classmethod
    def some_random_points(cls, count=100):
        """

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

    def assertSameActivities(self, backend1, backend2, with_what=True): # pylint: disable=invalid-name
        """both backends must hold identical activities"""
        self.maxDiff = None # pylint: disable=invalid-name
        if backend1 == backend2:
            return True
        keys1 = sorted(x.key(with_what) for x in backend1)
        keys2 = sorted(x.key(with_what) for x in backend2)
        self.assertEqual(keys1, keys2)

    def assertEqualActivities(self, activity1, activity2, xml: bool = False): # pylint: disable=invalid-name
        """both activities must be identical. We test more than necessary for better test coverage.

        Args:
            xml: if True, also compare to_xml()"""
        self.maxDiff = None
        self.assertEqual(activity1.key(), activity2.key())
        self.assertTrue(activity1.points_equal(activity2))
        if xml:
            self.assertEqual(activity1.gpx.to_xml(), activity2.gpx.to_xml())

    def assertNotEqualActivities(self, activity1, activity2): # pylint: disable=invalid-name
        """both activities must be identical. We test more than necessary for better test coverage."""
        self.assertNotEqual(activity1.key(), activity2.key())
        self.assertFalse(activity1.points_equal(activity2))
        self.assertNotEqual(activity1.gpx.to_xml(), activity2.gpx.to_xml())

    def setup_backend(self, cls_, username: str = None, url: str = None, count: int = 0,  # pylint: disable=too-many-arguments
                      cleanup: bool = True, clear_first: bool = True, what: str = None,
                      public: bool = False, debug: bool = False):
        """sets up an instance of a backend with count activities.

        If count == len(:attr:`Activity.legal_whats <gpxity.Activity.legal_whats>`),
        the list of activities will always be identical. For an example
        see :meth:`TestBackends.test_all_what <gpxity.backends.test.test_backends.TestBackends.test_all_what>`.

        Args:
            cls_ (Backend): the class of the backend to be created
            username: use this to for a specific accout name. Default is 'gpxitytest'
            url: for the backend
            count: how many random activities should be inserted?
            cleanup: If True, remove all activities when done. Passed to the backend.
            clear_first: if True, first remove all existing activities
            public: should the activities be public or private?

        Returns:
            the prepared Backend
        """

        result = cls_(url, auth=username or 'gpxitytest', cleanup=cleanup, debug=debug)
        if clear_first:
            result.remove_all()
        while count > len(result):
            activity = self.create_test_activity(count, len(result), what=what, public=public)
            result.add(activity)
        self.assertGreaterEqual(len(result), count)
        if clear_first:
            self.assertEqual(len(result), count)
        return result

    @contextmanager
    def temp_backend(self, cls_, url=None, count=0,  # pylint: disable=too-many-arguments
                     cleanup=True, clear_first=True, what=None,
                     public: bool = False, debug: bool = False, username=None):
        """Just like setup_backend but usable as a context manager. which will
        call destroy() when done.
        """
        tmp_backend = self.setup_backend(cls_, username, url, count, cleanup, clear_first, what, public, debug)
        try:
            yield tmp_backend
        finally:
            tmp_backend.destroy()

    @staticmethod
    def clone_backend(backend):
        """returns a clone of backend
        """
        return backend.__class__(backend.url, backend.auth)

    @staticmethod
    def _find_backend_classes(with_skip: bool = False):
        """Finds all backend classes. Those will be tested.

        Args:
            with_skip: if True, also finds those with skip_test=False
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
        #sort because we want things reproducibly
        return sorted(set(result), key=lambda x: x.__class__.__name__)

    @staticmethod
    def move_times(activity, delta):
        """move all times by delta"""
        for point in activity.points():
            point.time += delta
