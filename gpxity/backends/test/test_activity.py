# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for Activity
"""

import datetime
import io
import unittest

from gpxpy.gpx import GPX

from .basic import BasicTest
from ... import Activity
from .. import Directory

# pylint: disable=attribute-defined-outside-init


class Init(unittest.TestCase):

    """Test Activity.__init__"""

    def test_init(self):
        """test initialisation"""
        Activity()
        with self.assertRaises(AssertionError):
            Activity(backend=Directory(), gpx=GPX())


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

