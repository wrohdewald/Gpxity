# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for Activity. They only use backend Directory,
so there is no network traffic involved (unless Directory is a network
file system, of course).
"""

import os
import io
import filecmp
import tempfile

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
        with Directory(cleanup=True) as backend:
            with self.assertRaises(Exception):
                Activity(backend, gpx=GPX())
            Activity(backend)
            self.assertEqual(len(backend.activities), 1)

        test_url = tempfile.mkdtemp(prefix=Directory.prefix)
        self.assertTrue(os.path.exists(test_url))
        os.rmdir(test_url)
        self.assertFalse(os.path.exists(test_url))
        try:
            with Directory(url=test_url, cleanup=True):
                self.assertTrue(os.path.exists(test_url))
        finally:
            os.rmdir(test_url)

    def test_dirty(self):
        """Activity.dirty"""
        with Directory(cleanup=True) as directory:
            activity = Activity(directory)
            with self.assertRaises(Exception):
                activity.dirty = False
            self.assertFalse(activity.dirty)
            activity.dirty = True
            self.assertFalse(activity.dirty)
            activity.title = 'new title'
            self.assertFalse(activity.dirty)
            with activity.batch_changes():
                activity.title = 'new 2'
                self.assertTrue(activity.dirty)
            self.assertFalse(activity.dirty)

    def test_activity_list(self):
        """test ActivityList"""
        with Directory(cleanup=True) as directory: # we have no direct access to class ActivityList
            ali = directory.activities
            self.assertEqual(len(ali), 0)
            activity1 = Activity(backend=directory)
            self.assertIn(activity1, ali)
            self.assertIsNone(activity1.id_in_backend)
            activity1.description = 'x'
            self.assertIsNotNone(activity1.id_in_backend)

    def test_clone(self):
        """is the clone identical?"""
        activity1 = self.create_test_activity()
        activity2 = activity1.clone()
        self.assertEqualActivities(activity1, activity2)
        count1 = activity1.gpx.get_track_points_no()
        del activity1.gpx.tracks[0].segments[0].points[0]
        self.assertEqual(count1, activity1.gpx.get_track_points_no() + 1)
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
        self.assertTrue(len(lines) >= activity.gpx.get_track_points_no())

    def test_parse(self):
        """does Activity parse xml correctly"""
        activity = self.create_test_activity()
        activity.keywords = ['Here are some keywords']
        xml = activity.to_xml()
        activity2 = Activity()
        activity2.parse(None)
        activity2.parse('')
        activity2.parse(xml)
        self.assertEqualActivities(activity, activity2)
        self.assertEqual(activity.keywords, activity2.keywords)
        activity2 = Activity()
        activity2.parse(io.StringIO(xml))
        self.assertEqualActivities(activity, activity2)

    def test_combine(self):
        """combine values in activity with newly parsed"""
        # first, does it overwrite?
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
        activity2.what = Activity.legal_what[3]
        activity2.public = False
        activity2.parse(xml)
        self.assertTrue(activity2.public)

        # second, does it keep old values if there are no new values?
        activity = self.create_test_activity()
        activity.title = ''
        activity.description = ''
        xml = activity.to_xml()
        if activity.what == 'Cycling':
            other_what = 'Running'
        else:
            other_what = 'Cycling'

        activity2 = Activity()
        activity2.title = 'Title2'
        activity2.description = 'Description2'
        activity2.parse(xml)
        self.assertEqual(activity2.title, 'Title2')
        self.assertEqual(activity2.description, 'Description2')

    def test_save(self):
        """save locally"""
        with Directory(cleanup=True) as directory:
            os.chmod(directory.url, 0o555)
            activity = self.create_test_activity()
            with self.assertRaises(OSError):
                activity.backend = directory
            self.assertIsNone(activity.backend)
            os.chmod(directory.url, 0o755)
            activity.backend = directory
            self.assertIsNotNone(activity.backend)

        with Directory(cleanup=True) as directory:
            dir2 = self.clone_backend(directory)
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
            trunk = os.path.join(directory.url, 'Random GPX # 0')
            expected_names = list(trunk + x for x in ('.gpx', '.1.gpx', '.2.gpx'))
            files = list(os.path.join(directory.url, x) for x in os.listdir(directory.url) if x.endswith('.gpx'))
            self.assertEqual(files, expected_names)
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
        self.assertEqual(activity.gpx.get_track_points_no(), point_count)
        with self.assertRaises(Exception):
            activity.add_points(points)
        activity.add_points(points[:-1])
        self.assertEqual(activity.gpx.get_track_points_no(), point_count * 2 - 1)

    def test_points_equal(self):
        """test Activity.points_equal"""
        for _ in range(100):
            point_count = 7
            points = self.some_random_points(count=point_count)
            activity1 = Activity()
            activity1.add_points(points)
            activity2 = activity1.clone()
            points2 = list(activity2.all_points()) # those are cloned points
            self.assertTrue(activity1.points_equal(activity2))
            activity2.gpx.tracks.clear()
            activity2.add_points(points2[:5])
            self.assertFalse(activity1.points_equal(activity2))
            activity2.add_points(points2[5:])
            self.assertTrue(activity1.points_equal(activity2))

            old_long = activity2.gpx.tracks[-1].segments[-1].points[-2].longitude
            activity2.gpx.tracks[-1].segments[-1].points[-2].longitude += 1
            self.assertFalse(activity1.points_equal(activity2))
            activity2.gpx.tracks[-1].segments[-1].points[-2].longitude = old_long
            self.assertTrue(activity1.points_equal(activity2))

            old_lat = activity2.gpx.tracks[-1].segments[-1].points[-2].latitude
            activity2.gpx.tracks[-1].segments[-1].points[-2].latitude += 1
            self.assertFalse(activity1.points_equal(activity2))
            activity2.gpx.tracks[-1].segments[-1].points[-2].latitude = old_lat
            self.assertTrue(activity1.points_equal(activity2))

            activity2.gpx.tracks[-1].segments[-1].points[-2].elevation += 1
            self.assertFalse(activity1.points_equal(activity2))
            activity2.gpx.tracks[-1].segments[-1].points[-2].elevation -= 1
            self.assertTrue(activity1.points_equal(activity2), '{} != {}'.format(
                list(activity1.all_points()), list(activity2.all_points())))

            old_long = activity2.gpx.tracks[-1].segments[-1].points[-1].longitude
            activity2.gpx.tracks[-1].segments[-1].points[-1].longitude += 1
            self.assertFalse(activity1.points_equal(activity2))
            a1_points = list(activity1.all_points())
            a2_points = list(activity2.all_points())
            a1_first = a1_points[0]
            a1_last = a1_points[-1]
            a2_first = a2_points[0]
            a2_last = a2_points[-1]
            self.assertNotEqual(
                activity1.angle(), activity2.angle(),
                'a1.first:{} a1.last:{} a2.first:{} a2.last:{}'.format(
                    a1_first, a1_last, a2_first, a2_last))
            activity2.gpx.tracks[-1].segments[-1].points[-1].longitude = old_long
            self.assertTrue(activity1.points_equal(activity2))

    def test_str(self):
        """test __str__"""
        activity = Activity()
        self.assertNotIn('id:', str(activity))
        with Directory(cleanup=True) as directory:
            activity = Activity(directory)
            activity.title = 'Title'
            activity.what = 'Running'
            activity.add_points(self.some_random_points(10))
            self.assertIn('id:', str(activity))
            self.assertIn('Title', str(activity))
            self.assertIn('Running', str(activity))
            self.assertIn(str(activity.time), str(activity))
            self.assertIn(str(activity.last_time()), str(activity))
            self.assertTrue(str(activity).startswith('Activity('))
            self.assertTrue(str(activity).endswith(')'))
            activity.add_points(self.some_random_points(count=5))
            self.assertIn('5 points', str(activity))
            self.assertIn('angle=', str(activity))

    def test_angle(self):
        """test Activity.angle"""
        for _ in range(1000):
            activity1 = Activity()
            activity1.add_points(self.some_random_points(2))
            angle = activity1.angle()
            self.assertLess(angle, 360.001)
            self.assertGreater(angle, -0.001)

        activity1 = Activity()
        activity1.add_points(self.some_random_points(2))
        first_point = None
        for point in activity1.all_points():
            if first_point is None:
                first_point = point
            else:
                point.latitude = first_point.latitude
                point.longitude = first_point.longitude
        self.assertEqual(activity1.angle(), 0)

    def test_key(self):
        """Activity.key()"""
        title = 'This is a niße title'
        description = title + ' NOT - it is the description'
        what = Activity.legal_what[3]
        public = True
        points = self.some_random_points(10)
        activity = Activity()
        activity.title = title
        activity.description = description
        activity.what = what
        activity.public = public
        activity.add_points(points)
        key = activity.key()
        self.assertIn('title:{}'.format(title), key)
        self.assertIn('description:{}'.format(description), key)
        self.assertIn('what:{}'.format(what), key)
        self.assertIn('public:True', key)
        self.assertIn('last_time:{}'.format(activity.last_time()), key)
        self.assertIn('angle:{}'.format(activity.angle()), key)
        self.assertIn('points:{}'.format(activity.gpx.get_track_points_no()), key)

    def test_symlinks(self):
        """Directory symlinks"""
        with Directory(cleanup=True) as directory:
            source = os.path.join(directory.url, 'deadlink')
            target = 'deadtarget'
            target_path = os.path.join(directory.url, target)
            with open(target_path, 'w') as target_file:
                target_file.write(' ')
            os.symlink('deadtarget', source)
            os.remove(target_path)
            with self.assertRaises(Exception):
                directory.list_all() # this loads symlinks
