#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements :class:`gpxity.WPTrackServer`.

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
from .mmt import MMT

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

    The section in  auth.cfg could look like

    [wptrackserver:username]
    Url = hostname
    Mysql =user@db_name
    Password = mysql_password

    username is the wordpress user name.

    hostname is the server wordpress is running on

    user is the mysql user. Find it in the wordpress config file,
    look for DB_USER.

    db_name is the name of the database. Find it in the wordpress config file,
    look for DB_NAME.

    mysql_password is for the mysql user. Find it in the wordpress config file,
    look for DB_PASSWORD.

    """

    # pylint: disable=abstract-method

    legal_categories = MMT.legal_categories

    needs_config = False

    _keywords_marker = '\nKEYWORDS: '

    _max_length = {'title': 255, 'description': 255}

    def __init__(self, url=None, auth=None, cleanup=False, timeout=None):
        """See class docstring. The url is host."""
        super(WPTrackserver, self).__init__(url, auth, cleanup, timeout)
        self.logger.debug('new WPTrackserver:%s', id(self))
        try:
            user, database = self.config.mysql.split('@')
        except ValueError:
            raise Backend.BackendException('Url is illegal: {}'.format(self.url))
        self.logger.debug('connecting to %s as %s with pw %s to db %s', self.url, user, self.config.password, database)
        try:
            self._db = MySQLdb.connect(
                host=self.url, user=user, passwd=self.config.password, database=database,
                autocommit=True, charset='utf8')
        except _mysql_exceptions.OperationalError as exc:
            raise Backend.BackendException(exc)
        self._cursor = self._db.cursor()
        self._cursor.execute('select id from wp_users where user_login=%s', [self.config.username])
        row = self._cursor.fetchone()
        if row is None:
            raise Backend.BackendException('WPTrackserver: User {} is not known'.format(self.config.username))
        self.user_id = row[0]

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

    def _decode_description(self, track, value, into_header_data=False):
        """Extract keywords.

        Returns: The decoded description

        """
        if self._keywords_marker in value:
            descr, raw_keywords = value.split(self._keywords_marker)
            # not into_header_data! because _read_all only delivers points
            track._decode_keywords(raw_keywords)
        else:
            descr = value
        track._header_data['description'] = descr
        return descr

    def _enrich_with_headers(self, track, row):
        """Get header values out of row."""
        track._header_data['time'] = row[1]
        track._header_data['title'] = row[2]
        self._decode_description(track, row[3])
        track._header_data['distance'] = row[4] / 1000.0

    def _yield_tracks(self):
        """."""
        self._cursor.execute(
            'select id,created,name,comment,distance from wp_ts_tracks where user_id=%s', [self.user_id])
        for _ in self._cursor.fetchall():
            track = self._found_track('{:06}'.format(_[0]))
            self._enrich_with_headers(track, _)
            yield track

    @staticmethod
    def __point(row):
        """Make a GPX point.

        Returns:
            The point

        """
        return mod_gpx.GPXTrackPoint(
            latitude=float(row[0]),
            longitude=float(row[1]),
            time=row[2])

    def _read_all(self, track) ->None:
        """Read the full track."""
        assert track.id_in_backend
        self._cursor.execute(
            'select latitude,longitude,occurred from wp_ts_locations where trip_id=%s', [track.id_in_backend])
        track.add_points([self.__point(x) for x in self._cursor.fetchall()])

    def _save_header(self, track):
        """Write all header fields. May set track.id_in_backend."""
        description = self._encode_description(track)
        title = track.title[:self._max_length['title']]
        track_time = track.time or datetime.datetime(year=1970, month=1, day=1, hour=1)
        if track.id_in_backend is None:
            self._cursor.execute(
                'insert into wp_ts_tracks(user_id,name,created,comment,distance,source) values(%s,%s,%s,%s,%s,%s)',
                (self.user_id, title, track_time, description, track.distance(), ''))
            track.id_in_backend = str(self._cursor.lastrowid)
            self.logger.debug(
                'new id %s: insert into wp_ts_tracks(user_id,name,created,comment,distance,source) '
                'values(%s,%s,%s,%s,%s,%s)',
                track.id_in_backend, self.user_id, title, track_time, description, track.distance(), '')
        else:
            self._cursor.execute(
                'update wp_ts_tracks set name=%s,created=%s,comment=%s,distance=%s where id=%s',
                (title, track_time, description, track.distance(), track.id_in_backend))
            self.logger.debug(
                'update wp_ts_tracks set name=%s,created=%s,comment=%s,distance=%s where id=%s',
                title, track_time, description, track.distance(), track.id_in_backend)
            self.logger.debug('save_header: rewrite %s', track.id_in_backend)

    def _write_all(self, track) ->str:
        """save full gpx track.

        Since the file name uses title and title may have changed,
        compute new file name and remove the old files. We also adapt track.id_in_backend.

        Returns:
            the new track.id_in_backend

        """
        self._save_header(track)
        self._cursor.execute('delete from wp_ts_locations where trip_id=%s', [track.id_in_backend])
        data = [(track.id_in_backend, x.latitude, x.longitude, x.elevation or 0.0, x.time)
                for x in track.points()]  # noqa
        self._cursor.executemany(
            'insert into wp_ts_locations(trip_id, latitude, longitude, altitude, occurred, comment, speed, heading)'
            ' values(%s, %s, %s, %s, %s,"",0.0, 0.0)', data)
        return track.id_in_backend

    def _remove_ident(self, ident: str) ->None:
        """backend dependent implementation."""
        self._cursor.execute('delete from wp_ts_locations where trip_id=%s', [ident])
        cmd = 'delete from wp_ts_tracks where id=%s'
        self.logger.debug(cmd, ident)
        self._cursor.execute(cmd, [ident])

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
