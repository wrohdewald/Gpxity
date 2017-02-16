# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for all backends
"""

import time
import requests

from .basic import BasicTest
from .. import Directory

# pylint: disable=attribute-defined-outside-init


class Supported(BasicTest):
    """Are the :literal:`supported_` attributes set correctly?"""

    def test_supported(self):
        """check values supports_* for all backends"""
        expect_unsupported = dict()
        expect_unsupported['Directory'] = ('update', )
        expect_unsupported['MMT'] = ('allocate', 'deallocate', 'new_id')
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                self.assertIn(cls.__name__, expect_unsupported)
                expect_cls_unsupported = expect_unsupported[cls.__name__]
                backend = self.setup_backend(cls)
                attributes = (x for x in backend.__class__.__dict__.items() if x[0].startswith('supports_'))
                for name, _ in attributes:
                    short_name = name.replace('supports_', '')
                    with self.subTest('testing supported_{} for {}'.format(short_name, cls.__name__)):
                        self.assertIn(short_name, backend.supported)
                        if short_name in expect_cls_unsupported:
                            self.assertFalse(backend.supported[short_name])
                            self.assertFalse(getattr(backend, name))
                        else:
                            self.assertTrue(backend.supported[short_name])
                            self.assertTrue(getattr(backend, name))


class ActivityBackend(BasicTest):
    """test manipulation of Activity.backend"""

    def test_backend(self):
        """manipulate backend"""
        activity = self.create_unique_activity()
        directory1 = Directory()
        directory2 = Directory()

        saved = directory1.save(activity)
        self.assertEqual(saved.backend, directory1)
        with self.assertRaises(Exception):
            activity.backend = directory2
        with self.assertRaises(Exception):
            activity.backend = None

class WrongAuth(BasicTest):
    """what happens with a wrong password?"""

    def test_open_wrong_auth(self):
        """open backends with wrong password"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    if cls.__name__ == 'Directory':
                        self.setup_backend(cls, sub_name='wrong')
                    else:
                        with self.assertRaises(requests.exceptions.HTTPError):
                            self.setup_backend(cls, sub_name='wrong')


# Now the more expensive tests:

class CreateBackend(BasicTest):
    """Can we create a backend and connect with it?"""

    def test_create_backend(self):
        """test creation of a backend"""
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


class PageParser(BasicTest):

    """page parsing, actually needed only for mmt"""

    def test_change_remote_attributes(self):
        """if we change title, description, public, what in activity, is the backend updated?"""
        for cls in self._find_backend_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__name__)):
                    backend = self.setup_backend(cls, count=1, clear_first=True)
                    activity = backend.list_all(load_full=True)[0]
                    first_public = activity.public
                    first_title = activity.title
                    first_description = activity.description
                    first_what = activity.what
                    activity.public = not activity.public
                    activity.title = 'A new title'
                    activity.description = 'A new description'
                    if activity.what == 'Cycling':
                        activity.what = 'Running'
                    else:
                        activity.what = 'Cycling'
                    # make sure there is no cache in the way
                    backend2 = backend.clone()
                    activity2 = backend2.list_all(load_full=True)[0]
                    self.assertNotEqual(first_public, activity2.public)
                    self.assertNotEqual(first_title, activity2.title)
                    self.assertNotEqual(first_description, activity2.description)
                    self.assertNotEqual(first_what, activity2.what)
