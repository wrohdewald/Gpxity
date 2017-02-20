# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for Activity
"""

import os
import datetime
import io
import filecmp

from gpxpy.gpx import GPX

from .basic import BasicTest
from ... import Activity
from .. import Directory

# pylint: disable=attribute-defined-outside-init


class ActivityTests(BasicTest):

    """activity tests"""

    def test_init(self):
        """test initialisation"""
        Activity()
        with Directory() as backend:
            with self.assertRaises(Exception):
                Activity(backend, gpx=GPX())
            Activity(backend)
            self.assertEqual(len(backend.activities), 1)

    def test_activity_list(self):
        """test ActivityList"""
        with Directory() as directory: # we have no direct access to class ActivityList
            ali = directory.activities
            self.assertEqual(len(ali), 0)
            activity1 = Activity(backend=directory)
            self.assertIn(activity1, ali)
            self.assertEqual(activity1.id_in_backend, None)
            activity1.description = 'x'
            self.assertNotEqual(activity1.id_in_backend, None)

    def test_clone(self):
        """is the clone identical?"""
        activity1 = self.create_test_activity()
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

    def test_keywords(self):
        """save and load keywords. TODO: Also in test_backend for all backends"""
        with Directory() as directory:
            activity = Activity(backend=directory)
            activity.keywords = (['a', 'b', 'c'])
            with self.assertRaises(Exception):
                activity.add_keyword('b')
            activity.remove_keyword('b')
            self.assertEqual(activity.keywords, (['a', 'c']))
            with self.assertRaises(Exception):
                activity.add_keyword('What:whatever')
            activity.add_keyword('e')
            self.assertEqual(activity.keywords, (['a', 'c', 'e']))


    def test_remove_what(self):
        """remove what from Activity"""
        what_default = Activity.legal_what[0]
        what_other = Activity.legal_what[5]
        activity = Activity()
        activity.what = what_other
        self.assertEqual(activity.what, what_other)
        activity.what = None
        self.assertEqual(activity.what, what_default)

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

    def test_first_time(self):
        """about activity.time"""
        activity = self.create_test_activity()
        first_time = activity.gpx.get_time_bounds()[0]
        self.assertEqual(activity.time, first_time)

    def test_last_time(self):
        """Activity.last_time()"""
        activity = self.create_test_activity()
        gpx_last_time = activity.gpx.tracks[-1].segments[-1].points[-1].time
        self.assertEqual(activity.last_time(), gpx_last_time)

    def test_xml(self):
        """roughly check if we have one line per trackpoint"""
        activity = self.create_test_activity()
        xml = activity.to_xml()
        self.assertNotIn('<link ></link>', xml)
        lines = xml.split('\n')
        self.assertTrue(len(lines) >= activity.point_count())

    def test_parse(self):
        """does Activity parse xml correctly"""
        activity = self.create_test_activity()
        xml = activity.to_xml()
        activity2 = Activity()
        activity2.parse(xml)
        self.assertEqualActivities(activity, activity2)
        activity2 = Activity()
        activity2.parse(io.StringIO(xml))
        self.assertEqualActivities(activity, activity2)

    def test_combine(self):
        """combine values in activity with newly parsed"""
        activity = self.create_test_activity()
        xml = activity.to_xml()
        if activity.what == 'Cycling':
            other_what = 'Running'
        else:
            other_what = 'Cycling'

        activity2 = Activity()
        activity2.title = 'Title2'
        activity2.description = 'Description2'
        activity2.what = other_what
        activity2.public = True
        activity2.parse(xml)
        self.assertEqual(activity2.title, activity.title)
        self.assertEqual(activity2.description, activity.description)
        self.assertEqual(activity2.what, activity.what)
        self.assertTrue(activity2.public)
        self.assertEqual(activity2.keywords, list())

        activity.public = True
        xml = activity2.to_xml()
        self.assertIn('Status:public', xml)
        activity2 = Activity()
        activity2.what = 'Kayaking'
        activity2.public = False
        activity2.parse(xml)
        self.assertTrue(activity2.public)

    def test_save(self):
        """save locally"""
        # TODO: fuer die ganzen Directory) with machen oder destroy rufen, nach dem Test soll /tmp sauber sein
        directory = Directory()
        dir2 = directory.clone()
        activity = self.create_test_activity()
        activity.backend = directory
        self.assertEqual(len(directory.activities), 1)
        self.assertEqual(len(directory.activities), 1)
        aclone = activity.clone()
        self.assertEqualActivities(activity, aclone)

        self.assertEqual(len(dir2.activities), 0)
        dir2.list_all()
        self.assertEqual(len(dir2.activities), 1)

        activity2 = activity.clone()
        self.assertEqualActivities(activity, activity2)
        activity2.backend = directory
        self.assertEqual(len(directory.activities), 2)
        with self.assertRaises(Exception):
            activity2.backend = dir2
        with self.assertRaises(Exception):
            activity2.backend = None
        activity3 = dir2.save(activity2)
        self.assertEqualActivities(activity, activity3)
        self.assertEqualActivities(activity2, activity3)
        self.assertIs(activity.backend, directory)
        self.assertIs(activity2.backend, directory)
        self.assertIs(activity3.backend, dir2)
        self.assertEqual(len(directory.activities), 2)
        self.assertEqual(len(dir2.activities), 2)
        directory.list_all()
        self.assertEqual(len(directory.activities), 3)
        files = list(os.path.join(directory.url, x) for x in os.listdir(directory.url) if x.endswith('.gpx'))
        self.assertEqual(len(files), 3)
        filecmp.clear_cache()
        for idx1, idx2 in ((0, 1), (0, 2)):
            file1 = files[idx1]
            file2 = files[idx2]
            self.assertTrue(filecmp.cmp(file1, file2),
                            'Files are different: {} and {}'.format(file1, file2))

    def test_add_points(self):
        """test Activity.add_points"""
        point_count = 11
        activity = Activity()
        points = self.some_random_points(count=point_count)
        activity.add_points(points)
        self.assertEqual(activity.point_count(), point_count)
        with self.assertRaises(Exception):
            activity.add_points(points)
        activity.add_points(points[:-1])
        self.assertEqual(activity.point_count(), point_count * 2 - 1)
