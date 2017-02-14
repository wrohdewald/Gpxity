# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.


from .basic import BasicTest
from ...backends import *

# pylint: disable=attribute-defined-outside-init


class CreateStorage(BasicTest):
    """Can we create a storage?"""

    #def __init__(self):
       # super(CreateStorage,  self).__init__()

    def test_create_localstorage(self):
        """test creation of a local storage"""
        for cls in self._findStorageClasses():
            if not cls.skip_test:
                print('testing', cls.short_class_name())
                with self.subTest(' {}'.format(cls.__class__.__name__)):
                    storage = self.setup_storage(cls, count=3, clear_first=True)
                    self.assertEqual(len(storage.list_all()), 3)
