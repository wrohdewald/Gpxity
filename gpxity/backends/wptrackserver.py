#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.wptrackserver.WPTrackserver`.

WPTrackserver talks directly to the WP mysql database holding the trackserver data.

This backend does not directly support Track.category, Track.status, Track.keywords.
All this is added to the description when writing and extracted when reading. So
the description in the backend will contain all keywords, but Track.description
does not.

The database has a maximum field length of 255 for strings. If it is exceeded, the
last part of the strings will be thrown away silently when writing into the database.

"""

# pylint: disable=protected-access

import datetime

from gpxpy import gpx as mod_gpx

from ..backend import Backend
from ..util import add_speed, utc_to_local_delta

try:
    import MySQLdb
    HAVE_MYSQL = True
    import _mysql_exceptions
except ImportError:
    HAVE_MYSQL = False

__all__ = ['WPTrackserver']


class WPTrackserver(Backend):

    """Talk directly to the wordpress mysql database holding the trackserver data.

    See https://www.grendelman.net/wp/trackserver-wordpress-plugin/

    The section in the acounts file could look like::

        Account wp
            Backend WPTrackserver
            Username wordpress_username
            Url localhost
            Mysql wordpress_7@wordpress_7
            Password xxxx
            Fences 53.7505,10.7445/750

    Find the values for MySql in the wordpress config file (DB_USER and DB_NAME).

    Password is for the mysql user. Find it in the wordpress config file,
    look for DB_PASSWORD.

    """

    # pylint: disable=abstract-method

    test_is_expensive = False

    _keywords_marker = '\nKEYWORDS: '

    _max_length = {'title': 255, 'description': 255}

    def __init__(self, account=None):
        """See class docstring. The url is host."""
        super(WPTrackserver, self).__init__(account)
        self.__cached_db = None
        self.__cached_user_id = None

    def __connect_mysql(self):
        """Connect to the Mysql server.

        Returns: The db handle

        """
        try:
            user, database = self.account.mysql.split('@')
        except ValueError:
            raise Backend.BackendException('Url is illegal: {}'.format(self.url))
        try:
            result = MySQLdb.connect(
                host=self.url, user=user, passwd=self.account.password, database=database,
                autocommit=True, charset='utf8')
            if self.__cached_db:
                self.logger.info('reconnected to %s %s', self.url, database)
            else:
                self.logger.info('connected to %s %s', self.url, database)
            return result
        except _mysql_exceptions.Error as exc:
            raise Backend.BackendException(
                '{}: host={} user={} passwd={} database={}'.format(
                    exc, self.url, user, self.account.password, database))

    @property
    def _db(self):
        """Cached mysql handle.

        Returns: The handle.

        """
        if self.__cached_db is None:
            self.__cached_db = self.__connect_mysql()
        return self.__cached_db

    @property
    def _user_id(self):
        """Cached user_id from mysql.

        Returns: The user_id in wordpress

        """
        if self.__cached_user_id is None:
            if not self.account.username:
                raise self.BackendException('{} needs a username'.format(self.account))
            cursor = self.__exec_mysql('select id from wp_users where user_login=%s', [self.account.username])
            row = cursor.fetchone()
            if row is None:
                raise Backend.BackendException('WPTrackserver: User {} is not known'.format(self.account.username))
            self.__cached_user_id = row[0]
        return self.__cached_user_id

    def _encode_description(self, track):
        """Encode keywords in description.

        If description exceeds its maximum length, first remove keywords and then
        shorten the description.

        Returns: The string to be saved in the database.

        """
        def fmt_result():
            return '{}{}{}'.format(
                track.description, self._keywords_marker, ', '.join(kw_parts))

        max_length = self._max_length['description']
        kw_parts = track._encode_keywords().split(', ')
        result = fmt_result()
        if len(result) > max_length:
            while kw_parts and len(result) > max_length:
                kw_parts = kw_parts[:-1]
                result = fmt_result()
        return result[:max_length]

    def _decode_description(self, track, value):
        """Extract keywords.

        Returns: The decoded description

        """
        if self._keywords_marker in value:
            descr, raw_keywords = value.split(self._keywords_marker)
            track._decode_keywords(raw_keywords)
        else:
            descr = value
        track.description = descr
        return descr

    def _enrich_with_headers(self, track, row):
        """Get header values out of row."""
        track._header_data['time'] = row[1]
        track.title = row[2]
        self._decode_description(track, row[3].replace('\r', ''))
        track._set_distance(row[4] / 1000.0)

    def _load_track_headers(self):
        """."""
        cmd = 'select id,created,name,comment,distance from wp_ts_tracks where user_id=%s'
        args = (self._user_id, )  # noqa
        cursor = self.__exec_mysql(cmd, args)
        for _ in cursor.fetchall():
            track = self._found_track(str(int(_[0])))
            self._enrich_with_headers(track, _)

    @staticmethod
    def __point(row):
        """Make a GPX point.

        Returns:
            The point

        """
        time_delta = utc_to_local_delta()  # WPTrackserver wants local time
        return mod_gpx.GPXTrackPoint(
            latitude=float(row[0]),
            longitude=float(row[1]),
            time=row[2] - time_delta)

    def _read_all(self, track) ->None:
        """Read the full track."""
        assert track.id_in_backend
        cursor = self.__exec_mysql(
            'select latitude,longitude,occurred from wp_ts_locations where trip_id=%s', [track.id_in_backend])
        track.add_points([self.__point(x) for x in cursor.fetchall()])

    @staticmethod
    def __needs_insert(cursor, ident) -> bool:
        """Check if the header exists in the track table.

        Returns: True or False.

        """
        if ident is None:
            return True
        cursor.execute('select 1 from wp_ts_tracks where id=%s', (ident, ))  # noqa
        return len(cursor.fetchall()) == 0

    def _save_header(self, track):
        """Write all header fields. May set track.id_in_backend.

        Be aware that the track may still have 0 points (all fenced away).
        Returns: The new id_in_backend.

        """
        description = self._encode_description(track)
        title = track.title[:self._max_length['title']]
        # 1970-01-01 01:00:00 does not work. This is the local time but the minimal value 1970-01-01 ... is UTC
        track_time = track.time or datetime.datetime(year=1970, month=1, day=3, hour=1)
        track_distance = track.distance() * 1000
        cursor = self._db.cursor()
        if self.__needs_insert(cursor, track.id_in_backend):
            if track.id_in_backend is None:
                cmd = 'insert into wp_ts_tracks(user_id,name,created,comment,distance,source)' \
                    ' values(%s,%s,%s,%s,%s,%s)'
                args = (self._user_id, title, track_time, description, track_distance, '')
                cursor = self.__exec_mysql(cmd, args)
                track.id_in_backend = str(int(cursor.lastrowid))
            else:
                self.__exec_mysql(
                    'insert into wp_ts_tracks(id,user_id,name,created,comment,distance,source) '
                    ' values(%s,%s,%s,%s,%s,%s,%s)',
                    (track.id_in_backend, self._user_id, title, track_time, description, track_distance, ''))
                self.logger.error('wptrackserver wrote missing header with id=%s', track.id_in_backend)
        else:
            self.__exec_mysql(
                'update wp_ts_tracks set name=%s,created=%s,comment=%s,distance=%s where id=%s',
                (title, track_time, description, track_distance, track.id_in_backend))
        return track.id_in_backend

    def _write_all(self, track) ->str:
        """save full gpx track.

        Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt track.id_in_backend.

        Returns:
            the new track.id_in_backend

        """
        result = self._save_header(track)
        self.__exec_mysql('delete from wp_ts_locations where trip_id=%s', [int(result)])
        self.__write_points(track, track.points())
        return result

    def __write_points(self, track, points):
        """save points in the track."""
        points = list(points)
        time_delta = utc_to_local_delta()  # WPTrackserver wants local time
        cmd = 'insert into wp_ts_locations(trip_id, latitude, longitude, altitude,' \
            ' occurred, speed, comment, heading)' \
            ' values(%s, %s, %s, %s, %s, %s, "", 0.0)'
        args = [(
            track.id_in_backend, x.latitude, x.longitude, x.elevation or 0.0,
            x.time + time_delta, x.gpxity_speed if hasattr(x, 'gpxity_speed') else 0.0) for x in points]
        if args:
            self.__exec_mysql(cmd, args, many=True)

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation."""
        cmd = 'delete from wp_ts_locations where trip_id=%s'
        self.__exec_mysql(cmd, [int(ident)])
        cmd = 'delete from wp_ts_tracks where id=%s'
        self.__exec_mysql(cmd, [int(ident)])

    def _change_ident(self, track, new_ident: str):
        """Change the id in the backend."""
        assert track.id_in_backend != new_ident
        if new_ident in self:
            raise ValueError(
                'New id_in_backend {} already exists in {}'.format(
                    new_ident, self.account))
        try:
            self.__exec_mysql(
                'update wp_ts_tracks set id=%s where id=%s',
                (new_ident, track.id_in_backend))
        except _mysql_exceptions.DataError as exc:
            raise ValueError(str(exc))
        self.__exec_mysql(
            'update wp_ts_locations set trip_id=%s where trip_id=%s',
            (new_ident, track.id_in_backend))

        self.logger.info('%s: renamed %s to %s', self.account, track.id_in_backend, new_ident)
        track.id_in_backend = new_ident

    @classmethod
    def is_disabled(cls) ->bool:
        """True if this backend is disabled by env variable GPXITY_DISABLE_BACKENDS.

        or because python mysql is not installed.

        This variable is a comma separated list of Backend class names.

        Returns:
            True if disabled

        """
        if not HAVE_MYSQL:
            return True
        return super(WPTrackserver, cls).is_disabled()

    def _lifetrack_start(self, track, points) ->str:
        """Start a new lifetrack with initial points.

        Returns:
            new_ident: New track id

        """
        new_ident = self._save_header(track)
        self._lifetrack_update(track, points)
        return new_ident

    def _lifetrack_update(self, track, points):
        """Update a lifetrack with points.

        Args:
            track: The lifetrack
            points: The new points

        """
        points = list(points)
        add_speed(list(track.points()), window=10)
        cmd = 'update wp_ts_tracks set distance=%s where id=%s'
        args = (track.distance() * 1000, track.id_in_backend)
        self.__exec_mysql(cmd, args)
        self.__write_points(track, points)

    def __exec_mysql(self, cmd, args, many=False):
        """Wrapper.

        Returns:
            cursor or None if done nothing

        """
        def logit(prefix):
            if many:
                # only log the first one
                self.logger.debug(prefix + " executemany, first one: " + cmd, *args[0])
            else:
                self.logger.debug(prefix + ' ' + cmd, *args)

        def do_it():
            try:
                execute(cmd, args)
            except _mysql_exceptions.Error as exception:
                logit("MySQL Error: {} for".format(exception))
                raise
        cursor = self._db.cursor()
        execute = cursor.executemany if many else cursor.execute
        try:
            do_it()
        except _mysql_exceptions.OperationalError:
            # timeout disconnected
            self.__connect_mysql()
            do_it()
        return cursor

    @classmethod
    def _check_id_legal(cls, value):
        """Check if value is a legal id.

        If not, raise ValueError.

        """
        # it is not necessary to call BackendBase._check_id_legal
        if value is not None:
            if int(value) <= 0:
                # max is actually 2147483647 but the column is autoincrement
                # so just make mysql fail if we exceed that
                raise ValueError('{} not allowed as id_in_backend for WPTrackserver'.format(value))
