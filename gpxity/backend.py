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
from .gpxfile import GpxFile
from .util import collect_gpxfiles
from .gpx import Gpx

from .backend_base import BackendBase
__all__ = ['Backend']


class Backend(BackendBase):

    """A place where gpxfiles live. Something like the filesystem or http://mapmytracks.com.

    A Backend should hold only gpxfiles for one person, and they
    should not overlap in time. This is not enforced but sometimes
    behaviour is undefined if you ignore this.

    A Backend be used as a context manager.

    A Backend allows indexing by normal int index, by :class:`GpxFile <gpxity.gpxfile.GpxFile>`
    and by :attr:`GpxFile.id_in_backend <gpxity.gpxfile.GpxFile.id_in_backend>`.
    :literal:`if 'ident' in backend` is possible.
    len(backend) shows the number of gpxfiles. Please note that Code
    like :literal:`if backend:` may not behave as expected. This will be False if the backend
    has no gpxfile. If that is not what you want, consider :literal:`if backend is not None`

    The backend will automatically synchronize. So something like :literal:`len(Backend())` will work.
    However, some other Backend pointing to the same storage or even a different process
    might change things. If you want to cope with that, use :meth:`scan`.

    Not all backends support all methods. The unsupported methods
    will raise NotImplementedError. As a convenience every backend
    has a list **supported** to be used like :literal:`if 'gpxfile' in backend.supported:`
    where `gpxfile` is the name of the method.

    Backends support no locking. If others modify a backend concurrently, you may
    get surprises. It is up to you to handle those.

    Some backends may use cookies.

    Args:
        account (:class:`~gpxity.accounts.Account`): The account to be used.
            Alternatively a dict can be passed to build an ad hoc :class:`~gpxity.accounts.Account`
            instance.

    Attributes:
        supported (set(str)): The names of supported methods. Creating the first instance of
            the backend initializes this. Only methods which may not be supported are mentioned here.
            If a particular value write_* like write_public does not exist, the entire gpxfile is written instead
            which normally results in a new ident for the gpxfile.

            Some special values are:
                * rename: allows assigning values to id_in_backend

        full_support (set(str)): All possible values for the supported attribute.
        url (str): the address. May be a real URL or a directory, depending on the backend implementation.
            Every implementation may define its own default for url. Must never end with '/' except for
            Directory(url='/').
        test_is_expensive: For internal use. If True, the self tests will reduce test cases and try to
            avoid too much usage of the backend.
        max_field_sizes: Some backends have a limited size for some attributes like keywords. This
            is only an approximative guess. The backend will not protect you from overriding it
            but the unittests will try to stay within those limits.
        point_precision: The precision supported by this backend. We are never more precise than 6.
            That is the digits after the decimal separator.
        supported_categories: The categories supported by this backend. The first one is used as default.
        accepts_zero_points: True if the Backend accepts a GpxFile without Points

    """

    # pylint: disable=too-many-instance-attributes

    class NoMatch(Exception):
        """Is raised if a gpxfile is expected to pass the match filter but does not"""

    supported = set()

    default_url = None  # Override in the backends

    test_is_expensive = True

    max_field_sizes = {}

    _category_decoding = dict()
    _category_encoding = dict()

    full_support = (
        'scan', 'remove', 'write', 'write_title', 'write_public',
        'own_categories', 'rename',
        'write_category', 'write_description', 'keywords', 'write_add_keywords', 'write_remove_keywords')

    _max_length = dict()

    point_precision = 5

    _timeout = None

    __all_backends = dict()

    accepts_zero_points = False

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
        self.__gpxfiles = list()
        self._gpxfiles_fully_listed = False
        self.__match = None
        self.logger = logging.getLogger(str(self))
        # do not want to see "Resetting dropped connection"
        logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        self._cached_subscription = None  # to be used by specific Backend classes

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
        if self.account.url is None:
            self.account.config['url'] = self.default_url
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
            raise Backend.BackendException('{} needs a username'.format(self.url))
        return author

    def __str__(self) ->str:
        """A unique identifier for every physical backend.

        Two Backend() instances pointing to the same physical backend have the same identifier.

        Returns:
            A unique identifier

        """
        return self.account.name

    supported_categories = GpxFile.categories

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
        """Filter gpxfiles.

        A function with one argument returning None or str. The backend will call
            this with every gpxfile and ignore gpxfiles where match does not return None.
            The returned str should explain why the gpxfile does not match.

            If you change a gpxfile such that it does not match anymore, the exception
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
            '_change_ident': 'rename',
            '_list': 'scan',
            '_remove_ident': 'remove',
            '_write_all': 'write'}
        cls.supported = set()
        cls.supported.add('keywords')  # default
        if cls.supported_categories != GpxFile.categories:
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
        """Translate the value from the backend into one out of GpxFile.categories.

        Returns:
            The decoded name

        """
        if value in GpxFile.categories:
            return value
        if value in GpxFile._obsolete_categories:
            return GpxFile._obsolete_categories[value]
        if value.capitalize() in GpxFile.categories:
            return value.capitalize()
        if value not in cls._category_decoding:
            raise cls.BackendException('{} gave us an unknown gpxfile type "{}"'.format(cls.__name__, value))
        return cls._category_decoding[value]

    @classmethod
    def encode_category(cls, value: str) ->str:
        """Translate internal value (out of GpxFile.categories) into the backend specific value.

        Returns:
            The encoded name

        """
        if value in GpxFile._obsolete_categories:
            value = GpxFile._obsolete_categories[value]
        if value in cls.supported_categories:
            return value
        if value.lower() in cls.supported_categories:
            return value.lower()
        if value in cls._category_encoding:
            return cls._category_encoding[value]
        for key, target in cls._category_decoding.items():
            if value.lower() == target.lower():
                return key
        if value == Gpx.undefined_str:
            return cls.encode_category(GpxFile.categories[0])
        raise cls.BackendException('{} has no equivalent for "{}"'.format(cls.__name__, value))

    @staticmethod
    def _encode_keyword(value: str) ->str:
        """Replicate the translation the backend does. MMT for example capitalizes all words.

        Returns:
            the encoded keyword

        """
        return value

    @staticmethod
    def _encode_description(gpxfile) ->str:
        """A backend might put keywords into the description. WPTrackserver does.

        Returns: The string to be saved in the backend

        """
        return gpxfile.description

    @classmethod
    def _decode_description(cls, gpx, value):
        """A backend might put keywords into the description. WPTrackserver does.

        Returns: The description

        """
        gpx.description = value
        return value

    def get_time(self) ->datetime.datetime:  # pylint: disable=no-self-use
        """get time from the server where backend is located as a Linux timestamp.

        A backend implementation does not have to support this.

        Returns: datetime.datetime

        """
        return datetime.datetime.now()

    def _change_ident(self, gpxfile, new_ident: str):
        """Change the id in the backend.

        If new_ident already exists, the backend is free to
        change it to a unique name or to raise an Exception.

        """
        raise NotImplementedError

    def scan(self, now: bool = False) ->None:
        """Enforce a reload of the list of all gpxfiles in the backend.

        This will be delayed until the list is actually needed again.

        If this finds an unsaved gpxfile not matching the current match
        function, an exception is thrown.
        Saved Tracks not matching the current match will no be loaded.

        Args:
            now: If True, do not delay scanning.

        """
        self._gpxfiles_fully_listed = False
        if now:
            self._scan()

    @property
    def is_scanned(self) ->bool:
        """Check if the backend has already been scanned for gpxfiles.

        Returns: (bool)
            The answer

        """
        return self._gpxfiles_fully_listed

    def _scan(self) ->None:
        """load the list of all gpxfiles in the backend if not yet done.
        Enforce this by calling :meth:`scan` first.
        """
        if not self._gpxfiles_fully_listed and not self._decoupled:
            self._gpxfiles_fully_listed = True
            unsaved = [x for x in self.__gpxfiles if not x.id_in_backend]
            if self.__match is not None:
                for gpxfile in unsaved:
                    # side effect: raises exception if no match
                    self.matches(gpxfile, 'scan')
            self.__gpxfiles = unsaved
            if 'scan' in self.supported:
                match_function = self.__match
                self.__match = None
                try:
                    # _list loads ALL gpxfiles, match will be
                    # applied in a second loop. This way the Backend implementations
                    # do not have to worry about the match code.
                    with self._decouple():
                        self._list()
                finally:
                    self.__match = match_function
            if self.__match is not None:
                self.__gpxfiles = [x for x in self.__gpxfiles if self.matches(x)]

    def _found_gpxfile(self, ident: str, gpx):
        """Create an empty gpxfile for ident and insert it into this backend.

        Returns:
            the new gpxfile

        """
        result = GpxFile(gpx)
        with self._decouple():
            result._set_backend(self)
            result.id_in_backend = ident
        self._append(result)
        return result

    def _list(self):
        """Load all gpxfile headers and append them to the backend.

        The gpxfiles will not be loaded if possible.

        """
        raise NotImplementedError()

    def _read_all_decoupled(self, gpxfile) ->None:
        """Decouple and call the backend specific _read."""
        with self._decouple():
            self._read(gpxfile)
            gpxfile.gpx.default_country = self.account.country
            points_read = gpxfile.gpx.get_track_points_no()
            with gpxfile.fenced():
                fenced_points = gpxfile.gpx.get_track_points_no()
            gpxfile._illegal_points = points_read - fenced_points

    def _read(self, gpxfile) ->None:
        """fill the gpxfile with all its data from source."""
        raise NotImplementedError()

    def matches(self, gpxfile, exc_prefix: str = None):
        """match gpxfile against the current match function.

        Args:
            exc_prefix: If not None, use it for the beginning of an exception message.
                If None, never raise an exception

        Returns:
            True for match

        """
        if self.__match is None:
            return True
        match_error = self.__match(gpxfile)
        if match_error and exc_prefix:
            raise Backend.NoMatch('{}: {} does not match: {}'.format(exc_prefix, gpxfile, match_error))
        return match_error is None

    def _needs_full_save(self, changes) ->bool:
        """Do we have to rewrite the entire gpxfile?.

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

    def add(self, gpxfile):
        """
        Add a gpxfile to this backend.

        No gpxfile already existing in this backend will be overwritten.
        If  :attr:`GpxFile.id_in_backend <gpxity.gpxfile.GpxFile.id_in_backend>`
        is not given, the backend will create a unique value. If it is given,
        the backend will try to use it or create a new value at its discretion.

        Some Backends will not accept a gpxfile without Points. Only Directory
        is granted to handle a gpxfile wihout points.

        Note that some backends may reject a gpxfile if it is very
        similar to an existing gpxfile even if it belongs to some other user.

        If the gpxfile object is already in the list of gpxfiles, raise ValueError.

        If the gpxfile does not pass the current match function, raise an exception.

        Args:
            gpxfile (~gpxity.gpxfile.GpxFile): The gpxfile we want to save in this backend.

        Returns:
            ~gpxity.gpxfile.GpxFile: The saved gpxfile. If the original gpxfile lives in a different
            backend, a new gpxfile living in this backend will be created
            and returned.

        """
        if self._decoupled:
            raise Exception('A backend cannot save() while being decoupled. This is probably a bug in gpxity.')
        self.matches(gpxfile, 'add')
        if gpxfile.backend is not self and gpxfile.backend:
            # we do not want clone() loading the gpxfile because
            # that cannot be done with fences applied
            gpxfile._illegal_points = 0  # when copying a GpxFile, it is OK to lose points
            had_ids = gpxfile.ids
            had_ids.append(str(gpxfile))
            gpxfile._load_full()
            with gpxfile.fenced():
                new_gpxfile = gpxfile.clone()
                new_gpxfile.ids = had_ids
                try:
                    self._check_id_legal(gpxfile.id_in_backend)
                    new_gpxfile.id_in_backend = gpxfile.id_in_backend
                except ValueError:
                    pass
        else:
            if any(x is gpxfile for x in self.__gpxfiles):
                raise ValueError(
                    'Already in list: GpxFile {} with id={}, have={}'.format(
                        gpxfile, id(gpxfile), ','.join(str(x) for x in self)))
            new_gpxfile = gpxfile
        try:
            with self._decouple():
                new_gpxfile._set_backend(self)
                self.__check_empty(gpxfile)
                self._write_all(new_gpxfile)
            self._append(new_gpxfile)
            gpxfile._clear_dirty()
            return new_gpxfile
        except Exception:
            # do not do self.remove. If we try to upload the same gpxfile to gpsies,
            # gpsies will assign the same trackid, and we come here. __gpxfiles will
            # only hold the first uploaded gpxfile, and remove would remove that
            # instance instead of this one.
            # TODO: do we have a unittest for that case?
            self.__gpxfiles = [x for x in self.__gpxfiles if x is not new_gpxfile]
            with self._decouple():
                new_gpxfile.id_in_backend = None
                new_gpxfile._set_backend(None)
            raise

    def __check_empty(self, gpxfile):
        """Check if the track is empty but the backend needs points.

        May raise an exception.

        """
        if not self.accepts_zero_points and gpxfile.gpx.get_track_points_no() == 0:
            raise self.BackendException(
                '{} does not accept GpxFile without points: {}'.format(
                    self.__class__.__name__, gpxfile))

    def _rewrite(self, gpxfile, changes):
        """Rewrite the full gpxfile.

        Used only by GpxFile when things change.

        If this changes track.id_in_backend, the GpxFile with the old id_backend is removed.

        """
        assert gpxfile.backend is self
        assert self._has_item(gpxfile.id_in_backend), '{}: its id_in_backend {} is not in {}'.format(
            gpxfile, gpxfile.id_in_backend, ' / '.join(str(x) for x in self))
        assert gpxfile._dirty

        needs_full_save = self._needs_full_save(changes)

        self.matches(gpxfile, '_rewrite')
        if needs_full_save:
            with gpxfile.fenced():
                self.__check_empty(gpxfile)
                old_id = gpxfile.id_in_backend
                new_id = self._write_all(gpxfile)
                if old_id and old_id != new_id:
                    self._remove_ident(old_id)
            gpxfile.id_in_backend = new_id
        else:
            for change in changes:
                _ = change.split(self._dirty_separator)
                write_name = '_write_{}'.format(_[0])
                if len(_) == 1:
                    getattr(self, write_name)(gpxfile)
                elif len(_) == 2:
                    getattr(self, write_name)(gpxfile, _[1])
                else:
                    raise Exception('dirty {} got too many arguments:{}'.format(write_name, _[1:]))

    def _write_all(self, gpxfile) ->str:
        """the actual implementation for the concrete Backend.

        Writes the entire GpxFile.

        Returns:
            The new id_in_backend

        """
        raise NotImplementedError()

    def remove(self, value) ->None:
        """
        Remove gpxfile. This can also be done for gpxfiles not passing the current match function.

        Args:
            value: If it is not an :class:`~gpxity.gpxfile.GpxFile`, :meth:`remove` looks
                it up by doing :literal:`self[value]`

        """
        gpxfile = value if hasattr(value, 'id_in_backend') else self[value]
        if gpxfile.id_in_backend:
            self._remove_ident(gpxfile.id_in_backend)
        with self._decouple():
            gpxfile.gpx.is_complete = True  # we do not care about partially loaded GpxFile when deleting it
            gpxfile._set_backend(None)
            try:
                self.__gpxfiles = [x for x in self.__gpxfiles if x.id_in_backend != gpxfile.id_in_backend]
            except ValueError:
                pass

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation."""
        raise NotImplementedError()

    def _lifetrack_start(self, gpxfile, points) -> str:  # pylint: disable=unused-argument
        """Modelled after MapMyTracks. I hope this matches other services too.

        This will always produce a new gpxfile in the backend.

        Default is to just add the points to the gpxfile.

        Args:
            gpxfile(GpxFile): Holds initial data and points already added.
                keep in mind that this process might restart which should
                be invisible to the target.
            points: Initial points

        Returns: The new id_in_backend

        For details see :meth:`GpxFile.gpxfile() <gpxity.lifetrack.Lifetrack.start>`.

        """
        if gpxfile.id_in_backend not in self:
            gpxfile.id_in_backend = self.add(gpxfile.clone()).id_in_backend
        return gpxfile.id_in_backend

    def _lifetrack_update(self, gpxfile, points):
        """If the backend does not support lifetrack, just add the points to the gpxfile.

        Args:
            gpxfile(GpxFile): Holds initial data
            points: If None, stop tracking. Otherwise, start tracking
                and add points.

        For details see :meth:`GpxFile.gpxfile() <gpxity.lifetrack.Lifetrack.update>`.

        """
        self[gpxfile.id_in_backend].add_points(points)

    def _lifetrack_end(self, gpxfile):
        """Default: Nothing needs to be done."""

    def remove_all(self):
        """Remove all gpxfiles we know about.

        If their :attr:`id_in_backend` has meanwhile been changed
        through another backend instance or another process, we
        cannot find it anymore. We do **not** rescan all gpxfiles in the backend.
        If you want to make sure it will be empty, call :meth:`scan` first.

        If you use a match function, only matching gpxfiles will be removed."""
        for gpxfile in list(self):
            if self.matches(gpxfile):
                self.remove(gpxfile)

    def detach(self):
        """Should be called when access to the Backend is not needed anymore."""

    def __contains__(self, value) ->bool:
        """value is either an a gpxfile or a gpxfile id.

        Does NOT load gpxfiles, only checks what is already known.

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
        if hasattr(index, 'id_in_backend') and index in self.__gpxfiles:
            return True
        if isinstance(index, str) and index in [x.id_in_backend for x in self.__gpxfiles]:
            return True
        return False

    def __getitem__(self, index):
        """Allow accesses like alist[a_id].

        Do not call this when implementing a backend because this always calls scan() first.

        Instead use :meth:`_has_item`.

        Returns:
            the gpxfile

        """
        self._scan()
        if isinstance(index, int):
            return self.__gpxfiles[index]
        for _ in self.__gpxfiles:
            if _ is index or _.id_in_backend == index:
                return _
        raise IndexError

    def __len__(self) ->int:
        """do not call this when implementing a backend because this calls scan().

        Returns:
            the length

        """
        self._scan()
        return len(self.__gpxfiles)

    def real_len(self) ->int:
        """len(backend) without calling scan() first.

        Returns:

            the length"""
        return len(self.__gpxfiles)

    def _append(self, gpxfile):
        """Append a gpxfile to the cached list."""
        if gpxfile.id_in_backend is not None and not isinstance(gpxfile.id_in_backend, str):
            raise Exception('{}: id_in_backend must be str'.format(gpxfile))
        tracks_with_this_id = [x for x in self.__gpxfiles if x.id_in_backend == gpxfile.id_in_backend]
        if tracks_with_this_id:
            assert len(tracks_with_this_id) == 1
            track_with_this_id = tracks_with_this_id[0]
            if not track_with_this_id.backend:
                # we actually replace the unsaved gpxfile with the new one
                del self.__gpxfiles[track_with_this_id]
        if gpxfile.id_in_backend is not None and any(
                x.id_in_backend == gpxfile.id_in_backend for x in self.__gpxfiles):
            # cannot do "in self" because we are not decoupled, so that would call _scan()
            raise ValueError(
                'Backend.append(gpxfile {}): its id_in_backend {} is already in list: GpxFile={}, list={}'.format(
                    str(gpxfile), gpxfile.id_in_backend, self[gpxfile.id_in_backend], self.__gpxfiles))
        self.matches(gpxfile, 'append')
        self.__gpxfiles.append(gpxfile)

    def __repr__(self):
        """do not call len(self) because that does things.

        Returns:
            The repr str

        """
        return '{}({} in {})'.format(self.__class__.__name__, len(self.__gpxfiles), self.account)

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
            iterator over gpxfiles

        """
        self._scan()
        return iter(self.__gpxfiles)

    def __bool__(self):
        """Return True always.

        A programmer (myself included) may be tempted
        to say :literal:`if gpxfile.backend:` for checking if the
        GpxFile has a backend assigned. But without __bool__
        that would do len(backend) wich scans the - possibly remote - backend.Backend

        Returns: True

        """
        return True

    def __eq__(self, other) ->bool:  # TODO: use str
        """True if both backends have the same gpxfiles.

        Returns:
            True if both backends have the same gpxfiles

        """
        return {x.key() for x in self} == {x.key() for x in other}

    def __copy(self, other_gpxfiles, remove, dry_run):
        """Copy other_gpxfiles into self. Used only by self.merge().

        Returns:
            verbose messages

        """
        result = list()
        for old_gpxfile in other_gpxfiles:
            if not dry_run:
                new_gpxfile = self.add(old_gpxfile)
            result.append('{} {} -> {}'.format(
                'blind move' if remove else 'blind copy', old_gpxfile, self.account if dry_run else new_gpxfile))
            if remove and not dry_run:
                old_gpxfile.remove()
        return result

    def __find_mergable_groups(self, gpxfiles, partial: bool = False):
        """Find mergable groups.

        Returns:
            A list of gpxfiles. The first one is the sink for the others

        """
        result = list()
        rest = list(self)
        rest.extend(x for x in gpxfiles if str(x.backend) != str(self))
        while rest:
            root = rest[0]
            group = list([root])
            group.extend(x for x in rest[1:] if root.can_merge(x, partial)[0] is not None)  # noqa
            # merge target should be the longest gpxfile in self:
            group.sort(key=lambda x: (x.backend is self, x.gpx.get_track_points_no()), reverse=True)
            result.append(group)
            for _ in group:
                rest = [x for x in rest if x is not _]
        return result

    def merge(self, other, remove: bool = False, dry_run: bool = False, copy: bool = False,
              partial: bool = False) ->list:  # noqa
        """merge other backend or a single gpxfile into this one. Tracks within self are also merged.

        If two gpxfiles have identical points, or-ify their other attributes.

        Args:
            other: The backend or a single gpxfile to be merged
            remove: If True, remove merged gpxfiles
            dry_run: If True, do not really merge or remove
            copy: Do not try to find a matching gpxfile, just copy other into this Backend
            partial: If True, two gpxfiles are mergeable if one of them contains the other one.

        Returns:
            list(str) A list of messages for verbose output

        """
        # pylint: disable=too-many-branches,too-many-locals
        # TODO: test for dry_run
        # TODO: test for merging single track
        # TODO: test for merging a backend or a gpxfile with itself. Where
        # they may be identical instantiations or not. For all backends.
        result = list()
        other_gpxfiles = collect_gpxfiles(other)
        if copy:
            return self.__copy(other_gpxfiles, remove, dry_run)

        null_datetime = datetime.datetime(year=1, month=1, day=1)
        groups = self.__find_mergable_groups(other, partial)
        merge_groups = [x for x in groups if len(x) > 1]
        merge_groups.sort(key=lambda x: x[0].first_time or null_datetime)
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
                    source, remove=remove, dry_run=dry_run, partial=partial))
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
        mailed gpxfiles into one mail instead of sending separate mails
        for every gpxfile. Needed for lifetracking.

        """

    def clone(self):
        """return a clone."""
        return self.__class__(self.account)

    def _get_current_keywords(self, gpxfile):  # pylint:disable=no-self-use
        """A backend might be able to return the currently stored keywords.

        This is useful for unittests: Compare the internal state with what the
        backend actually says.

        """
        return gpxfile.keywords

    @classmethod
    def instantiate(cls, name: str):
        """Instantiate a Backend or a GpxFile out of its identifier.

        Calls instantiate_backend and optionally changes result to GpxFile.

        Args:
            name: The string identifier to be parsed

        Returns:
            A GpxFile or a Backend. If the Backend has already been instantiated, return the cached value.
            If the wanted object does not exist, exception FileNotFoundError is raised.

        """
        result, track_id = cls.instantiate_backend(name)
        if track_id:
            try:
                result = result[track_id]
            except IndexError:
                raise FileNotFoundError('{} not found'.format(GpxFile.identifier(result, track_id)))
        return result

    @classmethod
    def instantiate_backend(cls, name: str):
        """Instantiate a Backend.

        The full notation of an id_in_backend in a specific backend is
        similiar to what scp expects:

        Account:id_in_backend where Account is a reference to the accounts file.

        Locally reachable files or directories may be written without the leading
        Directory:. And a leading ~ is translated into the user home directory.
        The trailing .gpx can be omitted. It will be removed anyway for id_in_backend.

        If the file path of a local gpxfile (Directory) contains a ":", the file path
        must be absolute or relative (start with "/" or with "."), or the full notation
        with the leading Directory: is needed

        Args:
            name: The string identifier to be parsed

        Returns: tuple()
            * The first element is the Backend. If the Backend has already been instantiated, return the cached value.
                If the wanted object does not exist, exception FileNotFoundError is raised.
            * The second element is a track_id or None

        """
        account, track_id = cls.parse_objectname(name)
        cache_key = str(account)
        if cache_key in cls.__all_backends:
            result = cls.__all_backends[cache_key]
        else:
            result = cls.find_class(account.backend)(account)
            cls.__all_backends[cache_key] = result
        return result, track_id

    @property
    def subscription(self) ->str:
        """Get the subscription model. Like free, paid, plus, whatever.

        If the backend has no subscription model, return None.

        The unpaid subscription is granted to always return :literal:`free`.
        The most expensive subscription is granted to always return :literal:`full`.
        Intermediate values may vary.

        Because I  (the developer) have no paid account, I can test this only
        partially. Feedback is welcome!

        Returns: The name of the subscription or None

        """
        return None
