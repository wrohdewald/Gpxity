#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.Backend`."""

import datetime
from inspect import getmembers, isfunction
import dis
from contextlib import contextmanager
from collections import defaultdict
import logging
from http.client import HTTPConnection

from .auth import Authenticate
from .track import Track
from .util import collect_tracks

__all__ = ['Backend']


class Backend:

    """A place where tracks live. Something like the filesystem or http://mapmytracks.com.

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
            If a particular value write_* like write_public does not exist, the entire track is written instead
            which normally results in a new ident for the track.
        full_support (set(str)): All possible values for the supported attribute.
        url (str): the address. May be a real URL or a directory, depending on the backend implementation.
            Every implementation may define its own default for url.
        debug: If True, print debugging information
        timeout: If None, there are no timeouts: Gpxity waits forever. For legal values
            see http://docs.python-requests.org/en/master/user/advanced/#timeouts
        verify: True, False or the name of a local cert file

    """

    # pylint: disable=too-many-instance-attributes

    class NoMatch(Exception):
        """Is raised if a track is expected to pass the match filter but does not"""

    class BackendException(Exception):
        """Is raised for general backend exceptions, especially error messages from a remote server"""

    supported = None

    skip_test = False

    _legal_categories = None  # Override in the backends

    default_url = None  # Override in the backends

    full_support = (
        'scan', 'remove', 'lifetrack', 'get_time', 'write', 'write_title', 'write_public', 'write_category',
        'write_gpx', 'write_description', 'write_add_keywords', 'write_remove_keywords')

    # It is important that we have only one global session per identifier()
    # because gpsies.com seems to have several servers and their
    # synchronization is sometimes slower than expected. See
    # cookie "SERVERID".
    _session = dict()

    def __init__(self, url: str = None, auth=None, cleanup: bool = False,
                 debug: bool = False, timeout=None, verify=True):
        """See class docstring."""
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
        self.verify = verify
        self._current_track = None

    def identifier(self, track=None) ->str:
        """Used for formatting strings. A unique identifier for every physical backend.

        Two Backend() instances pointing to the same physical backend have the same identifier.

        Args:
            track: If given, add it to the identifier.

        Returns:
            A unique identifier

        """
        result = '{}:{}{}/'.format(
            self.__class__.__name__.lower(),
            '' if self.url == self.default_url else self.url,
            self.auth[0] if self.auth and self.auth[0] else '')
        if track:
            result += track.id_in_backend
        return result

    @property
    def legal_categories(self):
        """
        A list with all legal categories.

        Returns: list(str)
            all legal values for this backend

        """
        raise NotImplementedError

    @contextmanager
    def _decouple(self):
        """Context manager: disable automic synchronization with the backend.

        In that state, automatic writes of changes into
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
    def _is_implemented(cls, method) ->bool:
        """False if the first instruction in method raises NotImplementedError or if the method does nothing.

        Returns:
            True if method is implemented

        """
        first_instruction = next(dis.get_instructions(method.__code__))
        return first_instruction is not None and first_instruction.argval != 'NotImplementedError'

    @classmethod
    def _define_support(cls):
        """If the first thing a method does is raising NotImplementedError, it is marked as unsupported."""
        support_mappings = {
            # map internal names to more user friendly ones. See doc for
            # Backend.supported.
            '_lifetrack_start': 'lifetrack',
            '_remove_ident': 'remove',
            '_write_all': 'write',
            '_yield_tracks': 'scan',
            'get_time': 'get_time'}
        cls.supported = set()
        for name, method in getmembers(cls, isfunction):
            if name in support_mappings:
                if cls._is_implemented(method):
                    cls.supported.add(support_mappings[name])
            elif name.startswith('_write_') and name != '_write_attribute':
                if cls._is_implemented(method):
                    cls.supported.add(name[1:])

    @property
    def debug(self) ->bool:
        """True: output HTTP debugging data to stdout.
        Returns:
            True if debug is active"""
        return self.__debug

    @debug.setter
    def debug(self, value):
        """see debug.getter."""
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
        """Filter tracks.

        A function with one argument returning None or str. The backend will call
            this with every track and ignore tracks where match does not return None.
            The returned str should explain why the track does not match.

            If you change a track such that it does not match anymore, the exception
            NoMatch will be raised and the match stays unchanged.

        """
        return self.__match

    @match.setter
    def match(self, value):
        """see match.getter."""
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

    @staticmethod
    def _encode_keyword(value: str) ->str:
        """Replicate the translation the backend does. MMT for example capitalizes all words.

        Returns:
            the encoded keyword

        """
        return value

    def get_time(self) ->datetime.datetime:
        """get time from the server where backend is located as a Linux timestamp.
        A backend implementation does not have to support this."""
        raise NotImplementedError()

    def _change_id(self, track, new_ident: str):
        """Change the id in the backend."""
        raise NotImplementedError

    def scan(self, now: bool = False) ->None:
        """Enforce a reload of the list of all tracks in the backend.

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
        """load the list of all tracks in the backend if not yet done.
        Enforce this by calling :meth:`scan` first.
        """
        if not self._tracks_fully_listed and not self._decoupled:
            self._tracks_fully_listed = True
            unsaved = [x for x in self.__tracks if x.id_in_backend is None]
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
                self.__tracks = [x for x in self.__tracks if self.matches(x)]

    def _found_track(self, ident: str):
        """Create an empty track for ident and inserts it into this backend.

        Returns:
            the new track

        """
        result = Track()
        with self._decouple():
            result._set_backend(self)  # pylint: disable=protected-access
            result.id_in_backend = ident
        self.__append(result)
        return result

    def _yield_tracks(self):
        """A generator for all tracks. It yields the next found and appends it to tracks.

        The tracks will not be loaded if possible.

        Yields:
            the next track

        """
        raise NotImplementedError()

    def _read_all_decoupled(self, track) ->None:
        """Decouple and calls the backend specific _read_all."""
        with self._decouple():
            self._read_all(track)

    def _read_all(self, track) ->None:
        """fill the track with all its data from source."""
        raise NotImplementedError()

    def matches(self, track, exc_prefix: str = None):
        """match track against the current match function.

        Args:
            exc_prefix: If not None, use it for the beginning of an exception message.
                If None, never raise an exception

        Returns:
            True for match

        """
        if self.__match is None:
            return True
        match_error = self.__match(track)
        if match_error and exc_prefix:
            raise Backend.NoMatch('{}: {} does not match: {}'.format(exc_prefix, track, match_error))
        return match_error is None

    def _needs_full_save(self, changes) ->bool:
        """Do we have to rewrite the entire track?.

        Returns:
            True if we must save fully

        """
        for change in changes:
            if change == 'all':
                return True
            write_name = 'write_{}'.format(change.split(':')[0])
            if write_name not in self.supported:
                return True
        return False

    def add(self, track):
        """
        Add a track to this backend.

        We do not check if it already exists in this backend. No track
        already existing in this backend will be overwritten, the id_in_backend
        of track will be deduplicated if needed. This is currently only needed
        for Directory. Note that some backends reject a track if it is very
        similar to an existing track even if it belongs to some other user.

        If the track object is already in the list of tracks, raise ValueError.

        If the track does not pass the current match function, raise an exception.

        Args:
            track (~gpxity.Track): The track we want to save in this backend.

        Returns:
            ~gpxity.Track: The saved track. If the original track lives in a different
            backend, a new track living in this backend will be created
            and returned.

        """
        if self._decoupled:
            raise Exception('A backend cannot save() while being decoupled. This is probably a bug in gpxity.')
        self._current_track = track
        self.matches(track, 'add')
        if track.backend is not self and track.backend is not None:
            new_track = track.clone()
        else:
            if any(x is track for x in self.__tracks):
                raise ValueError('Already in list: Track {} with id={}'.format(track, id(track)))
            new_track = track
        with self._decouple():
            new_track._set_backend(self)  # pylint: disable=protected-access
            if track.keywords:
                _ = (x.strip() for x in track.keywords)
                track.gpx.keywords = ', '.join(self._encode_keyword(x) for x in _)
        try:
            with self._decouple():
                self._write_all(new_track)
            self.__append(new_track)
            track._clear_dirty()  # pylint: disable=protected-access
            return new_track
        except Exception:
            # do not do self.remove. If we try to upload the same track to gpsies,
            # gpsies will assign the same trackid, and we come here. __tracks will
            # only hold the first uploaded track, and remove would remove that
            # instance instead of this one.
            # TODO: do we have a unittest for that case?
            self.__tracks = [x for x in self.__tracks if x is not new_track]
            with self._decouple():
                new_track.id_in_backend = None
                new_track._set_backend(None)  # pylint: disable=protected-access
            raise
        return new_track

    def _new_ident(self, track) ->str:
        """Create an id for track.

        Returns:
            The new ident. If the backend does not
            create an ident in advance, return None. Such
            backends will return a new ident after writing.

        """

    def _rewrite(self, track, changes):
        """Rewrite the full track.

        Used only by Track when things change.

        """
        self._current_track = track
        assert track.backend is self
        assert self._has_item(track.id_in_backend), '{}: its id_in_backend {} is not in {}'.format(
            track, track.id_in_backend, ' / '.join(str(x) for x in self))
        assert track._dirty  # pylint: disable=protected-access

        needs_full_save = self._needs_full_save(changes)

        self.matches(track, '_rewrite')
        if needs_full_save:
            new_id = self._write_all(track)
            track.id_in_backend = new_id
        else:
            for change in changes:
                _ = change.split(':')
                write_name = '_write_{}'.format(_[0])
                if len(_) == 1:
                    getattr(self, write_name)(track)
                elif len(_) == 2:
                    getattr(self, write_name)(track, _[1])
                else:
                    raise Exception('dirty {} got too many arguments:{}'.format(write_name, _[1:]))

    def _write_all(self, track) ->str:
        """the actual implementation for the concrete Backend.

        Writes the entire Track.

        Returns:
            The new id_in_backend

        """
        raise NotImplementedError()

    def remove(self, value) ->None:
        """
        Remove track. This can also be done for tracks not passing the current match function.

        Args:
            value: If it is not an :class:`~gpxity.Track`, :meth:`remove` looks
                it up by doing :literal:`self[value]`

        """
        track = value if hasattr(value, 'id_in_backend') else self[value]
        self._current_track = track
        if track.id_in_backend:
            self._remove_ident(track.id_in_backend)
        with self._decouple():
            track._set_backend(None)  # pylint: disable=protected-access
            try:
                self.__tracks = [x for x in self.__tracks if x.id_in_backend != track.id_in_backend]
            except ValueError:
                pass

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation."""
        raise NotImplementedError()

    def _lifetrack_start(self, track, points):
        """Modelled after MapMyTracks. I hope this matches other services too.

        This will always produce a new track in the backend.supported

        If the backend does not support lifetrack, just add the points
        to the track.

        Args:
            track(Track): Holds initial data
            points: If None, stop tracking. Otherwise, start tracking
                and add points.

        For details see :meth:`Track.track() <gpxity.Track.track>`.

        """
        raise NotImplementedError()

    def _lifetrack_update(self, track, points):
        """If the backend does not support lifetrack, just add the points to the track.

        Args:
            track(Track): Holds initial data
            points: If None, stop tracking. Otherwise, start tracking
                and add points.

        For details see :meth:`Track.track() <gpxity.Track.track>`.

        """
        raise NotImplementedError()

    def _lifetrack_end(self, track):
        """If the backend does not support lifetrack, do nothing."""
        raise NotImplementedError()

    def remove_all(self):
        """Remove all tracks we know about.

        If their :attr:`id_in_backend` has meanwhile been changed
        through another backend instance or another process, we
        cannot find it anymore. We do **not** rescan all tracks in the backend.
        If you want to make sure it will be empty, call :meth:`scan` first.

        If you use a match function, only matching tracks will be removed."""
        for track in list(self):
            if self.matches(track):
                self.remove(track)

    def destroy(self):
        """If `cleanup` was set at init time, removes all tracks.

        Some backends (example: :class:`Directory <gpxity.Directory.destroy>`)

        may also remove the account (or directory). See also :meth:`remove_all`."""
        if self._cleanup:
            self.remove_all()

    def __contains__(self, value) ->bool:
        """value is either an a track or a track id.

        Does NOT load tracks, only checks what is already known.

        Returns:
            True if we have the item

        """
        self._scan()
        return self._has_item(value)

    def _has_item(self, index) ->bool:
        """like __contains__ but for internal use: does not call _scan first.

        Must not call self._scan.

        Returns:
            True if we have the item

        """
        if hasattr(index, 'id_in_backend') and index in self.__tracks:
            return True
        if isinstance(index, str) and index in [x.id_in_backend for x in self.__tracks]:
            return True
        return False

    def __getitem__(self, index):
        """Allow accesses like alist[a_id].

        Do not call this when implementing a backend because this always calls scan() first.

        Instead use :meth:`_has_item`.

        Returns:
            the track

        """
        self._scan()
        if isinstance(index, int):
            return self.__tracks[index]
        for _ in self.__tracks:
            if _ is index or _.id_in_backend == index:
                return _
        raise IndexError

    def __len__(self) ->int:
        """do not call this when implementing a backend because this calls scan().

        Returns:
            the length

        """
        self._scan()
        return len(self.__tracks)

    def real_len(self) ->int:
        """len(backend) without calling scan() first.

        Returns:

            the length"""
        return len(self.__tracks)

    def __append(self, track):
        """Append a track to the cached list."""
        self._current_track = track
        if track.id_in_backend is not None and not isinstance(track.id_in_backend, str):
            raise Exception('{}: id_in_backend must be str'.format(track))
        if track.id_in_backend is not None and any(x.id_in_backend == track.id_in_backend for x in self.__tracks):
            # cannot do "in self" because we are not decoupled, so that would call _scan()
            raise ValueError(
                'Backend.append(track): its id_in_backend {} is already in list: Track={}, list={}'.format(
                    track.id_in_backend, self[track.id_in_backend], self.__tracks))
        self.matches(track, 'append')
        self.__tracks.append(track)

    def __repr__(self):
        """do not call len(self) because that does things.

        Returns:
            The repr str

        """
        dirname = ''
        if self.auth:
            dirname = self.auth[0] or ''
        result = '{}({} in {}{})'.format(
            self.__class__.__name__, len(self.__tracks), self.url, dirname)
        return result

    def __enter__(self):
        """See class docstring.

        Returns:
            self

        """
        return self

    def __exit__(self, exc_type, exc_value, trback):
        """See class docstring."""
        self.destroy()

    def __iter__(self):
        """See class docstring.

        Returns:
            iterator over tracks

        """
        self._scan()
        return iter(self.__tracks)

    def __eq__(self, other) ->bool:
        """True if both backends have the same tracks.

        Returns:
            True if both backends have the same tracks

        """
        self._scan()
        other._scan()  # pylint: disable=protected-access
        return {x.key() for x in self} == {x.key() for x in other}

    def __copy(self, other_tracks, remove, dry_run):
        """Copy other_tracks into self. Used only by self.merge().

        Returns:
            verbose messages

        """
        result = list()
        for old_track in other_tracks:
            if not dry_run:
                new_track = self.add(old_track)
            result.append('{} {} -> {}'.format(
                'blind move' if remove else 'blind copy', old_track.identifier(),
                '' if dry_run else new_track.identifier()))
            if remove and not dry_run:
                old_track.remove()
        return result

    def merge(self, other, remove: bool = False, dry_run: bool = False, copy: bool = False) ->list:
        """merge other backend or a single track into this one.

        If two tracks have identical points, or-ify their other attributes.
        Args:
            other: The backend or a single track to be merged
            remove: If True, remove merged tracks
            dry_run: If True, do not really merge or remove
            copy: Do not try to find a matching track, just copy other into this Backend

        Returns:
            list(str) A list of messages for verbose output

        """
        # pylint: disable=too-many-branches,too-many-locals
        # TODO: test for dry_run
        # TODO: test for merging single track
        # TODO: test for merging a backend or a track with itself. Where
        # they may be identical instantiations or not. For all backends.
        result = list()
        other_tracks = collect_tracks(other)
        if copy:
            return self.__copy(other_tracks, remove, dry_run)

        src_dict = defaultdict(list)
        dst_dict = dict()
        for self_track in self:
            _ = self_track.points_hash()
            if _ not in dst_dict:
                dst_dict[_] = self_track
            else:
                src_dict[_].append(self_track)
        for _ in other_tracks:
            if _.backend.identifier() != self.identifier():
                src_dict[_.points_hash()].append(_)

        # 1. get all tracks existing only in other
        for point_hash in sorted(set(src_dict.keys()) - set(dst_dict.keys())):
            for old_track in src_dict[point_hash]:
                if not dry_run:
                    new_track = self.add(old_track)
                result.append('{} {} -> {}'.format(
                    'move' if remove else 'copy', old_track.identifier(),
                    new_track.identifier() if new_track else self.identifier()))
                if remove and not dry_run:
                    old_track.remove()

        # 2. merge the rest
        for point_hash in set(src_dict.keys()) & set(dst_dict.keys()):
            target = dst_dict[point_hash]
            for source in src_dict[point_hash]:
                result.extend(target.merge(source, remove=remove, dry_run=dry_run))
        return result

    @staticmethod
    def _html_encode(value) ->str:
        """encode str to something gpies.com accepts.

        Returns:
            the encoded value

        """
        if value is None:
            return ''
        return value.encode('ascii', 'xmlcharrefreplace').decode()
