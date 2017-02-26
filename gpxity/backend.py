#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.backend.Backend`
"""

import datetime
from inspect import getmembers, isfunction
import dis

__all__ = ['Backend']


class _ActivityList(list):

    """A list of all activities in a backend,
    allowing activity id as index like in
    backend.activities['12345']

    Args:
        content (list(Activity): Initial list of activities
    """

    def __init__(self, content=None):
        super(_ActivityList, self).__init__()
        if content is not None:
            self.extend(content)

    def __contains__(self, index) ->bool:
        return self.__getitem__(index) is not None

    def __getitem__(self, index):
        """Allows accesses like alist[a_id]"""
        for _ in self:
            if _ is index:
                return _
            if _.id_in_backend == index:
                return _
        if isinstance(index, int) and 0 <= index < len(self):
            return list.__getitem__(self, index)


class Backend:
    """A place where activities live. Something like the filesystem or
    http://mapmytracks.com.

    This can be used as a context manager. At termination, all activities
    may be removed automatically, if cleanup=True. Some concrete
    implementations may also remove the backend itself.

    Not all backends support all methods. The unsupported methods
    will raise NotImplementedError. As a convenience every backend
    has a list **supported** to be used like :literal:`if 'update' in backend.supported:`
    where `update` is the name of the method.

    Args:
        url (str): the address. May be a real URL or a directory, depending on the backend implementation.
            Every implementation may define its own default for url.
        auth (tuple(str, str)): (username, password)
        cleanup (bool): If true, :meth:`destroy` will remove all activities.

    Attributes:
        supported (set(str)): The names of all supported methods. Creating the first instance of
            the backend initializes this.
    """
    supported = None

    skip_test = False

    def __init__(self, url=None, auth=None, cleanup=False):
        super(Backend, self).__init__()
        self.activities = _ActivityList()
        self._activities_fully_listed = False
        self.url = url or ''
        if self.url and not self.url.endswith('/'):
            self.url += '/'
        self.auth = auth
        self._cleanup = cleanup

    @classmethod
    def _define_support(cls):
        """If the first thing a method does is raising NotImplementedError, it is
        marked as unsupported. Those are the default values, the implementations
        will have to refine the results.
        """
        cls.supported = set()
        for name, _ in getmembers(cls, isfunction):
            if not name.startswith('_')  or (name.startswith('_write_') and name != '_write_attribute'):
                first_instruction = next(dis.get_instructions(_.__code__))
                supported = first_instruction is None or first_instruction.argval != 'NotImplementedError'
                if supported:
                    cls.supported.add(name)

    def get_time(self) ->datetime.datetime:
        """get time from the server where backend is located as a Linux timestamp"""
        raise NotImplementedError()

    def list_all(self):
        """list all activities for this user

        Returns:
            list(Activity): all activities
        """
        return list(self._yield_activities())

    def _yield_activities(self):
        """A generator for all activities. It yields the next found and appends it to activities.
        It first clears self.activities.

        Yields:
            the next activity
        """
        raise NotImplementedError()

    def list_activities(self):
        """A generator returning all activities. If all have already been listed,
        return their cached list. For rescanning first call
        :meth:`self.activities.clear()`.

        Yields:
            the next activity"""
        if not self.activities:
            self._activities_fully_listed = False
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

    def save(self, activity, attributes=None):
        """save full activity.

        Args:
            activity (Activity): The activity we want to save in this backend.
                It may be associated with an arbitrary backend.
            attributes (set(str)): If given and the backend supports specific saving for all given attributes,
                save only those.
                Otherwise, save the entire activity.

        Returns:
            Activity: The saved activity. If the original activity lives in a different
            backend, a new activity living in this backend will be created
            and returned.
        """

        if activity.is_loading:
            raise Exception('A backend cannot save() if activity.is_loading. This is a bug in gpxity.')
        if activity.backend is not self and activity.backend is not None:
            activity = activity.clone()
        if activity.backend is None:
            activity.backend = self
            # this calls us again!
            return activity

        fully = False
        if attributes is None or attributes == set(['all']):
            fully = True
        else:
            for attribute in attributes:
                write_name = '_write_{}'.format(attribute)
                if write_name not in self.supported:
                    fully = True
                    break

        if fully:
            self._save_full(activity)
        else:
            for attribute in attributes:
                write_name = '_write_{}'.format(attribute)
                getattr(self, write_name)(activity)
        if activity not in self.activities:
            self.activities.append(activity)
        return activity

    def _save_full(self, activity) ->None:
        """the actual implementation for the concrete Backend"""
        raise NotImplementedError()

    def remove(self, activity) ->None:
        """Removes activity."""
        self._remove_activity_in_backend(activity)
        self.activities.remove(activity)
        activity.id_in_backend = None

    def _remove_activity_in_backend(self, activity) ->None:
        """backend dependent implementation"""
        raise NotImplementedError()

    def update(self, activity, points) ->None: # pylint: disable=no-self-use
        """Appends to the remove activity. points are already
        added to activity

        Todo:
            should not be exposed."""
        raise NotImplementedError()

    def remove_all(self):
        """Removes all activities we know about. If their :attr:`id_in_backend`
        has meanwhile been changed through another backend instance
        or another process, we cannot find it anymore. We do **not**
        relist all activities in the backend. If you want to make shure it
        will be empty, call :meth:`self.activities.clear` before :meth:`remove_all`."""
        for activity in list(self.list_activities()):
            self.remove(activity)

    def copy_all_from(self, from_backend):
        """Copies all activities into this backend.

        Args:
            from_backend (Backend): The source of the activities

        Returns:
            List of all new activities in this backend
        """
        result = list()
        for activity in from_backend.list_all():
            result.append(self.save(activity))
        return result

    def destroy(self):
        """If `cleanup` was set at init time, removes all activities. Some backends
       (example: :class:`Directory <gpxity.backends.directory.Directory.destroy>`)
       may also remove the account (or directory). See also :meth:`remove_all`."""
        if self._cleanup:
            self.remove_all()

    def has_same_activities(self, other) ->bool:
        """True if both backends have the same activities."""
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
        """compares activities in both backends. Used for testing."""
        return self.has_same_activities(other)
