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

    Args:
        url (str): a directory. If not given, allocate a temporary directory and remove
            it in destroy().
            if url is given but the directory does not exist it is allocated.
        auth (tuple(str, str)): Unused.
        cleanup (bool): If True and Url is None, destroy() will deallocate the directory.
    """

    # pylint: disable=abstract-method

    def __init__(self, url=None, auth=None, cleanup=False):
        self.url_given = bool(url)
        if not self.url_given:
            url = tempfile.mkdtemp(prefix='gpxity.')
        super(Directory, self).__init__(os.path.abspath(os.path.expanduser(url)), auth=auth, cleanup=cleanup)
        if not os.path.exists(self.url):
            self.allocate()
        self._symlinks = self._load_symlinks()

    def _load_symlinks(self):
        """scan the subdirectories with the symlinks. If the content of an
        actiivty changes, the symlinks might have to be adapted. But
        we do not know the name of the existing symlink anymore. So
        just scan them all and assign them to id_in_backend."""
        result = defaultdict(list)
        for dirpath, _, filenames in os.walk(self.url):
            for filename in filenames:
                full_name = os.path.join(dirpath, filename)
                try:
                    result[os.readlink(full_name)].append(full_name)
                except OSError:
                    pass
        return result

    def allocate(self):
        """create the directory as specified by self.url"""
        os.makedirs(self.url)

    def deallocate(self):
        """deletes the entire directory. Since this is dangerous, all activities must be removed first."""
        os.rmdir(self.url)

    def _set_new_id(self, activity):
        """a not yet existant file name"""
        if activity.backend is self and activity.id_in_backend:
            value = activity.id_in_backend
        elif activity.title:
            value = activity.title
        else:
            value = tempfile.NamedTemporaryFile(dir=self.url).name
        ctr = 0
        unique_value = value
        while os.path.exists(os.path.join(self.url, unique_value + '.gpx')):
            ctr += 1
            unique_value = '{}.{}'.format(value, ctr)
        activity.id_in_backend = unique_value

    def destroy(self):
        """remove the entire backend IF we created it in __init__, otherwise only empty it"""
        super(Directory, self).destroy()
        if self.cleanup and not self.url_given:
            self.deallocate()

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
        for _ in self._list_gpx():
            yield Activity(self, _)

    def get_time(self) ->datetime.datetime:
        """get server time as a Linux timestamp"""
        return datetime.datetime.now()

    def load_full(self, activity):
        """fills the activity with all its data from source."""
        activity.loading = True
        try:
            with open(self._gpx_path(activity)) as in_file:
                activity.parse(in_file)
        finally:
            activity.loading = False

    def _remove_activity_in_backend(self, activity):
        """remove all data about it in this backend"""
        os.remove(self._gpx_path(activity))

    def _remove_activity_file(self, activity):
        """remove the file, its symlinks and empty symlink parent directories"""
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
        link_name = activity.id_in_backend
        if not link_name:
            link_name = '{:02}_{:02}:{:02}:{:02}'.format(
                time.day, time.hour, time.minute, time.second)
        return os.path.join(by_month_dir, link_name)

    def _save_full(self, activity):
        """save full gpx track. Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt activity.id_in_backend."""
        self._remove_activity_file(activity)
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
                os.symlink(_gpx_path, link_name)
                self._symlinks[activity.id_in_backend].append(link_name)
        except BaseException as exc:
            print(exc)
            os.remove(_gpx_path)
            raise

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.url)
