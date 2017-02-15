# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for all backends
"""

import time
import unittest
import requests

from .basic import BasicTest
from ... import Activity

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


class What(BasicTest):

    """test manipulations on Activity.what"""

    def test_no_what(self):
        """what must return default value if not present in gpx.keywords"""
        what_default = Activity.legal_what[0]
        activity = Activity()
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
        activity.add_keyword('What:{}'.format(what_other))
        self.assertEqual(activity.what, what_other)


class Public(unittest.TestCase):
    """test manipulations on Activity.public"""

    def test_no_public(self):
        """public must return False if not present in gpx.keywords"""
        activity = Activity()
        self.assertFalse(activity.public)

    def test_duplicate_public(self):
        """try to set public via its property and additionally with add_keyword"""
        activity = Activity()
        activity.public = True
        self.assertTrue(activity.public)
        activity.add_keyword('public')
        self.assertTrue(activity.public)

    def test_remove_public(self):
        """remove and add public from Activity using remove_keyword and add_keyword"""
        activity = Activity()
        activity.public = True
        activity.remove_keyword('Status:public')
        self.assertFalse(activity.public)
        activity.add_keyword('Status:public')
        self.assertTrue(activity.public)


class WrongAuth(BasicTest):
    """what happens with a wrong password?"""

    def test_open_wrong_auth(self):
        """open backends with wrong password"""
        for cls in self._find_backend_classes():
            if not cls.skip_test and cls.__name__ != 'Directory':
                with self.subTest(' {}'.format(cls.__name__)):
                    with self.assertRaises(requests.exceptions.HTTPError):
                        self.setup_backend(cls, sub_name='wrong')

    def test_save_wrong_auth(self):
        """can we save an activity on the MMT server with a wrong password?"""


class CreateBackend(BasicTest):
    """Can we create a backend and connect with it?"""

    def xtest_create_backend(self):
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
