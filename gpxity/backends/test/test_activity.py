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
import datetime

from .basic import BasicTest
from ... import Activity
from .. import Directory
from ...util import repr_timespan

# pylint: disable=attribute-defined-outside-init


class ActivityTests(BasicTest):

    """activity tests"""

    def test_init(self):
        """test initialisation"""
        activity = Activity()
        self.assertFalse(activity.public)
        with Directory(cleanup=True) as backend:
            activity = Activity()
            activity._set_backend(backend)  # pylint: disable=protected-access
            self.assertEqual(len(backend), 0)
            backend.add(activity)
            self.assertEqual(len(backend), 1)

        with self.temp_backend(Directory, count=2) as backend:
            backend.add(Activity())
            self.assertEqual(len(backend), 3)

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
        """Activity._dirty"""
        # pylint: disable=protected-access
        with Directory(cleanup=True) as directory:
            activity = Activity()
            directory.add(activity)
            with self.assertRaises(Exception):
                activity._dirty = False
            self.assertFalse(activity._dirty)
            # version 1.1 should perhaps be a test on its own, see Activity.to_xml()
            activity._dirty = 'gpx'
            self.assertFalse(activity._dirty)
            activity.title = 'new title'
            self.assertFalse(activity._dirty)
            with activity.batch_changes():
                activity.title = 'new 2'
                self.assertEqual(activity._dirty, set(['title']))
            self.assertFalse(activity._dirty)
            with Directory(directory.url, cleanup=True) as dir2:
                dir2[0]._dirty = 'gpx'

    def test_activity_list(self):
        """test list of activities"""
        with Directory(cleanup=True) as directory:
            self.assertEqual(len(directory), 0)
            activity1 = Activity()
            directory.add(activity1)
            self.assertIn(activity1, directory)
            self.assertIsNotNone(activity1.id_in_backend)
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
        self.assertTrue(activity1.points_equal(activity2))
        activity1.gpx.tracks.clear()
        activity2.gpx.tracks.clear()
        self.assertEqualActivities(activity1, activity2)

    def test_no_what(self):
        """what must return default value if not present in gpx.keywords"""
        what_default = Activity.legal_whats[0]
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
        what_other = Activity.legal_whats[5]
        activity = Activity()
        activity.what = what_other
        with self.assertRaises(Exception):
            activity.add_keyword('What:{}'.format(what_other))

    def test_remove_what(self):
        """remove what from Activity"""
        what_default = Activity.legal_whats[0]
        what_other = Activity.legal_whats[5]
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

    def test_last_time(self):
        """Activity.last_time"""
        activity = self.create_test_activity()
        gpx_last_time = activity.gpx.tracks[-1].segments[-1].points[-1].time
        self.assertEqual(activity.last_time, gpx_last_time)

    def test_one_line_per_trkpt(self):
        """One line per trackpoint"""
        activity = self.create_test_activity()
        xml = activity.to_xml()
        self.assertNotIn('<link ></link>', xml)
        lines = xml.split('\n')
        start_lines = set(x for x in lines if x.startswith('<trkpt'))
        end_lines = set(x for x in lines if x.endswith('</trkpt>'))
        have_points = activity.gpx.get_track_points_no()
        self.assertEqual(len(start_lines), have_points)
        self.assertEqual(len(end_lines), have_points)
        self.assertEqual(start_lines, end_lines)

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
        activity2.what = Activity.legal_whats[3]
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

    def test_save_dir(self):
        """Correct files?"""
        with Directory(cleanup=True) as directory:
            os.chmod(directory.url, 0o555)
            activity = self.create_test_activity()
            if os.getuid() == 0:
                # for root, this works even with 555
                directory.add(activity)
                self.assertIsNotNone(activity.backend)
            else:
                with self.assertRaises(OSError):
                    directory.add(activity)
                self.assertIsNone(activity.backend)
            os.chmod(directory.url, 0o755)
            directory.add(activity)
            self.assertIsNotNone(activity.backend)

    def test_save(self):
        """save locally"""
        with Directory(cleanup=True) as directory:
            dir2 = self.clone_backend(directory)
            try:
                activity = self.create_test_activity()
                directory.add(activity)
                self.assertEqual(len(directory), 1)
                aclone = activity.clone()
                self.assertEqualActivities(activity, aclone)

                self.assertEqual(len(dir2), 1)

                activity2 = activity.clone()
                self.assertEqualActivities(activity, activity2)
                directory.add(activity2)
                self.assertEqual(len(directory), 2)
                dir2.add(activity2)
                self.assertEqual(len(dir2), 2)

                activity2_copy = dir2.add(activity2)
                self.assertEqualActivities(activity, activity2_copy)
                self.assertEqualActivities(activity2, activity2_copy)
                self.assertIs(activity.backend, directory)
                self.assertIs(activity2.backend, directory)
                self.assertIs(activity2_copy.backend, dir2)
                self.assertEqual(len(directory), 2)
                self.assertEqual(len(dir2), 3)
                directory.scan() # we changed it through dir2
                self.assertEqual(len(directory), 4)
                dir2.scan()
                self.assertEqual(len(directory), 4)
                trunk = os.path.join(directory.url, 'Random GPX # 0')
                expected_names = list(trunk + x + '.gpx' for x in ('.1.1', '.1.2', '.1', ''))
                files = sorted(os.path.join(directory.url, x) for x in os.listdir(directory.url) if x.endswith('.gpx'))
                self.assertEqual(files, expected_names)
                self.assertEqual(len(dir2), 4)
                dir2.merge(directory, remove=True)
                self.assertEqual(len(dir2), 1)
                filecmp.clear_cache()
            finally:
                dir2.destroy()

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
            points2 = list(activity2.points()) # those are cloned points
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
            self.assertTrue(activity1.points_equal(activity2))
            activity2.gpx.tracks[-1].segments[-1].points[-2].elevation -= 1

            old_long = activity2.gpx.tracks[-1].segments[-1].points[-1].longitude
            activity2.gpx.tracks[-1].segments[-1].points[-1].longitude += 1
            self.assertFalse(activity1.points_equal(activity2))
            a1_points = list(activity1.points())
            a2_points = list(activity2.points())
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
            activity = Activity()
            activity.title = 'Title'
            activity.what = 'Running'
            activity.add_points(self.some_random_points(10))
            self.assertIn('Title', str(activity))
            self.assertIn('public' if activity.public else 'private', str(activity))
            self.assertIn('Running', str(activity))
            self.assertIn(repr_timespan(activity.time, activity.last_time), str(activity))
            self.assertTrue(str(activity).startswith('Activity('))
            self.assertTrue(str(activity).endswith(')'))
            activity.add_points(self.some_random_points(count=5))
            self.assertIn(' 15 points', str(activity))
            directory.add(activity)
            self.assertIn('id:', str(activity))

            # str(activity) must not fully load it
            clone = self.clone_backend(directory)
            self.assertIn(' 0 points', str(clone[0]))
            self.assertEqual(clone[0].gpx.get_track_points_no(), 15)
            self.assertIn(' 15 points', str(clone[0]))

    def test_angle(self):
        """test Activity.angle"""
        activity1 = Activity()
        activity1.add_points(list())
        self.assertEqual(len(activity1.gpx.tracks), 0)
        self.assertEqual(activity1.angle(), 0)
        activity1.add_points(self.some_random_points(1))
        del activity1.gpx.tracks[0].segments[0]
        self.assertEqual(activity1.angle(), 0)
        for _ in range(1000):
            activity1 = Activity()
            activity1.add_points(self.some_random_points(2))
            angle = activity1.angle()
            self.assertLess(angle, 360.001)
            self.assertGreater(angle, -0.001)

        activity1 = Activity()
        activity1.add_points(self.some_random_points(2))
        first_point = None
        for point in activity1.points():
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
        what = Activity.legal_whats[3]
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
        self.assertIn('last_time:{}'.format(activity.last_time), key)
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
            directory.scan() # this loads symlinks. It removes the dead link.
            self.assertFalse(os.path.exists(source))

    def test_fs_encoding(self):
        """fs_encoding"""
        with Directory(cleanup=True) as directory:
            activity = Activity()
            directory.add(activity)
            for title in ('TITLE', 'Tätel'):
                activity.title = title
                self.assertEqual(activity.title, title)
                self.assertEqual(activity.id_in_backend, title)
            for title in ('a/b', '//', 'Ä/Ü', '...'):
                activity.title = title
                self.assertEqual(activity.title, title)
                self.assertEqual(activity.id_in_backend, title.replace('/', '_'))
            for title in ('a/b', '//', 'Ä/Ü'):
                activity.title = title
                self.assertEqual(activity.title, title)
                self.assertNotEqual(activity.id_in_backend, title)
            prev_encoding = directory.fs_encoding
            directory.fs_encoding = 'whatever'
            try:
                with self.assertRaises(Exception):
                    activity.title = 'TITLE'
            finally:
                directory.fs_encoding = prev_encoding

    def test_local_keywords(self):
        """Some keyword tests. More see in test_backends"""
        # What: and Status: are special
        gpx = self._get_gpx_from_test_file('test')
        gpx.keywords = 'What:Cycling, Status:public'
        activity = Activity(gpx=gpx)
        self.assertEqual(activity.keywords, list())

        # : is legal within a keyword
        gpx.keywords = 'Hello:Dolly'
        activity = Activity(gpx=gpx)
        self.assertEqual(activity.keywords, list(['Hello:Dolly']))

        # keywords are sorted
        gpx.keywords = 'Hello,Dolly'
        activity = Activity(gpx=gpx)
        self.assertEqual(activity.keywords, list(['Dolly', 'Hello']))

        # no comma within a keyword
        with self.assertRaises(Exception):
            activity.add_keyword('Bye,Sam')


    def test_keyword_args(self):
        """Activity.keywords must accept all types of iterable"""
        activity = Activity()
        test_activities = list(sorted(['a', self.unicode_string2]))
        activity.keywords = set(test_activities)
        self.assertEqual(activity.keywords, test_activities)
        activity.keywords = reversed(test_activities)
        self.assertEqual(activity.keywords, test_activities)
        with self.assertRaises(Exception):
            activity.add_keyword(test_activities[0])
        with self.assertRaises(Exception):
            activity.keywords = test_activities * 2

    def test_id(self):
        """id_in_backend must be str"""
        with Directory(cleanup=True) as directory:
            activity = Activity()
            with self.assertRaises(Exception):
                directory.add(activity, ident=56)
            directory.add(activity, ident='56')
            self.assertEqual(len(directory), 1)

    def test_in(self):
        """x in backend"""
        with Directory(cleanup=True) as directory:
            activity = Activity()
            directory.add(activity, '56')
            self.assertEqual(activity.id_in_backend, '56')
            self.assertIn(activity, directory)
            self.assertIn(activity.id_in_backend, directory)
            directory.remove_all()
            self.assertNotIn(activity, directory)
            self.assertNotIn(activity.id_in_backend, directory)

    def test_getitem(self):
        """backend[idx]"""
        with Directory(cleanup=True) as directory:
            directory.scan(now=True)
            activity = Activity()
            directory.add(activity, '56')
            self.assertIs(directory[0], activity)
            self.assertIs(directory[activity], activity)
            self.assertIs(directory['56'], activity)
            directory.remove_all()
            with self.assertRaises(IndexError):
                directory[0] # pylint: disable=pointless-statement

    def test_adjust_time(self):
        """adjust_time()"""
        activity = self.create_test_activity()
        first_wp_time = activity.gpx.waypoints[0].time
        first_trkpt_time = next(activity.points()).time
        seconds10 = datetime.timedelta(seconds=10)
        activity.adjust_time(seconds10)
        self.assertEqual(activity.gpx.waypoints[0].time, first_wp_time + seconds10)
        self.assertEqual(next(activity.points()).time, first_trkpt_time + seconds10)

    def test_overlapping_times(self):
        """Activity.overlapping_times(activities)"""
        now = datetime.datetime.now()
        activity1 = self.create_test_activity(start_time=now)
        seconds10 = datetime.timedelta(seconds=10)
        activity2 = self.create_test_activity(start_time=activity1.last_time - seconds10)
        activity3 = self.create_test_activity(start_time=activity1.last_time)
        self.assertEqual(activity1.last_time - seconds10, activity2.time)
        group1 = list([activity1, activity2, activity3])
        activity4 = self.create_test_activity(start_time=activity3.last_time + seconds10)
        group2 = list([activity4, activity4])
        self.assertEqual(list(Activity.overlapping_times(group1 + group2)), list([group1, group2]))
        group2 = list([activity4])
        self.assertEqual(list(Activity.overlapping_times(group1 + group2)), list([group1]))
