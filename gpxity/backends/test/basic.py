# -*- coding: utf-8 -*-


# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""Tests for gpxity.backends."""

import unittest
import pwd
import os
import io
import datetime
import time
import random
from pkgutil import get_data
import tempfile
from contextlib import contextmanager
from subprocess import Popen, PIPE
import logging
try:
    import MySQLdb
    import _mysql_exceptions
except ImportError:
    pass


import gpxpy
from gpxpy.gpx import GPXTrackPoint

from ... import Track, Backend, Authenticate
from .. import Mailer, WPTrackserver, Directory, GPSIES

# pylint: disable=attribute-defined-outside-init,protected-access

__all__ = ['BasicTest']


def disabled(*args) ->bool:
    """True if any of the backends is disabled.

    Returns:
        True or False

    """
    reason = list()
    for _ in args:
        if _.is_disabled():
            reason.append(_.__name__)
    return bool(reason), '{} {} disabled'.format(','.join(reason), 'is' if len(reason) == 1 else 'are')  # noqa


class BasicTest(unittest.TestCase):

    """define some helpers."""

    test_passwd = 'pwd'

    mysql_ip_address = None
    mysql_docker_name = 'gpxitytest_mysql'

    def setUp(self):  # noqa
        """define test specific Directory.prefix."""
        self.maxDiff = None  # pylint: disable=invalid-name
        Authenticate.path = os.path.join(os.path.dirname(__file__), 'test_auth_cfg')
        self.logger = logging.getLogger()
        self.logger.level = logging.DEBUG
        self.logger.debug('auth file now is %s', Authenticate.path)
        self.start_time = datetime.datetime.now()
        self.unicode_string1 = 'unicode szlig: ß'
        self.unicode_string2 = 'something japanese:の諸問題'
        Directory.prefix = 'gpxity.' + '.'.join(self.id().split('.')[-2:]) + '_'  # noqa
        path = tempfile.mkdtemp(prefix=Directory.prefix)
        Backend._session.clear()

        if not os.path.exists(path):
            os.mkdir(path)
        Directory.prefix = path

        if not Mailer.is_disabled():
            self.start_mailserver()

    def tearDown(self):  # noqa
        """Check if there are still /tmp/gpxitytest.* directories."""
        if not Mailer.is_disabled():
            self.stop_mailserver()
        os.rmdir(Directory.prefix)
        timedelta = datetime.datetime.now() - self.start_time
        self.logger.debug('%s seconds ', timedelta.seconds)
        logging.shutdown()

    @contextmanager
    def subTest(self, name, **params):  # noqa pylint: disable=arguments-differ
        """With pytest, subTest does not do much. At least print the name."""
        if not isinstance(name, str):
            name = name.__name__
        _ = '{} subTest {}: {}'.format('-' * 10, self.id().split('.')[-1], name)
        _ += '-' * (80 - len(_))
        self.logger.debug(_)
        yield super(BasicTest, self).subTest(' ' + name, **params)

    @staticmethod
    def _get_gpx_from_test_file(name: str):
        """get data from a predefined gpx file.

        name is without .gpx

        Returns:=
            A GPX object

        """
        gpx_test_file = os.path.join(os.path.dirname(__file__), '{}.gpx'.format(name))
        if not os.path.exists(gpx_test_file):
            raise Exception('MMTTests needs a GPX file named {}.gpx for testing in {}'.format(
                name, os.getcwd()))
        return gpxpy.parse(io.StringIO(get_data(__package__, '{}.gpx'.format(name)).decode('utf-8')))

    @classmethod
    def create_test_track(
            cls, count: int = 1, idx: int = 0, category: str = None, public: bool = False,
            start_time=None, end_time=None):
        """create a :class:`~gpxity.track.Track`.

        It starts off with **test.gpx** and appends a
        last track point, it also changes the time stamp of the last point.
        This is done using **count** and **idx**: The last point is set such that
        looking at the tracks, they all go in a different direction clockwise, with an angle
        in degrees of :literal:`360 * idx / count`.

        Args:
            count: See above. Using 1 as default if not given.
            idx: See above. Using 0 as default if not given.
            category: The wanted value for the track.
                Default: if count == len(:attr:`Track.legal_categories <gpxity.track.Track.legal_categories>`),
                the default value will be legal_categories[idx].
                Otherwise a random value will be applied.
            public: should the tracks be public or private?
            start_time: If given, assign it to the first point and adjust all following times
            end_time: explicit time for the last point. If None: See above.

        Returns:
            (~gpxity.track.Track): A new track not bound to a backend

        """
        gpx = cls._get_gpx_from_test_file('test')
        if start_time is not None:
            _ = start_time - gpx.tracks[0].segments[0].points[0].time
            gpx.adjust_time(_)
        last_points = gpx.tracks[-1].segments[-1].points
        if end_time is None:
            end_time = last_points[-1].time + datetime.timedelta(hours=10, seconds=idx)
        new_point = GPXTrackPoint(
            latitude=last_points[-1].latitude, longitude=last_points[-1].longitude + 0.001, time=end_time)
        _ = gpxpy.geo.LocationDelta(distance=1000, angle=360 * idx / count)
        new_point.move(_)
        last_points.append(new_point)

        # now set all times such that they are in order with this track and do not overlap
        # with other test tracks
        _ = gpx.tracks[0].segments[0].points[0].time
        duration = new_point.time - _ + datetime.timedelta(seconds=10)
        for point in gpx.walk(only_points=True):
            point.time += duration * idx

        result = Track(gpx=gpx)
        result.title = 'Random GPX # {}'.format(idx)
        result.description = 'Description to {}'.format(gpx.name)
        if category:
            result.category = category
        elif count == len(Track.legal_categories):
            result.category = Track.legal_categories[idx]
        else:
            result.category = random.choice(Track.legal_categories)
        result.public = public
        return result

    @staticmethod
    def _random_datetime():
        """random datetime between now() - 10 days and now().

        Returns:
            A random datetime

        """
        end = datetime.datetime.now().replace(microsecond=0)
        start = end - datetime.timedelta(days=10)
        delta = end - start
        int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
        random_second = random.randrange(int_delta)
        return start + datetime.timedelta(seconds=random_second)

    @staticmethod
    def _random_keywords(count=100):
        """A set of random keywords, but always the same.

        We do not want to generate too many tag ids for MMT.

        Returns:
            A set of random keywords

        """
        state = random.getstate()
        try:
            random.seed(1)
            basis = 'abcdefghijklmnopqrstuvwxyz'
            basis += basis.upper()
            basis += '/-_+.% $"|\\'
            result = set()
            while len(result) < count:
                candidate = ''.join(random.choice(basis) for x in range(4))
                if candidate[0] not in ' -' and candidate[-1] not in ' ':
                    result.add(candidate)
            return result
        finally:
            random.setstate(state)

    @classmethod
    def _random_points(cls, count=100):
        """Get some random points.

        Returns:
            A list with count points

        """
        result = list()
        start_time = cls._random_datetime()
        for _ in range(count):
            point = GPXTrackPoint(
                latitude=random.uniform(0.0, 90.0),
                longitude=random.uniform(0.0, 180.0), elevation=_,
                time=start_time + datetime.timedelta(seconds=10 * _))
            result.append(point)
        return result

    def assertSameTracks(self, backend1, backend2, msg=None, with_category=True, with_last_time=None):  # noqa pylint: disable=invalid-name
        """both backends must hold identical tracks."""
        self.maxDiff = None  # pylint: disable=invalid-name
        if with_last_time is None:
            with_last_time = not (isinstance(backend1, GPSIES) or isinstance(backend2, GPSIES))
        if backend1 != backend2:
            keys1 = sorted(x.key(with_category, with_last_time) for x in backend1)
            keys2 = sorted(x.key(with_category, with_last_time) for x in backend2)
            self.assertEqual(keys1, keys2, msg)

    def assertEqualTracks(self, track1, track2, msg=None, xml: bool = False, with_category: bool = True):  # noqa pylint: disable=invalid-name
        """both tracks must be identical. We test more than necessary for better test coverage.

        Args:

            xml: if True, also compare to_xml()"""
        self.maxDiff = None

        # GPSIES: when uploading tracks. GPSIES sometimes assigns new times to all points,
        # starting at 2010-01-01 00:00. Until I find the reason, ignore point times for comparison.
        with_last_time = not (isinstance(track1.backend, GPSIES) or isinstance(track2.backend, GPSIES))

        self.assertEqual(track1.key(with_category, with_last_time), track2.key(with_category, with_last_time), msg)
        self.assertTrue(track1.points_equal(track2), msg)
        if xml:
            self.assertEqual(track1.gpx.to_xml(), track2.gpx.to_xml(), msg)

    def assertNotEqualTracks(self, track1, track2, msg=None, with_category: bool = True):  # noqa pylint: disable=invalid-name
        """both tracks must be different. We test more than necessary for better test coverage."""
        self.assertNotEqual(track1.key(with_category), track2.key(with_category), msg)
        self.assertFalse(track1.points_equal(track2), msg)
        self.assertNotEqual(track1.gpx.to_xml(), track2.gpx.to_xml(), msg)

    def assertTrackFileContains(self, track, string, msg=None):  # noqa pylint: disable=invalid-name
        """Assert that string is in the physical file. Works only for Directory backend."""
        with open(track.backend.gpx_path(track.id_in_backend), encoding='utf8') as trackfile:
            data = trackfile.read()
        self.assertIn(string, data, msg)

    def setup_backend(  # pylint: disable=too-many-arguments
            self, cls_, username: str = None, url: str = None, count: int = 0,
            cleanup: bool = True, clear_first: bool = True, category: str = None,
            public: bool = False):
        """set up an instance of a backend with count tracks.

        If count == len(:attr:`Track.legal_categories <gpxity.track.Track.legal_categories>`),
        the list of tracks will always be identical. For an example
        see :meth:`TestBackends.test_all_category <gpxity.backends.test.test_backends.TestBackends.test_all_category>`.

        Args:
            cls_ (Backend): the class of the backend to be created
            username: use this to for a specific accout name. Default is 'gpxitytest'.
                Special case WPTrackserver: pass the IP address of the mysql test server
            url: for the backend
            count: how many random tracks should be inserted?
            cleanup: If True, remove all tracks when done. Passed to the backend.
            clear_first: if True, first remove all existing tracks
            public: should the tracks be public or private?

        Returns:
            the prepared Backend

        """

        if username is None:
            username = 'gpxitytest'

        if cls_ is WPTrackserver:
            self.create_temp_mysqld()
            auth = {
                'Mysql': 'root@gpxitytest_db',
                'Password': self.test_passwd,
                'Url': self.mysql_ip_address,
                'Username': username}
            url = self.mysql_ip_address
        elif cls_ is Mailer:
            auth = {
                'Username': username,
                'interval': 2,
                'port': 8025,
                'url': pwd.getpwuid(os.geteuid()).pw_name}
        else:
            auth = username
        result = cls_(url, auth=auth, cleanup=cleanup)
        if clear_first and'scan' in cls_.supported and 'write' in cls_.supported:
            result.remove_all()
        if count:
            # if count == 0, skip this. Needed for write-only backends like Mailer.
            while count > len(result):
                track = self.create_test_track(count, len(result), category=category, public=public)
                result.add(track)
            self.assertGreaterEqual(len(result), count)
            if clear_first:
                self.assertEqual(len(result), count)
        return result

    @staticmethod
    @contextmanager
    def lifetrackserver(directory):
        """Start and ends a server for lifetrack testing."""
        exec_name = 'bin/gpxity_server'
        logfile = os.path.join(directory, 'gpxity_server.log')
        if not os.path.exists(exec_name):
            exec_name = 'gpxity_server'
        cmdline = '{} --loglevel debug --servername localhost --port 12398 {}'.format(
            exec_name, directory)
        user_filename = os.path.join(directory, '.users')
        if not os.path.exists(user_filename):
            with open(user_filename, 'w') as user_file:
                user_file.write('gpxitytest:gpxitytestpw\n')
        if not Mailer.is_disabled():
            cmdline += ' --smtp-port 8025'
        process = Popen(cmdline.split(), stdout=open(logfile, 'a'), stderr=open(logfile, 'a'))
        try:
            time.sleep(1)  # give the server time to start
            yield
        finally:
            if os.path.exists(user_filename):
                os.remove(user_filename)
            if os.path.exists(logfile):
                for _ in open(logfile):
                    if 'INFO' not in _ and 'HTTP/1.1' not in _:
                        logging.debug('SRV: %s', _.rstrip())
                os.remove(logfile)
            elif os.path.exists(directory):
                logging.debug('SRV: Directory exists but not gpxity_server.log')
            else:
                logging.debug('SRV: Directory %s does not exist', directory)
            Directory(directory).remove_all()
            process.kill()

    def start_mailserver(self):
        """Start an smptd server for mail testing."""
        self.mailserver_process = Popen(
            'aiosmtpd -u -n -d -l 127.0.0.1:8025'.split(),
            stdout=open('{}/smtpd_stdout'.format(Directory.prefix), 'w'),
            stderr=open('{}/smtpd_stderr'.format(Directory.prefix), 'w'))
        time.sleep(1)  # give the server time to start

    def stop_mailserver(self):
        """Stop the smtp server for mail testing."""
        self.mailserver_process.kill()
        for _ in ('out', 'err'):
            filename = '{}/smtpd_std{}'.format(Directory.prefix, _)
            if not os.path.exists(filename):
                logging.debug('MAIL: %s not found', filename)
                continue
            if _ == 'err':
                for fileline in open(filename):
                    if not fileline.startswith('INFO:'):
                        logging.debug('MAIL:%s: %s', _, fileline.rstrip())
            os.remove(filename)

    @contextmanager
    def temp_backend(self, cls_, url=None, count=0,  # pylint: disable=too-many-arguments
                     cleanup=True, clear_first=True, category=None,
                     public: bool = False, username=None):
        """Just like setup_backend but usable as a context manager. which will call destroy() when done."""
        tmp_backend = self.setup_backend(cls_, username, url, count, cleanup, clear_first, category, public)
        try:
            yield tmp_backend
        finally:
            tmp_backend.destroy()

    @classmethod
    def create_db_for_wptrackserver(cls):
        """Create the mysql database for the WPTrackserver tests."""
        while True:
            try:
                server = MySQLdb.connect(
                    host=cls.mysql_ip_address, user='root', passwd=cls.test_passwd, connect_timeout=2,
                    autocommit=True, charset='utf8',
                    sql_mode='ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION')
                break
            except _mysql_exceptions.OperationalError:
                # wait until the docker instance is ready
                time.sleep(1)
        logging.debug('%s: connected to %s', datetime.datetime.now(), cls.mysql_ip_address)
        cursor = server.cursor()
        cursor.execute('create database gpxitytest_db')
        cursor.execute('use gpxitytest_db')
        cursor.execute("""
            CREATE TABLE wp_ts_locations (
            id int(11) NOT NULL AUTO_INCREMENT,
            trip_id int(11) NOT NULL,
            latitude double NOT NULL,
            longitude double NOT NULL,
            altitude double NOT NULL,
            speed double NOT NULL default 0.0,
            heading double NOT NULL default 0.0,
            updated timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created timestamp NOT NULL default '0000-00-00 00:00:00',
            occurred timestamp not null default '0000-00-00 00:00:00',
            comment varchar(255) NOT NULL,
            hidden tinyint(1) NOT NULL default 0,
            PRIMARY KEY (id),
            KEY occurred (occurred),
            KEY trip_id (trip_id)
            ) ENGINE=InnoDB
        """)
        cursor.execute("""
            CREATE TABLE wp_ts_tracks (
            id int(11) NOT NULL AUTO_INCREMENT,
            user_id int(11) NOT NULL,
            name varchar({title_length}) NOT NULL,
            updated timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created timestamp NOT NULL default '0000-00-00 00:00:00',
            source varchar(255) NOT NULL default '',
            comment varchar({descr_length}) NOT NULL default '',
            distance int(11) NOT NULL,
            PRIMARY KEY (id),
            KEY user_id (user_id)
         )
        """.format(
            descr_length=WPTrackserver._max_length['description'],
            title_length=WPTrackserver._max_length['title']))
        cursor.execute("""
            CREATE TABLE wp_users (
            ID bigint(20) unsigned NOT NULL AUTO_INCREMENT,
            user_login varchar(60) NOT NULL DEFAULT '',
            user_pass varchar(255) NOT NULL DEFAULT '',
            user_nicename varchar(50) NOT NULL DEFAULT '',
            user_email varchar(100) NOT NULL DEFAULT '',
            user_url varchar(100) NOT NULL DEFAULT '',
            user_registered datetime NOT NULL DEFAULT '1970-01-01',
            user_activation_key varchar(255) NOT NULL DEFAULT '',
            user_status int(11) NOT NULL DEFAULT '0',
            display_name varchar(250) NOT NULL DEFAULT '',
            PRIMARY KEY (ID),
            KEY user_login_key (user_login),
            KEY user_nicename (user_nicename),
            KEY user_email (user_email)
         )
        """)
        cursor.execute("""
            insert into wp_users (user_login) values(%s)""", ['gpxitytest'])
        cursor.execute("select id,user_login from wp_users")
        logging.debug(cursor.fetchall())
        server.commit()
        server.close()

    @classmethod
    def find_mysql_docker(cls) ->bool:
        """Find an already running docker.

        Returns:
            the IP address

        """
        if cls.mysql_ip_address is not None:
            return True
        cls.mysql_ip_address = Popen([
            'docker', 'inspect', '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',
            cls.mysql_docker_name], stdout=PIPE).communicate()[0].decode().strip()
        if cls.mysql_ip_address == '':
            cls.mysql_ip_address = None
        return bool(cls.mysql_ip_address)

    @classmethod
    def create_temp_mysqld(cls):
        """Create a temporary mysql server and initialize it with test data for WPTrackserver."""
        if cls.find_mysql_docker():
            return
        cmd = [
            'docker', 'run', '--name', cls.mysql_docker_name, '--detach',
            '--env', 'MYSQL_ROOT_PASSWORD={}'.format(cls.test_passwd), 'mysql']
        with Popen(cmd, stdout=PIPE, stderr=PIPE) as _:
            std_err = _.stderr.read().strip().decode('utf8')
            if std_err:
                logging.error(std_err)
                if 'on network bridge: failed to add the host' in std_err:
                    logging.error('did you reboot after kernel upgrade?')
                raise Exception('Cannot run docker: {}'.format(std_err))
        if not cls.find_mysql_docker():
            raise Exception('Unknown problem while creating mysql docker')
        cls.create_db_for_wptrackserver()
