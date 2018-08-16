#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""Defines :class:`gpxity.Directory`."""


import os
import datetime
import tempfile
from collections import defaultdict

import gpxpy.gpxfield as mod_gpxfield

from .. import Backend, Track
from ..util import remove_directory

__all__ = ['Directory', 'Backup']


class Backup:

    """A context manager making a backup of the gpx file.

    If an exception happened, restore the backup.
    Otherwise, remove it again.

    """

    # pylint: disable=too-few-public-methods

    def __init__(self, track):
        """See class docstring."""
        self.track = track
        self.old_id = track.id_in_backend
        self.old_pathname = None
        if self.old_id is not None:
            self.old_pathname = track.backend.gpx_path(self.old_id)
            if os.path.exists(self.old_pathname):
                os.rename(self.old_pathname, self.old_pathname + '.old')

    def __enter__(self):
        """See class docstring.

        Returns:
            self

        """
        return self

    def __exit__(self, exc_type, exc_value, trback):
        """See class docstring."""
        if exc_value:
            self.undo_rename()
            with self.track._decouple():  # pylint: disable=protected-access
                self.track.id_in_backend = self.old_id
        else:
            if self.old_pathname is not None:
                if os.path.exists(self.old_pathname + '.old'):
                    os.remove(self.old_pathname + '.old')

    def undo_rename(self):
        """if something failed, undo change of file name and restore old file."""
        if self.old_pathname is not None:
            if os.path.exists(self.old_pathname):
                os.remove(self.old_pathname)
            if os.path.exists(self.old_pathname + '.old'):
                os.rename(self.old_pathname + '.old', self.old_pathname)


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
        """See class docstring."""
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

    def identifier(self, track=None) ->str:
        """Used for formatting strings. Must be unique.

        Returns:

            a unique identifier"""
        result = self.url
        if result:
            if result.startswith('./') or result == '.':
                result = result[2:]
        if track:
            if result:
                result += '/' + track.id_in_backend
            else:
                result = track.id_in_backend
        return result

    @property
    def legal_categories(self):
        """
        A list with all legal categories.

        Returns: list(str)
            all legal values for category for this backend.

        """
        return Track.legal_categories

    def decode_category(self, value: str) ->str:
        """Not needed for directory, this is always the internal value.

        Returns:
            the decoded category

        """
        return value

    def encode_category(self, value: str) ->str:
        """Not needed for directory, this is always the internal value.

        Returns:
            the encoded category

        """
        return value

    def _load_symlinks(self, directory=None):
        """scan the subdirectories with the symlinks.

        If the content of a track changes, the symlinks might have to
        be adapted. But we do not know the name of the existing symlink anymore.

        So just scan them all and assign them to id_in_backend."""
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
        """Return not yet existant file name.

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
    def _make_path_unique(value) ->str:
        """If the file name already exists, apply a serial number.

        If value ends with .gpx, put the serial number in front of that.

        Returns:
            the unique path name

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
        """Return a unique ident."""
        path = Directory._make_path_unique(os.path.join(self.url, value + '.gpx'))
        return os.path.basename(path)[:-4]

    def _sanitize_name(self, value) ->str:
        """Change it to legal file name characters.

        Returns:
            the sanitized name

        """
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

    def gpx_path(self, ident) ->str:
        """The full path name for the local copy of a track.

        Returns:
            The full path name

        """
        assert isinstance(ident, str), '{} must be str'.format(ident)
        return os.path.join(self.url, '{}.gpx'.format(ident))

    def _list_gpx(self):
        """return a generator of all gpx files, with .gpx removed.

        Returns:
            A list of all gpx file names with .gpx removed

        """
        gpx_names = (x for x in os.listdir(self.url) if x.endswith('.gpx'))
        return (x.replace('.gpx', '') for x in gpx_names)

    @staticmethod
    def _get_field(data, name) ->str:
        """Get xml field out of data.

        Returns:
            The xml field

        """
        start_html = '<{}>'.format(name)
        end_html = '</{}>'.format(name)
        data = data.split(end_html)
        if len(data) > 1:
            data = data[0]
            data = data.split(start_html)
            if len(data) > 1:
                data = data[-1]
                if start_html not in data:
                    return data
        return None

    def _enrich_with_headers(self, track):
        """Quick scan of file for getting some header fields."""
        with open(self.gpx_path(track.id_in_backend)) as raw_file:
            data = raw_file.read(10000)
            parts = data.split('<trk>')
            if len(parts) > 1:
                # pylint: disable=protected-access
                raw_data = parts[0].split('extensions')[0]
                track._header_data['title'] = self._get_field(raw_data, 'name')
                track._header_data['description'] = self._get_field(raw_data, 'desc')
                rest_kw = list()
                kw_raw = self._get_field(raw_data, 'keywords')
                if kw_raw:
                    for keyword in (x.strip() for x in kw_raw.split(',')):
                        if keyword == 'Status:public':
                            track._header_data['public'] = True
                        elif keyword == 'Status:private':
                            track._header_data['public'] = False
                        elif keyword.startswith('Category:'):
                            track._header_data['category'] = keyword.split(':')[1].strip()
                        else:
                            rest_kw.append(keyword)
                    track._header_data['keywords'] = sorted(rest_kw)

                time_raw = self._get_field(parts[1], 'time')
                track._header_data['time'] = mod_gpxfield.parse_time(time_raw)

    def _yield_tracks(self):
        """get all tracks for this user."""
        self._symlinks = defaultdict(list)
        self._load_symlinks()
        for _ in self._list_gpx():
            track = self._found_track(_)
            self._enrich_with_headers(track)
            yield track

    def get_time(self) ->datetime.datetime:
        """get server time as a Linux timestamp.

        Returns:
            The server time

        """
        return datetime.datetime.now()

    def _read_all(self, track):
        """fill the track with all its data from source."""
        assert track.id_in_backend
        with open(self.gpx_path(track.id_in_backend), encoding='utf-8') as in_file:
            track.parse(in_file)

    def _remove_symlinks(self, ident: str):
        """Remove its symlinks, empty symlink parent directories."""
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
        """Remove its symlinks and the file, in this order."""
        self._remove_symlinks(ident)
        gpx_file = self.gpx_path(ident)
        if os.path.exists(gpx_file):
            os.remove(gpx_file)

    def _symlink_path(self, track) ->str:
        """The path for the speaking symbolic link: YYYY/MM/title.gpx.

        Missing directories YYYY/MM are created.

        Returns:
            The path

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
        """Create an id for track.

        Returns: The new ident.

        """
        ident = track.id_in_backend
        if ident is None:
            ident = self._new_id_from(None)
        return ident

    def _make_symlinks(self, track):
        """Make all symlinks for track."""
        ident = track.id_in_backend
        gpx_pathname = self.gpx_path(ident)
        link_name = self._symlink_path(track)
        basename = os.path.basename(gpx_pathname)
        link_target = os.path.join('..', '..', basename)
        os.symlink(link_target, link_name)
        if link_name not in self._symlinks[ident]:
            self._symlinks[ident].append(link_name)

    def _set_filetime(self, track):
        """Set the file modification time to track start time.
        If the track has no start time, do nothing."""
        time = track.time
        if time:
            _ = self.gpx_path(track.id_in_backend)
            os.utime(_, (time.timestamp(), time.timestamp()))

    def _change_id(self, track, new_ident: str):
        """Change the id in the backend."""
        assert track.id_in_backend != new_ident
        unique_id = self._new_id_from(new_ident)
        self._remove_symlinks(track.id_in_backend)
        os.rename(self.gpx_path(track.id_in_backend), self.gpx_path(unique_id))
        track.id_in_backend = unique_id
        assert any(x is track for x in self._Backend__tracks)
        self._make_symlinks(track)

    def _write_all(self, track) ->str:
        """save full gpx track.

        Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt track.id_in_backend.

        Returns:
            the new id_in_backend

        """
        old_ident = track.id_in_backend
        new_ident = self._new_ident(track)

        with Backup(track):
            track.id_in_backend = new_ident
            with open(self.gpx_path(new_ident), 'w', encoding='utf-8') as out_file:
                out_file.write(track.to_xml())
            self._set_filetime(track)

        if old_ident and new_ident != old_ident:
            self._remove_symlinks(old_ident)
            self._make_symlinks(track)
        return new_ident
