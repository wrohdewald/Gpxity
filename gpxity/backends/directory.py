#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Defines :class:`gpxity.backends.directory.Directory`
"""


import os
import datetime
import tempfile
from collections import defaultdict

from .. import Backend, Activity

__all__ = ['Directory']

class Directory(Backend):
    """Uses a directory for storage. The filename minus the .gpx ending is used as the storage id.
    If the activity has a title, use the title as storage id, making it unique by attaching a number if needed.
    An activity without title gets a random name.

    The main directory (given by :attr:`~gpxity.backends.directory.Directory.url`) will have
    subdirectories YYYY/MM (year/month) with only the activities for one month.
    Those are symbolic links to the main file and have the same file name.

    This backend uses activity.title for the id. If an activity has no title, it uses a random
    sequence of characters. Changing the title also changes the id.

    Args:
        url (str): a directory. If not given, use a unique temporary directory named
            gpxpy.X where X are some random characters.
            If the directory does not exist, it is created.
        auth (tuple(str, str)): Unused.
        cleanup (bool): If True, :meth:`destroy` will remove all activities. If url was
            not given, it will also remove the directory.

    Attributes:
        prefix (str): The prefix for temporary directories.
    """

   # skip_test = True
    # pylint: disable=abstract-method

    prefix = 'gpxity.'

    def __init__(self, url=None, auth=None, cleanup=False):
        self.url_given = bool(url)
        if not self.url_given:
            url = tempfile.mkdtemp(prefix=self.prefix)
        super(Directory, self).__init__(os.path.abspath(os.path.expanduser(url)), auth=auth, cleanup=cleanup)
        if not os.path.exists(self.url):
            os.makedirs(self.url)
        self._symlinks = None
        self._load_symlinks()

    def _load_symlinks(self):
        """scan the subdirectories with the symlinks. If the content of an
        actiivty changes, the symlinks might have to be adapted. But
        we do not know the name of the existing symlink anymore. So
        just scan them all and assign them to id_in_backend."""
        self._symlinks = defaultdict(list)
        for dirpath, _, filenames in os.walk(self.url):
            for filename in filenames:
                full_name = os.path.join(dirpath, filename)
                if os.path.islink(full_name):
                    if os.path.exists(full_name):
                        target = os.readlink(full_name)
                        gpx_target = os.path.basename(target)
                        if gpx_target.endswith('.gpx'):
                            # it really should ...
                            gpx_target = gpx_target[:-4]
                        self._symlinks[gpx_target].append(full_name)
                    else:
                        os.remove(full_name)
                        raise Exception('{}: removed dead symbolic link {}'.format(
                            self, full_name))

    def _set_new_id(self, activity):
        """a not yet existant file name"""
        if activity.title:
            value = activity.title
        else:
            value = os.path.basename(tempfile.NamedTemporaryFile(dir=self.url, prefix='').name)
        path = self._make_path_unique(os.path.join(self.url, value + '.gpx'))
        activity.id_in_backend = os.path.basename(path)[:-4]

    @staticmethod
    def _make_path_unique(value):
        """if the file name already exists, append a serial number"""
        ctr = 0
        unique_value = value
        while os.path.exists(unique_value):
            ctr += 1
            if value.endswith('.gpx'):
                unique_value = '{}.{}.gpx'.format(value[:-4], ctr)
            else:
                unique_value = '{}.{}'.format(value, ctr)
        return unique_value

    def destroy(self):
        """If `cleanup` was set at init time, removes all activities.
        If :attr:`~gpxity.backends.directory.Directory.url` was set at init time,
        also removes the directory."""
        super(Directory, self).destroy()
        if self._cleanup:
            self.remove_all()
            if not self.url_given:
                os.rmdir(self.url)

    def _gpx_path(self, activity):
        """The full path name for the local copy of an activity"""
        if not activity.id_in_backend:
            self._set_new_id(activity)
        base_name = '{}.gpx'.format(activity.id_in_backend)
        return os.path.join(self.url, base_name)

    def _list_gpx(self):
        """returns a generator of all gpx files, with .gpx removed"""
        gpx_names = (x for x in os.listdir(self.url) if x.endswith('.gpx'))
        return (x.replace('.gpx', '') for x in gpx_names)

    def _yield_activities(self):
        self.activities.clear()
        self._load_symlinks()
        for _ in self._list_gpx():
            yield Activity(self, _)

    def get_time(self) ->datetime.datetime:
        """get server time as a Linux timestamp"""
        return datetime.datetime.now()

    def load_full(self, activity):
        """fills the activity with all its data from source."""
        with activity.loading():
            with open(self._gpx_path(activity)) as in_file:
                activity.parse(in_file)

    def _remove_activity_in_backend(self, activity):
        """Removes its symlinks, empty symlink parent directories  and the file, in this order."""
        for symlink in self._symlinks[activity.id_in_backend]:
            os.remove(symlink)
            symlink_dir = os.path.split(symlink)[0]
            try:
                os.removedirs(symlink_dir)
            except OSError:
                pass
        self._symlinks[activity.id_in_backend] = list()
        gpx_file = self._gpx_path(activity)
        if os.path.exists(gpx_file):
            os.remove(gpx_file)

    def _symlink_path(self, activity):
        """The path for the speaking symbolic link: YYYY/MM/title.gpx.
        Missing directories YYYY/MM are created.
        activity.time must be set."""
        time = activity.time
        by_month_dir = os.path.join(self.url, '{}'.format(time.year), '{:02}'.format(time.month))
        if not os.path.exists(by_month_dir):
            os.makedirs(by_month_dir)
        name = activity.title or activity.id_in_backend
        return self._make_path_unique(os.path.join(by_month_dir, name))

    def _save_full(self, activity):
        """save full gpx track. Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt activity.id_in_backend."""
        self._remove_activity_in_backend(activity)
        if activity.title:
            # enforce new id_in_backend using title
            activity.id_in_backend = None
        _gpx_path = self._gpx_path(activity)
        try:
            with open(_gpx_path, 'w') as out_file:
                out_file.write(activity.to_xml())
            time = activity.time
            if time:
                os.utime(_gpx_path, (time.timestamp(), time.timestamp()))
                link_name = self._symlink_path(activity)
                link_target = os.path.join('..', '..', '{}.gpx'.format(activity.id_in_backend))
                os.symlink(link_target, link_name)
                self._symlinks[activity.id_in_backend].append(link_name)
        except BaseException:
            raise

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.url)

Directory._define_support() # pylint: disable=protected-access
