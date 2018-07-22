# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements :class:`gpxity.backends.test.test_backends.TestBackends` for all backends
"""

import os
import time
import datetime
import random
import tempfile

from unittest import skip

from .basic import BasicTest
from .. import Directory, MMT, GPSIES, ServerDirectory, TrackMMT
from ...auth import Authenticate
from ... import Track

# pylint: disable=attribute-defined-outside-init


class TestBackends(BasicTest):
    """Are the :literal:`supported_` attributes set correctly?"""

    def test_supported(self):
        """Check values in supported for all backends"""
        expect_unsupported = dict()
        expect_unsupported[Directory] = set(['track'])
        expect_unsupported[ServerDirectory] = set(['track'])
        expect_unsupported[MMT] = set()
        expect_unsupported[GPSIES] = set()
        expect_unsupported[TrackMMT] = set([
            'remove', '_write_attribute',
            '_write_title', '_write_description', '_write_public',
            '_write_category', '_write_keyword', '_write_add_keyword',
            '_write_remove_keyword'])
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                self.assertTrue(cls.supported & expect_unsupported[cls] == set())

    def test_save_empty(self):
        """Save empty track"""
        for cls in self._find_backend_classes():
            if cls is TrackMMT:
                # TODO: automatically start expected local server
                continue
            with self.subTest(' {}'.format(cls.__name__)):
                can_remove = 'remove' in cls.supported
                with self.temp_backend(cls, cleanup=can_remove, clear_first=can_remove) as backend:
                    track = Track()
                    if cls in (MMT, TrackMMT, GPSIES):
                        with self.assertRaises(cls.BackendException):
                            backend.add(track)
                    else:
                        self.assertIsNotNone(backend.add(track))

    def test_directory_backend(self):
        """Manipulate backend"""
        track = self.create_test_track()
        with Directory(cleanup=True) as directory1:
            with Directory(cleanup=True) as directory2:
                saved = directory1.add(track)
                self.assertEqual(len(directory1), 1)
                self.assertEqual(saved.backend, directory1)
                directory1.add(track.clone())
                self.assertEqual(len(directory1), 2)
                directory2.add(track)
                self.assertEqual(len(directory2), 1)
                directory2.scan()
                self.assertEqual(len(directory2), 1)

    def test_duplicate_tracks(self):
        """What happens if we save the same track twice?"""
        for cls in self._find_backend_classes():
            if 'remove' in cls.supported:
                with self.subTest(' {}'.format(cls.__name__)):
                    with self.temp_backend(cls) as backend:
                        track = self.create_test_track()
                        backend.add(track)
                        self.assertEqual(len(backend), 1)
                        with self.assertRaises(ValueError):
                            backend.add(track)
                        self.assertEqual(len(backend), 1)
                        if cls is GPSIES:
                            # if the same track data is uploaded again, we get the same id_in_backend.
                            with self.assertRaises(ValueError):
                                backend.add(track.clone())
                            self.assertEqual(len(backend), 1)
                        else:
                            backend.add(track.clone())
                            self.assertEqual(len(backend), 2)

    def test_open_wrong_username(self):
        """Open backends with username missing in auth.cfg"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                with self.assertRaises(KeyError):
                    self.setup_backend(cls, username='wrong')

    def test_open_wrong_password(self):
        """Open backends with wrong password"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                if not issubclass(cls, Directory):
                    with self.assertRaises(cls.BackendException):
                        self.setup_backend(cls, username='wrong_password')

    def test_match(self):
        """test backend match function"""
        def match_date(track):
            """match against a date"""
            if track.time < datetime.datetime(year=2016, month=9, day=5):
                return 'time {} is before {}'.format(track.time, '2016-09-05')
            return None
        for cls in (Directory, ):
            with self.subTest(' {}'.format(cls.__name__)):
                with self.temp_backend(cls, count=3) as backend:
                    for idx, _ in enumerate(backend):
                        _.adjust_time(datetime.timedelta(hours=idx))
                    new_track = backend[0].clone()
                    self.assertIsNotNone(match_date(new_track))
                    self.assertEqual(len(backend), 3)
                    backend.match = match_date
                    self.assertEqual(len(backend), 1)
                    with self.assertRaises(cls.NoMatch):
                        backend.add(new_track)
                    self.assertEqual(len(backend), 1)
                    orig_time = backend[0].time
                    delta = datetime.timedelta(days=-5)
                    with self.assertRaises(cls.NoMatch):
                        backend[0].adjust_time(delta)
                    self.assertEqual(len(backend), 1)
                    self.assertEqual(orig_time + delta, backend[0].time)

    def test_z9_create_backend(self):
        """Test creation of a backend"""
        for cls in self._find_backend_classes():
            if 'remove' in cls.supported and 'get_time' in cls.supported:
                with self.subTest(' {}'.format(cls.__name__)):
                    with self.temp_backend(cls, count=3) as backend:
                        self.assertEqual(len(backend), 3)
                        first_time = backend.get_time()
                        time.sleep(2)
                        second_time = backend.get_time()
                        total_seconds = (second_time - first_time).total_seconds()
                        self.assertTrue(1 < total_seconds < 8, 'Time difference should be {}, is {}-{}={}'.format(
                            2, second_time, first_time, second_time - first_time))

    def test_slow_write_remoteattr(self):
        """If we change title, description, public, category in track, is the backend updated?"""
        for cls in self._find_backend_classes():
            if 'remove' in cls.supported:
                with self.subTest(' {}'.format(cls.__name__)):
                    with self.temp_backend(cls, count=1, category='Horse riding') as backend:
                        track = backend[0]
                        first_public = track.public
                        first_title = track.title
                        first_description = track.description
                        first_category = track.category
                        self.assertEqual(first_category, 'Horse riding')
                        self.assertFalse(track.public)
                        track.public = True
                        self.assertTrue(track.public)
                        track.title = 'A new title'
                        self.assertEqual(track.title, 'A new title')
                        track.description = 'A new description'
                        track.category = 'Cycling'
                        # make sure there is no cache in the way
                        backend2 = self.clone_backend(backend)
                        track2 = backend2[0]
                        self.assertEqualTracks(track, track2)
                        self.assertNotEqual(first_public, track2.public)
                        self.assertNotEqual(first_title, track2.title)
                        self.assertNotEqual(first_description, track2.description)
                        self.assertNotEqual(first_category, track2.category)

    def xtest_gpsies_bug(self):
        """This bug only triggers sometimes: title, category or time will be wrong in track2.
        Workaround is in GPSIES._edit."""
        for _ in range(20):
            with self.temp_backend(GPSIES, count=1, category='Horse riding', debug=True) as backend:
                track = backend[0]
                track.title = 'A new title'
                track.description = 'A new description'
                track.category = 'Cycling'
                # make sure there is no cache in the way
                backend2 = self.clone_backend(backend)
                track2 = backend2[0]
                self.assertEqualTracks(track, track2)

    @skip
    def test_zz_all_category(self):
        """can we up- and download all values for :attr:`Track.category`?"""
        category_count = len(Track.legal_categories)
        backends = list(
            self.setup_backend(x, count=category_count, clear_first=True)
            for x in self._find_backend_classes() if 'remove' in x.supported)
        copies = list(self.clone_backend(x) for x in backends)
        try:
            first_backend = copies[0]
            for other in copies[1:]:
                self.assertSameTracks(first_backend, other)
        finally:
            for backend in copies:
                backend.destroy()
            for backend in backends:
                backend.destroy()

    def test_z2_keywords(self):
        """save and load keywords. For now, all test keywords
        start with uppercase, avoiding MMT problems"""
        kw_a = 'A'
        kw_b = 'Berlin'
        kw_c = 'CamelCase'
        kw_d = 'D' # self.unicode_string2

        for cls in self._find_backend_classes():
            if cls.__name__ == 'TrackMMT':
                continue
            with self.subTest(' {}'.format(cls.__name__)):
                is_mmt = cls.__name__ == 'MMT'
                with self.temp_backend(cls, clear_first=not is_mmt, cleanup=not is_mmt) as backend:
                    if not backend:
                        continue
                    track = backend[0]
                    track.keywords = list()
                    self.assertEqual(track.keywords, list())
                    track.keywords = ([kw_a, kw_b, kw_c])
                    track.remove_keyword(kw_b)
                    self.assertEqual(track.keywords, ([kw_a, kw_c]))
                    with self.assertRaises(Exception):
                        track.add_keyword('Category:whatever')
                    track.add_keyword(kw_d)
                    self.assertEqual(set(track.keywords), set([kw_a, kw_c, kw_d]))
                    backend2 = self.clone_backend(backend)
                    track2 = backend2[track.id_in_backend]
                    track2.remove_keyword(kw_d)
                    self.assertEqual(track2.keywords, ([kw_a, kw_c]))
                    self.assertEqual(track.keywords, ([kw_a, kw_c, kw_d]))
                    backend.scan()
                    self.assertEqual(track.keywords, ([kw_a, kw_c, kw_d]))
                    self.assertEqual(backend[track.id_in_backend].keywords, ([kw_a, kw_c]))
                    track.remove_keyword(kw_a)
                    # this is tricky: The current implementation assumes that track.keywords is
                    # current - which it is not. track still thinks kw_d is there but it has been
                    # removed by somebody else. MMT has a work-around for removing tracks which
                    # removes them all and re-adds all wanted. So we get kw_d back.
                    self.assertEqual(track.keywords, ([kw_c, kw_d]))
                    #track2.remove_keyword(kw_a)
                    track.remove_keyword(kw_c)
                    track.remove_keyword(kw_d)
                    backend.scan()
                    self.assertEqual(backend[0].keywords, list())

    def test_z_unicode(self):
        """Can we up- and download unicode characters in all text attributes?"""
        tstdescr = 'DESCRIPTION with ' + self.unicode_string1 + ' and ' + self.unicode_string2
        for cls in self._find_backend_classes():
            if 'remove' in cls.supported:
                with self.subTest(' {}'.format(cls.__name__)):
                    with self.temp_backend(cls, count=1) as backend:
                        backend2 = self.clone_backend(backend)
                        track = backend[0]
                        self.assertIsNotNone(track.backend)
                        track.title = 'Title ' + self.unicode_string1
                        self.assertIsNotNone(track.backend)
                        self.assertEqual(track.backend, backend)
                        backend2.scan() # because backend2 does not know about changes thru backend
                        track2 = backend2[0]
                        # track and track2 may not be identical. If the original track
                        # contains gpx xml data ignored by MMT, it will not be in track2.
                        self.assertEqual(track.title, track2.title)
                        track.description = tstdescr
                        self.assertEqual(track.description, tstdescr)
                        if cls is Directory:
                            self.assertTrackFileContains(track, tstdescr)
                        backend2.scan()
                        self.assertEqual(backend2[0].description, tstdescr)
                        backend2.destroy()

    def test_change_points(self):
        """Can we change the points of a track?

        For MMT this means re-uploading and removing the previous instance, so this
        is not always as trivial as it should be."""

    def test_slow_download_many(self):
        """Download many tracks"""
        many = 150
        backend = self.setup_backend(MMT, username='gpxstoragemany', count=many, cleanup=False, clear_first=True)
        self.assertEqual(len(backend), many)

    def test_duplicate_title(self):
        """two tracks having the same title"""
        for cls in self._find_backend_classes():
            if 'remove' in cls.supported:
                with self.subTest(' {}'.format(cls.__name__)):
                    with self.temp_backend(cls, count=2) as backend:
                        backend[0].title = 'TITLE'
                        backend[1].title = 'TITLE'

    def test_private(self):
        """Up- and download private tracks"""
        with self.temp_backend(Directory, count=5, category='Cycling') as local:
            track = Track(gpx=self._get_gpx_from_test_file('test2'))
            self.assertTrue(track.public) # as defined in test2.gpx keywords
            track.public = False
            self.assertFalse(track.public)
            local.add(track)
            for cls in self._find_backend_classes():
                if 'remove' in cls.supported:
                    with self.subTest(' {}'.format(cls.__name__)):
                        with self.temp_backend(cls) as backend:
                            backend.merge(local)
                            for _ in backend:
                                self.assertFalse(_.public)
                            backend2 = self.clone_backend(backend)
                            with Directory(cleanup=True) as copy:
                                copy.merge(backend2)
                                self.assertSameTracks(local, copy)

    def test_merge(self):
        """merge backends"""
        with self.temp_backend(Directory, count=5) as source:

            with self.temp_backend(Directory, username='gpxitytest2', count=4) as sink:
                for _ in sink:
                    self.move_times(_, datetime.timedelta(hours=100))
                sink.merge(source)
                # the first track created by temp_backend always has the same points,
                # so one of the sink tracks will be merged
                self.assertEqual(len(source), 5)
                self.assertEqual(len(sink), 8)
                sink.merge(source, remove=True)
                self.assertEqual(len(source), 0)

    def test_scan(self):
        """some tests about Backend.scan()"""
        with self.temp_backend(Directory, count=5) as source:
            backend2 = self.clone_backend(source)
            track = self.create_test_track()
            backend2.add(track)
            self.assertEqual(len(backend2), 6)
            source.scan() # because it cannot know backend2 added something

    def xtest_sync_trackmmt(self):
        """sync from local to MMT. TODO: automatically start the expected local server"""
        with self.temp_backend(Directory, count=5) as source:
            with TrackMMT(auth='test') as sink:
                prev_len = len(sink)
                for _ in sink:
                    self.move_times(_, datetime.timedelta(hours=-random.randrange(10000)))
                sink.merge(source)
                self.assertEqual(len(sink), prev_len + 5)

    def xtest_track(self):
        """test life tracking. TODO: automatically start the expected local server"""
        track = self.create_test_track()
        with TrackMMT(auth='test') as uplink:
            track.lifetrack(uplink, self.some_random_points())
            new_id = track.id_in_backend
            time.sleep(2)
            track.lifetrack(points=self.some_random_points())
            track.lifetrack()
            self.assertIn(new_id, uplink)

    def test_backend_dirty(self):
        """Track._dirty"""
        # pylint: disable=protected-access
        for cls in self._find_backend_classes():
            with self.temp_backend(cls, count=1) as backend:
                track = backend[0]
                with self.assertRaises(Exception):
                    track._dirty = False
                self.assertFalse(track._dirty)
                # version 1.1 should perhaps be a test on its own, see Track.to_xml()
                track._dirty = 'gpx'
                self.assertFalse(track._dirty)
                track.title = 'new title'
                self.assertFalse(track._dirty)
                with track.batch_changes():
                    track.title = 'new 2'
                    self.assertEqual(track._dirty, set(['title']))
                self.assertFalse(track._dirty)
                with track.batch_changes():
                    track.title = 'new 3'
                    track.keywords = ['Eystrup', 'Hello Dolly']
                backend2 = self.clone_backend(backend)
                self.assertEqual(backend2[0].title, 'new 3')

    def test_directory_dirty(self):
        """test gpx._dirty where id_in_backend is not the default. Currently
        track._dirty = 'gpx' changes the file name which is wrong."""
        pass

    def test_directory(self):
        """directory creation/deletion"""
        with self.assertRaises(Exception):
            with Directory('url', prefix='x', cleanup=True):
                pass

        dir_a = Directory(cleanup=True)
        self.assertTrue(dir_a.is_temporary)
        a_url = dir_a.url
        self.assertTrue(os.path.exists(a_url))
        dir_a.destroy()
        self.assertFalse(os.path.exists(a_url))

        test_url = tempfile.mkdtemp() + '/'
        dir_b = Directory(url=test_url, cleanup=True)
        self.assertFalse(dir_b.is_temporary)
        self.assertTrue(dir_b.url == test_url)
        dir_b.destroy()
        self.assertTrue(os.path.exists(test_url))
        os.rmdir(test_url)

        dir_c = Directory(auth='gpxitytest2')
        auth_dir = Authenticate(Directory, 'gpxitytest2').url
        if not auth_dir.endswith('/'):
            auth_dir += '/'
        self.assertFalse(dir_c.is_temporary)
        self.assertNotEqual(dir_c.url, auth_dir)
        dir_c.destroy()
        self.assertTrue(os.path.exists(auth_dir))
        os.rmdir(auth_dir)

    def test_mmt_empty(self):
        """MMT refuses upload without a specific error message if there is no track point"""
        track = self.create_test_track()
        del track.gpx.tracks[0]
        with MMT(auth='gpxitytest', cleanup=True) as mmt:
            with self.assertRaises(mmt.BackendException):
                mmt.add(track)
