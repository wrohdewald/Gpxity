# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""implements :class:`gpxity.backends.test.test_backends.TestBackends` for all backends."""

# pylint: disable=protected-access

import os
import time
import datetime
import random
import tempfile

from unittest import skipIf

from .basic import BasicTest, disabled
from .. import Directory, MMT, GPSIES, ServerDirectory, TrackMMT, Mailer, WPTrackserver
from ... import Track, Lifetrack, Backend

# pylint: disable=attribute-defined-outside-init


class TestBackends(BasicTest):

    """Are the :literal:`supported_` attributes set correctly?."""

    def test_supported(self):
        """Check values in supported for all backends."""
        expect_unsupported = dict()
        expect_unsupported[Directory] = {
            'own_categories', 'lifetrack', 'lifetrack_end', 'write_add_keywords', 'write_remove_keywords',
            'write_category', 'write_description', 'write_public', 'write_title'}
        expect_unsupported[ServerDirectory] = {
            'own_categories', 'lifetrack', 'lifetrack_end', 'write_add_keywords', 'write_remove_keywords',
            'write_category', 'write_title', 'write_description', 'write_public'}
        expect_unsupported[MMT] = set()
        expect_unsupported[GPSIES] = {
            'lifetrack', 'lifetrack_end', 'keywords', 'write_add_keywords', 'write_remove_keywords'}
        expect_unsupported[TrackMMT] = {
            'scan', 'remove',
            'write_title', 'write_description', 'write_public',
            'write_category', 'write_add_keywords',
            'write_remove_keywords'}
        expect_unsupported[Mailer] = {
            'own_categories', 'scan', 'remove',
            'write_title', 'write_description', 'write_public',
            'write_category', 'write_add_keywords',
            'write_remove_keywords'}
        expect_unsupported[WPTrackserver] = {
            'lifetrack_end', 'own_categories',
            'write_add_keywords', 'write_remove_keywords', 'write_category',
            'write_description', 'write_public', 'write_title'}
        for cls in Backend.all_backend_classes():
            with self.subTest(cls):
                self.assertTrue(
                    cls.supported & expect_unsupported[cls] == set(),
                    '{}: supported & unsupported: {}'.format(
                        cls.__name__, cls.supported & expect_unsupported[cls]))
                self.assertEqual(
                    sorted(cls.supported | expect_unsupported[cls]),
                    sorted(cls.full_support))

    def test_all_backends(self):
        """Check if Backend.all_backend_classes works."""
        backends = Backend.all_backend_classes()
        expected = [Directory, GPSIES, Mailer, ServerDirectory, TrackMMT, WPTrackserver]
        expected = [x for x in expected if not x.is_disabled()]
        self.assertEqual(backends, expected)

    def test_save_empty(self):
        """Save empty track."""
        for cls in Backend.all_backend_classes(needs={'write'}):
            with self.subTest(cls):
                can_remove = 'remove' in cls.supported
                with self.temp_backend(cls, cleanup=can_remove, clear_first=can_remove) as backend:
                    track = Track()
                    if cls in (MMT, TrackMMT, GPSIES):
                        with self.assertRaises(cls.BackendException):
                            backend.add(track)
                    else:
                        self.assertIsNotNone(backend.add(track))

    @skipIf(*disabled(Directory))
    def test_directory_backend(self):
        """Manipulate backend."""
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

    def test_slow_duplicate_tracks(self):
        """What happens if we save the same track twice?."""
        for cls in Backend.all_backend_classes(needs={'remove', 'write'}):
            with self.subTest(cls):
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
        """Open backends with username missing in auth.cfg."""
        for cls in Backend.all_backend_classes(exclude=[Directory, ServerDirectory]):
            with self.subTest(cls):
                with self.assertRaises(KeyError):
                    self.setup_backend(cls, username='wrong_user')

    def test_open_wrong_password(self):
        """Open backends with wrong password."""
        for cls in Backend.all_backend_classes(needs={'scan'}):
            with self.subTest(cls):
                if not issubclass(cls, Directory):
                    with self.assertRaises(cls.BackendException):
                        self.setup_backend(cls, username='wrong_password')

    @skipIf(*disabled(Directory))
    def test_match(self):
        """test backend match function.

        Returns:
            None

        """
        def match_date(track) ->str:
            """match against a date.

            Returns:
                None if match else an error message
            """
            if track.time < datetime.datetime(year=2016, month=9, day=5):
                return 'time {} is before {}'.format(track.time, '2016-09-05')
            return None
        cls = Directory
        with self.subTest(cls):
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
        """Test creation of a backend."""
        for cls in Backend.all_backend_classes(needs={'remove'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=3) as backend:
                    self.assertEqual(len(backend), 3)
                    first_time = backend.get_time()
                    time.sleep(2)
                    second_time = backend.get_time()
                    total_seconds = (second_time - first_time).total_seconds()
                    self.assertTrue(1 < total_seconds < 8, 'Time difference should be {}, is {}-{}={}'.format(
                        2, second_time, first_time, second_time - first_time))

    def test_slow_write_remoteattr(self):
        """If we change title, description, public, category in track, is the backend updated?."""
        for cls in Backend.all_backend_classes(needs={'remove', }):
            with self.subTest(cls):
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
                    backend2 = backend.clone()
                    track2 = backend2[0]
                    self.assertEqualTracks(track, track2, with_category=False)
                    self.assertNotEqual(first_public, track2.public)
                    self.assertNotEqual(first_title, track2.title)
                    self.assertNotEqual(first_description, track2.description)
                    self.assertNotEqual(first_category, track2.category)

    def xtest_gpsies_bug(self):
        """We have this bug only sometimes: title, category or time will be wrong in track2.
        Workaround is in GPSIES._edit."""
        for _ in range(20):
            with self.temp_backend(GPSIES, count=1, category='Horse riding') as backend:
                track = backend[0]
                track.title = 'A new title'
                track.description = 'A new description'
                track.category = 'Cycling'
                # make sure there is no cache in the way
                backend2 = backend.clone()
                track2 = backend2[0]
                self.assertEqualTracks(track, track2, with_category=True)

    def test_z2_keywords(self):
        """save and load keywords.

        For now, all test keywords start with uppercase, avoiding MMT problems
        """         # noqa hides bug in eric6 style checker

        kw_a = 'A'
        kw_b = 'Berlin'
        kw_c = 'CamelCase'
        kw_d = self.unicode_string2

        def minus(value):
            """

            Returns:
                value preceded with -

            """
            return '-' + value

        for cls in Backend.all_backend_classes(needs={'write', 'scan', 'keywords'}):
            with self.subTest(cls):
                is_mmt = cls.__name__ == 'MMT'
                with self.temp_backend(cls, clear_first=not is_mmt, cleanup=not is_mmt) as backend:
                    if not backend:
                        continue
                    track = backend[0]
                    track.keywords = list()
                    self.assertEqual(track.keywords, list())
                    track.keywords = ([kw_a, kw_b, kw_c])
                    track.change_keywords(minus(kw_b))
                    self.assertEqual(track.keywords, ([kw_a, kw_c]))
                    with self.assertRaises(Exception):
                        track.change_keywords('Category:whatever')
                    track.change_keywords(kw_d)
                    self.assertEqual(set(track.keywords), {kw_a, kw_c, kw_d})
                    backend2 = backend.clone()
                    track2 = backend2[track.id_in_backend]
                    track2.change_keywords(minus(kw_d))
                    self.assertEqual(track2.keywords, ([kw_a, kw_c]))
                    self.assertEqual(track.keywords, ([kw_a, kw_c, kw_d]))
                    backend.scan()
                    self.assertEqual(track.keywords, ([kw_a, kw_c, kw_d]))
                    self.assertEqual(backend[track.id_in_backend].keywords, ([kw_a, kw_c]))
                    track.change_keywords(minus(kw_a))
                    # this is tricky: The current implementation assumes that track.keywords is
                    # current - which it is not. track still thinks kw_d is there but it has been
                    # removed by somebody else. MMT has a work-around for removing tracks which
                    # removes them all and re-adds all wanted. So we get kw_d back.
                    self.assertEqual(track.keywords, ([kw_c, kw_d]))
                    # track2.change_keywords(minus(kw_a))
                    track.change_keywords(minus(kw_c))
                    track.change_keywords(minus(kw_d))
                    backend.scan()
                    self.assertEqual(backend[0].keywords, list())

    def test_z_unicode(self):
        """Can we up- and download unicode characters in all text attributes?."""
        tstdescr = 'DESCRIPTION with ' + self.unicode_string1 + ' and ' + self.unicode_string2
        for cls in Backend.all_backend_classes(needs={'remove'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=1) as backend:
                    backend2 = backend.clone()
                    track = backend[0]
                    self.assertIsNotNone(track.backend)
                    track.title = 'Title ' + self.unicode_string1
                    self.assertIsNotNone(track.backend)
                    self.assertEqual(track.backend, backend)
                    backend2.scan()  # because backend2 does not know about changes thru backend
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
        """Can we change the points of a track?.

        For MMT this means re-uploading and removing the previous instance, so this

        is not always as trivial as it should be."""

    @skipIf(*disabled(MMT))
    def test_slow_download_many(self):
        """Download many tracks."""
        many = 150
        backend = self.setup_backend(MMT, username='gpxstoragemany', count=many, cleanup=False, clear_first=True)
        self.assertEqual(len(backend), many)

    def test_duplicate_title(self):
        """two tracks having the same title."""
        for cls in Backend.all_backend_classes(needs={'remove'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=2) as backend:
                    backend[0].title = 'TITLE'
                    backend[1].title = 'TITLE'

    @skipIf(*disabled(Directory))
    def test_private(self):
        """Up- and download private tracks."""
        with self.temp_backend(Directory, count=5, category='Cycling') as local:
            track = Track(gpx=self._get_gpx_from_test_file('test2'))
            self.assertTrue(track.public)  # as defined in test2.gpx keywords
            track.public = False
            self.assertFalse(track.public)
            local.add(track)
            for cls in Backend.all_backend_classes(needs={'remove'}):
                with self.subTest(cls):
                    with self.temp_backend(cls) as backend:
                        backend.merge(local)
                        for _ in backend:
                            self.assertFalse(_.public)
                        backend2 = backend.clone()
                        with Directory(cleanup=True) as copy:
                            for _ in copy.merge(backend2):
                                self.logger.debug(_)
                            self.assertSameTracks(local, copy, with_last_time=cls is not GPSIES)

    @skipIf(*disabled(Directory))
    def test_merge_backends(self):
        """merge backends."""
        def dump(msg):
            for line in msg:
                self.logger.debug(line)
        org_source_len = 2
        assert org_source_len >= 2
        org_sink_len = 2
        assert org_sink_len >= 2
        with self.temp_backend(Directory, url='source', count=org_source_len) as source:
            with self.temp_backend(Directory, url='sink', count=org_sink_len) as sink:
                for _ in list(sink)[1:]:
                    _.adjust_time(datetime.timedelta(hours=100))

                # let's have two identical tracks in source without match in sink:
                next(source[0].points()).latitude = 6
                source.add(source[0].clone())

                # and two identical tracks in sink without match in source:
                next(sink[1].points()).latitude = 7
                sink.add(sink[1].clone())

                # and one track twice in source and once in sink:
                sink.add(source[0])

                # and one track once in source and once in sink:
                sink.add(source[1])

                self.assertEqual(len(source), org_source_len + 1)
                self.assertEqual(len(sink), org_sink_len + 3)

                dump(sink.merge(source, dry_run=True))
                self.assertEqual(len(source), org_source_len + 1)
                self.assertEqual(len(sink), org_sink_len + 3)

                dump(sink.merge(source))
                self.assertEqual(len(source), org_source_len + 1)
                self.assertEqual(len(sink), org_source_len + org_sink_len + 1)

                for _ in range(2):
                    dump(sink.merge(source, remove=True))
                    self.assertEqual(len(source), 0)
                    self.assertEqual(len(sink), org_source_len + org_sink_len)

    @skipIf(*disabled(Directory))
    def test_scan(self):
        """some tests about Backend.scan()."""
        with self.temp_backend(Directory, count=5) as source:
            backend2 = source.clone()
            track = self.create_test_track()
            backend2.add(track)
            self.assertEqual(len(backend2), 6)
            source.scan()  # because it cannot know backend2 added something

    @skipIf(*disabled(MMT))
    def test_lifetrack_mmt(self):
        """test life tracking against a free account on mapmytracks.com."""
        with MMT(auth='gpxitytest') as uplink:
            self.assertTrue(uplink.is_free_account)
            life = Lifetrack('127.0.0.1', [uplink])
            with self.assertRaises(Exception) as context:
                life.start(self._random_points())
            self.assertEqual(str(context.exception), 'Your free MMT account does not allow lifetracking')

    @skipIf(*disabled(Directory))
    def test_lifetrack_local(self):
        """test life tracking against a local server."""
        def track():
            life = Lifetrack('127.0.0.1', [local_serverdirectory, uplink])
            points = self._random_points(100)
            life.start(points[:50])
            time.sleep(7)
            life.update(points[50:])
            life.end()

        for cls in Backend.all_backend_classes(needs={'lifetrack'}):
            with self.subTest(cls):
                with self.temp_backend(ServerDirectory) as local_serverdirectory:
                    with self.temp_backend(ServerDirectory) as remote_serverdirectory:
                        with self.lifetrackserver(remote_serverdirectory.url):
                            with self.temp_backend(cls) as uplink:
                                track()
                                local_serverdirectory.scan()
                                if cls is TrackMMT:
                                    remote_serverdirectory.scan()
                                    self.assertSameTracks(local_serverdirectory, remote_serverdirectory)
                                elif cls is Mailer:
                                    self.assertEqual(
                                        len(uplink.history), 3,
                                        'Mailer.history: {}'.format(uplink.history))
                                    self.assertIn('Lifetracking starts', uplink.history[0])
                                    self.assertIn('Lifetracking continues', uplink.history[1])
                                    self.assertIn('Lifetracking ends', uplink.history[2])
                                else:
                                    uplink.scan()
                                    self.assertSameTracks(local_serverdirectory, uplink)

    def test_backend_dirty(self):
        """Track._dirty."""
        for cls in Backend.all_backend_classes(needs={'scan', 'write'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=1) as backend:
                    track = backend[0]
                    with self.assertRaises(Exception):
                        track._dirty = False
                    self.assertFalse(track._dirty)
                    # version 1.1 should perhaps be a test on its own, see Track.to_xml()
                    track.category = 'Driving'
                    track._dirty = 'gpx'
                    self.assertFalse(track._dirty)
                    backend2 = backend.clone()
                    self.assertEqual(backend2[0].category, 'Driving')
                    b2track = backend2[0]
                    self.assertEqual(b2track.category, 'Driving')
                    b2track.title = 'another new title'
                    self.assertEqual(b2track.category, 'Driving')
                    self.assertEqual(backend2[0].category, 'Driving')
                    track.title = 'new title'
                    self.assertEqual(track.category, 'Driving')
                    backend3 = backend.clone()
                    self.assertEqual(backend3[0].category, 'Driving')
                    self.assertFalse(track._dirty)
                    with track.batch_changes():
                        track.title = 'new 2'
                        self.assertEqual(track._dirty, ['title'])
                    self.assertFalse(track._dirty)
                    with track.batch_changes():
                        track.title = 'new 3'
                        track.keywords = ['Something', 'something xlse']
                    backend4 = backend.clone()
                    self.assertEqual(backend4[0].title, 'new 3')

    def test_directory_dirty(self):
        """test gpx._dirty where id_in_backend is not the default.

        Currently track._dirty = 'gpx' changes the file name which is wrong."""

    @skipIf(*disabled(Directory))
    def test_directory(self):
        """directory creation/deletion."""

        dir_a = Directory(cleanup=True)
        self.assertTrue(dir_a.is_temporary)
        a_url = dir_a.url
        self.assertTrue(os.path.exists(a_url))
        dir_a.destroy()
        self.assertFalse(os.path.exists(a_url))

        test_url = tempfile.mkdtemp()
        dir_b = Directory(url=test_url, cleanup=True)
        self.assertFalse(dir_b.is_temporary)
        self.assertTrue(dir_b.url == test_url)
        dir_b.destroy()
        self.assertTrue(os.path.exists(test_url))
        os.rmdir(test_url)

        dir_c = Directory(auth='gpxitytest')
        self.assertTrue(dir_c.is_temporary)

        self.assertIn('/gpxity.TestBackends.test_directory_', dir_c.url)
        dir_c.destroy()

    @skipIf(*disabled(MMT))
    def test_mmt_empty(self):
        """MMT refuses upload without a specific error message if there is no track point."""
        track = self.create_test_track()
        del track.gpx.tracks[0]
        with MMT(auth='gpxitytest', cleanup=True) as mmt:
            with self.assertRaises(mmt.BackendException):
                mmt.add(track)

    def test_setters(self):
        """For all Track attributes with setters, test if we can change them without changing something else."""
        for cls in Backend.all_backend_classes(needs={'write', 'scan'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=1) as backend:
                    track = backend[0]
                    backend2 = backend.clone()
                    self.assertEqualTracks(track, backend2[0], with_category=False)
                    test_values = {
                        'title': ('default title', 'Täst Titel'),
                        'description': ('default description', 'Täst description'),
                        'category': ('Driving', 'Rowing'), 'public': (True, False)}
                    if cls is not GPSIES:
                        test_values['keywords'] = (['A', 'Hello Dolly', 'Whatever'], ['Something Else', 'Two'])
                    for main in test_values:
                        for key, (default_value, _) in test_values.items():
                            if key != main:
                                setattr(track, key, default_value)
                        setattr(track, main, test_values[main][1])
                        backend2.scan()
                        for key, (default_value, _) in test_values.items():
                            if key != main:
                                self.assertEqual(getattr(backend2[0], key), default_value)
                        self.assertEqual(getattr(backend2[0], main), test_values[main][1])

    def test_keywords(self) ->None:
        """Test arbitrary keyword changes.

        Returns:
            None

        """
        for cls in Backend.all_backend_classes(needs={'scan', 'keywords'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=1) as backend:
                    backend2 = backend.clone()
                    track = backend[0]
                    keywords = {
                        backend._encode_keyword(x)
                        for x in self._random_keywords(count=50)}
                    for _ in range(20):
                        self.assertEqual(backend._get_current_keywords(track), track.keywords)
                        add_keywords = set(random.sample(keywords, random.randint(0, 10)))
                        remove_keywords = set(random.sample(keywords, random.randint(0, 10)))
                        if not add_keywords & remove_keywords:
                            continue
                        expected_keywords = (set(track.keywords) | add_keywords) - remove_keywords
                        track.change_keywords(list(add_keywords) * 2)
                        self.assertEqual(
                            backend._get_current_keywords(track),
                            sorted(list(set(track.keywords) | add_keywords)))
                        track.change_keywords('-' + x for x in remove_keywords)
                        self.assertEqual(backend._get_current_keywords(track), sorted(expected_keywords))
                        self.assertEqual(sorted(expected_keywords), sorted(track.keywords))
                        backend2.scan()
                        self.assertEqual(sorted(expected_keywords), backend2[0].keywords)
                    with track.batch_changes():
                        # WPTrackserver has limited field lengths
                        loops, kwcount = (5, 5) if cls is WPTrackserver else (50, 10)
                        for _ in range(loops):
                            add_keywords = set(random.sample(keywords, random.randint(0, kwcount)))
                            remove_keywords = set(random.sample(keywords, random.randint(0, kwcount))) & add_keywords
                            if not add_keywords & remove_keywords:
                                continue
                            expected_keywords = (set(track.keywords) | add_keywords) - remove_keywords
                            track.change_keywords(add_keywords)
                            track.change_keywords('-' + x for x in remove_keywords)
                            self.assertEqual(sorted(expected_keywords), sorted(track.keywords))
                    backend2.scan()
                    self.assertEqual(
                        backend2._get_current_keywords(backend2[0]),
                        backend2[0].keywords)
                    self.assertEqual(sorted(expected_keywords), backend2[0].keywords)

    def test_legal_categories(self):
        """Check if our fixed list of categories still matches the online service."""

        def check():
            """check this backend."""
            downloaded = backend._download_legal_categories()
            self.assertEqual(sorted(backend.legal_categories), downloaded)

        for cls in Backend.all_backend_classes(needs={'own_categories'}):
            if cls is TrackMMT and Directory.is_disabled():
                continue
            with self.subTest(cls):
                with self.temp_backend(cls, clear_first=False, cleanup=False) as backend:
                    if cls is TrackMMT:
                        with self.temp_backend(Directory) as serverdirectory:
                            with self.lifetrackserver(serverdirectory.url):
                                check()
                    else:
                        check()

    def test_long_description(self):
        """Test long descriptions."""
        unlimited_length = 50000  # use this if the backend sets no limit
        for cls in Backend.all_backend_classes(needs={'scan'}):
            with self.subTest(cls):
                with self.temp_backend(cls, count=1) as backend:
                    track = backend[0]
                    max_length = backend._max_length.get('description') or unlimited_length
                    # a backend may encode keywords in description
                    max_descr_length = max_length - (len(backend._encode_description(track)) - len(track.description))
                    track.description = ('long description' * 4000)[:max_descr_length]
                    self.assertEqual(len(backend._encode_description(track)), max_length)
                    clone = backend.clone()[0]
                    self.assertEqual(track.description, clone.description)
                    if max_length < unlimited_length:
                        try_description = 'long description' * 4000
                        encoded = backend._encode_description(track)
                        decoded = backend._decode_description(track, encoded)
                        self.assertEqual(len(encoded), max_length)
                        self.assertTrue(try_description.startswith(decoded))

    def test_no_auth(self):
        """Some backends must fail if given no login data."""
        for cls in Backend.all_backend_classes(needs={'scan'}):
            if not cls.needs_config:
                continue
            for _ in ({'username': 'gpxitytest', 'password': ''}, {'username': ''}, {}, {'password': 'test'}):
                with self.assertRaises(Backend.BackendException) as context:
                    with self.temp_backend(cls, username=_):
                        pass
                self.assertEqual(str(context.exception), '{}: Needs authentication data'.format(cls.default_url))
