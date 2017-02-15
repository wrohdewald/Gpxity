# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for all backends
"""

from .basic import BasicTest

# pylint: disable=attribute-defined-outside-init

class Supported(BasicTest):
    """Are the supported_ attributes set correctly?"""

    def test_supported(self):
        """check values supports_* for all backends"""
        expect_unsupported = dict()
        expect_unsupported['Directory'] = ('update', )
        expect_unsupported['MMT'] = ('allocate', 'deallocate', 'new_id')
        for cls in self._find_storage_classes():
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


class CreateStorage(BasicTest):
    """Can we create a backend?"""

    #def __init__(self):
       # super(CreateStorage, self).__init__()

    def test_create_localbackend(self):
        """test creation of a local backend"""
        for cls in self._find_storage_classes():
            if not cls.skip_test:
                with self.subTest(' {}'.format(cls.__class__.__name__)):
                    backend = self.setup_backend(cls, count=3, clear_first=True)
                    self.assertEqual(len(backend.list_all()), 3)
