# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
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
from .. import Memory, Directory, MMT, GPSIES, TrackMMT, Mailer, WPTrackserver, Openrunner
from ... import GpxFile, Lifetrack, Backend, Account, MemoryAccount, DirectoryAccount, Fences
from ...util import remove_directory

# pylint: disable=attribute-defined-outside-init


class TestBackends(BasicTest):

    """Are the :literal:`supported_` attributes set correctly?."""

    def test_supported(self):
        """Check values in supported for all backends."""
        expect_unsupported = dict()
        expect_unsupported[Directory] = {
            'own_categories', 'write_add_keywords', 'write_remove_keywords',
            'write_category', 'write_description', 'write_public', 'write_title'}
        expect_unsupported[MMT] = {
            'rename', }
        expect_unsupported[GPSIES] = {
            'keywords', 'write_add_keywords', 'write_remove_keywords', 'rename'}
        expect_unsupported[TrackMMT] = {
            'scan', 'remove', 'rename',
            'write_title', 'write_description', 'write_public',
            'write_category', 'write_add_keywords',
            'write_remove_keywords'}
        expect_unsupported[Mailer] = {
            'own_categories', 'scan', 'remove', 'rename',
            'write_title', 'write_description', 'write_public',
            'write_category', 'write_add_keywords',
            'write_remove_keywords'}
        expect_unsupported[Openrunner] = {
            'write_title', 'write_description', 'write_public',
            'write_category', 'write_add_keywords', 'rename',
            'write_remove_keywords'}
        expect_unsupported[WPTrackserver] = {
            'own_categories',
            'write_add_keywords', 'write_remove_keywords', 'write_category',
            'write_description', 'write_public', 'write_title'}
        expect_unsupported[Memory] = {
            'own_categories',
            'write_add_keywords', 'write_remove_keywords', 'write_category',
            'write_description', 'write_public', 'write_title'}
        for cls in Backend.all_backend_classes():
            with self.tst_backend(cls):
                self.assertTrue(
                    cls.supported & expect_unsupported[cls] == set(),
                    '{}: supported & unsupported: {}'.format(
                        cls.__name__, cls.supported & expect_unsupported[cls]))
                self.assertEqual(
                    sorted(cls.supported | expect_unsupported[cls]),
                    sorted(cls.full_support),
                    '{}.supported is wrong'.format(cls.__name__))

    def test_all_backends(self):
        """Check if Backend.all_backend_classes works."""
        backends = Backend.all_backend_classes()
        expected = [Directory, GPSIES, MMT, Mailer, Memory, Openrunner, TrackMMT, WPTrackserver]
        expected = [x for x in expected if not x.is_disabled()]
        self.assertEqual(backends, expected)

    def test_account_none(self):
        """Test access with Account=None."""
        for cls in Backend.all_backend_classes():
            with self.tst_backend(cls):
                if cls is Memory:
                    backend = cls(MemoryAccount())
                elif cls is Directory:
                    backend = cls(DirectoryAccount())
                else:
                    backend = cls(Account())
                if cls in (GPSIES, MMT, Openrunner):
                    with self.assertRaises(backend.BackendException) as context:
                        backend.scan(now=True)
                    self.assertEqual(str(context.exception), '{} needs a username'.format(backend.url))

    def test_subscription(self):
        """Test backend.subscription."""
        for cls in Backend.all_backend_classes():
            with self.tst_backend(cls):
                with self.temp_backend(cls) as backend:
                    if cls in (MMT, Openrunner):
                        self.assertEqual(backend.subscription, 'free')
                    elif cls == TrackMMT:
                        self.assertEqual(backend.subscription, 'full')
                    else:
                        self.assertIsNone(backend.subscription)

    def test_save_empty(self):
        """Save empty gpxfile."""
        for cls in Backend.all_backend_classes(needs={'write'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls) as backend:
                    gpxfile = GpxFile()
                    if backend.accepts_zero_points:
                        self.assertIsNotNone(backend.add(gpxfile))
                    else:
                        with self.assertRaises(cls.BackendException):
                            backend.add(gpxfile)

    @skipIf(*disabled(Directory))
    def test_rewrite_empty(self):
        """Remove all points and rewrite a gpxfile."""

        def check(cls):
            """The real check."""
            backend.add(gpxfile)
            gpxfile.gpx.tracks[0].segments[0].points = list()
            if backend.accepts_zero_points:
                gpxfile.rewrite()
            else:
                with self.assertRaises(cls.BackendException):
                    gpxfile.rewrite()

        for cls in Backend.all_backend_classes(needs={'write'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls) as backend:
                    gpxfile = GpxFile()
                    # some backends may refuse tracks without title right away
                    # gpsies even refuses fuzzy titles
                    gpxfile.title = 'Hamburg Berlin test writing empty tracks'
                    gpxfile.add_points(self._random_points(count=20))
                    if cls is TrackMMT:
                        with self.temp_directory() as serverdirectory:
                            serverdirectory.account.config['id_method'] = 'counter'
                            with self.lifetrackserver(serverdirectory.url):
                                check(cls)
                    else:
                        check(cls)

    @skipIf(*disabled(Directory))
    def test_directory_backend(self):
        """Manipulate backend."""
        gpxfile = self.create_test_track()
        with self.temp_directory() as directory1:
            with self.temp_directory() as directory2:
                saved = directory1.add(gpxfile)
                self.assertBackendLength(directory1, 1)
                self.assertEqual(saved.backend, directory1)
                directory1.add(gpxfile.clone())
                self.assertBackendLength(directory1, 2)
                directory2.add(gpxfile)
                self.assertBackendLength(directory2, 1)
                directory2.scan()
                self.assertBackendLength(directory2, 1)

    def test_duplicate_gpxfiles(self):
        """What happens if we save the same gpxfile twice?."""
        for cls in Backend.all_backend_classes(needs={'remove', 'write'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls) as backend:
                    gpxfile = self.create_test_track(cls)
                    backend.add(gpxfile)
                    self.assertBackendLength(backend, 1)
                    with self.assertRaises(ValueError):
                        backend.add(gpxfile)
                    self.assertBackendLength(backend, 1)
                    if cls is GPSIES:
                        # if the same gpxfile data is uploaded again, we get the same id_in_backend.
                        with self.assertRaises(ValueError):
                            backend.add(gpxfile.clone())
                        self.assertBackendLength(backend, 1)
                    else:
                        backend.add(gpxfile.clone())
                        self.assertBackendLength(backend, 2)

    def test_open_wrong_username(self):
        """Open backends with username missing in Account."""
        for cls in Backend.all_backend_classes(exclude=[Memory, Directory, Mailer, TrackMMT, Openrunner]):
            # Openrunner allows arbitrary user names
            with self.tst_backend(cls):
                with self.assertRaises(cls.BackendException):
                    self.setup_backend(cls, test_name='wrong_username').scan(now=True)

    def test_open_wrong_password(self):
        """Open backends with wrong password."""
        for cls in Backend.all_backend_classes(needs={'scan'}, exclude=[Directory, Memory]):
            with self.tst_backend(cls):
                with self.assertRaises(cls.BackendException):
                    self.setup_backend(cls, test_name='wrong_password').scan(now=True)

    @skipIf(*disabled(Directory))
    def test_match(self):
        """test backend match function.

        Returns:
            None

        """
        def match_date(gpxfile) ->str:
            """match against a date.

            Returns:
                None if match else an error message
            """
            if gpxfile.first_time < datetime.datetime(year=2016, month=9, day=5, tzinfo=datetime.timezone.utc):
                return 'time {} is before {}'.format(gpxfile.first_time, '2016-09-05')
            return None

        cls = Directory
        with self.tst_backend(cls):
            with self.temp_backend(cls, count=3) as backend:
                for idx, _ in enumerate(backend):
                    _.adjust_time(datetime.timedelta(hours=4 + idx))
                new_gpxfile = backend[0].clone()
                self.assertIsNotNone(match_date(new_gpxfile))
                self.assertBackendLength(backend, 3)
                backend.match = match_date
                self.assertBackendLength(backend, 1)
                with self.assertRaises(cls.NoMatch):
                    backend.add(new_gpxfile)
                self.assertBackendLength(backend, 1)
                orig_time = backend[0].first_time
                delta = datetime.timedelta(days=-5)
                with self.assertRaises(cls.NoMatch):
                    backend[0].adjust_time(delta)
                self.assertBackendLength(backend, 1)
                self.assertEqual(orig_time + delta, backend[0].first_time)

    def test_z9_create_backend(self):
        """Test creation of a backend."""
        for cls in Backend.all_backend_classes(needs={'remove'}):
            if not cls.test_is_expensive:
                with self.tst_backend(cls):
                    with self.temp_backend(cls, count=3) as backend:
                        self.assertBackendLength(backend, 3)
                        first_time = backend.get_time()
                        time.sleep(2)
                        second_time = backend.get_time()
                        total_seconds = (second_time - first_time).total_seconds()
                        self.assertTrue(1 < total_seconds < 8, 'Time difference should be {}, is {}-{}={}'.format(
                            2, second_time, first_time, second_time - first_time))

    def test_write_remoteattr(self):
        """If we change title, description, public, category in gpxfile, is the backend updated?."""
        for cls in Backend.all_backend_classes(needs={'remove', }):
            with self.tst_backend(cls):
                with self.temp_backend(cls, count=1) as backend:
                    gpxfile = backend[0]
                    first_title = gpxfile.title
                    first_description = gpxfile.description
                    gpxfile.title = 'A new title'
                    self.assertEqual(gpxfile.title, 'A new title')
                    gpxfile.description = 'A new description'
                    # make sure there is no cache in the way
                    backend2 = backend.clone()
                    gpxfile2 = backend2[0]
                    self.assertEqualTracks(gpxfile, gpxfile2)
                    self.assertNotEqual(first_title, gpxfile2.title)
                    self.assertNotEqual(first_description, gpxfile2.description)

    def test_write_category(self):
        """If we change category in gpxfile, is the backend updated?."""
        for cls in Backend.all_backend_classes(needs={'remove', }):
            with self.tst_backend(cls):
                test_category = cls.decode_category(cls.supported_categories[10])
                test_category2 = cls.decode_category(cls.supported_categories[15])
                with self.temp_backend(cls, count=1, category=test_category) as backend:
                    gpxfile = backend[0]
                    self.assertEqual(gpxfile.category, test_category)
                    gpxfile.category = test_category2
                    # make sure there is no cache in the way
                    backend2 = backend.clone()
                    gpxfile2 = backend2[0]
                    self.assertEqualTracks(gpxfile, gpxfile2, 'category should be {}'.format(test_category2))
                    self.assertEqual(gpxfile2.category, test_category2, 'category should be {}'.format(test_category2))

    def test_write_public(self):
        """If we change public in gpxfile, is the backend updated?."""
        for cls in Backend.all_backend_classes(needs={'remove', }):
            with self.tst_backend(cls):
                test_public = True
                test_public2 = False
                with self.temp_backend(cls, count=1, public=test_public) as backend:
                    gpxfile = backend[0]
                    orig_cat = gpxfile.category
                    self.assertEqual(gpxfile.public, test_public)
                    gpxfile.public = test_public2
                    self.assertEqual(gpxfile.category, orig_cat)
                    # make sure there is no cache in the way
                    backend2 = backend.clone()
                    gpxfile2 = backend2[0]
                    self.assertEqual(gpxfile2.category, orig_cat)
                    self.assertEqualTracks(gpxfile, gpxfile2)
                    self.assertEqual(gpxfile2.public, test_public2)

    def xtest_gpsies_bug(self):
        """We have this bug only sometimes: title, category or time will be wrong in gpxfile2.
        Workaround is in GPSIES._edit."""
        for _ in range(20):
            with self.temp_backend(GPSIES, count=1, category=GPSIES.supported_categories[3]) as backend:
                gpxfile = backend[0]
                gpxfile.title = 'A new title'
                gpxfile.description = 'A new description'
                gpxfile.category = backend.decode_category(backend.supported_categories[8])
                # make sure there is no cache in the way
                backend2 = backend.clone()
                gpxfile2 = backend2[0]
                self.assertEqualTracks(gpxfile, gpxfile2, with_category=True)

    def test_z2_keywords(self):
        """save and load keywords."""  # noqa

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
            with self.tst_backend(cls):
                with self.temp_backend(cls, clear_first=True, count=1) as backend:
                    # TODO: warum  noch clear_first?
                    gpxfile = backend[0]
                    gpxfile.keywords = list()
                    self.assertEqual(gpxfile.keywords, list())
                    gpxfile.keywords = ([kw_a, kw_b, kw_c])
                    gpxfile.change_keywords(minus(kw_b))
                    self.assertTrue(gpxfile is backend[0])
                    self.assertHasKeywords(gpxfile, (kw_a, kw_c))
                    with self.assertRaises(Exception):
                        gpxfile.change_keywords('Category:whatever')
                    gpxfile.change_keywords(kw_d)
                    self.assertHasKeywords(gpxfile, (kw_a, kw_c, kw_d))
                    backend2 = backend.clone()
                    gpxfile2 = backend2[gpxfile.id_in_backend]
                    self.assertTrue(gpxfile is backend[0])
                    gpxfile2.change_keywords(minus(kw_d))
                    self.assertHasKeywords(backend[0], (kw_a, kw_c, kw_d))
                    # change_keywords may have change id_in_backend in some backend classes, so reload gpxfile
                    backend.scan()
                    gpxfile = backend[0]
                    self.assertHasKeywords(gpxfile2, (kw_a, kw_c))
                    self.assertHasKeywords(gpxfile, (kw_a, kw_c))
                    self.assertTrue(gpxfile is backend[0])
                    backend.scan()
                    self.assertHasKeywords(gpxfile, (kw_a, kw_c))
                    gpxfile.change_keywords(minus(kw_a))
                    self.assertHasKeywords(gpxfile, [kw_c])
                    # gpxfile2.change_keywords(minus(kw_a))
                    gpxfile.change_keywords(minus(kw_c))
                    gpxfile.change_keywords(minus(kw_d))
                    backend.scan()
                    self.assertHasKeywords(backend[0], list())

    def test_z_unicode(self):
        """Can we up- and download unicode characters in all text attributes?."""
        tstdescr = 'DESCRIPTION with ' + self.unicode_string1 + ' and ' + self.unicode_string2
        for cls in Backend.all_backend_classes(needs={'remove'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls, count=1) as backend:
                    backend2 = backend.clone()
                    gpxfile = backend[0]
                    self.assertIsNotNone(gpxfile.backend)
                    gpxfile.title = 'Title ' + self.unicode_string1
                    self.assertIsNotNone(gpxfile.backend)
                    self.assertEqual(gpxfile.backend, backend)
                    backend2.scan()  # because backend2 does not know about changes thru backend
                    gpxfile2 = backend2[0]
                    # gpxfile and gpxfile2 may not be identical. If the original gpxfile
                    # contains gpx xml data ignored by MMT, it will not be in gpxfile2.
                    self.assertEqual(gpxfile.title, gpxfile2.title)
                    gpxfile.description = tstdescr
                    self.assertEqual(gpxfile.description, tstdescr)
                    if cls is Directory:
                        self.assertTrackFileContains(gpxfile, tstdescr)
                    backend2.scan()
                    self.assertEqual(backend2[0].description, tstdescr)
                    backend2.detach()

    def test_change_points(self):
        """Can we change the points of a gpxfile?.

        For MMT this means re-uploading and removing the previous instance, so this

        is not always as trivial as it should be."""

    @skipIf(True, "enable manually if needed")
    def test_download_many_from_mmt(self):
        """Download many gpxfiles."""
        many = 150
        with self.temp_backend(MMT, test_name='gpxstoragemany', count=many, clear_first=True) as backend:
            self.assertBackendLength(backend, many)

    def test_duplicate_title(self):
        """two gpxfiles having the same title."""
        for cls in Backend.all_backend_classes(needs={'remove'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls, count=2) as backend:
                    backend[0].title = 'TITLE'
                    backend[1].title = 'TITLE'

    @skipIf(*disabled(Directory))
    def test_private(self):
        """Up- and download private gpxfiles."""
        with self.temp_directory() as local:
            # TODO: make cls outer loop and count for expensive cls
            gpxfile = self._get_track_from_test_file('test2')
            self.assertTrue(gpxfile.public)  # as defined in test2.gpx keywords
            gpxfile.public = False
            self.assertFalse(gpxfile.public)
            local.add(gpxfile)
            self.assertBackendLength(local, 1)
            for cls in Backend.all_backend_classes(needs={'remove'}):
                with self.tst_backend(cls):
                    with self.temp_backend(cls) as backend:
                        backend.merge(local)
                        for _ in backend:
                            self.assertFalse(_.public)
                        backend2 = backend.clone()
                        with self.temp_directory() as copy:
                            for _ in copy.merge(backend2):
                                self.logger.debug(_)
                            self.assertSameTracks(
                                local, copy,
                                with_last_time=cls not in (GPSIES, Openrunner),
                                with_category=False)

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
        with self.temp_directory(url='source', count=org_source_len) as source:
            with self.temp_directory(url='sink', count=org_sink_len) as sink:
                for _ in list(sink)[1:]:
                    _.adjust_time(datetime.timedelta(hours=100))

                # let's have two identical gpxfiles in source without match in sink:
                next(source[0].points()).latitude += 0.06
                source.add(source[0].clone())

                # and two identical gpxfiles in sink without match in source:
                next(sink[1].points()).latitude += 0.07
                sink.add(sink[1].clone())

                # and one gpxfile twice in source and once in sink:
                sink.add(source[0])

                # and one gpxfile once in source and once in sink:
                sink.add(source[1])

                self.assertBackendLength(source, org_source_len + 1)
                self.assertBackendLength(sink, org_sink_len + 3)

                dump(sink.merge(source, dry_run=True))
                self.assertBackendLength(source, org_source_len + 1)
                self.assertBackendLength(sink, org_sink_len + 3)

                dump(sink.merge(source))
                self.assertBackendLength(source, org_source_len + 1)
                self.assertBackendLength(sink, org_source_len + org_sink_len + 1)

                for _ in range(2):
                    dump(sink.merge(source, remove=True))
                    self.assertBackendLength(source, 0)
                    self.assertBackendLength(sink, org_source_len + org_sink_len)

    @skipIf(*disabled(Directory))
    def test_scan(self):
        """some tests about Backend.scan()."""
        with self.temp_directory(count=5) as source:
            backend2 = source.clone()
            gpxfile = self.create_test_track()
            backend2.add(gpxfile)
            self.assertBackendLength(backend2, 6)
            source.scan()  # because it cannot know backend2 added something

    @skipIf(*disabled(Directory))
    def test_lifetrack(self):
        """test life tracking against a local server."""

        def track():
            life = Lifetrack('127.0.0.1', [local_serverdirectory, uplink])
            points = self._random_points(100)
            life.start(
                points[:50],
                category=uplink.decode_category(uplink.supported_categories[0]))
            time.sleep(7)
            life.update_trackers(points[50:])
            life.end()
            for target in life.targets:
                self.assertNotIn('UNDEFINED', target.gpxfile.xml())

        fence_variants = (None, '0/0/5000000000',)

        for fence_variant in fence_variants:
            fences = Fences(fence_variant)
            for cls in Backend.all_backend_classes(needs={'write'}):
                with self.tst_backend(cls, subtest='fences:{}'.format(fence_variant or 'None')):
                    with self.temp_directory() as local_serverdirectory:
                        local_serverdirectory.account.config['id_method'] = 'counter'
                        with self.temp_directory() as remote_serverdirectory:
                            remote_serverdirectory.account.config['id_method'] = 'counter'
                            with self.lifetrackserver(remote_serverdirectory.url):
                                with self.temp_backend(cls) as uplink:
                                    uplink.account.fences = fences
                                    local_serverdirectory.account.fences = fences
                                    track()
                                    track()
                                    local_serverdirectory.scan()
                                    self.assertBackendLength(local_serverdirectory, 2)
                                    local_ids = [x.id_in_backend for x in local_serverdirectory]
                                    self.assertEqual(local_ids, ['1', '2'])
                                    if cls is TrackMMT and not fences:
                                        remote_serverdirectory.scan()
                                        self.assertSameTracks(local_serverdirectory, remote_serverdirectory)
                                    elif cls is Mailer:
                                        self.logger.debug('uplink.history:')
                                        for _ in uplink.history:
                                            self.logger.debug('    %s', _)
                                        mails_per_track = 2 if fences else 3
                                        self.assertEqual(
                                            len(uplink.history), 2 * mails_per_track,
                                            'Mailer.history: {}'.format(uplink.history))
                                        for _ in range(2):
                                            self.assertIn('Lifetracking starts', uplink.history[_ * mails_per_track])
                                            if mails_per_track == 2:
                                                self.assertIn(
                                                    'Lifetracking ends', uplink.history[_ * mails_per_track + 1])
                                            else:
                                                self.assertIn(
                                                    'Lifetracking continues', uplink.history[_ * mails_per_track + 1])
                                                self.assertIn(
                                                    'Lifetracking ends', uplink.history[_ * mails_per_track + 2])
                                    else:
                                        uplink.scan()
                                        if uplink.accepts_zero_points:
                                            self.assertSameTracks(local_serverdirectory, uplink)

    def test_backend_dirty(self):
        """gpxfile1._dirty."""
        for cls in Backend.all_backend_classes(needs={'scan', 'write'}):
            with self.tst_backend(cls):
                # category in the GpxFile domain:
                test_category_backend = cls.supported_categories[1]
                test_category = cls.decode_category(test_category_backend)
                with self.temp_backend(cls, count=1) as backend1:
                    gpxfile1 = backend1[0]
                    self.assertFalse(gpxfile1._dirty)
                    # version 1.1 should perhaps be a test on its own, see GpxFile.xml()
                    gpxfile1.category = test_category
                    self.assertEqual(gpxfile1.category, test_category)
                    gpxfile1._dirty = 'gpx'
                    self.assertEqual(gpxfile1.category, test_category)
                    backend2 = backend1.clone()
                    self.assertEqual(backend2[0].category, test_category)
                    b2gpxfile = backend2[0]
                    self.assertEqual(b2gpxfile.category, test_category)
                    b2gpxfile.title = 'another new title'
                    self.assertEqual(b2gpxfile.category, test_category)
                    self.assertEqual(backend2[0].category, test_category)
                    gpxfile1.title = 'new title'
                    self.assertEqual(gpxfile1.category, test_category)
                    backend3 = backend1.clone()
                    self.assertEqual(backend3[0].category, test_category)
                    self.assertFalse(gpxfile1._dirty)
                    with gpxfile1.batch_changes():
                        gpxfile1.title = 'new 2'
                        self.assertEqual(gpxfile1._dirty, ['title'])
                    self.assertFalse(gpxfile1._dirty)
                    with gpxfile1.batch_changes():
                        gpxfile1.title = 'new 3'
                        gpxfile1.keywords = ['Something', 'something xlse']
                    backend4 = backend1.clone()
                    self.assertEqual(backend4[0].title, 'new 3')

    def test_directory_dirty(self):
        """test gpx._dirty where id_in_backend is not the default.

        Currently gpxfile._dirty = 'gpx' changes the file name which is wrong."""

    @skipIf(*disabled(Directory))
    def test_directory(self):
        """directory creation/deletion."""

        with self.temp_directory() as dir_a:
            self.assertTrue(dir_a.account.is_temporary)
            a_url = dir_a.url
            self.assertTrue(os.path.exists(a_url), a_url)
        self.assertFalse(os.path.exists(a_url), a_url)

        test_url = tempfile.mkdtemp()
        with self.temp_directory(url=test_url) as dir_b:
            self.assertTrue(dir_b.url == test_url)
        self.assertTrue(os.path.exists(test_url), test_url)
        remove_directory(test_url)

        dir_c = Directory(DirectoryAccount())

        self.assertIn('/gpxity.TestBackends.test_directory_', dir_c.url)
        dir_c.detach()

    @skipIf(*disabled(MMT))
    def test_mmt_empty(self):
        """MMT refuses upload without a specific error message if there is no gpxfile point."""
        gpxfile = self.create_test_track(MMT)
        del gpxfile.gpx.tracks[0]
        with MMT(Account()) as mmt:
            with self.assertRaises(mmt.BackendException):
                mmt.add(gpxfile)

    def test_setters(self):
        """For all GpxFile attributes with setters, test if we can change them without changing something else."""
        for cls in Backend.all_backend_classes(needs={'write', 'scan'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls, count=1) as backend:
                    gpxfile = backend[0]
                    backend2 = backend.clone()
                    self.assertEqualTracks(gpxfile, backend2[0], with_category=False)
                    test_values = {
                        'category': (
                            cls.decode_category(cls.supported_categories[4]),
                            cls.decode_category(cls.supported_categories[2])),
                        'description': ('first description', 'Täst description'),
                        'public': (True, False),
                        'title': ('first title', 'Täst Titel'),
                    }
                    if cls is MMT and backend.subscription == 'free':
                        del test_values['public']
                    if 'keywords' in cls.supported:
                        test_values['keywords'] = (['A', 'Hello Dolly', 'Whatever'], ['Something Else', 'Two'])
                    prev_track = gpxfile.clone()
                    for val_idx in (0, 1):
                        for key, values in test_values.items():
                            value = values[val_idx]
                            self.logger.debug('  %s: %s->%s', key, getattr(gpxfile, key), value)
                            setattr(gpxfile, key, value)
                            setattr(prev_track, key, value)
                            self.assertEqualTracks(prev_track, gpxfile)
                            backend2.scan()
                            self.assertEqualTracks(prev_track, backend2[0])

    def test_keywords(self) ->None:
        """Test arbitrary keyword changes.

        Returns:
            None

        """
        def testcases(cls):
            """Prepare test cases for this backend."""
            keywords = {
                backend._encode_keyword(x)
                for x in self._random_keywords(count=50)}
            repeats = 2 if cls.test_is_expensive else 20
            max_size = cls.max_field_sizes.get('keywords', 10000)
            for _ in range(repeats):
                while True:
                    add_keywords = set(random.sample(keywords, random.randint(0, 10)))
                    remove_keywords = set(random.sample(keywords, random.randint(0, 10)))
                    if not add_keywords & remove_keywords:
                        continue
                    expected_keywords = (set(gpxfile.keywords) | add_keywords) - remove_keywords
                    if len(', '.join(expected_keywords)) < max_size:
                        break
                yield add_keywords, remove_keywords, expected_keywords

        for cls in Backend.all_backend_classes(needs={'scan', 'keywords', 'write'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls, count=1) as backend:
                    backend2 = backend.clone()
                    gpxfile = backend[0]
                    for add_keywords, remove_keywords, expected_keywords in testcases(cls):
                        self.assertEqual(backend._get_current_keywords(gpxfile), gpxfile.keywords)
                        gpxfile.change_keywords(list(add_keywords) * 2)
                        self.assertEqual(
                            backend._get_current_keywords(gpxfile),
                            sorted(list(set(gpxfile.keywords) | add_keywords)))
                        gpxfile.change_keywords('-' + x for x in remove_keywords)
                        self.assertEqual(backend._get_current_keywords(gpxfile), sorted(expected_keywords))
                        self.assertEqual(sorted(expected_keywords), sorted(gpxfile.keywords))
                        backend2.scan()
                        self.assertEqual(sorted(expected_keywords), backend2[0].keywords)
                    with gpxfile.batch_changes():
                        for add_keywords, remove_keywords, expected_keywords in testcases(cls):  # noqa
                            gpxfile.change_keywords(add_keywords)
                            gpxfile.change_keywords('-' + x for x in remove_keywords)
                    self.assertEqual(sorted(expected_keywords), sorted(gpxfile.keywords))
                    backend2.scan()
                    self.assertEqual(
                        backend2._get_current_keywords(backend2[0]),
                        backend2[0].keywords)
                    self.assertEqual(sorted(expected_keywords), backend2[0].keywords)

    @skipIf(*disabled(Directory))
    def test_legal_categories(self):
        """Check if our fixed list of categories still matches the online service."""

        def check():
            """check this backend."""
            downloaded = backend._download_legal_categories()
            self.assertEqual(sorted(backend.supported_categories), downloaded)

        for cls in Backend.all_backend_classes(needs={'own_categories'}):
            if cls is TrackMMT and Directory.is_disabled():
                continue
            with self.tst_backend(cls):
                with self.temp_backend(cls, clear_first=False, cleanup=False) as backend:
                    if cls is TrackMMT:
                        with self.temp_directory() as serverdirectory:
                            serverdirectory.account.config['id_method'] = 'counter'
                            with self.lifetrackserver(serverdirectory.url):
                                check()
                    else:
                        check()

    def test_long_description(self):
        """Test long descriptions."""
        unlimited_length = 50000  # use this if the backend sets no limit
        for cls in Backend.all_backend_classes(needs={'scan', 'write'}):
            with self.tst_backend(cls):
                with self.temp_backend(cls, count=1) as backend:
                    gpxfile = backend[0]
                    max_length = backend._max_length.get('description') or unlimited_length
                    # a backend may encode keywords in description
                    max_descr_length = max_length - (
                        len(backend._encode_description(gpxfile)) - len(gpxfile.description))
                    gpxfile.description = ('long description' * 4000)[:max_descr_length]
                    self.assertEqual(len(backend._encode_description(gpxfile)), max_length)
                    clone = backend.clone()[0]
                    self.assertEqual(gpxfile.description, clone.description)
                    if max_length < unlimited_length:
                        try_description = 'long description' * 4000
                        encoded = backend._encode_description(gpxfile)
                        decoded = backend._decode_description(gpxfile.gpx, encoded)
                        self.assertEqual(len(encoded), max_length)
                        self.assertTrue(try_description.startswith(decoded))

    def test_can_encode_all_categories(self):
        """Check if we can encode all internal categories to a given backend value for all backends."""
        for cls in Backend.all_backend_classes(needs={'own_categories'}):
            with self.tst_backend(cls):
                for category in GpxFile.categories:
                    cls.encode_category(category)

    def test_can_decode_all_categories(self):
        """Check if we can decode all backend categories."""
        for cls in Backend.all_backend_classes(needs={'own_categories'}):
            with self.tst_backend(cls):
                for category in cls.supported_categories:
                    cls.decode_category(category)

    def test_category_map(self):
        """Check if all backends can losslessly encode/decode all supported_categories.

        This is done locally assuming that Backend.supported_categories is correct.
        test_legal_categories() tests Backend.supported_categories for correctness.

        """
        for cls in Backend.all_backend_classes(needs={'own_categories'}):
            with self.tst_backend(cls):
                for key, value in cls._category_decoding.items():
                    self.assertIn(key, cls.supported_categories)
                    self.assertIn(value, GpxFile.categories)
                for key, value in cls._category_encoding.items():
                    self.assertIn(key, GpxFile.categories)
                    self.assertIn(value, cls.supported_categories)
                for category in cls.supported_categories:
                    internal = cls.decode_category(category)
                    back = cls.encode_category(internal)
                    self.assertEqual(
                        category, back,
                        '{}: {} -> {} -> {}'.format(cls.__name__, category, internal, back))

    def test_id_change(self):
        """id_in_backend must be legal."""
        for cls in Backend.all_backend_classes(needs={'rename'}):
            if cls is Directory:
                failing = ('', 56, 'a/b', '/', '.', True, False, 5.0)
                working = ('6', 'fdasfds:fasdds')
            elif cls is WPTrackserver:
                failing = ('', 'a', '/', 19, True, False, 5.0, '2147483648')
                working = ('8', '17', '2147483647')
            elif cls is Memory:
                failing = ('', 19, True, False, 5.0)
                working = ('8', '17', '2147483647', '.', '/', 'ä')
            else:
                raise Exception('untested class {}'.format(cls))
            with self.tst_backend(cls):
                with self.temp_backend(cls) as backend:
                    gpxfile = GpxFile()
                    gpxfile.add_points(self._random_points(count=1))
                    backend.add(gpxfile)
                    orig_id = gpxfile.id_in_backend
                    for _ in failing:
                        with self.assertRaises(ValueError, msg='for class={} id={}'.format(cls.__name__, _)):
                            gpxfile.id_in_backend = _
                    backend.scan()
                    self.assertEqual(len(backend), 1)
                    self.assertEqual(backend[0].id_in_backend, orig_id, 'Testing {} for {}'.format(_, cls.__name__))
                    for _ in working:
                        gpxfile.id_in_backend = _
                        backend.scan()
                        self.assertEqual(len(backend), 1)
                        self.assertEqual(backend[0].id_in_backend, _, 'Testing {} for {}'.format(_, cls.__name__))
