#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Defines :class:`gpxity.backends.Directory`
"""


import os
import datetime
import tempfile

from .. import Backend, Activity

__all__ = ['Directory']

class Directory(Backend):
    """Uses a directory for storage.

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

    def allocate(self):
        """create the directory as specified by self.url"""
        os.makedirs(self.url)

    def deallocate(self):
        """deletes the entire directory. Since this is dangerous, all activities must be removed first."""
        os.rmdir(self.url)

    def new_id(self, activity):
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
        return unique_value

    def destroy(self):
        """remove the entire backend IF we created it in __init__, otherwise only empty it"""
        super(Directory, self).destroy()
        if self.cleanup and not self.url_given:
            self.deallocate()

    def _gpx_path(self, activity):
        """The full path name for the local copy of an activity"""
        if not activity.id_in_backend:
            activity.id_in_backend = self.new_id(activity)
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

    def change_title(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def change_description(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def change_what(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def change_public(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def _save(self, activity):
        """save full gpx track"""
        _gpx_path = self._gpx_path(activity)
        try:
            with open(_gpx_path, 'w') as out_file:
                out_file.write(activity.to_xml())
            time = activity.time
            if time:
                os.utime(_gpx_path, (time.timestamp(), time.timestamp()))
            link_name = activity.title
            if not link_name and time:
                link_name = '{:02}_{:02}:{:02}:{:02}'.format(
                    time.day, time.hour, time.minute, time.second)
            if link_name:
                by_month_dir = '{}{}/{:02}/'.format(self.url, time.year, time.month)
                by_month_path = by_month_dir + link_name
                if not os.path.exists(by_month_dir):
                    os.makedirs(by_month_dir)
                if os.path.lexists(by_month_path):
                    os.remove(by_month_path)
                os.symlink(_gpx_path, by_month_path)
        except BaseException as exc:
            print(exc)
            os.remove(_gpx_path)
            raise

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.url)
