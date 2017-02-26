# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements :class:`gpxpy.backends.test.test_backends.TestBackends` for all backends
"""

import time
import requests

from .basic import BasicTest
from .. import Directory, MMT, ServerDirectory
from ... import Activity

# pylint: disable=attribute-defined-outside-init


class TestBackends(BasicTest):
    """Are the :literal:`supported_` attributes set correctly?"""

    def test_supported(self):
        """Check values in supported for all backends"""
        expect_unsupported = dict()
        expect_unsupported[Directory] = set(['update'])
        expect_unsupported[ServerDirectory] = set(['update'])
        expect_unsupported[MMT] = set()
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                self.assertTrue(cls.supported & expect_unsupported[cls] == set())

    def test_save_empty(self):
        """Save empty activity"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                backend = self.setup_backend(cls, cleanup=True)
                try:
                    activity = Activity()
                    if cls is MMT:
                        with self.assertRaises(Exception):
                            backend.save(activity)
                    else:
                        self.assertIsNotNone(backend.save(activity))
                finally:
                    backend.destroy()

    def test_backend(self):
        """Manipulate backend"""
        activity = self.create_test_activity()
        with Directory(cleanup=True) as directory1:
            with Directory(cleanup=True) as directory2:
                saved = directory1.save(activity)
                self.assertEqual(saved.backend, directory1)
                activity.backend = directory1
                with self.assertRaises(Exception):
                    activity.backend = directory2
                with self.assertRaises(Exception):
                    activity.backend = None

    def test_open_wrong_auth(self):
        """Open backends with wrong password"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                if issubclass(cls, Directory):
                    try:
                        backend = self.setup_backend(cls, sub_name='wrong', cleanup=True)
                    finally:
                        backend.destroy()
                else:
                    with self.assertRaises(requests.exceptions.HTTPError):
                        self.setup_backend(cls, sub_name='wrong')

    def test_create_backend(self):
        """Test creation of a backend"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                backend = self.setup_backend(cls, count=3, clear_first=True, cleanup=True)
                try:
                    self.assertEqual(len(backend.list_all()), 3)
                    first_time = backend.get_time()
                    time.sleep(2)
                    second_time = backend.get_time()
                    total_seconds = (second_time - first_time).total_seconds()
                    self.assertTrue(1 < total_seconds < 4, 'Time difference should be {}, is {}-{}={}'.format(
                        2, second_time, first_time, second_time - first_time))
                finally:
                    backend.destroy()

    def test_write_remote_attributes(self):
        """If we change title, description, public, what in activity, is the backend updated?"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                backend = self.setup_backend(cls, count=1, clear_first=True, cleanup=True)
                try:
                    activity = backend.list_all()[0]
                    first_public = activity.public
                    first_title = activity.title
                    first_description = activity.description
                    first_what = activity.what
                    activity.public = not activity.public
                    activity.title = 'A new title'
                    self.assertEqual(activity.title, 'A new title')
                    activity.description = 'A new description'
                    if activity.what == 'Cycling':
                        activity.what = 'Running'
                    else:
                        activity.what = 'Cycling'
                    # make sure there is no cache in the way
                    backend2 = self.clone_backend(backend)
                    activity2 = backend2.list_all()[0]
                    self.assertNotEqual(first_public, activity2.public)
                    self.assertNotEqual(first_title, activity2.title)
                    self.assertNotEqual(first_description, activity2.description)
                    self.assertNotEqual(first_what, activity2.what)
                finally:
                    backend.destroy()

    def test_all_what(self):
        """can we up- and download all values for :attr:`Activity.what`?"""
        what_count = len(Activity.legal_what)
        backends = list(
            self.setup_backend(x, count=what_count, clear_first=True)
            for x in self._find_backend_classes())
        copies = list(self.clone_backend(x) for x in backends)
        first_backend = copies[0]
        for other in copies[1:]:
            self.assertSameActivities(first_backend, other)
        for backend in copies:
            backend.destroy()
        for backend in backends:
            backend.destroy()

    def test_keywords(self):
        """save and load keywords"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                backend = self.setup_backend(cls, count=1, clear_first=True, cleanup=True)
                try:
                    activity = Activity(backend)
                    activity.add_points(self.some_random_points(5))
                    activity.keywords = (['a', 'b', 'c'])
                    with self.assertRaises(Exception):
                        activity.add_keyword('b')
                    activity.remove_keyword('b')
                    self.assertEqual(activity.keywords, (['a', 'c']))
                    with self.assertRaises(Exception):
                        activity.add_keyword('What:whatever')
                    activity.add_keyword('e')
                    self.assertEqual(activity.keywords, (['a', 'c', 'e']))
                finally:
                    backend.destroy()

    def test_unicode(self):
        """Can we up- and download unicode characters in all text attributes?"""
        tstdescr = 'DESCRIPTION with utf-8 char ß (unicode szlig) and something japanese:の諸問題'
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                backend = self.setup_backend(cls, count=1, clear_first=True)
                backend2 = self.clone_backend(backend)
                try:
                    activity = backend.list_all()[0]
                    activity.title = 'Title with utf-8 char ß (unicode szlig)'
                    backend2.list_all()
                    activity2 = backend2.activities[0]
                    self.assertEqualActivities(activity, activity2)
                    activity.description = tstdescr
                    self.assertEqual(activity.description, tstdescr)
                    backend2.activities.clear()
                    backend2.list_all()
                    activity2 = backend2.activities[0]
                    self.assertEqual(activity2.description, tstdescr)
                    self.assertEqualActivities(activity, activity2)
                finally:
                    backend.destroy()
                    backend2.destroy()

    def test_change_points(self):
        """Can we change the points of a track?

        For MMT this means re-uploading and removing the previous instance, so this
        is not always as trivial as it should be."""

    def test_download_many(self):
        """download many activities"""
        many = 100
        backend = self.setup_backend(MMT, count=many, cleanup=False, clear_first=False, sub_name='many')
        self.assertEqual(len(backend.list_all()), many)

    def test_duplicate_title(self):
        """two activities having the same title"""
        for cls in self._find_backend_classes():
            with self.subTest(' {}'.format(cls.__name__)):
                backend = self.setup_backend(cls, count=2, clear_first=True)
                activity1, activity2 = backend.list_all()
                try:
                    activity1.title = 'TITLE'
                    activity2.title = 'TITLE'
                finally:
                    backend.destroy()
