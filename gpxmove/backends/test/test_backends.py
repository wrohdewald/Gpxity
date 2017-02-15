# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.


from .basic import BasicTest
from ...backends import *

# pylint: disable=attribute-defined-outside-init


class CreateStorage(BasicTest):
    """Can we create a backend?"""

    #def __init__(self):
       # super(CreateStorage,  self).__init__()

    def test_create_localbackend(self):
        """test creation of a local backend"""
        for cls in self._findStorageClasses():
            if not cls.skip_test:
                print('testing', cls.short_class_name())
                with self.subTest(' {}'.format(cls.__class__.__name__)):
                    backend = self.setup_backend(cls, count=3, clear_first=True)
                    self.assertEqual(len(backend.list_all()), 3)
