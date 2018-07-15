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
from .track import Track

__all__ = ['Backend']


class Backend:
    """A place where tracks live. Something like the filesystem or
    http://mapmytracks.com.

    A Backend should hold only tracks for one person, and they
    should not overlap in time. This is not enforced but sometimes
    behaviour is undefined if you ignore this.

    A Backend be used as a context manager. Upon termination, all tracks
    may be removed automatically by setting cleanup=True. Some concrete
    implementations may also remove the backend itself.

    A Backend allows indexing by normal int index, by :class:`Track <gpxity.Track>`
    and by :attr:`Track.id_in_backend <gpxity.Track.id_in_backend>`.
    :literal:`if 'ident' in backend` is possible.
    len(backend) shows the number of tracks. Please note that Code
    like :literal:`if backend:` may not behave as expected. This will be False if the backend
    has no track. If that is not what you want, consider :literal:`if backend is not None`

    The backend will automatically synchronize. So something like :literal:`len(Backend())` will work.
    However, some other Backend pointing to the same storage or even a different process
    might change things. If you want to cope with that, use :meth:`scan`.

    Not all backends support all methods. The unsupported methods
    will raise NotImplementedError. As a convenience every backend
    has a list **supported** to be used like :literal:`if 'track' in backend.supported:`
    where `track` is the name of the method.

    Backends support no locking. If others modify a backend concurrently, you may
    get surprises. It is up to you to handle those.

    Some backends may use cookies.

    Args:
        url (str): Initial value for :attr:`url`
        auth (tuple(str, str)): (username, password). Alternatively you can pass the username as a single string.
            This will lookup the password from :class:`Authenticate <gpxity.auth.Authenticate>`.
        cleanup (bool): If true, :meth:`destroy` will remove all tracks.

    Attributes:
        supported (set(str)): The names of supported methods. Creating the first instance of
            the backend initializes this. Only methods which may not be supported are mentioned here.
            Those are: remove, lifetrack, get_time, _write_title, _write_public, _write_category,
            _write_gpx, _write_description, _write_keywords, _write_add_keyword, _write_remove_keyword.
            If a particular _write_* like _write_public does not exist, the entire track is written instead
            which normally results in a new ident for the track.
        url (str): the address. May be a real URL or a directory, depending on the backend implementation.
            Every implementation may define its own default for url.
        debug: If True, print debugging information
        timeout: If None, there are no timeouts: Gpxity waits forever. For legal values
            see http://docs.python-requests.org/en/master/user/advanced/#timeouts
    """

    class NoMatch(Exception):
        """Is raised if a track is expected to pass the match filter but does not"""

    class BackendException(Exception):
        """Is raised for general backend exceptions, especially error messages from a remote server"""


    supported = None

    skip_test = False

    _legal_categories = None # Override in the backends

    def __init__(self, url: str = None, auth=None, cleanup: bool = False, debug: bool = False, timeout=None):
        self._decoupled = False
        super(Backend, self).__init__()
        self.__tracks = list()
        self._tracks_fully_listed = False
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
        self.__debug = None
        self.debug = debug
        self.timeout = timeout

    def identifier(self):
        """Used for formatting strings"""
        return '{}:{}/'.format(
            self.__class__.__name__.lower(),
            self.auth[0] if self.auth and self.auth[0] else '')

    @property
    def legal_categories(self):
        """
        Returns: list(str)
            all legal values for this backend
        """
        raise NotImplementedError

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
            # map internal names to more user friendly ones. See doc for
            # Backend.supported.
            '_remove_ident':'remove',
            '_lifetrack':'lifetrack',
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
            this with every track and ignore tracks where match does not return None.
            The returned str should explain why the track does not match.

            If you change a track such that it does not match anymore, the exception
            NoMatch will be raised and the match stays unchanged.
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

    def decode_category(self, value: str) ->str:
        """Translate the value from the backend into internal one."""
        raise NotImplementedError

    def encode_category(self, value: str) ->str:
        """Translate internal value into the backend specific value."""
        raise NotImplementedError

    def get_time(self) ->datetime.datetime:
        """get time from the server where backend is located as a Linux timestamp.
        A backend implementation does not have to support this."""
        raise NotImplementedError()

    def _change_id(self, track, new_ident: str):
        """Changes the id in the backend."""
        raise NotImplementedError

    def scan(self, now: bool = False) ->None:
        """Enforces a reload of the list of all tracks in the backend.
        This will be delayed until the list is actually needed again.

        If this finds an unsaved track not matching the current match
        function, an exception is thrown.
        Saved Tracks not matching the current match will no be loaded.

        Args:
            now: If True, do not delay scanning.
        """
        self._tracks_fully_listed = False
        if now:
            self._scan()

    def _scan(self) ->None:
        """loads the list of all tracks in the backend if not yet done.
        Enforce this by calling :meth:`scan` first.
        """
        if not self._tracks_fully_listed and not self._decoupled:
            self._tracks_fully_listed = True
            unsaved = list(x for x in self.__tracks if x.id_in_backend is None)
            if self.__match is not None:
                for track in unsaved:
                    self.matches(track, 'scan')
            self.__tracks = unsaved
            match_function = self.__match
            self.__match = None
            try:
                # _yield_tracks should return ALL tracks, match will be
                # applied in a second loop. This way the Backend implementations
                # do not have to worry about the match code.
                with self._decouple():
                    list(self._yield_tracks())
            finally:
                self.__match = match_function
            if self.__match is not None:
                self.__tracks = list(x for x in self.__tracks if self.matches(x))

    def _found_track(self, ident: str):
        """Creates an empty track for ident and inserts it into this backend."""
        result = Track()
        with self._decouple():
            result._set_backend(self)  # pylint: disable=protected-access
            result.id_in_backend = ident
        self.append(result)
        return result

    def _yield_tracks(self):
        """A generator for all tracks. It yields the next found and appends it to tracks.
        The tracks will not be loaded if possible.

        Yields:
            the next track
        """
        raise NotImplementedError()

    def _read_all_decoupled(self, track) ->None:
        """Decouples and calls the backend specific _read_all"""
        with self._decouple():
            self._read_all(track)

    def _read_all(self, track) ->None:
        """fills the track with all its data from source"""
        raise NotImplementedError()

    def matches(self, track, exc_prefix: str = None):
        """Does track match the current match function?

        Args:
            exc_prefix: If not None, use it for the beginning of an exception message.
                If None, never raise an exception
        """
        if self.__match is None:
            return True
        match_error = self.__match(track)
        if match_error and exc_prefix:
            raise Backend.NoMatch('{}: {} does not match: {}'.format(exc_prefix, track, match_error))
        return match_error is None

    def _needs_full_save(self, attributes) ->bool:
        """Do we have to rewrite the entire track?"""
        for attribute in attributes:
            if attribute == 'all':
                return True
            write_name = '_write_{}'.format(attribute.split(':')[0])
            if write_name not in self.supported:
                return True
        return False

    def add(self, track, ident: str = None):
        """        We do not check if it already exists in this backend. No track
        already existing in this backend will be overwritten, the id_in_backend
        of track will be deduplicated if needed. This is currently only needed
        for Directory. Note that some backends reject a track if it is very
        similar to an existing track even if it belongs to some other user.

        If the track does not pass the current match function, raise an exception.

        Args:
            track (~gpxity.Track): The track we want to save in this backend.
            ident: If given, a backend may use this as id_in_backend.
                :class:`~gpxity.Directory` might but it will prefer the id_in_backend the
                track might already have. Other backends always create their own new
                unique identifier when the full track is saved/uploaded.

        Returns:
            ~gpxity.Track: The saved track. If the original track lives in a different
            backend, a new track living in this backend will be created
            and returned.
        """
        if self._decoupled:
            raise Exception('A backend cannot save() while being decoupled. This is probably a bug in gpxity.')

        self.matches(track, 'add')
        if track.backend is not self and track.backend is not None:
            new_track = track.clone()
        else:
            new_track = track
        with self._decouple():
            new_track._set_backend(self)  # pylint: disable=protected-access

        try:
            with self._decouple():
                self._write_all(new_track, ident)
            self.append(new_track)
            track._clear_dirty()  # pylint: disable=protected-access
            return new_track
        except Exception:
            # do not do self.remove. If we try to upload the same track to gpsies,
            # gpsies will assign the same trackid, and we come here. __tracks will
            # only hold the first uploaded track, and remove would remove that
            # instance instead of this one.
            self.__tracks = list(x for x in self.__tracks if x is not new_track)
            with self._decouple():
                new_track.id_in_backend = None
                new_track._set_backend(None)  # pylint: disable=protected-access
            raise
        return new_track

    def _new_ident(self, track) ->str:
        """Creates an id for track.

        Returns: The new ident. If the backend does not
        create an ident in advance, return None. Such
        backends will return a new ident after writing.
        """

    def _rewrite(self, track, attributes):
        """Rewrites the full track.

        Used only by Track when things change.
        """
        assert track.backend is self
        assert self._has_item(track.id_in_backend), '{} not in {}'.format(track, ' / '.join(str(x) for x in self))
        assert track._dirty  # pylint: disable=protected-access

        needs_full_save = self._needs_full_save(attributes)

        self.matches(track, '_rewrite')
        if needs_full_save:
            new_id = self._write_all(track)
            track.id_in_backend = new_id
        else:
            for attribute in attributes:
                _ = attribute.split(':')
                write_name = '_write_{}'.format(_[0])
                if len(_) == 1:
                    getattr(self, write_name)(track)
                else:
                    getattr(self, write_name)(track, ''.join(_[1:]))
        return track

    def _write_all(self, track, new_ident: str = None) ->str:
        """the actual implementation for the concrete Backend.
        Writes the entire Track.

        Returns:
            The new id_in_backend
        """
        raise NotImplementedError()

    def remove(self, value) ->None:
        """Removes track. This can also be done for tracks
        not passing the current match function.

        Args:
            value: If it is not an :class:`~gpxity.Track`, :meth:`remove` looks
                it up by doing :literal:`self[value]`
            new_ident: The backend may use this if it is able to create its own idents.
        """

        track = value if hasattr(value, 'id_in_backend') else self[value]
        if track.id_in_backend:
            self._remove_ident(track.id_in_backend)
        with self._decouple():
            track._set_backend(None)  # pylint: disable=protected-access
            try:
                self.__tracks.remove(track)
            except ValueError:
                pass

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation"""
        raise NotImplementedError()

    def _lifetrack(self, track, points):
        """Modelled after MapMyTracks. I hope this matches other
        services too.

        This will always produce a new track in the backend.supported

        Args:
            track(Track): Holds initial data
            points: If None, stop tracking. Otherwise, start tracking
                and add points.

        For details see :meth:`Track.track() <gpxity.Track.track>`.

        """
        raise NotImplementedError()

    def remove_all(self):
        """Removes all tracks we know about. If their :attr:`id_in_backend`
        has meanwhile been changed through another backend instance
        or another process, we cannot find it anymore. We do **not**
        rescan all tracks in the backend. If you want to make sure it
        will be empty, call :meth:`scan` first.

        If you use a match function, only matching tracks will be removed."""
        for track in list(self):
            if self.matches(track):
                self.remove(track)

    def destroy(self):
        """If `cleanup` was set at init time, removes all tracks. Some backends
       (example: :class:`Directory <gpxity.Directory.destroy>`)
       may also remove the account (or directory). See also :meth:`remove_all`."""
        if self._cleanup:
            self.remove_all()

    def __contains__(self, value) ->bool:
        """value is either an a track or a track id.
        Does NOT load tracks, only checks what is already known."""
        self._scan()
        return self._has_item(value)

    def _has_item(self, index) ->bool:
        """like __contains__ but for internal use: does not call _scan first.
        Must not call self._scan."""
        if hasattr(index, 'id_in_backend') and index in self.__tracks:
            return True
        if isinstance(index, str) and index in list(x.id_in_backend for x in self.__tracks):
            return True
        return False

    def __getitem__(self, index):
        """Allows accesses like alist[a_id]. Do not call this when implementing
        a backend because this always calls scan() first. Instead use :meth:`_has_item`."""
        self._scan()
        if isinstance(index, int):
            return self.__tracks[index]
        for _ in self.__tracks:
            if _ is index or _.id_in_backend == index:
                return _
        raise IndexError

    def __len__(self):
        """do not call this when implementing a backend because this calls scan()"""
        self._scan()
        return len(self.__tracks)

    def real_len(self):
        """len(backend) without calling scan() first"""
        return len(self.__tracks)

    def append(self, value):
        """Appends a track to the cached list."""
        if value.id_in_backend is not None and not isinstance(value.id_in_backend, str):
            raise Exception('{}: id_in_backend must be str'.format(value))
        self.matches(value, 'append')
        self.__tracks.append(value)

    def __repr__(self):
        """do not call len(self) because that does things"""
        dirname = ''
        if self.auth:
            dirname = self.auth[0] or ''
        result = '{}({} in {}{})'.format(
            self.__class__.__name__, len(self.__tracks), self.url, dirname)
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, trback):
        self.destroy()

    def __iter__(self):
        self._scan()
        return iter(self.__tracks)

    def __eq__(self, other):
        """True if both backends have the same tracks."""
        self._scan()
        other._scan() # pylint: disable=protected-access
        return set(x.key() for x in self) == set(x.key() for x in other)

    def merge(self, other, remove: bool = False, dry_run: bool = False, copy: bool = False) ->list:
        """merge other backend or a single track into this one.
        If two tracks have identical points, or-ify their other attributes.
        Args:
            other: The backend or a single track to be merged
            remove: If True, remove merged tracks
            dry_run: If True, do not really merge or remove
            copy: Do not try to find a matching track, just copy other into this Backend
        Returns: list(str) A list of messages for verbose output
        """
        # pylint: disable=too-many-branches,too-many-locals
        # TODO: test for dry_run
        # TODO: test for merging single track
        # TODO: test for merging a backend or a track with itself. Where
        # they may be identical instantiations or not. For all backends.
        result = list()
        src_dict = defaultdict(list)
        if isinstance(other, Track):
            other_tracks = [other]
            other_backend = other.backend
        else:
            other_tracks = list(other)
            other_backend = other
        if copy:
            for old_track in other_tracks:
                if not dry_run:
                    new_track = self.add(old_track)
                result.append('{} {} -> {} {}'.format(
                    'blind move' if remove else 'blind copy', old_track, self,
                    '' if dry_run else ' / ' + new_track.id_in_backend))
                if remove:
                    if not dry_run:
                        other_backend.remove(old_track)
            return result

        for _ in other_tracks:
            src_dict[_.points_hash()].append(_)
        if other_backend.url == self.url and other_backend.auth == self.auth:
            dst_dict = src_dict
        else:
            dst_dict = defaultdict(list)
            for _ in self:
                dst_dict[_.points_hash()].append(_)

        # 1. get all tracks existing only in other
        for point_hash in sorted(set(src_dict.keys()) - set(dst_dict.keys())):
            # but only the first one of those with same points
            src_tracks = src_dict[point_hash]
            old_track = src_tracks[0]

            if not dry_run:
                new_track = self.add(old_track)
            result.append('{} {} -> {} {}'.format(
                'move' if remove else 'copy', old_track, self,
                '' if dry_run else ' / ' + new_track.id_in_backend))
            if remove:
                if not dry_run:
                    other_backend.remove(old_track)
            del src_tracks[0]

        # 2. merge the rest
        for point_hash in sorted(set(src_dict.keys()) & set(dst_dict.keys())):
            if dst_dict is src_dict:
                sources = src_dict[point_hash][1:]
            else:
                sources = src_dict[point_hash]     # no need to copy the list
                sources.extend(dst_dict[point_hash][1:])
            sources = sorted(sources)
            target = dst_dict[point_hash][0]
            for source in sources:
                result.extend(target.merge(source, remove=remove, dry_run=dry_run))
        return result

    @staticmethod
    def _html_encode(value):
        """encodes str to something gpies.com accepts"""
        if value is None:
            return ''
        return value.encode('ascii', 'xmlcharrefreplace').decode()
