# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for GpxFile.

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

from gpxpy import gpx as mod_gpx

from .basic import BasicTest, disabled
from ... import GpxFile, Backend, Account, DirectoryAccount
from ...backend_base import BackendBase
from ...gpx import Gpx
from .. import Directory, MMT, GPSIES, Mailer, TrackMMT, WPTrackserver
from .. import Openrunner
from ...util import repr_timespan, positions_equal, remove_directory

# pylint: disable=attribute-defined-outside-init

GPXTrackPoint = mod_gpx.GPXTrackPoint


class TrackTests(BasicTest):

    """gpxfile tests."""

    @skipIf(*disabled(Directory))
    def test_init(self):
        """test initialisation."""
        gpxfile = GpxFile()
        self.assertFalse(gpxfile.public)
        with self.temp_backend(Directory) as backend:
            gpxfile = GpxFile()
            gpxfile._set_backend(backend)
            self.assertEqual(len(backend), 0)
            backend.add(gpxfile)
            self.assertEqual(len(backend), 1)

        with self.temp_backend(Directory, count=2) as backend:
            backend.add(GpxFile())
            self.assertEqual(len(backend), 3)

        test_url = tempfile.mkdtemp(prefix=DirectoryAccount.prefix)
        self.assertTrue(os.path.exists(test_url))
        remove_directory(test_url)
        self.assertFalse(os.path.exists(test_url))
        try:
            with self.temp_backend(Directory, url=test_url):
                self.assertTrue(os.path.exists(test_url))
        finally:
            remove_directory(test_url)

    @skipIf(*disabled(Directory))
    def test_track_list(self):
        """test list of gpxfiles."""
        with self.temp_backend(Directory) as directory:
            self.assertEqual(len(directory), 0)
            gpxfile1 = GpxFile()
            directory.add(gpxfile1)
            self.assertIn(gpxfile1, directory)
            self.assertIsNotNone(gpxfile1.id_in_backend)
            gpxfile1.description = 'x'
            self.assertIsNotNone(gpxfile1.id_in_backend)

    def test_clone(self):
        """True if the clone is identical."""
        gpxfile1 = self.create_test_track()
        gpxfile2 = gpxfile1.clone()
        self.assertEqualTracks(gpxfile1, gpxfile2)
        count1 = gpxfile1.gpx.get_track_points_no()
        del gpxfile1.gpx.tracks[0].segments[0].points[0]
        self.assertEqual(count1, gpxfile1.gpx.get_track_points_no() + 1)
        self.assertNotEqualTracks(gpxfile1, gpxfile2)
        gpxfile2 = gpxfile1.clone()
        gpxfile2.gpx.tracks[-1].segments[-1].points[-1].latitude = 5
        self.assertNotEqualTracks(gpxfile1, gpxfile2)
        gpxfile2 = gpxfile1.clone()
        gpxfile2.gpx.tracks[-1].segments[-1].points[-1].longitude = 5
        self.assertNotEqual(gpxfile1, gpxfile2)
        gpxfile2 = gpxfile1.clone()
        last_point2 = gpxfile2.gpx.tracks[-1].segments[-1].points[-1]
        last_point2.elevation = 500000
        self.assertEqual(last_point2.elevation, 500000)
        # here assertNotEqualTracks is wrong because keys() are still identical
        self.assertTrue(gpxfile1.points_equal(gpxfile2))
        gpxfile1.gpx.tracks.clear()
        gpxfile2.gpx.tracks.clear()
        self.assertEqualTracks(gpxfile1, gpxfile2)

    def test_no_category(self):
        """category must return default value if not present in gpx.keywords."""
        category_default = GpxFile.categories[0]
        gpxfile = GpxFile()
        self.assertEqual(gpxfile.category, category_default)
        gpxfile.category = None
        self.assertEqual(gpxfile.category, category_default)
        with self.assertRaises(Exception):
            gpxfile.category = 'illegal value'
        self.assertEqual(gpxfile.category, category_default)
        with self.assertRaises(Exception):
            gpxfile.change_keywords('Category:illegal value')
        self.assertEqual(gpxfile.category, category_default)

    def test_duplicate_category(self):
        """try to add two categories to GpxFile."""
        category_other = GpxFile.categories[5]
        gpxfile = GpxFile()
        gpxfile.category = category_other
        with self.assertRaises(Exception):
            gpxfile.change_keywords('Category:{}'.format(category_other))

    def test_remove_category(self):
        """remove category from GpxFile."""
        category_default = GpxFile.categories[0]
        category_other = GpxFile.categories[5]
        gpxfile = GpxFile()
        gpxfile.category = category_other
        self.assertEqual(gpxfile.category, category_other)
        gpxfile.category = None
        self.assertEqual(gpxfile.category, category_default)

    def test_no_public(self):
        """public must return False if not present in gpx.keywords."""
        gpxfile = GpxFile()
        self.assertFalse(gpxfile.public)

    def test_duplicate_public(self):
        """try to set public via its property and additionally with change_keywords."""
        gpxfile = GpxFile()
        gpxfile.public = True
        self.assertTrue(gpxfile.public)
        with self.assertRaises(Exception):
            gpxfile.change_keywords('Status:public')

    def test_remove_public(self):
        """remove and add public from GpxFile using remove_keywords and change_keywords."""
        gpxfile = GpxFile()
        gpxfile.public = True
        with self.assertRaises(Exception):
            gpxfile.change_keywords('-Status:public')
        self.assertTrue(gpxfile.public)
        with self.assertRaises(Exception):
            gpxfile.change_keywords('Status:public')
        self.assertTrue(gpxfile.public)

    def test_last_time(self):
        """GpxFile.last_time."""
        gpxfile = self.create_test_track()
        gpx_last_time = gpxfile.gpx.tracks[-1].segments[-1].points[-1].time
        self.assertEqual(gpxfile.last_time, gpx_last_time)

    def test_one_line_per_trkpt(self):
        """One line per trackpoint."""
        gpxfile = self.create_test_track()
        xml = gpxfile.xml()
        self.assertNotIn('<link ></link>', xml)
        lines = xml.split('\n')
        self.logger.debug('xml is:%s', xml)
        start_lines = {x for x in lines if x.strip().startswith('<trkpt')}
        end_lines = {x for x in lines if x.strip().endswith('</trkpt>')}
        have_points = gpxfile.gpx.get_track_points_no()
        self.assertEqual(len(start_lines), have_points)
        self.assertEqual(len(end_lines), have_points)
        self.assertEqual(start_lines, end_lines)

    def test_parse(self):
        """check for GpxFile parsing xml correctly."""
        gpxfile = self.create_test_track()
        gpxfile.keywords = ['Here are some keywords']
        xml = gpxfile.xml()
        gpx = Gpx.parse(xml)
        gpxfile2 = GpxFile()
        gpxfile2.gpx = gpx
        self.assertEqualTracks(gpxfile, gpxfile2)
        self.assertEqual(gpxfile.keywords, gpxfile2.keywords)
        gpxfile2 = GpxFile()
        gpxfile2.gpx = Gpx.parse(io.StringIO(xml))
        self.assertEqualTracks(gpxfile, gpxfile2)

    def test_combine(self):
        """combine values in gpxfile with newly parsed."""
        # Here, category is always from the domain GpxFile.category, no backend involved.
        # first, does it overwrite?
        gpxfile = self.create_test_track()
        self.assertFalse(gpxfile.public)
        xml = gpxfile.xml()
        self.assertIn('Status:private', xml)
        track_category = gpxfile.category
        if track_category == 'Cycling':
            other_category = 'Running'
        else:
            other_category = 'Cycling'
        gpxfile2 = GpxFile()
        gpxfile2.title = 'Title2'
        gpxfile2.description = 'Description2'
        gpxfile2.category = other_category
        gpxfile2.public = True
        gpxfile2.gpx = Gpx.parse(xml)
        self.assertEqual(gpxfile2.title, gpxfile.title)
        self.assertEqual(gpxfile2.description, gpxfile.description)
        self.assertEqual(gpxfile2.category, gpxfile.category)
        self.assertFalse(gpxfile2.public)
        self.assertEqual(gpxfile2.keywords, list())

        gpxfile.public = True
        xml = gpxfile2.xml()
        self.assertIn('Status:private', xml)
        gpxfile2 = GpxFile()
        gpxfile2.category = GpxFile.categories[3]
        self.assertEqual(gpxfile2.gpx.keywords, 'Category:{}, Status:private'.format(GpxFile.categories[3]))
        gpxfile2.public = True
        self.assertEqual(gpxfile2.gpx.keywords, 'Category:{}, Status:public'.format(GpxFile.categories[3]))
        gpxfile2.gpx = Gpx.parse(xml)
        self.assertFalse(gpxfile2.public)

        # second, does it keep old values if there are no new values?
        gpxfile = self.create_test_track()
        gpxfile.title = ''
        gpxfile.description = 'xx'
        xml = gpxfile.xml()
        if gpxfile.category == 'Cycling':
            other_category = 'Running'
        else:
            other_category = 'Cycling'

        gpxfile2 = GpxFile()
        gpxfile2.title = 'Title2'
        gpxfile2.description = 'Description2'
        self.assertIn('<desc>Description2</desc>', gpxfile2.xml())
        gpxfile2.gpx = Gpx.parse(xml)
        self.assertEqual(gpxfile2.title, '')
        self.assertEqual(gpxfile2.description, 'xx')

    @skipIf(*disabled(Directory))
    def test_save_dir(self):
        """Correct files?."""
        with self.temp_backend(Directory) as directory:
            os.chmod(directory.url, 0o555)
            gpxfile = self.create_test_track()
            if os.getuid() == 0:
                # for root, this works even with 555
                directory.add(gpxfile)
                self.assertIsNotNone(gpxfile.backend)
            else:
                with self.assertRaises(OSError):
                    directory.add(gpxfile)
                self.assertIsNone(gpxfile.backend)
                os.chmod(directory.url, 0o755)
                directory.add(gpxfile)
            self.assertIsNotNone(gpxfile.backend)

    @skipIf(*disabled(Directory))
    def test_save(self):
        """save locally."""
        with self.temp_backend(Directory) as directory:
            dir2 = directory.clone()
            try:
                gpxfile = self.create_test_track()
                directory.add(gpxfile)
                self.assertEqual(len(directory), 1)
                aclone = gpxfile.clone()
                self.assertEqualTracks(gpxfile, aclone)

                self.assertEqual(len(dir2), 1)

                gpxfile2 = gpxfile.clone()
                self.assertEqualTracks(gpxfile, gpxfile2)
                directory.add(gpxfile2)
                self.assertEqual(len(directory), 2)
                dir2.add(gpxfile2)
                self.assertEqual(len(dir2), 2)

                track2_copy = dir2.add(gpxfile2.clone())
                self.assertEqualTracks(gpxfile, track2_copy)
                self.assertEqualTracks(gpxfile2, track2_copy)
                self.assertIs(gpxfile.backend, directory)
                self.assertIs(gpxfile2.backend, directory)
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
                dir2.detach()

    def test_add_points(self):
        """test GpxFile.add_points."""
        point_count = 11
        gpxfile = GpxFile()
        points = self._random_points(count=point_count)
        gpxfile.add_points(points)
        self.assertEqual(gpxfile.gpx.get_track_points_no(), point_count)
        with self.assertRaises(Exception):
            gpxfile.add_points(points)
        gpxfile.add_points(points[:-1])
        self.assertEqual(gpxfile.gpx.get_track_points_no(), point_count * 2 - 1)

    def test_points_equal(self):
        """test GpxFile.points_equal."""
        for _ in range(100):
            points = self._random_points(count=7)
            gpxfile1 = GpxFile()
            gpxfile1.add_points(points)
            gpxfile2 = gpxfile1.clone()
            points2 = list(gpxfile2.points())  # those are cloned points
            self.assertTrue(gpxfile1.points_equal(gpxfile2))
            gpxfile2.gpx.tracks.clear()
            gpxfile2.add_points(points2[:5])
            self.assertFalse(gpxfile1.points_equal(gpxfile2))
            gpxfile2.add_points(points2[5:])
            self.assertTrue(gpxfile1.points_equal(gpxfile2))

            old_long = gpxfile2.gpx.tracks[-1].segments[-1].points[-2].longitude
            gpxfile2.gpx.tracks[-1].segments[-1].points[-2].longitude += 1
            self.assertFalse(gpxfile1.points_equal(gpxfile2))
            gpxfile2.gpx.tracks[-1].segments[-1].points[-2].longitude = old_long
            self.assertTrue(gpxfile1.points_equal(gpxfile2))

            old_lat = gpxfile2.gpx.tracks[-1].segments[-1].points[-2].latitude
            gpxfile2.gpx.tracks[-1].segments[-1].points[-2].latitude += 1
            self.assertFalse(gpxfile1.points_equal(gpxfile2))
            gpxfile2.gpx.tracks[-1].segments[-1].points[-2].latitude = old_lat
            self.assertTrue(gpxfile1.points_equal(gpxfile2))

            gpxfile2.gpx.tracks[-1].segments[-1].points[-2].elevation += 1
            self.assertTrue(gpxfile1.points_equal(gpxfile2))
            gpxfile2.gpx.tracks[-1].segments[-1].points[-2].elevation -= 1

            old_long = gpxfile2.gpx.tracks[-1].segments[-1].points[-1].longitude
            gpxfile2.gpx.tracks[-1].segments[-1].points[-1].longitude += 1
            self.assertFalse(gpxfile1.points_equal(gpxfile2))
            a1_points = list(gpxfile1.points())
            a2_points = list(gpxfile2.points())
            a1_first = a1_points[0]
            a1_last = a1_points[-1]
            a2_first = a2_points[0]
            a2_last = a2_points[-1]
            self.assertNotEqual(
                gpxfile1.angle(), gpxfile2.angle(),
                'a1.first:{} a1.last:{} a2.first:{} a2.last:{}'.format(
                    a1_first, a1_last, a2_first, a2_last))
            gpxfile2.gpx.tracks[-1].segments[-1].points[-1].longitude = old_long
            self.assertTrue(gpxfile1.points_equal(gpxfile2))

    @skipIf(*disabled(Directory))
    def test_repr(self):
        """test __str__."""
        gpxfile = GpxFile()
        self.assertNotIn('id:', str(gpxfile))
        with self.temp_backend(Directory) as directory:
            gpxfile = GpxFile()
            gpxfile.title = 'Title'
            gpxfile.category = 'Running'
            gpxfile.add_points(self._random_points(10))
            first_distance = gpxfile.distance
            self.assertIn('public' if gpxfile.public else 'private', repr(gpxfile))
            self.assertIn('Running', repr(gpxfile))
            self.assertIn(repr_timespan(gpxfile.first_time, gpxfile.last_time), repr(gpxfile))
            self.assertTrue(repr(gpxfile).startswith(str(gpxfile)))
            self.assertTrue(repr(gpxfile).endswith(')'))
            gpxfile.add_points(self._random_points(count=5, root=gpxfile.last_point()))
            self.assertGreater(gpxfile.distance, first_distance)
            self.assertIn('km', repr(gpxfile))
            directory.add(gpxfile)

            # repr(gpxfile) must not fully load it
            clone = directory.clone()
            self.assertNotIn(' points', repr(clone[0]))
            self.assertEqual(clone[0].gpx.get_track_points_no(), 15)
            self.assertIn('km', repr(clone[0]))
            self.assertEqual(gpxfile.category, 'Running')
            self.assertEqual(clone[0].category, 'Running')

    def test_angle(self):
        """test GpxFile.angle."""
        gpxfile1 = GpxFile()
        gpxfile1.add_points(list())
        self.assertEqual(len(gpxfile1.gpx.tracks), 0)
        self.assertEqual(gpxfile1.angle(), 0)
        gpxfile1.add_points(self._random_points(1))
        del gpxfile1.gpx.tracks[0].segments[0]
        self.assertEqual(gpxfile1.angle(), 0)
        for _ in range(1000):
            gpxfile1 = GpxFile()
            gpxfile1.add_points(self._random_points(2))
            angle = gpxfile1.angle()
            self.assertLess(angle, 360.001)
            self.assertGreater(angle, -0.001)

        gpxfile1 = GpxFile()
        gpxfile1.add_points(self._random_points(2))
        first_point = None
        for point in gpxfile1.points():
            if first_point is None:
                first_point = point
            else:
                point.latitude = first_point.latitude
                point.longitude = first_point.longitude
        self.assertEqual(gpxfile1.angle(), 0)

    def test_key(self):
        """GpxFile.key()."""
        title = 'This is a niße title'
        description = title + ' NOT - it is the description'
        category = GpxFile.categories[3]
        public = True
        points = self._random_points(10)
        gpxfile = GpxFile()
        gpxfile.title = title
        gpxfile.description = description
        gpxfile.category = category
        gpxfile.public = public
        gpxfile.add_points(points)
        key = gpxfile.key()
        self.assertIn('title:{}'.format(title), key)
        self.assertIn('description:{}'.format(description), key)
        self.assertIn('category:{}'.format(category), key)
        self.assertIn('public:True', key)
        self.assertIn('last_time:{}'.format(gpxfile.last_time), key)
        self.assertIn('angle:{}'.format(gpxfile.angle()), key)
        self.assertIn('points:{}'.format(gpxfile.gpx.get_track_points_no()), key)

    @skipIf(*disabled(Directory))
    def test_symlinks(self):
        """Directory symlinks."""
        with self.temp_backend(Directory) as directory:
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
            gpxfile = GpxFile()
            directory.add(gpxfile)
            org_ident = gpxfile.id_in_backend
            gpxfile.title = 'TITLE'
            self.assertEqual(gpxfile.id_in_backend, org_ident)
            self.assertEqual(gpxfile.title, 'TITLE')
            gpxfile.title = 'Tätel'
            self.assertEqual(gpxfile.title, 'Tätel')
            for title in ('a/b', '//', 'Ä/Ü', '...'):
                gpxfile.title = title
                self.assertEqual(gpxfile.title, title)
                self.assertNotEqual(gpxfile.id_in_backend, title)
                gpxfile.id_in_backend = gpxfile.title.replace('/', '_')
                self.assertEqual(gpxfile.id_in_backend, title.replace('/', '_'))

        prev_encoding = sys.getfilesystemencoding
        try:
            sys.getfilesystemencoding = lambda: 'wrong'
            with self.assertRaises(Backend.BackendException) as context:
                with self.temp_backend(Directory):
                    pass
            expect = (
                'Backend Directory needs a unicode file system encoding,'
                ' .* has wrong. Please change your locale settings.')
            self.assertRegex(str(context.exception), expect, msg='{} != {}'.format(context.exception, expect))
        finally:
            sys.getfilesystemencoding = prev_encoding

    def test_local_keywords(self):
        """Some keyword tests. More see in test_backends."""
        # Category: and Status: are special
        gpx = self._get_track_from_test_file('test').gpx
        gpx.keywords = 'Category:Cycling, Status:public'
        gpxfile = GpxFile(gpx=gpx)
        self.assertEqual(gpxfile.keywords, list())

        # : is legal within a keyword
        gpx.keywords = 'Hello:Dolly'
        gpxfile = GpxFile(gpx=gpx)
        self.assertEqual(gpxfile.keywords, list(['Hello:Dolly']))

        # keywords are sorted
        gpx.keywords = 'Hello,Dolly'
        gpxfile = GpxFile(gpx=gpx)
        self.assertEqual(gpxfile.keywords, list(['Dolly', 'Hello']))

        # no comma within a keyword
        with self.assertRaises(Exception):
            gpxfile.change_keywords(['Bye,Sam'])

        # keywords as string
        gpxfile.change_keywords('Bye,Sam')
        self.assertEqual(gpxfile.keywords, ['Bye', 'Dolly', 'Hello', 'Sam'])

    def test_keyword_args(self):
        """'GpxFile.keywords' must accept any variant of iterable."""
        gpxfile = GpxFile()
        test_keywords = list(sorted(['a', self.unicode_string2]))
        gpxfile.keywords = set(test_keywords)
        self.assertEqual(gpxfile.keywords, test_keywords)
        gpxfile.keywords = reversed(test_keywords)
        self.assertEqual(gpxfile.keywords, test_keywords)
        gpxfile.change_keywords(test_keywords[0])
        self.assertEqual(gpxfile.keywords, test_keywords)
        gpxfile.keywords = test_keywords * 2
        self.assertEqual(gpxfile.keywords, test_keywords)

    @skipIf(*disabled(Directory))
    def test_in(self):
        """x in backend."""
        with self.temp_backend(Directory) as directory:
            gpxfile = GpxFile()
            directory.add(gpxfile).id_in_backend = '56'
            self.assertEqual(gpxfile.id_in_backend, '56')
            self.assertIn(gpxfile, directory)
            self.assertIn(gpxfile.id_in_backend, directory)
            directory.remove_all()
            self.assertNotIn(gpxfile, directory)
            self.assertNotIn(gpxfile.id_in_backend, directory)

    @skipIf(*disabled(Directory))
    def test_getitem(self):
        """backend[idx]."""
        with self.temp_backend(Directory) as directory:
            directory.scan(now=True)
            gpxfile = GpxFile()
            directory.add(gpxfile).id_in_backend = '56'
            self.assertIs(directory[0], gpxfile)
            self.assertIs(directory[gpxfile], gpxfile)
            self.assertIs(directory['56'], gpxfile)
            directory.remove_all()
            with self.assertRaises(IndexError):
                directory[0]  # pylint: disable=pointless-statement

    def test_adjust_time(self):
        """adjust_time()."""
        gpxfile = self.create_test_track()
        first_wp_time = gpxfile.gpx.waypoints[0].time
        first_trkpt_time = next(gpxfile.points()).time
        seconds10 = datetime.timedelta(seconds=10)
        gpxfile.adjust_time(seconds10)
        self.assertEqual(gpxfile.gpx.waypoints[0].time, first_wp_time + seconds10)
        self.assertEqual(next(gpxfile.points()).time, first_trkpt_time + seconds10)

    def test_overlapping_times(self):
        """GpxFile.overlapping_times(gpxfiles)."""
        now = datetime.datetime.now()
        gpxfile1 = self.create_test_track(start_time=now)
        seconds10 = datetime.timedelta(seconds=10)
        gpxfile2 = self.create_test_track(start_time=gpxfile1.last_time - seconds10)
        gpxfile3 = self.create_test_track(start_time=gpxfile1.last_time)
        self.assertEqual(gpxfile1.last_time - seconds10, gpxfile2.first_time)
        group1 = list([gpxfile1, gpxfile2, gpxfile3])
        gpxfile4 = self.create_test_track(start_time=gpxfile3.last_time + seconds10)
        group2 = list([gpxfile4, gpxfile4])
        self.assertEqual(list(GpxFile.overlapping_times(group1 + group2)), list([group1, group2]))
        group2 = list([gpxfile4])
        self.assertEqual(list(GpxFile.overlapping_times(group1 + group2)), list([group1]))

    @skipIf(*disabled(Directory))
    def test_header_changes(self):
        """Change fields loaded by gpxfile scan, before _load_full() is done."""
        with self.temp_backend(Directory, count=1) as backend:
            backend2 = backend.clone()
            backend2[0].description = 'test'
            self.assertTrackFileContains(backend2[0], '<trk>')
        with self.temp_backend(Directory, count=1) as backend:
            backend2 = Directory(DirectoryAccount(backend.url))
            backend2[0].title = 'test title'
            self.assertTrackFileContains(backend2[0], '<trk>')
        with self.temp_backend(Directory, count=1) as backend:
            backend2 = Directory(DirectoryAccount(backend.url))
            backend2[0].category = backend2.supported_categories[2]
            self.assertTrackFileContains(backend2[0], '<trk>')

    @skipIf(*disabled(Directory))
    def test_remove_track(self):
        """If a backend has several identical gpxfiles, make sure we remove the right one."""
        with self.temp_backend(Directory, count=1) as backend:
            gpxfile = backend[0]
            track_id = gpxfile.id_in_backend
            gpxfile2 = gpxfile.clone()
            backend.add(gpxfile2)
            backend.remove(gpxfile2)
            self.assertEqual(backend[0].id_in_backend, track_id)

    def test_header_data(self):
        """Test usage of GpxFile._header_data."""
        # TODO: still needed?
        gpxfile = GpxFile()
        gpx_track = self.create_test_track()
        gpxfile.distance = 5000
        self.assertEqual(gpxfile.distance, 5000)
        gpxfile.gpx = Gpx.parse(gpx_track.xml())
        self.assertEqual(gpxfile.distance, gpx_track.distance)

    @skipIf(*disabled(WPTrackserver))
    def test_merge_track(self):
        """Check if everything is correctly merged."""
        gpxfile1 = self.create_test_track()
        gpxfile1.title = '44432321'
        gpxfile1.keywords = 'KeyA,KeyB,KeyA'
        gpxfile1.ids = ['wptrackserver_unittest:5', '/tmp/x.gpx']
        gpxfile2 = gpxfile1.clone()
        gpxfile2.title = 'Track2-title'
        gpxfile2.ids = ['wptrackserver_unittest:5', 'wptrackserver_unittest:6', 'tmp/y.gpx']
        msg = gpxfile1.merge(gpxfile2, partial=True)
        for _ in msg:
            self.logger.debug(_)
        self.assertEqual(gpxfile1.gpx.get_track_points_no(), gpxfile2.gpx.get_track_points_no())
        self.assertTrue(gpxfile1.points_equal(gpxfile2, digits=9))
        self.assertEqual(gpxfile1.title, 'Track2-title')
        self.assertEqual(
            gpxfile1.ids,
            ['wptrackserver_unittest:5', '/tmp/x.gpx', 'wptrackserver_unittest:6', 'tmp/y.gpx'])

    def test_merge_partial_tracks(self):
        """Test GpxFile.merge(partial=True)."""

        gpxfile1 = self.create_test_track()
        gpxfile1.title = '44432321'
        gpxfile1.keywords = 'KeyA,KeyB,KeyA'
        gpxfile2 = gpxfile1.clone()
        gpxfile2.title = 'Track2-title'
        self.assertTrue(gpxfile1.points_equal(gpxfile2, digits=9))

        gpxfile2.add_points(self._random_points(5, root=gpxfile1.last_point()))
        msg = gpxfile1.merge(gpxfile2, partial=True)
        for _ in msg:
            self.logger.debug(_)
        self.assertEqual(gpxfile1.gpx.get_track_points_no(), gpxfile2.gpx.get_track_points_no())
        self.assertTrue(gpxfile1.points_equal(gpxfile2, digits=9))
        self.assertEqual(gpxfile1.title, 'Track2-title')

        points2 = gpxfile2.point_list()
        points2[2].latitude = 5
        with self.assertRaises(Exception) as context:
            msg = gpxfile1.merge(gpxfile2, partial=True)
        self.assertEqual(
            str(context.exception),
            'Cannot merge {} with 27 points into {} with 27 points'.format(gpxfile2, gpxfile1))

    def test_all_backend_classes(self):
        """Test Backend.all_backend_classes."""
        all_classes = [x.__name__ for x in Backend.all_backend_classes()]
        expected = [Directory, GPSIES, MMT, Mailer, Openrunner, TrackMMT, WPTrackserver]
        expected = [x.__name__ for x in expected if not x.is_disabled()]
        self.assertEqual(all_classes, expected)

    def parse_objectnames(self, cases):
        """Helper for test_parse_objectname."""
        for string, expect_account_str, expect_backend, expect_ident in cases:
            account, track_id = BackendBase.parse_objectname(string)
            self.assertEqual(
                str(account), expect_account_str, 'str(account) wrong in test case:{}'.format(string))
            self.assertEqual(
                account.backend, expect_backend, 'backend wrong in test case:{}'.format(string))
            self.assertEqual(
                track_id, expect_ident, 'track_id wrong in test case:{}'.format(string))

    @skipIf(*disabled(Directory))
    def test_parse_objectname_directory(self):
        """Test Backend.parse_objectname for directory."""
        save = os.getenv('HOME'), os.getcwd()
        try:
            prefix = DirectoryAccount.prefix
            abs_prefix = os.path.abspath(prefix)
            os.chdir(prefix)
            test_home = os.path.abspath('subdir')
            os.environ['HOME'] = test_home  # for ~ in pathname
            cases = (
                ('.', '', 'Directory', None),
                ('subdir', 'subdir/', 'Directory', None),
                ('abc', '', 'Directory', 'abc'),
                ('subdir/abc', 'subdir/', 'Directory', 'abc'),
                ('subdir/sub2', 'subdir/sub2/', 'Directory', None),
                ('subdir/sub2/sub3/xy', 'subdir/sub2/sub3/', 'Directory', 'xy'),
                ('~/sub2', os.path.join(abs_prefix, 'subdir/sub2/'), 'Directory', None),
                ('~/sub2/sub3/xy', os.path.join(abs_prefix, 'subdir/sub2/sub3/'), 'Directory', 'xy'),
                ('missing_dir/24', 'missing_dir/', 'Directory', '24'),
                ('wptrackserver_unittest', 'wptrackserver_unittest/', 'Directory', None),
                ('wptrackserver_unittest/24', 'wptrackserver_unittest/', 'Directory', '24'),
                (os.path.join(test_home, 'sub2/sub3/xy'), os.path.join(test_home, 'sub2/sub3/'), 'Directory', 'xy'),
            )

            subdirs = list()
            subdirs.append(os.path.join(prefix, 'subdir'))
            subdirs.append(os.path.join(subdirs[0], 'sub2'))
            subdirs.append(os.path.join(subdirs[1], 'sub3'))
            subdirs.append(os.path.join(prefix, 'wptrackserver_unittest'))
            try:
                for _ in subdirs:
                    os.mkdir(_)
                self.parse_objectnames(cases)
            finally:
                for _ in reversed(subdirs):
                    remove_directory(_)
        finally:
            os.environ['HOME'] = save[0]
            os.chdir(save[1])

    def test_parse_objectname_other(self):
        """Test Backend.parse_objectname for other than Directory."""
        for cls in Backend.all_backend_classes():
            if cls is Directory:
                continue
            acc_name = cls.__name__.lower() + '_unittest'
            cases = (
                (acc_name + ':', acc_name + ':', cls.__name__, None),
                (acc_name + ':24', acc_name + ':', cls.__name__, '24'),
            )
            self.parse_objectnames(cases)
            break

    def test_fences(self):
        """Test fences."""

        # TODO: check accounts parsing

        for illegal in (
                '', 'a/b', '5.4.3/3.0/10', '5.4.3/3/10', '5/6/7/8'
        ):
            with self.assertRaises(ValueError, msg='fence "{}" is illegal'.format(illegal)):
                account = Account(fences=illegal)

        points = set(self._random_points())
        with self.temp_backend(Directory) as directory:
            accounts = (
                directory.account,
                DirectoryAccount('.', fences=None),
                Account(fences=' '.join("{}/{}/{}".format(
                    x.latitude, x.longitude, 500) for x in random.sample(points, 3))),
            )
            for account in accounts:
                fences = account.fences
                inside = {x for x in points if not fences.outside(x)}
                outside = {x for x in points if fences.outside(x)}
                self.assertEqual(inside | outside, points)
                self.assertEqual(len(inside & outside), 0)
                for point in inside:
                    self.assertFalse(fences.outside(point))
                for point in outside:
                    self.assertTrue(fences.outside(point))

    def test_openrunner_point_encoding(self):
        """Test Openrunner encoding/decoding of points."""
        for gpxfile, result in [
                ([(50.0, 7.0), (60.0, 8.0)], True),
                ([(-50.1, -7.2), (0.1, 8.4)], True),
                ([(-50.12, -7.23), (0.12, 8.45)], True),
                ([(-50.124, -7.234), (0.125, 8.458)], True),
                ([(-50.1041, -7.2354), (0.1325, 8.7458)], True),
                ([(-50.10341, -7.23554), (0.13325, 8.7458)], True),
                ([(-50.109341, -7.203554), (0.133425, 8.74258)], False),
        ]:
            points = [GPXTrackPoint(latitude=lat, longitude=lon) for lat, lon in gpxfile]
            enc_dec = Openrunner._decode_points(Openrunner._encode_points(points))
            self.assertEqual(
                result,
                all(positions_equal(*x, digits=10) for x in zip(points, enc_dec)), gpxfile)  # noqa
