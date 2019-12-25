#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This implements :class:`gpxity.directory.Directory`."""

# pylint: disable=protected-access

import os
import sys
import datetime
import tempfile
import logging
import signal

from collections import defaultdict

from gpxpy.gpx import GPXXMLSyntaxException

from .. import Backend, GpxFile, DirectoryAccount
from ..util import remove_directory
from ..gpx import Gpx

__all__ = ['Directory']


class Directory(Backend):

    """Uses a directory for storage.

    The filename minus the .gpx ending is used
    as :attr:`GpxFile.id_in_backend <gpxity.gpxfile.GpxFile.id_in_backend>`.

    If the :class:`~gpxity.directory.Directory` has a title but no id_in_backend,
    use the title as id_in_backend.
    Make the storage id unique by attaching a number if needed.
    A gpxfile without title gets a random name.

    The main directory (given by account.url) will have
    subdirectories YYYY/MM (year/month) with only the gpxfiles for one month.
    Those are symbolic links to the main file and have the same file name.

    If :meth:`~gpxity.backend.Backend.save` is given a value for ident, this
    is used as id, the file name will be :literal:`id.gpx`.
    Otherwise, this backend uses :attr:`GpxFile.title <gpxity.gpxfile.GpxFile.title>` for the id.
    If a gpxfile has no title, it uses a random sequence of characters.
    Changing the title also changes the id.

    Args:
        Account: If its url is unset, this will create a temporary
            directory named :attr:`prefix`.X where X are some random characters.
            It will be removed in __exit__ / detach.
    Attributes:
        fs_encoding (str): The encoding for file system names. By default, we
            expect the file system being able to handle arbitrary UTF-8 encoded names
            except character '/' and special names '.' and '..'. If needed, we will introduce
            new possible values for fs_encoding like perhaps 'windows'. Gpxity will **never**
            support any other character set but UTF-8.
            Note that :attr:`fs_encoding` is independent of the platform we are running on - we
            might use a network file system.

    """

    # pylint: disable=abstract-method

    test_is_expensive = False
    accepts_zero_points = True

    def __init__(self, account):
        """See class docstring."""
        assert isinstance(account, DirectoryAccount)
        super(Directory, self).__init__(account)

        self.fs_encoding = sys.getfilesystemencoding()
        if not self.fs_encoding.lower().startswith('utf-8'):
            raise Backend.BackendException(
                'Backend Directory needs a unicode file system encoding, {} has {}.'
                ' Please change your locale settings.'.format(self, self.fs_encoding))

        self._symlinks = defaultdict(list)  # TODO: account.symlinks True
        self._load_symlinks()

    def __str__(self) ->str:
        """Used for formatting strings. Must be unique within the process.

        Returns:

            a unique identifier"""
        result = self.url
        if result:
            if result.startswith('./'):
                result = result[2:]
        else:
            result = '.'
        return result

    @staticmethod
    def _strip_gpx(name: str) ->str:
        """If it is there, strip traling .gpx.

        Returns:
            The stripped string.

        """
        if name.endswith('.gpx'):
            return name[:-4]
        return name

    def _load_symlinks(self, directory=None):
        """scan the subdirectories with the symlinks.

        If the content of a gpxfile changes, the symlinks might have to
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
                        gpx_target = self._strip_gpx(os.path.basename(target))
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

    @staticmethod
    def _sanitize_name(value) ->str:
        """Change it to legal file name characters.

        Returns:
            the sanitized name

        """
        if value is None:
            return None
        return value.replace('/', '_')

    def gpx_path(self, ident) ->str:
        """The full path name for the local copy of a gpxfile.

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

    def _gpx_from_headers(self, ident):
        """Quick scan of file for getting some header fields.

        We do this by removing everything after the first point
        (or if no point is given everthin after metadata).

        Returns: Gpx

        """
        self.dump_ids('_gpx_from_headers', ident)
        result = Gpx()
        with open(self.gpx_path(ident), encoding='utf8') as raw_file:
            data = raw_file.read(100000)
            head = None
            parts = data.split('</trkpt>')
            if len(parts) > 1:
                head = parts[0] + '</trkpt></trkseg></trk></gpx>'
            else:
                parts = data.split('</metadata>')
                if len(parts) > 1:
                    head = parts[0] + '</metadata></gpx>'
            if head:
                try:
                    result = Gpx.parse(head, is_complete=False)
                    self.logger.info('Incompletely parsed %s', result)
                except GPXXMLSyntaxException:
                    self.logger.info(
                        '%s: GpxFile metadata cannot be extracted, there is too much',
                        GpxFile.identifier(self, ident))
        return result

    def _list(self):
        """get all gpxfiles for this user."""
        self._symlinks = defaultdict(list)
        self._load_symlinks()
        for _ in self._list_gpx():
            gpx = self._gpx_from_headers(_)
            gpx.is_complete = False
            self._found_gpxfile(_, gpx)

    def _read(self, gpxfile):
        """fill the gpxfile with all its data from source."""
        self.dump_ids('_read', gpxfile.id_in_backend)
        with open(self.gpx_path(gpxfile.id_in_backend), encoding='utf-8') as in_file:
            gpxfile.gpx = Gpx.parse(in_file.read())

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

    def _symlink_path(self, gpxfile) ->str:
        """The path for the speaking symbolic link: YYYY/MM/title.gpx.

        Missing directories YYYY/MM are created.

        Returns:
            The path

        """
        ident = gpxfile.id_in_backend
        time = datetime.datetime.fromtimestamp(os.path.getmtime(self.gpx_path(ident)))
        by_month_dir = os.path.join(self.url, '{}'.format(time.year), '{:02}'.format(time.month))  # noqa
        if not os.path.exists(by_month_dir):
            os.makedirs(by_month_dir)
        else:
            # make sure there is no dead symlink with our wanted name.
            self._load_symlinks(by_month_dir)
        name = gpxfile.title or ident
        name += '.gpx'
        return self._make_path_unique(os.path.join(by_month_dir, self._sanitize_name(name)))

    def _new_ident(self, gpxfile):
        """Create an id for gpxfile.

        Returns: The new ident.

        """
        ident = gpxfile.id_in_backend
        if ident is None:
            if self.account.id_method == 'counter':
                try:
                    ident = str(max(int(x) for x in self._list_gpx()) + 1)
                except ValueError:
                    ident = '1'
            else:
                ident = self._new_id_from(None)
        return ident

    def _make_symlinks(self, gpxfile):
        """Make all symlinks for gpxfile."""
        ident = gpxfile.id_in_backend
        gpx_pathname = self.gpx_path(ident)
        link_name = self._symlink_path(gpxfile)
        basename = os.path.basename(gpx_pathname)
        link_target = os.path.join('..', '..', basename)
        os.symlink(link_target, link_name)
        if link_name not in self._symlinks[ident]:
            self._symlinks[ident].append(link_name)

    def _change_ident(self, gpxfile, new_ident: str):
        """Change the id in the backend. Make it unique if needed."""
        assert gpxfile.id_in_backend != new_ident
        unique_id = self._new_id_from(new_ident)
        self._remove_symlinks(gpxfile.id_in_backend)
        self.logger.info('%s: renamed %s to %s', self.account, gpxfile.id_in_backend, unique_id)
        os.rename(self.gpx_path(gpxfile.id_in_backend), self.gpx_path(unique_id))
        gpxfile.id_in_backend = unique_id
        self._make_symlinks(gpxfile)

    def _write_all(self, gpxfile) ->str:
        """save full gpx gpxfile.

        Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt gpxfile.id_in_backend.

        Returns:
            the new gpxfile.id_in_backend

        """
        new_ident = self._new_ident(gpxfile)

        gpxfile.id_in_backend = new_ident
        new_path = self.gpx_path(new_ident)
        tmp_path = new_path + '.new'
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        with open(tmp_path, 'w', encoding='utf-8') as out_file:
            out_file.write(gpxfile.xml())
        time = gpxfile.first_time
        if time:
            os.utime(tmp_path, (time.timestamp(), time.timestamp()))
        os.replace(tmp_path, new_path)
        logging.debug('written %s', new_path)
        self.dump_ids('_write_all after os.replace', new_ident)
        return new_ident

    def dump_ids(self, prefix, ident):
        """For debugging show the IDs found in a file."""
        if self.logger.isEnabledFor(logging.DEBUG):
            with open(self.gpx_path(ident), 'r', encoding='utf-8') as written_file:
                for line in written_file:
                    if 'Id:' in line:
                        self.logger.debug('%s: ident:%s ID-Line:%s', prefix, ident, line)

    def detach(self):
        """also remove temporary directory."""
        super(Directory, self).detach()
        if self.account.is_temporary:
            remove_directory(self.url)

    @classmethod
    def _check_id_legal(cls, value):
        """Check if value is a legal id.

        If not, raise ValueError.

        """
        # it is not necessary to call BackendBase._check_id_legal
        if value is not None:
            if '/' in value:
                raise ValueError('/ not allowed as id_in_backend for Directory')
            if value == '.':
                raise ValueError('. not allowed as id_in_backend for Directory')
