#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Defines :class:`gpxity.Directory`
"""


import os
import datetime
import tempfile
from collections import defaultdict

from .. import Backend, Track
from ..util import remove_directory

__all__ = ['Directory']

class Directory(Backend):
    """Uses a directory for storage. The filename minus the .gpx ending is used as the track id.
    If the track has a title but no storage id yet, use the title as storage id.
    Make the storage id unique by attaching a number if needed.
    An track without title gets a random name.

    The main directory (given by :attr:`Directory.url <gpxity.backend.Backend.url>`) will have
    subdirectories YYYY/MM (year/month) with only the tracks for one month.
    Those are symbolic links to the main file and have the same file name.

    If :meth:`~gpxity.backend.Backend.save` is given a value for ident, this
    is used as id, the file name will be :literal:`id.gpx`.
    Otherwise, this backend uses :attr:`Track.title <gpxity.Track.title>` for the id.
    If a track has no title, it uses a random sequence of characters.
    Changing the title also changes the id.

    Args:
        url (str): a directory. If no Url is given, either here or through auth, use a unique
            temporary directory named
            :attr:`prefix`.X where X are some random characters.
            If the directory does not exist, it is created.
        auth (str): You can use this as in every backend to define Url= in auth.cfg
        cleanup (bool): If True, :meth:`destroy` will remove all tracks. If url was
            not given, it will also remove the directory.
        prefix: The prefix for a temporary directory path. Must not be given if url is given.

    Attributes:
        prefix (str):  Class attribute, may be changed. The default prefix for
            temporary directories. Default value is :literal:`gpxity.`
        fs_encoding (str): The encoding for file system names. By default, we
            expect the file system being able to handle arbitrary UTF-8 encoded names
            except character '/' and special names '.' and '..'. If needed, we will introduce
            new possible values for fs_encoding like perhaps 'windows'. Gpxity will **never**
            support any other character set but UTF-8.
            Note that :attr:`fs_encoding` is independent of the platform we are running on - we
            might use a network file system.
        is_temporary (bool): True if no Url was given and we created a temporary directory
    """

   # skip_test = True
    # pylint: disable=abstract-method

    prefix = 'gpxity.'

    def __init__(self, url=None, auth=None, cleanup=False, debug=False, prefix: str = None):
        self.fs_encoding = None
        if prefix is None:
            prefix = self.__class__.prefix
        elif url:
            raise Exception('Directory does not accept both url and prefix')
        super(Directory, self).__init__(url=url, auth=auth, cleanup=cleanup, debug=debug)
        self.is_temporary = not bool(self.url)
        if self.is_temporary:
            self.url = tempfile.mkdtemp(prefix=prefix)
        if not os.path.exists(self.url):
            os.makedirs(self.url)
        self._symlinks = defaultdict(list)
        self._load_symlinks()

    def identifier(self):
        """Used for formatting strings"""
        result = self.url
        if result:
            if  result.startswith('./') or result == '.':
                result = result[2:]
        return result

    @property
    def legal_categories(self):
        """
        Returns: list(str)
            all legal values for category for this backend."""
        return Track.legal_categories

    def decode_category(self, value: str) ->str:
        """Not needed for directory, this is always the internal value."""
        return value

    def encode_category(self, value: str) ->str:
        """Not needed for directory, this is always the internal value."""
        return value

    def _load_symlinks(self, directory=None):
        """scan the subdirectories with the symlinks. If the content of an
        track changes, the symlinks might have to be adapted. But
        we do not know the name of the existing symlink anymore. So
        just scan them all and assign them to id_in_backend."""
        if directory is None:
            directory = self.url
        for dirpath, _, filenames in os.walk(directory):
            for filename in filenames:
                full_name = os.path.join(dirpath, filename)
                if os.path.islink(full_name):
                    if os.path.exists(full_name):
                        target = os.readlink(full_name)
                        gpx_target = os.path.basename(target)
                        if gpx_target.endswith('.gpx'):
                            # it really should ...
                            gpx_target = gpx_target[:-4]
                        if full_name not in self._symlinks[gpx_target]:
                            self._symlinks[gpx_target].append(full_name)
                    else:
                        os.remove(full_name)

    def _new_id_from(self, ident_proposal: str) ->str:
        """Returns not yet existant file name.

        Args:
            ident_proposal: If this proposal does not lead to a valid ident, create unique random ident.

        Returns:
            The new unique ident
        """
        value = self._sanitize_name(ident_proposal)
        if not value:
            value = os.path.basename(tempfile.NamedTemporaryFile(dir=self.url, prefix='').name)
        return self._make_ident_unique(value)

    @staticmethod
    def _make_path_unique(value):
        """If the file name already exists, apply a serial number. If value
        ends with .gpx, put the serial number in front of that.
        """
        ctr = 0
        unique_value = value
        while os.path.exists(unique_value):
            ctr += 1
            if value.endswith('.gpx'):
                unique_value = '{}.{}.gpx'.format(value[:-4], ctr)
            else:
                unique_value = '{}.{}'.format(value, ctr)
        return unique_value

    def _make_ident_unique(self, value):
        """Returns a unique ident"""
        path = Directory._make_path_unique(os.path.join(self.url, value + '.gpx'))
        return os.path.basename(path)[:-4]

    def _sanitize_name(self, value):
        """Change it to legal file name characters"""
        if value is None:
            return None
        if self.fs_encoding is not None:
            raise Exception('No support for fs_encoding={}'.format(self.fs_encoding))
        return value.replace('/', '_')

    def destroy(self):
        """If `cleanup` was set at init time, removes all tracks.
        If :attr:`~gpxity.Directory.url` was set at init time,
        also removes the directory."""
        super(Directory, self).destroy()
        if self._cleanup:
            self.remove_all()
            if self.is_temporary:
                remove_directory(self.url)

    def gpx_path(self, ident):
        """The full path name for the local copy of a track"""
        return os.path.join(self.url, '{}.gpx'.format(ident))

    def _list_gpx(self):
        """returns a generator of all gpx files, with .gpx removed"""
        gpx_names = (x for x in os.listdir(self.url) if x.endswith('.gpx'))
        return (x.replace('.gpx', '') for x in gpx_names)

    def _yield_tracks(self):
        """get all tracks for this user."""
        self._symlinks = defaultdict(list)
        self._load_symlinks()
        for _ in self._list_gpx():
            yield self._found_track(_)

    def get_time(self) ->datetime.datetime:
        """get server time as a Linux timestamp"""
        return datetime.datetime.now()

    def _read_all(self, track):
        """fills the track with all its data from source."""
        assert track.id_in_backend
        with open(self.gpx_path(track.id_in_backend), encoding='utf-8') as in_file:
            track.parse(in_file)

    def _remove_symlinks(self, ident: str):
        """Removes its symlinks, empty symlink parent directories"""
        for symlink in self._symlinks[ident]:
            if os.path.exists(symlink):
                os.remove(symlink)
            symlink_dir = os.path.split(symlink)[0]
            try:
                os.removedirs(symlink_dir)
            except OSError:
                pass
        self._symlinks[ident] = list()

    def _remove_ident(self, ident: str):
        """Removes its symlinks and the file, in this order."""
        self._remove_symlinks(ident)
        gpx_file = self.gpx_path(ident)
        if os.path.exists(gpx_file):
            os.remove(gpx_file)

    def _symlink_path(self, track):
        """The path for the speaking symbolic link: YYYY/MM/title.gpx.
        Missing directories YYYY/MM are created.
        """
        ident = track.id_in_backend
        time = datetime.datetime.fromtimestamp(os.path.getmtime(self.gpx_path(ident)))
        by_month_dir = os.path.join(self.url, '{}'.format(time.year), '{:02}'.format(time.month))
        if not os.path.exists(by_month_dir):
            os.makedirs(by_month_dir)
        else:
            # make sure there is no dead symlink with our wanted name.
            self._load_symlinks(by_month_dir)
        name = track.title or ident
        return self._make_path_unique(os.path.join(by_month_dir, self._sanitize_name(name)))

    def _new_ident(self, track) ->str:
        """Creates an id for track.

        Returns: The new ident.
        """
        ident = track.id_in_backend
        if ident is None:
            ident = self._new_id_from(None)
        return ident

    def _make_symlinks(self, track):
        """Makes all symlinks for track"""
        ident = track.id_in_backend
        gpx_pathname = self.gpx_path(ident)
        link_name = self._symlink_path(track)
        basename = os.path.basename(gpx_pathname)
        link_target = os.path.join('..', '..', basename)
        os.symlink(link_target, link_name)
        if link_name not in self._symlinks[ident]:
            self._symlinks[ident].append(link_name)

    def __set_filetime(self, track):
        """Sets the file modification time to track start time.
        If the track has no start time, do nothing."""
        time = track.time
        if time:
            _ = self.gpx_path(track.id_in_backend)
            os.utime(_, (time.timestamp(), time.timestamp()))

    def __undo_rename(self, old_ident):
        """if _write_all fails, undo change of file name and restore old file."""
        if old_ident:
            old_pathname = self.gpx_path(old_ident)
            if os.path.exists(old_pathname):
                os.remove(old_pathname)
            if os.path.exists(old_pathname + '.old'):
                os.rename(old_pathname + '.old', old_pathname)

    def _change_id(self, track, new_ident: str):
        """Changes the id in the backend."""
        raise NotImplementedError

    def _write_all(self, track) ->str:
        """save full gpx track. Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt track.id_in_backend."""
        old_ident = track.id_in_backend
        old_pathname = None
        if old_ident:
            old_pathname = self.gpx_path(old_ident)
            if os.path.exists(old_pathname):
                os.rename(old_pathname, old_pathname + '.old')
        try:
            new_ident = self._new_ident(track)
        except BaseException:
            self.__undo_rename(old_ident)
            raise

        track.id_in_backend = new_ident
        gpx_pathname = self.gpx_path(new_ident)
        try:
            # only remove the old file after the new one has been written
            with open(gpx_pathname, 'w', encoding='utf-8') as out_file:
                out_file.write(track.to_xml())
            self.__set_filetime(track)
            self._make_symlinks(track)
        except BaseException:
            self.__undo_rename(old_ident)
            raise
        if old_ident:
            self._remove_symlinks(old_ident)
            if old_pathname and os.path.exists(old_pathname + '.old'):
                os.remove(old_pathname + '.old')
        return new_ident

Directory._define_support() # pylint: disable=protected-access
