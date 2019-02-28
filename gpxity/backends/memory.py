#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This implements :class:`gpxity.memory.Memory`."""

# pylint: disable=protected-access


from .. import Backend
from ..accounts import MemoryAccount

__all__ = ['Memory']


class Memory(Backend):

    """Keep it in RAM only.

    Uses id(GpxFile) as id_in_backend, if none is given.
    Memory.clone() returns self._new_id_from

    Useful if you want to do multiple manipulations and
    batch_changes() would be inconvenient.

    Args:
        Account: If its url is unset, this will create a temporary
            directory named :attr:`prefix`.X where X are some random characters.
            It will be removed in __exit__ / detach.
    """

    # pylint: disable=abstract-method

    test_is_expensive = False
    accepts_zero_points = True

    def __init__(self, account=None):
        """See class docstring."""
        if account is None:
            account = MemoryAccount()
        assert isinstance(account, MemoryAccount)
        super(Memory, self).__init__(account)
        self.__my_storage = dict()

    def clone(self):
        """Return myself."""
        result = super(Memory, self).clone()
        result.__my_storage = self.__my_storage
        return result

    def _load_gpxfile_headers(self):
        """get all gpxfiles for this user."""
        for key, value in self.__my_storage.items():
            self._found_gpxfile(key, value)

    def _read(self, gpxfile):
        """Nothing to do, _load_gpxfile_headers already read everything."""

    def _write_all(self, gpxfile) ->str:
        """Just do nothing but give an id_in_backend if needed."""
        if gpxfile.id_in_backend is None:
            gpxfile.id_in_backend = self._new_id_from(str(id(gpxfile)))
        self.__my_storage[gpxfile.id_in_backend] = gpxfile.gpx.clone()
        return gpxfile.id_in_backend

    def _new_id_from(self, wanted):
        """Make it unique within this Backend.

        Returns: The unique id_in_backend.

        """
        result = wanted
        counter = 1
        while result in self.__my_storage:
            result = '{}.{}'.format(wanted, counter)
        return result

    def _change_ident(self, gpxfile, new_ident: str):
        """Change the id in the backend. Make it unique if needed."""
        assert gpxfile.id_in_backend != new_ident
        gpx = self.__my_storage[gpxfile.id_in_backend]
        del self.__my_storage[gpxfile.id_in_backend]
        unique_id = self._new_id_from(new_ident)
        self.__my_storage[unique_id] = gpx
        self.logger.info('%s: renamed %s to %s', self.account, gpxfile.id_in_backend, unique_id)
        gpxfile.id_in_backend = unique_id

    def _remove_ident(self, ident: str):
        """Remove this GpxFile."""
        del self.__my_storage[ident]

    def __str__(self) ->str:
        """Used for formatting strings. Must be unique within the process.

        Returns:
            a unique identifier

        """
        return str(self.account)

    @staticmethod
    def _new_ident(gpxfile):
        """Create an id for gpxfile.

        Returns: The new ident.

        """
        return gpxfile.id_in_backend or str(id(gpxfile))
