#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.backend.Backend`."""

# pylint: disable=protected-access

import os
from inspect import getmembers, isclass, getmro
import dis
import importlib

from .accounts import Account

__all__ = ['BackendBase']



class BackendBase:

    """Classmethods.

    Track cannot import Backend because Backend imports Track.

    BackendBase is imported by both, containing what both need.

    """

    # pylint: disable=too-many-instance-attributes

    __all_backend_classes = None
    __all_backends = dict()

    class BackendException(Exception):
        """Is raised for general backend exceptions, especially error messages from a remote server"""

    @classmethod
    def _is_implemented(cls, method) ->bool:
        """False if the first instruction in method raises NotImplementedError or if the method does nothing.

        Returns:
            True if method is implemented

        """
        first_instruction = next(dis.get_instructions(method.__code__))
        return first_instruction is not None and first_instruction.argval != 'NotImplementedError'

    @classmethod
    def is_disabled(cls) ->bool:
        """True if this backend is disabled by env variable GPXITY_DISABLE_BACKENDS.

        This variable is a comma separated list of Backend class names.

        Returns:
            True if disabled

        """
        disabled = os.getenv('GPXITY_DISABLE_BACKENDS')
        if not disabled:
            return False
        clsname = cls.__name__.split('.')[-1].lower()
        return clsname in disabled.lower().split()

    @classmethod
    def find_class(cls, name: str):
        """Find the Backend class name "name".

        The only backend where the backend is not specified
        is Directory, so that is returned if no class is found.

        Args:
            name: May be anycase (upper,lower). Must match an
                existing Backend class name.

        Returns:
            the backend class or Exception

        """
        assert name
        for _ in cls.all_backend_classes():
            if _.__name__.lower() == name.lower():
                return _
        raise Exception('find_class failed for {}'.format(name))

    @classmethod
    def _find_local(cls, name: str) ->str:
        """If name refers to a local file, return its expanded path.dirname.

        Returns: The expanded path or None.

        """
        name = os.path.expanduser(name)
        if os.path.exists(name):
            if name.endswith('.gpx'):
                name = name[:-4]
            return name
        if not name.endswith('.gpx'):
            if os.path.exists(name + '.gpx'):
                return name
        dirname, file = os.path.split(name)
        if file:
            if os.path.isdir(dirname):
                return name
        return None

    @classmethod
    def parse_objectname(cls, name):
        """Parse the full identifier for a track.

        1. if name is an existing file or directory, or if name.gpx is an existing file, Backend will be Directory
        2. if ":" is not in name: Backend will be Directory, url=None, track_id=name without .gpx
        3. the part before the first ":" is used as key into accounts. Not case sensitive.

        Args:
            name: the full identifier for a Track

        Returns:
            A tuple with account, track_id

        """
        assert name
        expanded = cls._find_local(name)
        if expanded:
            if os.path.isdir(expanded):
                url = expanded
                track_id = None
            else:
                url, track_id = os.path.split(expanded)
                if not url and not os.path.exists(track_id):
                    url = '.'
            account = Account(url=url)
        elif ':' not in name:
            url = None
            track_id = name
            if track_id.endswith('.gpx'):
                track_id = track_id[:-4]
            account = Account(url='.')
        else:
            _ = name.split(':')
            account_name = _[0]
            track_id = ':'.join(_[1:]) or None
            if 'directory' in account_name.lower() and not track_id:
                account_name += ':.'
            account = Account(account_name)
            # backend name in accounts is case insensitive, we want the exact name
            account.backend = cls.find_class(account.backend).__name__
        return account, track_id

    @classmethod
    def all_backend_classes(cls, exclude=None, needs=None):
        """Find all backend classes.

        Args:
            exclude: A list with classes to be excluded
            needs: set(str) with needed supported actions

        Returns:
            A sorted list of all backend classes. Disabled backends are not
            returned.

        """
        if cls.__all_backend_classes is None:
            backends_directory = os.path.join(os.path.dirname(__file__), 'backends')
            if not os.path.exists(backends_directory):
                raise Exception('we are not where we should be')
            cls.__all_backend_classes = list()
            mod_names = os.listdir(backends_directory)
            for mod in mod_names:
                if not mod.endswith('.py'):
                    continue
                if mod == '__init__':
                    continue
                try:
                    imported = importlib.import_module('.backends.{}'.format(mod[:-3]), __package__)
                    classes = (x[1] for x in getmembers(imported, isclass))
                    # isinstance and is do not work here
                    classes = [x for x in classes if BackendBase in getmro(x)[1:]]
                    classes = [x for x in classes if not x.is_disabled()]
                    cls.__all_backend_classes.extend(classes)
                except ImportError:
                    pass
            cls.__all_backend_classes = set(
                x for x in cls.__all_backend_classes if x.__name__ != 'Backend')
        if exclude is None:
            exclude = list()
        if needs is None:
            needs = set()
        return sorted(
            (x for x in cls.__all_backend_classes
             if x not in exclude and needs < x.supported), key=lambda x: x.__name__)

    @classmethod
    def instantiate(cls, name: str):
        """Instantiate a Backend or a Track out of its identifier.

        The full notation of an id_in_backend in a specific backend is
        similiar to what scp expects:

        Account:id_in_backend where Account is a reference to the accounts file.

        Locally reachable files or directories may be written without the leading
        Directory:. And a leading ~ is translated into the user home directory.
        The trailing .gpx can be omitted. It will be removed anyway for id_in_backend.

        If the file path of a local track (Directory) contains a ":", the file path
        must be absolute or relative (start with "/" or with "."), or the full notation
        with the leading Directory: is needed

        Args:
            name: The string identifier to be parsed

        Returns:
            A Track or a Backend. If the Backend has already been instantiated, return the cached value.

        """
        account, track_id = cls.parse_objectname(name)
        cache_key = str(account)
        if cache_key in cls.__all_backends:
            result = cls.__all_backends[cache_key]
        else:
            account.backend_cls = cls.find_class(account.backend)
            result = account.backend_cls(account)
            cls.__all_backends[cache_key] = result
        if track_id:
            try:
                result = result[track_id]
            except IndexError:
                raise Exception('gpxdo: {}:{} not found'.format(result.account.name, track_id))

        assert result is not None
        return result

    def _get_current_keywords(self, track):  # pylint:disable=no-self-use
        """A backend might be able to return the currently stored keywords.

        This is useful for unittests: Compare the internal state with what the
        backend actually says.

        """
        return track.keywords
