# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements :class:`gpxpy.backends.test.test_backends.TestBackends` for all backends
"""

import time
import requests

from .basic import BasicTest
from .. import Directory

# pylint: disable=attribute-defined-outside-init


class TestBackends(BasicTest):
    """Are the :literal:`supported_` attributes set correctly?"""

    def test_supported(self):
        """Check values in supported for all backends"""
        expect_unsupported = dict()
        expect_unsupported['Directory'] = set(['update'])
        expect_unsupported['MMT'] = set()
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    cls() # only this initializes supported
                    self.assertTrue(cls.supported & expect_unsupported[cls.__name__] == set())

    def test_backend(self):
        """Manipulate backend"""
        activity = self.create_unique_activity()
        directory1 = Directory()
        directory2 = Directory()

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
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    if cls.__name__ == 'Directory':
                        self.setup_backend(cls, sub_name='wrong')
                    else:
                        with self.assertRaises(requests.exceptions.HTTPError):
                            self.setup_backend(cls, sub_name='wrong')

    def test_create_backend(self):
        """Test creation of a backend"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    backend = self.setup_backend(cls, count=3, clear_first=True)
                    self.assertEqual(len(backend.list_all()), 3)
                    first_time = backend.get_time()
                    time.sleep(2)
                    second_time = backend.get_time()
                    total_seconds = (second_time - first_time).total_seconds()
                    self.assertTrue(1 < total_seconds < 4, 'Time difference should be {}, is {}-{}={}'.format(
                        2, second_time, first_time, second_time - first_time))

    def test_write_remote_attributes(self):
        """If we change title, description, public, what in activity, is the backend updated?"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    backend = self.setup_backend(cls, count=1, clear_first=True)
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
                    backend2 = backend.clone()
                    activity2 = backend2.list_all()[0]
                    self.assertNotEqual(first_public, activity2.public)
                    self.assertNotEqual(first_title, activity2.title)
                    self.assertNotEqual(first_description, activity2.description)
                    self.assertNotEqual(first_what, activity2.what)
