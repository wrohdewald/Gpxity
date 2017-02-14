#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
Defines :class:`gpxmove.backends.LocalStorage`
"""


import os
import datetime
import tempfile


from .. import Storage, Activity

__all__ = ['LocalStorage']

class LocalStorage(Storage):
    """The local source. url is an existing directory. If url
    is not given, allocate a temporary directory and remove
    it in destroy().
    Those are GPX files not coming from an external source
    but created locally or copied manually from somewhere
    else. They may have arbitrary file names.
    The activity ident is the file name without .gpx

    """

    def __init__(self, url=None, auth=None, cleanup=False):
        self.url_given = bool(url)
        if not self.url_given:
            url = tempfile.mkdtemp(prefix='gpxmove.')
        super(LocalStorage, self).__init__(os.path.abspath(os.path.expanduser(url)), auth=auth, cleanup=cleanup)
        self._supports_all()
        if not os.path.exists(self.url):
            os.makedirs(self.url)
            self.created = True

    def new_id(self, activity):
        """a not yet existant file name"""
        try:
            value = activity.storage_ids[activity.source_storage]
        except KeyError:
            if activity.title:
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
        """remove the entire storage IF we created it in __init__, otherwise only empty it"""
        super(LocalStorage, self).destroy()
        if self.cleanup and not self.url_given:
            os.rmdir(self.url)

    def gpx_path(self, activity):
        """The full path name for the local copy of an activity"""
        if self not in activity.storage_ids:
            activity.add_to_storage(self, self.new_id(activity))
        value = activity.storage_ids[self]
        base_name = '{}.gpx'.format(value)
        return os.path.join(self.url, base_name)

    def list_gpx(self):
        """returns a generator of all gpx files, with .gpx removed"""
        gpx_names = (x for x in os.listdir(self.url) if x.endswith('.gpx'))
        return (x.replace('.gpx', '') for x in gpx_names)

    def _yield_activities(self):
        self.activities.clear()
        for _ in self.list_gpx():
            yield Activity(self, _)

    def get_time(self):
        """get MMT server time as a Linux timestamp"""
        return datetime.datetime.now()

    def load_full(self, activity):
        """fills the activity with all its data from source."""
        activity.loading = True
        try:
            with open(self.gpx_path(activity)) as in_file:
                activity.parse(in_file)
        finally:
            activity.loading = False

    def exists(self, activity):
        """is the full activity permanently in this storage?"""
        return os.path.exists(self.gpx_path(activity))

    def _remove_activity_in_storage(self, activity):
        """remove all data about it in this storage"""
        os.remove(self.gpx_path(activity))

    def change_title(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def change_description(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def change_what(self, activity):
        """We simply rewrite the entire local .gpx file"""
        self.save(activity)

    def save(self, activity):
        """save full gpx track"""
        gpx_path = self.gpx_path(activity)
        try:
            with open(gpx_path, 'w') as out_file:
                out_file.write(activity.to_xml())
            time = activity.time
            if time:
                os.utime(gpx_path, (time.timestamp(), time.timestamp()))
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
                os.symlink(gpx_path, by_month_path)
        except BaseException as exc:
            print(exc)
            os.remove(gpx_path)
            raise

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.url)
