# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for all backends
"""

import time
import datetime
import io
import unittest
import requests

from gpxpy.gpx import GPX

from .basic import BasicTest
from ... import Activity
from .. import Directory

# pylint: disable=attribute-defined-outside-init

# first the cheap tests

class Init(unittest.TestCase):

    """Test Activity.__init__"""

    def test_init(self):
        """test initialisation"""
        Activity()
        with self.assertRaises(AssertionError):
            Activity(backend=Directory(), gpx=GPX())


class Supported(BasicTest):
    """Are the :literal:`supported_` attributes set correctly?"""

    def test_supported(self):
        """check values supports_* for all backends"""
        expect_unsupported = dict()
        expect_unsupported['Directory'] = ('update', )
        expect_unsupported['MMT'] = ('allocate', 'deallocate', 'new_id')
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                self.assertIn(cls.__name__, expect_unsupported)
                expect_cls_unsupported = expect_unsupported[cls.__name__]
                backend = self.setup_backend(cls)
                attributes = (x for x in backend.__class__.__dict__.items() if x[0].startswith('supports_'))
                for name, _ in attributes:
                    short_name = name.replace('supports_', '')
                    with self.subTest('testing supported_{} for {}'.format(short_name, cls.__name__)):
                        self.assertIn(short_name, backend.supported)
                        if short_name in expect_cls_unsupported:
                            self.assertFalse(backend.supported[short_name])
                            self.assertFalse(getattr(backend, name))
                        else:
                            self.assertTrue(backend.supported[short_name])
                            self.assertTrue(getattr(backend, name))


class Clone(BasicTest):

    """equality tests"""

    def test_clone(self):
        """is the clone identical?"""
        activity1 = self.create_unique_activity()
        activity2 = activity1.clone()
        self.assertEqualActivities(activity1, activity2)
        count1 = activity1.point_count()
        del activity1.gpx.tracks[0].segments[0].points[0]
        self.assertEqual(count1, activity1.point_count() + 1)
        self.assertNotEqualActivities(activity1, activity2)
        activity2 = activity1.clone()
        activity2.gpx.tracks[-1].segments[-1].points[-1].latitude = 5
        self.assertNotEqualActivities(activity1, activity2)
        activity2 = activity1.clone()
        activity2.gpx.tracks[-1].segments[-1].points[-1].longitude = 5
        self.assertNotEqual(activity1, activity2)
        activity2 = activity1.clone()
        last_point2 = activity2.gpx.tracks[-1].segments[-1].points[-1]
        last_point2.elevation = 500000
        self.assertEqual(last_point2.elevation, 500000)
        self.assertEqual(activity2.gpx.tracks[-1].segments[-1].points[-1].elevation, 500000)
        # here assertNotEqualActivities is wrong because keys() are still identical
        self.assertFalse(activity1.points_equal(activity2))
        activity1.gpx.tracks.clear()
        activity2.gpx.tracks.clear()
        self.assertEqualActivities(activity1, activity2)


class What(BasicTest):

    """test manipulations on Activity.what"""

    def test_no_what(self):
        """what must return default value if not present in gpx.keywords"""
        what_default = Activity.legal_what[0]
        activity = Activity()
        self.assertEqual(activity.what, what_default)
        activity.what = None
        self.assertEqual(activity.what, what_default)
        with self.assertRaises(Exception):
            activity.what = 'illegal value'
        self.assertEqual(activity.what, what_default)
        with self.assertRaises(Exception):
            activity.add_keyword('What:illegal value')
        self.assertEqual(activity.what, what_default)

    def test_duplicate_what(self):
        """try to add two whats to Activity"""
        what_other = Activity.legal_what[5]
        activity = Activity()
        activity.what = what_other
        with self.assertRaises(Exception):
            activity.add_keyword('What:{}'.format(what_other))

    def test_remove_what(self):
        """remove what from Activity"""
        what_default = Activity.legal_what[0]
        what_other = Activity.legal_what[5]
        activity = Activity()
        activity.what = what_other
        self.assertEqual(activity.what, what_other)
        activity.what = None
        self.assertEqual(activity.what, what_default)


class Public(unittest.TestCase):
    """test manipulations on Activity.public"""

    def test_no_public(self):
        """public must return False if not present in gpx.keywords"""
        activity = Activity()
        self.assertFalse(activity.public)

    def test_duplicate_public(self):
        """try to set public via its property and additionally with add_keyword"""
        activity = Activity()
        activity.public = True
        self.assertTrue(activity.public)
        with self.assertRaises(Exception):
            activity.add_keyword('Status:public')

    def test_remove_public(self):
        """remove and add public from Activity using remove_keyword and add_keyword"""
        activity = Activity()
        activity.public = True
        with self.assertRaises(Exception):
            activity.remove_keyword('Status:public')
        self.assertTrue(activity.public)
        with self.assertRaises(Exception):
            activity.add_keyword('Status:public')
        self.assertTrue(activity.public)

class Time(BasicTest):

    """test server time"""

    def test_first_time(self):
        """about activity.time"""
        activity = self.create_unique_activity()
        first_time = activity.gpx.get_time_bounds()[0]
        activity.time = None
        self.assertEqual(activity.time, first_time)
        activity.time += datetime.timedelta(days=1)
        self.assertNotEqual(activity.time, first_time)

    def test_last_time(self):
        """Activity.last_time()"""
        activity = self.create_unique_activity()
        gpx_last_time = activity.gpx.tracks[-1].segments[-1].points[-1].time
        self.assertEqual(activity.last_time(), gpx_last_time)


class Xml(BasicTest):

    """xml related tests"""

    def setUp(self):
        self.activity = self.create_unique_activity()

    def test_xml(self):
        """roughly check if we have one line per trackpoint"""
        xml = self.activity.to_xml()
        self.assertNotIn('<link ></link>', xml)
        lines = xml.split('\n')
        self.assertTrue(len(lines) >= self.activity.point_count())

    def test_parse(self):
        """does Activity parse xml correctly"""
        xml = self.activity.to_xml()
        activity2 = Activity()
        activity2.parse(xml)
        self.assertEqualActivities(self.activity, activity2)
        activity2 = Activity()
        activity2.parse(io.StringIO(xml))
        self.assertEqualActivities(self.activity, activity2)

    def test_combine(self):
        """combine values in activity with newly parsed"""
        xml = self.activity.to_xml()
        if self.activity.what == 'Cycling':
            other_what = 'Running'
        else:
            other_what = 'Cycling'

        activity2 = Activity()
        activity2.title = 'Title2'
        activity2.description = 'Description2'
        activity2.what = other_what
        activity2.public = True
        activity2.parse(xml)
        self.assertEqual(activity2.title, self.activity.title)
        self.assertEqual(activity2.description, self.activity.description)
        self.assertEqual(activity2.what, self.activity.what)
        self.assertTrue(activity2.public)
        self.assertEqual(activity2.keywords, list())

        self.activity.public = True
        xml = activity2.to_xml()
        self.assertIn('Status:public', xml)
        activity2 = Activity()
        activity2.what = 'Kayaking'
        activity2.public = False
        activity2.parse(xml)
        self.assertTrue(activity2.public)

class WrongAuth(BasicTest):
    """what happens with a wrong password?"""

    def test_open_wrong_auth(self):
        """open backends with wrong password"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    if cls.__name__ == 'Directory':
                        self.setup_backend(cls, sub_name='wrong')
                    else:
                        with self.assertRaises(requests.exceptions.HTTPError):
                            self.setup_backend(cls, sub_name='wrong')


# Now the more expensive tests:

class CreateBackend(BasicTest):
    """Can we create a backend and connect with it?"""

    def test_create_backend(self):
        """test creation of a backend"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    backend = self.setup_backend(cls, count=3, clear_first=True)
                    self.assertEqual(len(backend.list_all()), 3)
                    first_time = backend.get_time()
                    time.sleep(2)
                    second_time = backend.get_time()
                    total_seconds = (second_time - first_time).total_seconds()
                    self.assertTrue(1 < total_seconds < 4, 'Time difference should be {}, is {}-{}={}'.format(
                        2, second_time, first_time, second_time - first_time))


class PageParser(BasicTest):

    """page parsing, actually needed only for mmt"""

    def test_change_remote_attributes(self):
        """if we change title, description, public, what in activity, is the backend updated?"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    backend = self.setup_backend(cls, count=1, clear_first=True)
                    activity = backend.list_all(load_full=True)[0]
                    first_public = activity.public
                    first_title = activity.title
                    first_description = activity.description
                    first_what = activity.what
                    activity.public = not activity.public
                    activity.title = 'A new title'
                    activity.description = 'A new description'
                    if activity.what == 'Cycling':
                        activity.what = 'Running'
                    else:
                        activity.what = 'Cycling'
                    # make sure there is no cache in the way
                    backend2 = backend.clone()
                    activity2 = backend2.list_all(load_full=True)[0]
                    self.assertNotEqual(first_public, activity2.public)
                    self.assertNotEqual(first_title, activity2.title)
                    self.assertNotEqual(first_description, activity2.description)
                    self.assertNotEqual(first_what, activity2.what)
