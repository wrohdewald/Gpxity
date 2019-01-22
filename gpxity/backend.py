#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.backend.Backend`."""

# pylint: disable=protected-access

import datetime
from inspect import getmembers, isfunction
from contextlib import contextmanager
import logging
from copy import deepcopy

from .accounts import Account
from .track import Track, Fences
from .util import collect_tracks

from .backend_base import BackendBase
__all__ = ['Backend']


class Backend(BackendBase):

    """A place where tracks live. Something like the filesystem or http://mapmytracks.com.

    A Backend should hold only tracks for one person, and they
    should not overlap in time. This is not enforced but sometimes
    behaviour is undefined if you ignore this.

    A Backend be used as a context manager.

    A Backend allows indexing by normal int index, by :class:`Track <gpxity.track.Track>`
    and by :attr:`Track.id_in_backend <gpxity.track.Track.id_in_backend>`.
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
        auth (str):  The username.
            This will lookup the password and account from :class:`Authenticate <gpxity.auth.Authenticate>`.
            You can also pass a dict containing what would normally be obtained from
            :class:`Authenticate <gpxity.auth.Authenticate>`. The dict must also contain 'Username'.

    Attributes:
        supported (set(str)): The names of supported methods. Creating the first instance of
            the backend initializes this. Only methods which may not be supported are mentioned here.
            If a particular value write_* like write_public does not exist, the entire track is written instead
            which normally results in a new ident for the track.
        full_support (set(str)): All possible values for the supported attribute.
        url (str): the address. May be a real URL or a directory, depending on the backend implementation.
            Every implementation may define its own default for url. Must never end with '/' except for
            Directory(url='/').
        fences: The fences as found in account. You can programmatically change them but they will
            never be applied to already existing data.
        needs_config: If True, the Backend class expects data in auth.cfg
        account: A Section with all entries in auth.cfg for this backend
        account.fences: The backend will never write points within fences.
            You can define any number of fences separated by spaces. Every fence is a circle.
            It has the form Lat/Long/meter.
            Lat and Long are the center position in decimal degrees, meter is the radius.
        test_is_expensive: For internal use. If True, the self tests will reduce test cases and try to
            avoid too much usage of the backend.
        max_field_sizes: Some backends have a limited size for some attributes like keywords. This
            is only an approximative guess. The backend will not protect you from overriding it
            but the unittests will try to stay within those limits.
        point_precision: The precision supported by this backend. We are never more precise than 6.
            That is the digits after the decimal separator.
        supported_categories: The categories supported by this backend. The first one is used as default.

    """

    # pylint: disable=too-many-instance-attributes

    class NoMatch(Exception):
        """Is raised if a track is expected to pass the match filter but does not"""

    supported = set()

    default_url = None  # Override in the backends

    needs_config = True

    test_is_expensive = True

    max_field_sizes = {}

    _category_decoding = dict()
    _category_encoding = dict()

    full_support = (
        'scan', 'remove', 'write', 'write_title', 'write_public',
        'own_categories', 'rename',
        'write_category', 'write_description', 'keywords', 'write_add_keywords', 'write_remove_keywords')

    _max_length = dict()

    _default_public = False

    point_precision = 5

    _timeout = None

    __all_backends = dict()

    # It is important that we have only one global session
    # because gpsies.com seems to have several servers and their
    # synchronization is sometimes slower than expected. See
    # cookie "SERVERID".
    _session = dict()

    def __init__(self, account):
        """See class docstring."""
        if self.is_disabled():
            raise Backend.BackendException('class {} is disabled'.format(self.__class__.__name__))
        if not isinstance(account, Account):
            raise Exception('Backend() wants an Account')
        account.config = deepcopy(account.config)
        self.account = account
        if 'url' not in self.account.config:
            self.account.config['url'] = self.default_url
        if 'backend' not in self.account.config:
            self.account.config['backend'] = self.__class__.__name__
        self._decoupled = False
        self.__tracks = list()
        self._tracks_fully_listed = False
        self.__match = None
        self.logger = logging.getLogger(str(self))
        self.fences = Fences(self.account.fences)

    @property
    def timeout(self):
        """Timeout from account or class default.

        Returns: The timeout

        """
        return self.account.timeout or self._timeout

    @property
    def url(self):
        """get self.account.url.

        This also makes sure Backend.url is not writable.

        Returns: The url

        """
        return self.account.url

    def _has_default_url(self) ->bool:
        """Check if the backend has the default url.

        Returns:
            True if so

        """
        if self.default_url is None:
            return False
        return self.url == self.default_url

    def _get_author(self) ->str:
        """Get the username for the account.

        Raise BackendException if no username is given.

        Returns:
            The username

        """
        author = self.account.username
        if not author:
            raise Backend.BackendException('{} needs a username'.format(self.account))
        return author


    def __str__(self) ->str:
        """A unique identifier for every physical backend.

        Two Backend() instances pointing to the same physical backend have the same identifier.

        Returns:
            A unique identifier

        """
        return self.account.name

    supported_categories = Track.categories

    @contextmanager
    def _decouple(self):
        """Context manager: disable automic synchronization for the backend.

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

    @classmethod
    def _define_support(cls):
        """If the first thing a method does is raising NotImplementedError, it is marked as unsupported."""
        support_mappings = {
            # map internal names to more user friendly ones. See doc for
            # Backend.supported.
            '_load_track_headers': 'scan',
            '_change_ident': 'rename',
            '_remove_ident': 'remove',
            '_write_all': 'write'}
        cls.supported = set()
        cls.supported.add('keywords')  # default
        if cls.supported_categories != Track.categories:
            cls.supported.add('own_categories')
        for name, method in getmembers(cls, isfunction):
            if name in support_mappings:
                if cls._is_implemented(method):
                    cls.supported.add(support_mappings[name])
            elif name.startswith('_write_') and name != '_write_attribute':
                if cls._is_implemented(method):
                    cls.supported.add(name[1:])

    @classmethod
    def decode_category(cls, value: str) ->str:
        """Translate the value from the backend into one out of Track.categories.

        Returns:
            The decoded name

        """
        if value in Track.categories:
            return value
        if value == 'Mountain biking':
            # obsolete
            return 'Cycling - MTB'
        if value.capitalize() in Track.categories:
            return value.capitalize()
        if value not in cls._category_decoding:
            raise cls.BackendException('{} gave us an unknown track type "{}"'.format(cls.__name__, value))
        return cls._category_decoding[value]

    @classmethod
    def encode_category(cls, value: str) ->str:
        """Translate internal value (out of Track.categories) into the backend specific value.

        Returns:
            The encoded name

        """
        if value in cls.supported_categories:
            return value
        if value.lower() in cls.supported_categories:
            return value.lower()
        if value in cls._category_encoding:
            return cls._category_encoding[value]
        for key, target in cls._category_decoding.items():
            if value.lower() == target.lower():
                return key
        raise cls.BackendException('{} has no equivalent for "{}"'.format(cls.__name__, value))

    @staticmethod
    def _encode_keyword(value: str) ->str:
        """Replicate the translation the backend does. MMT for example capitalizes all words.

        Returns:
            the encoded keyword

        """
        return value

    @staticmethod
    def _encode_description(track) ->str:
        """A backend might put keywords into the description. WPTrackserver does.

        Returns: The string to be saved in the backend

        """
        return track.description

    def _decode_description(self, track, value, into_header_data=False):
        """A backend might put keywords into the description. WPTrackserver does.

        Returns: The description

        """
        assert self._decoupled
        if into_header_data:
            track._header_data['description'] = value
        else:
            track.description = value
        return value

    def get_time(self) ->datetime.datetime:  # pylint: disable=no-self-use
        """get time from the server where backend is located as a Linux timestamp.

        A backend implementation does not have to support this.

        Returns: datetime.datetime

        """
        return datetime.datetime.now()

    def _change_ident(self, track, new_ident: str):
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

    @property
    def is_scanned(self) ->bool:
        """Check if the backend has already been scanned for tracks.

        Returns: (bool)
            The answer

        """
        return self._tracks_fully_listed

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
            if 'scan' in self.supported:
                match_function = self.__match
                self.__match = None
                try:
                    # _load_track_headers loads ALL tracks, match will be
                    # applied in a second loop. This way the Backend implementations
                    # do not have to worry about the match code.
                    with self._decouple():
                        self._load_track_headers()
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
            result._set_backend(self)
            result.id_in_backend = ident
        self._append(result)
        return result

    def _load_track_headers(self):
        """Load all track headers and append them to the backend.

        The tracks will not be loaded if possible.

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
            track (~gpxity.track.Track): The track we want to save in this backend.

        Returns:
            ~gpxity.track.Track: The saved track. If the original track lives in a different
            backend, a new track living in this backend will be created
            and returned.

        """
        if self._decoupled:
            raise Exception('A backend cannot save() while being decoupled. This is probably a bug in gpxity.')
        self.matches(track, 'add')
        if track.backend is not self and track.backend is not None:
            with track.fenced(self.fences):
                new_track = track.clone()
        else:
            if any(x is track for x in self.__tracks):
                raise ValueError(
                    'Already in list: Track {} with id={}, have={}'.format(
                        track, id(track), ','.join(str(x) for x in self)))
            new_track = track
        try:
            with self._decouple():
                new_track._set_backend(self)
                self._write_all(new_track)
            self._append(new_track)
            track._clear_dirty()
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
                new_track._set_backend(None)
            raise

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
        assert track.backend is self
        assert self._has_item(track.id_in_backend), '{}: its id_in_backend {} is not in {}'.format(
            track, track.id_in_backend, ' / '.join(str(x) for x in self))
        assert track._dirty

        needs_full_save = self._needs_full_save(changes)

        self.matches(track, '_rewrite')
        if needs_full_save:
            with track.fenced(self.fences):
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
            value: If it is not an :class:`~gpxity.track.Track`, :meth:`remove` looks
                it up by doing :literal:`self[value]`

        """
        track = value if hasattr(value, 'id_in_backend') else self[value]
        if track.id_in_backend:
            self._remove_ident(track.id_in_backend)
        with self._decouple():
            track._set_backend(None)
            try:
                self.__tracks = [x for x in self.__tracks if x.id_in_backend != track.id_in_backend]
            except ValueError:
                pass

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation."""
        raise NotImplementedError()

    def _lifetrack_start(self, track, points) -> str:  # pylint: disable=unused-argument
        """Modelled after MapMyTracks. I hope this matches other services too.

        This will always produce a new track in the backend.

        Default is to just add the points to the track.

        Args:
            track(Track): Holds initial data and points already added.
                keep in mind that this process might restart which should
                be invisible to the target.
            points: Initial points

        Returns: The new id_in_backend

        For details see :meth:`Track.track() <gpxity.lifetrack.Lifetrack.start>`.

        """
        if track.id_in_backend not in self:
            track.id_in_backend = self.add(track.clone()).id_in_backend
        return track.id_in_backend

    def _lifetrack_update(self, track, points):
        """If the backend does not support lifetrack, just add the points to the track.

        Args:
            track(Track): Holds initial data
            points: If None, stop tracking. Otherwise, start tracking
                and add points.

        For details see :meth:`Track.track() <gpxity.lifetrack.Lifetrack.update>`.

        """
        self[track.id_in_backend].add_points(points)

    def _lifetrack_end(self, track):
        """Default: Nothing needs to be done."""

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

    def detach(self):
        """Should be called when access to the Backend is not needed anymore."""

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

    def _append(self, track):
        """Append a track to the cached list."""
        if track.id_in_backend is not None and not isinstance(track.id_in_backend, str):
            raise Exception('{}: id_in_backend must be str'.format(track))
        tracks_with_this_id = [x for x in self.__tracks if x.id_in_backend == track.id_in_backend]
        if tracks_with_this_id:
            assert len(tracks_with_this_id) == 1
            track_with_this_id = tracks_with_this_id[0]
            if track_with_this_id.backend is None:
                # we actually replace the unsaved track with the new one
                del self.__tracks[track_with_this_id]
        if track.id_in_backend is not None and any(x.id_in_backend == track.id_in_backend for x in self.__tracks):
            # cannot do "in self" because we are not decoupled, so that would call _scan()
            raise ValueError(
                'Backend.append(track {}): its id_in_backend {} is already in list: Track={}, list={}'.format(
                    str(track), track.id_in_backend, self[track.id_in_backend], self.__tracks))
        self.matches(track, 'append')
        self.__tracks.append(track)

    def __repr__(self):
        """do not call len(self) because that does things.

        Returns:
            The repr str

        """
        return '{}({} in {})'.format(self.__class__.__name__, len(self.__tracks), self.account)

    def __enter__(self):
        """See class docstring.

        Returns:
            self

        """
        return self

    def __exit__(self, exc_type, exc_value, trback):
        """See class docstring."""
        self.detach()

    def __iter__(self):
        """See class docstring.

        Returns:
            iterator over tracks

        """
        self._scan()
        return iter(self.__tracks)

    def __eq__(self, other) ->bool:  # TODO: use str
        """True if both backends have the same tracks.

        Returns:
            True if both backends have the same tracks

        """
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
                'blind move' if remove else 'blind copy', old_track, self.account if dry_run else new_track))
            if remove and not dry_run:
                old_track.remove()
        return result

    def __find_mergable_groups(self, tracks, partial_tracks: bool = False):
        """Find mergable groups.

        Returns:
            A list of tracks. The first one is the sink for the others

        """
        result = list()
        rest = list(self)
        rest.extend(x for x in tracks if str(x.backend) != str(self))
        while rest:
            root = rest[0]
            group = list([root])
            group.extend(x for x in rest[1:] if root.can_merge(x, partial_tracks)[0] is not None)  # noqa
            # merge target should be the longest track in self:
            group.sort(key=lambda x: (x.backend is self, x.gpx.get_track_points_no()), reverse=True)
            result.append(group)
            for _ in group:
                rest = [x for x in rest if x is not _]
        return result

    def merge(self, other, remove: bool = False, dry_run: bool = False, copy: bool = False,
              partial_tracks: bool = False) ->list:  # noqa
        """merge other backend or a single track into this one. Tracks within self are also merged.

        If two tracks have identical points, or-ify their other attributes.

        Args:
            other: The backend or a single track to be merged
            remove: If True, remove merged tracks
            dry_run: If True, do not really merge or remove
            copy: Do not try to find a matching track, just copy other into this Backend
            partial_tracks: If True, two tracks are mergeable if one of them contains the other one.

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

        null_datetime = datetime.datetime(year=1, month=1, day=1)
        groups = self.__find_mergable_groups(other, partial_tracks)
        merge_groups = [x for x in groups if len(x) > 1]
        merge_groups.sort(key=lambda x: x[0].time or null_datetime)
        if merge_groups:
            result.append('{} mergable groups:'.format(len(merge_groups)))
            for _ in merge_groups:
                result.append('  {} ----> {}'.format(', '.join(str(x) for x in _[1:]), _[0]))  # noqa
        for destination, *sources in groups:
            if destination.backend is not self:
                new_destination = destination if dry_run else self.add(destination)
                result.append('{} {} -> {}'.format(
                    'move' if remove else 'copy', destination, self if dry_run else new_destination))
                if remove and not dry_run:
                    destination.remove()
                destination = new_destination
            for source in sources:
                result.extend(destination.merge(
                    source, remove=remove, dry_run=dry_run, partial_tracks=partial_tracks))
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

    def flush(self):
        """Some backends delay actual writing. This enforces writing.

        Currently, only the Mailer backend can delay, it will bundle all
        mailed tracks into one mail instead of sending separate mails
        for every track. Needed for lifetracking.

        """

    def clone(self):
        """return a clone."""
        return self.__class__(self.account)

    def _get_current_keywords(self, track):  # pylint:disable=no-self-use
        """A backend might be able to return the currently stored keywords.

        This is useful for unittests: Compare the internal state with what the
        backend actually says.

        """
        return track.keywords

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
            If the wanted object does not exist, exception FileNotFoundError is raised.

        """
        account, track_id = cls.parse_objectname(name)
        cache_key = str(account)
        if cache_key in cls.__all_backends:
            result = cls.__all_backends[cache_key]
        else:
            result = cls.find_class(account.backend)(account)
            cls.__all_backends[cache_key] = result
        if track_id:
            try:
                result = result[track_id]
            except IndexError:
                raise FileNotFoundError('{} not found'.format(Track.identifier(account, track_id)))
        assert result is not None
        return result
