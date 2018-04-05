#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Backend`
"""

import datetime
from inspect import getmembers, isfunction
import dis
from contextlib import contextmanager
from collections import defaultdict
import logging
from http.client import HTTPConnection

from .auth import Authenticate

__all__ = ['Backend', 'BackendDiff']


class BackendDiff:
    """Compares two backends.directory

    Args:
        left (Backend): A backend
        right (Backend): The other one
        key: A lambda which does the comparison.
            Default is the start time: `key=lambda x: x.time`
        right_key: Default is key. If given, this will be used for activities from right.
            This allows things like `BackendDiff(b1, b2, key_right = lambda x: x.time + hours2)`
            where hours2 is a timedelta of two hours. If your GPX data has a problem with
            the time zone, this lets you find activities differring only by exactly 2 hours.

    Attributes:
        left(:class:`BackendDiffSide`): Attributes for the left side
        right(:class:`BackendDiffSide`): Attributes for the right side
        keys_in_both(list): keys appearing on both sides.
        matches(list): For every keys_in_both, this lists all matching activities from both sides
    """

    # pylint: disable=too-few-public-methods

    class BackendDiffSide:
        """Represents a backend in BackendDiff.

        Attributes:
            backend: The backend
            key_lambda: The used lambda for calculating the key values
            entries(dict): keys are what key_lambda calculates. values are lists of matching activities
            exclusive(dict): keys with corresponding activity lists for activities existing only on this side
        """

        # pylint: disable=too-few-public-methods

        def __init__(self, backend, key_lambda=None):
            self.backend = backend
            self.key_lambda = key_lambda
            self.entries = defaultdict(list)
            for _ in backend:
                try:
                    key = key_lambda(_)
                except TypeError:
                    print('BackendDiffSide cannot apply key in {}: {}'.format(backend, _))
                    key = None
                self.entries[key].append(_)
            self.exclusive = dict()

        def _use_other(self, other):
            """use data from the other side"""
            for _ in self.entries.keys():
                if _ not in other.entries:
                    self.exclusive[_] = self.entries[_]

    def __init__(self, left, right, key=None, right_key=None):
        if key is None:
            key = lambda x: x.time
        if right_key is None:
            right_key = key
        self.left = BackendDiff.BackendDiffSide(left, key)
        self.right = BackendDiff.BackendDiffSide(right, right_key)
        self.left._use_other(self.right) # pylint: disable=protected-access
        self.right._use_other(self.left) # pylint: disable=protected-access
        self.keys_in_both = self.left.entries.keys() & self.right.entries.keys()
        self.matches = defaultdict(list)
        for _ in self.keys_in_both:
            self.matches[_].extend(self.left.entries[_])
            self.matches[_].extend(self.right.entries[_])


class Backend:
    """A place where activities live. Something like the filesystem or
    http://mapmytracks.com.

    A Backend should hold only activities for one person, and they
    should not overlap in time. This is not enforced but sometimes
    behaviour is undefined if you ignore this.

    This can be used as a context manager. At termination, all activities
    may be removed automatically, if cleanup=True. Some concrete
    implementations may also remove the backend itself.

    A backend allows indexing by normal int index, by :class:`Activity <gpxity.Activity>`
    and by :attr:`Activity.id_in_backend <gpxity.Activity.id_in_backend>`.
    :literal:`if 'ident' in backend` is possible.
    len(backend) shows the number of activities. Please note that Code
    like :literal:`if backend:` may not behave as expected. This will be False if the backend
    has no activity. If that is not what you want, consider :literal:`if backend is not None`

    The backend will automatically synchronize. So something like :literal:`len(Backend())` will work.
    However, some other Backend pointing to the same storage or even a different process
    might change things. If you want to cope with that, use :meth:`scan`.

    Not all backends support all methods. The unsupported methods
    will raise NotImplementedError. As a convenience every backend
    has a list **supported** to be used like :literal:`if 'track' in backend.supported:`
    where `track` is the name of the method.

    Backends support no locking. If others modify a backend concurrently, you may
    get surprises. It is up to you to handle those.

    Args:
        url (str): Initial value for :attr:`url`
        auth (tuple(str, str)): (username, password). Alternatively you can pass the username as a single string.
            This will lookup the password from :class:`Authenticate <gpxity.auth.Authenticate>`.
        cleanup (bool): If true, :meth:`destroy` will remove all activities.

    Attributes:
        supported (set(str)): The names of supported methods. Creating the first instance of
            the backend initializes this. Only methods which may not be supported are mentioned here.
            Those are: remove, track, get_time, _write_title, _write_public, _write_what,
            _write_gpx, _write_description, _write_keywords, _write_add_keyword, _write_remove_keyword.
            If a particular _write_* like _write_public does not exist, the entire activity is written instead.
        url (str): the address. May be a real URL or a directory, depending on the backend implementation.
            Every implementation may define its own default for url.
    """

    class NoMatch(Exception):
        """Is raised if an activity is expected to pass the match filter but does not"""

    class BackendException(Exception):
        """Is raised for general backend exceptions, especially error messages from a remote server"""


    supported = None

    skip_test = False

    def __init__(self, url=None, auth=None, cleanup=False, debug=False):
        self._decoupled = False
        super(Backend, self).__init__()
        self.__activities = list()
        self._activities_fully_listed = False
        self.url = url or ''
        if isinstance(auth, str):
            _ = Authenticate(self.__class__, auth)
            self.auth = _.auth
            if _.url:
                self.url = _.url
        else:
            self.auth = auth
        if self.url and not self.url.endswith('/'):
            self.url += '/'
        self._cleanup = cleanup
        self.__match = None
        self._next_id = None # this is a hack, see save()
        self.__debug = None
        self.debug = debug



    @contextmanager
    def _decouple(self):
        """This context manager disables automic synchronization with
        the backend. In that state, automatic writes of changes into
        the backend are disabled, and if you access attributes which
        would normally trigger a full load from the backend, they will not.
        Use this to avoid recursions.

        You should never need this unless you implement a new backend.
        """
        prev_decoupled = self._decoupled
        self._decoupled = True
        try:
            yield
        finally:
            self._decoupled = prev_decoupled

    @classmethod
    def _is_implemented(cls, method):
        """False if the first instruction in method raises NotImplementedError
        or if the method does nothing"""
        first_instruction = next(dis.get_instructions(method.__code__))
        return first_instruction is not None and first_instruction.argval != 'NotImplementedError'

    @classmethod
    def _define_support(cls):
        """If the first thing a method does is raising NotImplementedError, it is
        marked as unsupported.
        """
        support_mappings = {
            '_remove_activity':'remove',
            '_track':'track',
            'get_time':'get_time'}
        cls.supported = set()
        for name, method in getmembers(cls, isfunction):
            if name in support_mappings:
                if cls._is_implemented(method):
                    cls.supported.add(support_mappings[name])
            elif name.startswith('_write_') and name != '_write_attribute':
                if cls._is_implemented(method):
                    cls.supported.add(name)

    @property
    def debug(self):
        """True: output HTTP debugging data to stdout"""
        return self.__debug

    @debug.setter
    def debug(self, value):
        if self.__debug != value:
            self.__debug = value
            if value:
                HTTPConnection.debuglevel = 1
                logging.basicConfig()
                logging.getLogger().setLevel(logging.DEBUG)
                requests_log = logging.getLogger("urllib3")
                requests_log.setLevel(logging.DEBUG)
                requests_log.propagate = True
            else:
                HTTPConnection.debuglevel = 0
                logging.basicConfig()
                logging.getLogger().setLevel(logging.CRITICAL + 1)
                requests_log = None

    @property
    def match(self):
        """A function with one argument returning None or str. The backend will call
            this with every activity and ignore activities where match does not return None.
            The returned str should explain why the activity does not match.

            If you change an activity such that it does not match anymore, the exception
            NoMatch will be raised and the activity will be re-loaded from the physical
            backend.
        """
        return self.__match

    @match.setter
    def match(self, value):
        old_match = self.__match
        self.__match = value
        try:
            self.scan()
        except self.NoMatch:
            self.__match = old_match
            raise

    def get_time(self) ->datetime.datetime:
        """get time from the server where backend is located as a Linux timestamp"""
        raise NotImplementedError()

    def scan(self, now: bool = False) ->None:
        """Enforces a reload of the list of all activities in the backend.
        This will be delayed until the list is actually needed again.

        If this finds an unsaved activity not matching the current match
        function, an exception is thrown.
        Saved Activities not matching the current match will no be loaded.

        Args:
            now: If True, do not delay scanning.
        """
        self._activities_fully_listed = False
        if now:
            self._scan()

    def _scan(self) ->None:
        """loads the list of all activities in the backend if not yet done.
        Enforce this by calling :meth:`scan` first.
        """
        if not self._activities_fully_listed:
            self._activities_fully_listed = True
            unsaved = list(x for x in self.__activities if x.id_in_backend is None)
            if self.__match is not None:
                for activity in unsaved:
                    self.matches(activity, 'scan')
            self.__activities = unsaved
            match_function = self.__match
            self.__match = None
            try:
                # _yield_activities should return ALL activities, match will be
                # applied in a second loop. This way the Backend implementations
                # do not have to worry about the match code.
                list(self._yield_activities())
            finally:
                self.__match = match_function
            if self.__match is not None:
                self.__activities = list(x for x in self.__activities if self.matches(x))

    def _yield_activities(self):
        """A generator for all activities. It yields the next found and appends it to activities.
        The activities will not be loaded if possible.

        Yields:
            the next activity
        """
        raise NotImplementedError()

    def _read_all(self, activity) ->None:
        """fills the activity with all its data from source"""
        raise NotImplementedError()

    def matches(self, activity, exc_prefix: str = None):
        """Does activity match the current match function?

        Args:
            exc_prefix: If not None, use it for the beginning of an exception message.
                If None, never raise an exception
        """
        if self.__match is None:
            return True
        match_error = self.__match(activity)
        if match_error and exc_prefix:
            raise Backend.NoMatch('{}: {} does not match: {}'.format(exc_prefix, activity, match_error))
        return match_error is None

    def save(self, activity, ident: str = None, attributes=None):
        """save full activity.

        It is not allowed but possible to set :attr:`Activity.id_in_backend <gpxity.Activity.id_in_backend>` to
        something other than str. But here we raise an exception
        if that ident is used for saving.

        If the activity does not pass the current match function, raise an exception.

        Args:
            activity (~gpxity.Activity): The activity we want to save in this backend.
                It may be associated with an arbitrary backend.
            ident: If given, a backend may use this as id_in_backend.
                :class:`~gpxity.Directory` does.
            attributes (set(str)): If given and the backend supports specific saving for all given attributes,
                save only those.
                Otherwise, save the entire activity.

        Returns:
            ~gpxity.Activity: The saved activity. If the original activity lives in a different
            backend, a new activity living in that backend will be created
            and returned.
        """

        # pylint: disable=too-many-branches

        if activity.is_decoupled:
            raise Exception('A backend cannot save() if activity.is_decoupled. This is probably a bug in gpxity.')
        try:
            self.matches(activity, 'save')
        except Backend.NoMatch:
            if activity.backend is not None:
                # it already exists in the backend, reset to correct values
                self._read_all(activity)
                self.matches(activity) # should always be the case
            raise
        if activity.backend is not self and activity.backend is not None:
            activity = activity.clone()
        if activity.backend is None:
            self._next_id = ident
            activity.backend = self
            # this calls us again!
            return activity

        fully = False
        if attributes is None or attributes == set(['all']) or self._next_id:
            fully = True
        else:
            for attribute in attributes:
                write_name = '_write_{}'.format(attribute.split(':')[0])
                if write_name not in self.supported:
                    fully = True
                    break

        if fully:
            activity_id = ident or self._next_id or activity.id_in_backend
            if activity_id is not None and not isinstance(activity_id, str):
                raise Exception('{}: id_in_backend must be str')
            self._write_all(activity, ident or self._next_id)
        else:
            for attribute in attributes:
                _ = attribute.split(':')
                write_name = '_write_{}'.format(_[0])
                if len(_) == 1:
                    getattr(self, write_name)(activity)
                else:
                    getattr(self, write_name)(activity, ''.join(_[1:]))
        if not self._has_item(activity.id_in_backend):
            self.append(activity)
        return activity

    def _write_all(self, activity, ident: str = None) ->None:
        """the actual implementation for the concrete Backend"""
        raise NotImplementedError()

    def remove(self, value) ->None:
        """Removes activity. This can also be done for activities
        not passing the current match function.

        Args:
            value: If it is not an :class:`~gpxity.Activity`, :meth:`remove` looks
                it up by doing :literal:`self[value]`
        """

        activity = value if hasattr(value, 'id_in_backend') else self[value]
        self._remove_activity(activity)
        self.__activities.remove(activity)
        activity.id_in_backend = None

    def _remove_activity(self, activity) ->None:
        """backend dependent implementation"""
        raise NotImplementedError()

    def _track(self, activity, points):
        """Modelled after MapMyTracks. I hope this matches other
        services too.

        This will always produce a new activity in the backend.supported

        Args:
            activity(Activity): Holds initial data
            points: If None, stop tracking. Otherwise, start tracking
                and add points.

        For details see :meth:`Activity.track() <gpxity.Activity.track>`.

        """
        raise NotImplementedError()

    def remove_all(self):
        """Removes all activities we know about. If their :attr:`id_in_backend`
        has meanwhile been changed through another backend instance
        or another process, we cannot find it anymore. We do **not**
        rescan all activities in the backend. If you want to make sure it
        will be empty, call :meth:`scan` first.

        If you use a match function, only matching activities will be removed."""
        for activity in list(self):
            if self.matches(activity):
                self.remove(activity)

    def sync_from(self, from_backend, remove: bool = False,
                  use_remote_ident: bool = False, verbose: bool = False) ->None:
        """Copies all activities into this backend.

        Args:
            from_backend (Backend): The source of the activities
            remove: If True, remove activities in self which do not exist in from_backend
            use_remote_ident: If True, uses the remote id for our id_in_backend. This
                may or may not be honoured by the backend. Directory does.
        """
        for activity in from_backend:
            if use_remote_ident and activity.id_in_backend in self:
                self.remove(self[activity.id_in_backend])
            else:
                for mine in self:
                    if mine.time == activity.time:
                        self.remove(mine)
            self.save(activity, ident=activity.id_in_backend if use_remote_ident else None)
            if verbose:
                print('saved', activity)
        if remove:
            differ = BackendDiff(self, from_backend)
            for activities in differ.left.exclusive.values():
                for activity in activities:
                    self.remove(activity)

    def destroy(self):
        """If `cleanup` was set at init time, removes all activities. Some backends
       (example: :class:`Directory <gpxity.Directory.destroy>`)
       may also remove the account (or directory). See also :meth:`remove_all`."""
        if self._cleanup:
            self.remove_all()

    def __contains__(self, value) ->bool:
        """value is either an an activity or an activity id.
        Does NOT load activities, only checks what is already known."""
        self._scan()
        return self._has_item(value)

    def _has_item(self, index) ->bool:
        """like __contains__ but for internal use: does not call _scan first.
        Must not call self._scan."""
        if hasattr(index, 'id_in_backend') and index in self.__activities:
            return True
        if isinstance(index, str) and index in list(x.id_in_backend for x in self.__activities):
            return True
        return False

    def __getitem__(self, index):
        """Allows accesses like alist[a_id]. Do not call this when implementing
        a backend because this always calls scan() first. Instead use :meth:`_has_item`."""
        self._scan()
        if isinstance(index, int):
            return self.__activities[index]
        for _ in self.__activities:
            if _ is index or _.id_in_backend == index:
                return _
        raise IndexError

    def __len__(self):
        """do not call this when implementing a backend because this calls scan()"""
        self._scan()
        return len(self.__activities)

    def real_len(self):
        """len(backend) without calling scan() first"""
        return len(self.__activities)

    def append(self, value):
        """Appends an activity to the cached list."""
        self.matches(value, 'append')
        self.__activities.append(value)
        if value.id_in_backend is not None and not isinstance(value.id_in_backend, str):
            raise Exception('{}: id_in_backend must be str'.format(value))

    def __repr__(self):
        """do not call len(self) because that does things"""
        result = '{}({} in {}{})'.format(
            self.__class__.__name__, len(self.__activities), self.url, ' ' + self.auth[0] if self.auth else '')
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, trback):
        self.destroy()

    def __iter__(self):
        self._scan()
        return iter(self.__activities)

    def __eq__(self, other):
        """True if both backends have the same activities."""
        self._scan()
        other._scan() # pylint: disable=protected-access
        return set(x.key() for x in self) == set(x.key() for x in other)
