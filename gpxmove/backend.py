#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxmove.Storage`
"""

import datetime
from inspect import getmembers, ismethod

__all__ = ['Storage']


class _ActivityList(list):

    """A list of all activities in a storage,
    allowing activity id as index like in
    storage.activities['12345']

    Args:
        storage (:class:`gpxmove.backend.Storage`): The storage holding this list
        content (list(Activity): Initial list of activities
    """

    def __init__(self, storage, content=None):
        super(_ActivityList, self).__init__()
        if content is not None:
            self.extend(content)
        self.storage = storage

    def __contains__(self, index) ->bool:
        return self.__getitem__(index) is not None

    def __getitem__(self, index):
        """Allows accesses like alist[a_id]"""
        for _ in self:
            if _.storage_ids[self.storage] == index:
                return _
        if 0 <= index < len(self):
            return list.__getitem__(self, index)


class Storage:
    """A place where activities live. Something like the filesystem or MMT

    This can be used as a context manager. At termination, all activities
    may be removed automatically, if cleanup=True. Some concrete
    implementations may also remove the storage itself.

    Arguments:
        url (str): the address. May be a real URL or a directory, depending on the storage implementation.
        auth (tuple(str, str)): (username, password)
        cleanup (bool): If true, destroy() will remove all activities.
    """

    prefix = None

    skip_test = False

    supports_methods = set()
    supports_keywords = True

    def __init__(self, url=None, auth=None, cleanup=False):
        super(Storage, self).__init__()
        self.supports_methods.add(self.clone)

        self.activities = _ActivityList(self)
        self._activities_fully_listed = False
        self.url = url or ''
        if self.url and not self.url.endswith('/'):
            self.url += '/'
        self.auth = auth
        self.cleanup = cleanup

    @classmethod
    def short_class_name(cls):
        """used for unittests"""
        parts = cls.__name__.split('.')
        return parts[-1]

    def _supports_all(self):
        """this marks all methods as suppported. If a storage supports most,
        we can first call this and the unset unsupported methods again."""
        self.supports_methods = set(getmembers(self.__class__, ismethod))

    def supports(self, method):
        """bool: does this storage support method?
        method may be a string or a method"""
        lookup = method
        if isinstance(lookup, str):
            lookup = getattr(self, lookup)
        return lookup in self.supports_methods

    def allocate(self):
        """allocates a backend.
        By default, this does nothing - we expect the account in the
        backend to exist. FSStorage is one example which does something:
        it allocates a directory."""

    def clone(self):
        """returns a clone with nothing listed or loaded"""
        return self.__class__(self.url, self.auth)

    def get_time(self) ->datetime.datetime:
        """get time from the server where storage is located as a Linux timestamp"""
        raise NotImplementedError()

    def new_id(self, activity) ->str:
        """defines an id for activity in this storage

        Args:
            activity: The activity requesting an id"""
        raise NotImplementedError()

    def list_all(self, load_full: bool=False):
        """list all activities for this user

        Args:
            load_full: load the full activities including all GPX data

        Returns:
            list(Activity): all activities
        """
        for _ in self._yield_activities():
            if load_full:
                self.load_full(_)
        return self.activities

    def _yield_activities(self):
        """A generator for all activities. It yields the next found and appends it to activities.
        It first clears self.activities.

        Yields:
            the next activity
        """
        raise NotImplementedError()

    def list_activities(self):
        """A generator returning all activities. If all have already been listed,
        return their cached list. For rescanning, allocate a new Storage object.

        Yields:
            the next activity"""
        if self._activities_fully_listed:
            for _ in self.activities:
                yield _
        else:
            for _ in self._yield_activities():
                yield _
            self._activities_fully_listed = True

    def load_full(self, activity) ->None:
        """fills the activity with all its data from source"""
        raise NotImplementedError()

    def save(self, activity) ->None:
        """save full activity"""
        raise NotImplementedError()

    def remove(self, activity) ->None:
        """remove activity from storage"""
        self._remove_activity_in_storage(activity)
        self.activities.remove(activity)

    def _remove_activity_in_storage(self, activity) ->None:
        """storage dependent implementation"""
        raise NotImplementedError()

    def update(self, activity, points): # pylint: disable=no-self-use
        """append to the remove activity. points are already
        added to activity"""
        raise NotImplementedError()

    def change_title(self, activity):
        """change title in storage, activity already has the new title"""
        raise NotImplementedError()

    def change_description(self, activity):
        """changes description in storage, activity already has the new description"""
        raise NotImplementedError()

    def change_what(self, activity):
        """change what in storage, activity already has the new type"""
        raise NotImplementedError()

    def remove_all(self):
        """removes all activities"""
        for activity in list(self.list_activities()):
            self.remove(activity)

    def copy_all_from(self, from_storage):
        """copy all activities into this storage"""
        for activity in from_storage.list_all(load_full=True):
            self.save(activity)

    def destroy(self):
        """removes all traces of this storage ONLY if we created it in __init__"""
        if self.cleanup:
            self.remove_all()

    def __hash__(self):
        """dict needs hashable keys"""
        return id(self)

    def has_same_activities(self, other):
        """True if both storages have the same activities"""
        return set(x.key() for x in self.activities) == set(x.key() for x in other.activities)

    def __repr__(self):
        result = '{}({} {})'.format(
            self.__class__.__name__, self.url, self.auth[0] if self.auth else 'anonymous')
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, trback):
        self.destroy()

    def __eq__(self, other):
        """compares activities in both storages. Used for testing."""
        return self.has_same_activities(other)
