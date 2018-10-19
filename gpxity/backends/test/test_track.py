# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for Track.

They only use backend Directory, so there is no network traffic involved
(unless Directory is a network file system, of course).

"""

# pylint: disable=protected-access

import os
import sys
import io
import filecmp
import tempfile
import datetime
import random
from unittest import skipIf

from .basic import BasicTest, disabled
from ... import Track, Backend, Fences
from .. import Directory, ServerDirectory, MMT, GPSIES, Mailer, TrackMMT, WPTrackserver
from ...util import repr_timespan

# pylint: disable=attribute-defined-outside-init


class TrackTests(BasicTest):

    """track tests."""

    @skipIf(*disabled(Directory))
    def test_init(self):
        """test initialisation."""
        track = Track()
        self.assertFalse(track.public)
        with Directory(cleanup=True) as backend:
            track = Track()
            track._set_backend(backend)
            self.assertEqual(len(backend), 0)
            backend.add(track)
            self.assertEqual(len(backend), 1)

        with self.temp_backend(Directory, count=2) as backend:
            backend.add(Track())
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

    @skipIf(*disabled(Directory))
    def test_track_list(self):
        """test list of tracks."""
        with Directory(cleanup=True) as directory:
            self.assertEqual(len(directory), 0)
            track1 = Track()
            directory.add(track1)
            self.assertIn(track1, directory)
            self.assertIsNotNone(track1.id_in_backend)
            track1.description = 'x'
            self.assertIsNotNone(track1.id_in_backend)

    def test_clone(self):
        """True if the clone is identical."""
        track1 = self.create_test_track()
        track2 = track1.clone()
        self.assertEqualTracks(track1, track2)
        count1 = track1.gpx.get_track_points_no()
        del track1.gpx.tracks[0].segments[0].points[0]
        self.assertEqual(count1, track1.gpx.get_track_points_no() + 1)
        self.assertNotEqualTracks(track1, track2)
        track2 = track1.clone()
        track2.gpx.tracks[-1].segments[-1].points[-1].latitude = 5
        self.assertNotEqualTracks(track1, track2)
        track2 = track1.clone()
        track2.gpx.tracks[-1].segments[-1].points[-1].longitude = 5
        self.assertNotEqual(track1, track2)
        track2 = track1.clone()
        last_point2 = track2.gpx.tracks[-1].segments[-1].points[-1]
        last_point2.elevation = 500000
        self.assertEqual(last_point2.elevation, 500000)
        # here assertNotEqualTracks is wrong because keys() are still identical
        self.assertTrue(track1.points_equal(track2))
        track1.gpx.tracks.clear()
        track2.gpx.tracks.clear()
        self.assertEqualTracks(track1, track2)

    def test_no_category(self):
        """category must return default value if not present in gpx.keywords."""
        category_default = Track.legal_categories[0]
        track = Track()
        self.assertEqual(track.category, category_default)
        track.category = None
        self.assertEqual(track.category, category_default)
        with self.assertRaises(Exception):
            track.category = 'illegal value'
        self.assertEqual(track.category, category_default)
        with self.assertRaises(Exception):
            track.change_keywords('Category:illegal value')
        self.assertEqual(track.category, category_default)

    def test_duplicate_category(self):
        """try to add two categories to Track."""
        category_other = Track.legal_categories[5]
        track = Track()
        track.category = category_other
        with self.assertRaises(Exception):
            track.change_keywords('Category:{}'.format(category_other))

    def test_remove_category(self):
        """remove category from Track."""
        category_default = Track.legal_categories[0]
        category_other = Track.legal_categories[5]
        track = Track()
        track.category = category_other
        self.assertEqual(track.category, category_other)
        track.category = None
        self.assertEqual(track.category, category_default)

    def test_no_public(self):
        """public must return False if not present in gpx.keywords."""
        track = Track()
        self.assertFalse(track.public)

    def test_duplicate_public(self):
        """try to set public via its property and additionally with change_keywords."""
        track = Track()
        track.public = True
        self.assertTrue(track.public)
        with self.assertRaises(Exception):
            track.change_keywords('Status:public')

    def test_remove_public(self):
        """remove and add public from Track using remove_keywords and change_keywords."""
        track = Track()
        track.public = True
        with self.assertRaises(Exception):
            track.change_keywords('-Status:public')
        self.assertTrue(track.public)
        with self.assertRaises(Exception):
            track.change_keywords('Status:public')
        self.assertTrue(track.public)

    def test_last_time(self):
        """Track.last_time."""
        track = self.create_test_track()
        gpx_last_time = track.gpx.tracks[-1].segments[-1].points[-1].time
        self.assertEqual(track.last_time, gpx_last_time)

    def test_one_line_per_trkpt(self):
        """One line per trackpoint."""
        track = self.create_test_track()
        xml = track.to_xml()
        self.assertNotIn('<link ></link>', xml)
        lines = xml.split('\n')
        self.logger.debug('xml is:%s', xml)
        start_lines = {x for x in lines if x.strip().startswith('<trkpt')}
        end_lines = {x for x in lines if x.strip().endswith('</trkpt>')}
        have_points = track.gpx.get_track_points_no()
        self.assertEqual(len(start_lines), have_points)
        self.assertEqual(len(end_lines), have_points)
        self.assertEqual(start_lines, end_lines)

    def test_parse(self):
        """check for Track parsing xml correctly."""
        track = self.create_test_track()
        track.keywords = ['Here are some keywords']
        xml = track.to_xml()
        track2 = Track()
        track2.parse(None)
        track2.parse('')
        track2.parse(xml)
        self.assertEqualTracks(track, track2)
        self.assertEqual(track.keywords, track2.keywords)
        track2 = Track()
        track2.parse(io.StringIO(xml))
        self.assertEqualTracks(track, track2)

    def test_combine(self):
        """combine values in track with newly parsed."""
        # first, does it overwrite?
        track = self.create_test_track()
        xml = track.to_xml()
        if track.category == 'Cycling':
            other_category = 'Running'
        else:
            other_category = 'Cycling'

        track2 = Track()
        track2.title = 'Title2'
        track2.description = 'Description2'
        track2.category = other_category
        track2.public = True
        track2.parse(xml)
        self.assertEqual(track2.title, track.title)
        self.assertEqual(track2.description, track.description)
        self.assertEqual(track2.category, track.category)
        self.assertTrue(track2.public)
        self.assertEqual(track2.keywords, list())

        track.public = True
        xml = track2.to_xml()
        self.assertIn('Status:public', xml)
        track2 = Track()
        track2.category = Track.legal_categories[3]
        track2.public = False
        track2.parse(xml)
        self.assertTrue(track2.public)

        # second, does it keep old values if there are no new values?
        track = self.create_test_track()
        track.title = ''
        track.description = ''
        xml = track.to_xml()
        if track.category == 'Cycling':
            other_category = 'Running'
        else:
            other_category = 'Cycling'

        track2 = Track()
        track2.title = 'Title2'
        track2.description = 'Description2'
        track2.parse(xml)
        self.assertEqual(track2.title, 'Title2')
        self.assertEqual(track2.description, 'Description2')

    @skipIf(*disabled(Directory))
    def test_save_dir(self):
        """Correct files?."""
        with Directory(cleanup=True) as directory:
            os.chmod(directory.url, 0o555)
            track = self.create_test_track()
            if os.getuid() == 0:
                # for root, this works even with 555
                directory.add(track)
                self.assertIsNotNone(track.backend)
            else:
                with self.assertRaises(OSError):
                    directory.add(track)
                self.assertIsNone(track.backend)
                os.chmod(directory.url, 0o755)
                directory.add(track)
            self.assertIsNotNone(track.backend)

    @skipIf(*disabled(Directory))
    def test_save(self):
        """save locally."""
        with Directory(cleanup=True) as directory:
            dir2 = directory.clone()
            try:
                track = self.create_test_track()
                directory.add(track)
                self.assertEqual(len(directory), 1)
                aclone = track.clone()
                self.assertEqualTracks(track, aclone)

                self.assertEqual(len(dir2), 1)

                track2 = track.clone()
                self.assertEqualTracks(track, track2)
                directory.add(track2)
                self.assertEqual(len(directory), 2)
                dir2.add(track2)
                self.assertEqual(len(dir2), 2)

                track2_copy = dir2.add(track2.clone())
                self.assertEqualTracks(track, track2_copy)
                self.assertEqualTracks(track2, track2_copy)
                self.assertIs(track.backend, directory)
                self.assertIs(track2.backend, directory)
                self.assertIs(track2_copy.backend, dir2)
                self.assertEqual(len(directory), 2)
                self.assertEqual(len(dir2), 3)
                directory.scan()  # we changed it through dir2
                self.assertEqual(len(directory), 4)
                dir2.scan()
                self.assertEqual(len(directory), 4)
                title = 'whatevertitle'
                for _ in dir2:
                    _.id_in_backend = title
                trunk = os.path.join(directory.url, title)
                expected_names = [trunk + x + '.gpx' for x in ('.1', '.2', '.3', '')]
                files = sorted(
                    os.path.join(directory.url, x)
                    for x in os.listdir(directory.url) if x.endswith('.gpx'))
                self.assertEqual(files, expected_names)
                self.assertEqual(len(dir2), 4)
                directory.scan()
                dir2.merge(directory, remove=True)
                self.assertEqual(len(dir2), 1)
                filecmp.clear_cache()
            finally:
                dir2.destroy()

    def test_add_points(self):
        """test Track.add_points."""
        point_count = 11
        track = Track()
        points = self._random_points(count=point_count)
        track.add_points(points)
        self.assertEqual(track.gpx.get_track_points_no(), point_count)
        with self.assertRaises(Exception):
            track.add_points(points)
        track.add_points(points[:-1])
        self.assertEqual(track.gpx.get_track_points_no(), point_count * 2 - 1)

    def test_points_equal(self):
        """test Track.points_equal."""
        for _ in range(100):
            points = self._random_points(count=7)
            track1 = Track()
            track1.add_points(points)
            track2 = track1.clone()
            points2 = list(track2.points())  # those are cloned points
            self.assertTrue(track1.points_equal(track2))
            track2.gpx.tracks.clear()
            track2.add_points(points2[:5])
            self.assertFalse(track1.points_equal(track2))
            track2.add_points(points2[5:])
            self.assertTrue(track1.points_equal(track2))

            old_long = track2.gpx.tracks[-1].segments[-1].points[-2].longitude
            track2.gpx.tracks[-1].segments[-1].points[-2].longitude += 1
            self.assertFalse(track1.points_equal(track2))
            track2.gpx.tracks[-1].segments[-1].points[-2].longitude = old_long
            self.assertTrue(track1.points_equal(track2))

            old_lat = track2.gpx.tracks[-1].segments[-1].points[-2].latitude
            track2.gpx.tracks[-1].segments[-1].points[-2].latitude += 1
            self.assertFalse(track1.points_equal(track2))
            track2.gpx.tracks[-1].segments[-1].points[-2].latitude = old_lat
            self.assertTrue(track1.points_equal(track2))

            track2.gpx.tracks[-1].segments[-1].points[-2].elevation += 1
            self.assertTrue(track1.points_equal(track2))
            track2.gpx.tracks[-1].segments[-1].points[-2].elevation -= 1

            old_long = track2.gpx.tracks[-1].segments[-1].points[-1].longitude
            track2.gpx.tracks[-1].segments[-1].points[-1].longitude += 1
            self.assertFalse(track1.points_equal(track2))
            a1_points = list(track1.points())
            a2_points = list(track2.points())
            a1_first = a1_points[0]
            a1_last = a1_points[-1]
            a2_first = a2_points[0]
            a2_last = a2_points[-1]
            self.assertNotEqual(
                track1.angle(), track2.angle(),
                'a1.first:{} a1.last:{} a2.first:{} a2.last:{}'.format(
                    a1_first, a1_last, a2_first, a2_last))
            track2.gpx.tracks[-1].segments[-1].points[-1].longitude = old_long
            self.assertTrue(track1.points_equal(track2))

    @skipIf(*disabled(Directory))
    def test_repr(self):
        """test __str__."""
        track = Track()
        self.assertNotIn('id:', str(track))
        with Directory(cleanup=True) as directory:
            track = Track()
            track.title = 'Title'
            track.category = 'Running'
            track.add_points(self._random_points(10))
            self.assertIn('Title', repr(track))
            self.assertIn('public' if track.public else 'private', repr(track))
            self.assertIn('Running', repr(track))
            self.assertIn(repr_timespan(track.time, track.last_time), repr(track))
            self.assertTrue(repr(track).startswith(str(track)))
            self.assertTrue(repr(track).endswith(')'))
            track.add_points(self._random_points(count=5))
            self.assertIn(' 15 points', repr(track))
            directory.add(track)

            # repr(track) must not fully load it
            clone = directory.clone()
            self.assertNotIn(' points', repr(clone[0]))
            self.assertEqual(clone[0].gpx.get_track_points_no(), 15)
            self.assertIn(' 15 points', repr(clone[0]))

    def test_angle(self):
        """test Track.angle."""
        track1 = Track()
        track1.add_points(list())
        self.assertEqual(len(track1.gpx.tracks), 0)
        self.assertEqual(track1.angle(), 0)
        track1.add_points(self._random_points(1))
        del track1.gpx.tracks[0].segments[0]
        self.assertEqual(track1.angle(), 0)
        for _ in range(1000):
            track1 = Track()
            track1.add_points(self._random_points(2))
            angle = track1.angle()
            self.assertLess(angle, 360.001)
            self.assertGreater(angle, -0.001)

        track1 = Track()
        track1.add_points(self._random_points(2))
        first_point = None
        for point in track1.points():
            if first_point is None:
                first_point = point
            else:
                point.latitude = first_point.latitude
                point.longitude = first_point.longitude
        self.assertEqual(track1.angle(), 0)

    def test_key(self):
        """Track.key()."""
        title = 'This is a niße title'
        description = title + ' NOT - it is the description'
        category = Track.legal_categories[3]
        public = True
        points = self._random_points(10)
        track = Track()
        track.title = title
        track.description = description
        track.category = category
        track.public = public
        track.add_points(points)
        key = track.key()
        self.assertIn('title:{}'.format(title), key)
        self.assertIn('description:{}'.format(description), key)
        self.assertIn('category:{}'.format(category), key)
        self.assertIn('public:True', key)
        self.assertIn('last_time:{}'.format(track.last_time), key)
        self.assertIn('angle:{}'.format(track.angle()), key)
        self.assertIn('points:{}'.format(track.gpx.get_track_points_no()), key)

    @skipIf(*disabled(Directory))
    def test_symlinks(self):
        """Directory symlinks."""
        with Directory(cleanup=True) as directory:
            source = os.path.join(directory.url, 'deadlink')
            target = 'deadtarget'
            target_path = os.path.join(directory.url, target)
            with open(target_path, 'w') as target_file:
                target_file.write(' ')
            os.symlink('deadtarget', source)
            os.remove(target_path)
            directory.scan()  # this loads symlinks. It removes the dead link.
            self.assertFalse(os.path.exists(source))

    @skipIf(*disabled(Directory))
    def test_fs_encoding(self):
        """fs_encoding."""
        with self.temp_backend(Directory) as directory:
            track = Track()
            directory.add(track)
            org_ident = track.id_in_backend
            track.title = 'TITLE'
            self.assertEqual(track.id_in_backend, org_ident)
            self.assertEqual(track.title, 'TITLE')
            track.title = 'Tätel'
            self.assertEqual(track.title, 'Tätel')
            for title in ('a/b', '//', 'Ä/Ü', '...'):
                track.title = title
                self.assertEqual(track.title, title)
                self.assertNotEqual(track.id_in_backend, title)
                track.id_in_backend = track.title.replace('/', '_')
                self.assertEqual(track.id_in_backend, title.replace('/', '_'))

        prev_encoding = sys.getfilesystemencoding
        try:
            sys.getfilesystemencoding = lambda: 'wrong'
            with self.assertRaises(Backend.BackendException) as context:
                Directory(cleanup=True)
            expect = (
                'Backend Directory needs a unicode file system encoding,'
                ' .* has wrong. Please change your locale settings.')
            self.assertRegex(str(context.exception), expect, msg='{} != {}'.format(context.exception, expect))
        finally:
            sys.getfilesystemencoding = prev_encoding

    def test_local_keywords(self):
        """Some keyword tests. More see in test_backends."""
        # Category: and Status: are special
        gpx = self._get_gpx_from_test_file('test')
        gpx.keywords = 'Category:Cycling, Status:public'
        track = Track(gpx=gpx)
        self.assertEqual(track.keywords, list())

        # : is legal within a keyword
        gpx.keywords = 'Hello:Dolly'
        track = Track(gpx=gpx)
        self.assertEqual(track.keywords, list(['Hello:Dolly']))

        # keywords are sorted
        gpx.keywords = 'Hello,Dolly'
        track = Track(gpx=gpx)
        self.assertEqual(track.keywords, list(['Dolly', 'Hello']))

        # no comma within a keyword
        with self.assertRaises(Exception):
            track.change_keywords(['Bye,Sam'])

        # keywords as string
        track.change_keywords('Bye,Sam')
        self.assertEqual(track.keywords, ['Bye', 'Dolly', 'Hello', 'Sam'])

    def test_keyword_args(self):
        """'Track.keywords' must accept any variant of iterable."""
        track = Track()
        test_tracks = list(sorted(['a', self.unicode_string2]))
        track.keywords = set(test_tracks)
        self.assertEqual(track.keywords, test_tracks)
        track.keywords = reversed(test_tracks)
        self.assertEqual(track.keywords, test_tracks)
        track.change_keywords(test_tracks[0])
        self.assertEqual(track.keywords, test_tracks)
        track.keywords = test_tracks * 2
        self.assertEqual(track.keywords, test_tracks)

    @skipIf(*disabled(Directory))
    def test_id(self):
        """id_in_backend must be str."""
        with Directory(cleanup=True) as directory:
            track = Track()
            with self.assertRaises(Exception):
                directory.add(track).id_in_backend = 56
            with self.assertRaises(Exception):
                track.id_in_backend = 'a/b'
            self.assertEqual(len(directory), 1)
            with self.assertRaises(ValueError):
                directory.add(track)
            directory.add(track.clone())
            self.assertEqual(len(directory), 2)

    @skipIf(*disabled(Directory))
    def test_in(self):
        """x in backend."""
        with Directory(cleanup=True) as directory:
            track = Track()
            directory.add(track).id_in_backend = '56'
            self.assertEqual(track.id_in_backend, '56')
            self.assertIn(track, directory)
            self.assertIn(track.id_in_backend, directory)
            directory.remove_all()
            self.assertNotIn(track, directory)
            self.assertNotIn(track.id_in_backend, directory)

    @skipIf(*disabled(Directory))
    def test_getitem(self):
        """backend[idx]."""
        with Directory(cleanup=True) as directory:
            directory.scan(now=True)
            track = Track()
            directory.add(track).id_in_backend = '56'
            self.assertIs(directory[0], track)
            self.assertIs(directory[track], track)
            self.assertIs(directory['56'], track)
            directory.remove_all()
            with self.assertRaises(IndexError):
                directory[0]  # pylint: disable=pointless-statement

    def test_adjust_time(self):
        """adjust_time()."""
        track = self.create_test_track()
        first_wp_time = track.gpx.waypoints[0].time
        first_trkpt_time = next(track.points()).time
        seconds10 = datetime.timedelta(seconds=10)
        track.adjust_time(seconds10)
        self.assertEqual(track.gpx.waypoints[0].time, first_wp_time + seconds10)
        self.assertEqual(next(track.points()).time, first_trkpt_time + seconds10)

    def test_overlapping_times(self):
        """Track.overlapping_times(tracks)."""
        now = datetime.datetime.now()
        track1 = self.create_test_track(start_time=now)
        seconds10 = datetime.timedelta(seconds=10)
        track2 = self.create_test_track(start_time=track1.last_time - seconds10)
        track3 = self.create_test_track(start_time=track1.last_time)
        self.assertEqual(track1.last_time - seconds10, track2.time)
        group1 = list([track1, track2, track3])
        track4 = self.create_test_track(start_time=track3.last_time + seconds10)
        group2 = list([track4, track4])
        self.assertEqual(list(Track.overlapping_times(group1 + group2)), list([group1, group2]))
        group2 = list([track4])
        self.assertEqual(list(Track.overlapping_times(group1 + group2)), list([group1]))

    @skipIf(*disabled(Directory))
    def test_header_changes(self):
        """Only change things in _header_data. Assert that the full gpx is loaded before saving."""
        with self.temp_backend(Directory, count=1) as backend:
            backend2 = backend.clone()
            backend2[0].description = 'test'
            self.assertTrackFileContains(backend2[0], '<trk>')
        with self.temp_backend(Directory, count=1) as backend:
            backend2 = Directory(url=backend.url)
            backend2[0].title = 'test title'
            self.assertTrackFileContains(backend2[0], '<trk>')
        with self.temp_backend(Directory, count=1) as backend:
            backend2 = Directory(url=backend.url)
            backend2[0].category = 'Mountain biking'
            self.assertTrackFileContains(backend2[0], '<trk>')

    @skipIf(*disabled(Directory))
    def test_remove_track(self):
        """If a backend has several identical tracks, make sure we remove the right one."""
        with self.temp_backend(Directory, count=1) as backend:
            track = backend[0]
            track_id = track.id_in_backend
            track2 = track.clone()
            backend.add(track2)
            backend.remove(track2)
            self.assertEqual(backend[0].id_in_backend, track_id)

    def test_header_data(self):
        """Test usage of Track._header_data."""
        track = Track()
        gpx_track = self.create_test_track()
        track._header_data['distance'] = 5000
        self.assertEqual(track.distance(), 5000)
        track.parse(gpx_track.to_xml())
        self.assertNotIn('distance', track._header_data)
        self.assertEqual(track.distance(), gpx_track.distance())

    def test_merge_partial_tracks(self):
        """Test Track.merge(partial_tracks=True)."""

        track1 = self.create_test_track()
        track1.title = '44432321'
        track1.keywords = 'KeyA,KeyB,KeyA'
        track2 = track1.clone()
        track2.title = 'Track2-title'
        self.assertTrue(track1.points_equal(track2, digits=9))

        track2.add_points(self._random_points(5))
        msg = track1.merge(track2, partial_tracks=True)
        for _ in msg:
            self.logger.debug(_)
        self.assertEqual(track1.gpx.get_track_points_no(), track2.gpx.get_track_points_no())
        self.assertTrue(track1.points_equal(track2, digits=9))
        self.assertEqual(track1.title, 'Track2-title')

        points2 = track2.point_list()
        points2[2].latitude = 5
        with self.assertRaises(Exception) as context:
            msg = track1.merge(track2, partial_tracks=True)
        self.assertEqual(
            str(context.exception),
            'Cannot merge {} with 27 points into {} with 27 points'.format(track2, track1))

    def test_all_backend_classes(self):
        """Test Backend.all_backend_classes."""
        all_classes = [x.__name__ for x in Backend.all_backend_classes()]
        expected = [Directory, GPSIES, Mailer, ServerDirectory, TrackMMT, WPTrackserver]
        expected = [x.__name__ for x in expected if not x.is_disabled()]
        self.assertEqual(all_classes, expected)

    @skipIf(*disabled(Directory))
    def test_parse_objectname_directory(self):
        """Test Backend.parse_objectname for directory."""
        prefix = Directory.prefix
        subdir = os.path.join(prefix, 'subdir')
        sub2 = os.path.join(subdir, 'sub2')
        sub3 = os.path.join(subdir, 'sub3')
        os.mkdir(subdir)
        os.mkdir(sub2)
        os.mkdir(sub3)
        old_dir = os.getcwd()
        try:
            os.chdir(prefix)
            cases = (('.', 'Directory', '.', None),
                     ('subdir', 'Directory', 'subdir', None),
                     ('directory:', 'Directory', '.', None),
                     ('directory:.', 'Directory', '.', None),
                     ('directory:subdir', 'Directory', 'subdir', None),
                     ('abc', 'Directory', '.', 'abc'),
                     ('subdir/abc', 'Directory', 'subdir', 'abc'),
                     ('subdir/sub2', 'Directory', 'subdir/sub2', None),
                     ('subdir/sub2/sub3/xy', 'Directory', 'subdir/sub2/sub3', 'xy'))
            for string, *expect in cases:
                cls, account, ident = Backend.parse_objectname(string)
                self.assertEqual([cls.__name__, account, ident], expect, 'teststring:{}'.format(string))
        finally:
            os.chdir(old_dir)
            os.rmdir(sub3)
            os.rmdir(sub2)
            os.rmdir(subdir)

    @skipIf(*disabled(ServerDirectory))
    def test_parse_objectname_serverdirectory(self):
        """Test Backend.parse_objectname for serverdirectory."""
        prefix = Directory.prefix
        subdir = os.path.join(prefix, 'subdir')
        sub2 = os.path.join(subdir, 'sub2')
        sub3 = os.path.join(subdir, 'sub3')
        os.mkdir(subdir)
        os.mkdir(sub2)
        os.mkdir(sub3)
        old_dir = os.getcwd()
        try:
            os.chdir(prefix)
            cases = (('serverdirectory:.', 'ServerDirectory', '.', None),
                     ('serverdirectory:', 'ServerDirectory', '.', None),
                     ('serverdirectory:subdir', 'ServerDirectory', 'subdir', None),
                     ('serverdirectory:abc', 'ServerDirectory', '.', 'abc'),
                     ('serverdirectory:subdir/abc', 'ServerDirectory', 'subdir', 'abc'),
                     ('serverdirectory:subdir/sub2', 'ServerDirectory', 'subdir/sub2', None),
                     ('serverdirectory:subdir/sub2/sub3/xy', 'ServerDirectory', 'subdir/sub2/sub3', 'xy'))
            for string, *expect in cases:
                cls, account, ident = Backend.parse_objectname(string)
                self.assertEqual([cls.__name__, account, ident], expect, 'teststring:{}'.format(string))
        finally:
            os.chdir(old_dir)
            os.rmdir(sub3)
            os.rmdir(sub2)
            os.rmdir(subdir)

    @skipIf(*disabled(MMT))
    def test_parse_objectname_mmt(self):
        """Test Backend.parse_objectname for MMT."""
        cases = (('mmt:testlogin', 'MMT', 'testlogin', None),
                 ('mmt:testlogin/345', 'MMT', 'testlogin', '345'))
        for string, *expect in cases:
            cls, account, ident = Backend.parse_objectname(string)
            self.assertEqual([cls.__name__, account, ident], expect, 'teststring:{}'.format(string))

    def test_fences(self):
        """Test fences."""

        # TODO: check auth.cfg parsing

        for illegal in (
                '', 'a/b', '5.4.3/3.0/10', '5.4.3/3/10', '5/6/7/8'
        ):
            with self.assertRaises(Exception, msg='fence "{}" is illegal'.format(illegal)):
                Fences(illegal)
        points = set(self._random_points())
        fences = Fences(" ".join("{}/{}/{}".format(
            x.latitude, x.longitude, 500) for x in random.sample(points, 3)))
        inside = {x for x in points if not fences.outside(x)}
        outside = {x for x in points if fences.outside(x)}
        self.assertEqual(inside | outside, points)
        self.assertEqual(len(inside & outside), 0)
        for point in inside:
            self.assertFalse(fences.outside(point))
        for point in outside:
            self.assertTrue(fences.outside(point))
