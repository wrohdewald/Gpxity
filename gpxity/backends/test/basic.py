# -*- coding: utf-8 -*-


# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""Tests for gpxity.backends."""

import unittest
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
except ImportError:
    pass


import gpxpy
from gpxpy.gpx import GPXTrackPoint
from gpxpy.geo import LocationDelta

from ... import GpxFile, Backend, Account, MemoryAccount, DirectoryAccount
from .. import Memory, Mailer, WPTrackserver, Directory, GPSIES, Openrunner, MMT
from ...util import remove_directory
from ...gpx import Gpx

# pylint: disable=attribute-defined-outside-init,protected-access

__all__ = ['BasicTest']


def disabled(*args) ->tuple():
    """True if any of the backends is disabled.

    Returns:
        True or False and reason

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
        """define test specific DirectoryAccount.prefix."""
        self.maxDiff = None  # pylint: disable=invalid-name
        Account.path = os.path.join(os.path.dirname(__file__), 'test_accounts')
        self.logger = logging.getLogger()
        self.logger.level = logging.DEBUG
        self.logger.debug('Using accounts out of %s', Account.path)
        self.start_time = datetime.datetime.now()
        self.unicode_string1 = 'unicode szlig: ß'
        self.unicode_string2 = 'something japanese:の諸問題'
        self.org_dirprefix = DirectoryAccount.prefix
        DirectoryAccount.prefix = 'gpxity.' + '.'.join(self.id().split('.')[-2:]) + '_'  # noqa
        path = tempfile.mkdtemp(prefix=DirectoryAccount.prefix)
        Backend._session.clear()

        DirectoryAccount.prefix = path

        if not Mailer.is_disabled():
            self.start_mailserver()

    def tearDown(self):  # noqa
        """Check if there are still /tmp/gpxitytest.* directories."""
        if not Mailer.is_disabled():
            self.stop_mailserver()
        remove_directory(DirectoryAccount.prefix)
        DirectoryAccount.prefix = self.org_dirprefix
        timedelta = datetime.datetime.now() - self.start_time
        self.logger.debug('%s seconds ', timedelta.seconds)
        logging.shutdown()

    @contextmanager
    def tst_backend(self, backend_cls, subtest=None):  # noqa pylint: disable=arguments-differ
        """With pytest, subTest does not do much. At least print the name."""
        _ = '---------- subTest {}: {} '.format(self.id().split('.')[-1], backend_cls.__name__)
        if subtest:
            _ += subtest + ' '
        _ += '-' * (80 - len(_))
        self.logger.debug(_)
        yield super(BasicTest, self).subTest(' ' + backend_cls.__name__)

    @staticmethod
    def _get_track_from_test_file(name: str, backend_cls=None):
        """get data from a predefined gpx file with a random category supported by the backend.

        name is without .gpx

        Returns:=
            A GPX object

        """
        gpx_test_file = os.path.join(os.path.dirname(__file__), '{}.gpx'.format(name))
        if not os.path.exists(gpx_test_file):
            raise Exception('MMTTests needs a GPX file named {}.gpx for testing in {}'.format(
                name, os.getcwd()))
        filename = '{}.gpx'.format(name)
        data = io.StringIO(get_data(__package__, filename).decode('utf-8'))
        result = GpxFile(gpx=Gpx.parse(data))
        if backend_cls:
            result.category = backend_cls.decode_category(random.choice(backend_cls.supported_categories))
        return result

    @classmethod
    def create_test_track(
            cls, backend_class=None, count: int = 1, idx: int = 0, category: str = None, public: bool = False,
            start_time=None, end_time=None):
        """create a :class:`~gpxity.gpxfile.GpxFile`.

        It starts off with **test.gpx** and appends a
        last gpxfile point, it also changes the time stamp of the last point.
        This is done using **count** and **idx**: The last point is set such that
        looking at the gpxfiles, they all go in a different direction clockwise, with an angle
        in degrees of :literal:`360 * idx / count`.

        Args:
            backend_class: If given, use it as source for a random category
            count: See above. Using 1 as default if not given.
            idx: See above. Using 0 as default if not given.
            category: The wanted value for the gpxfile.
                Default: if count == len(:attr:`GpxFile.categories <gpxity.gpxfile.GpxFile.categories>`),
                the default value will be backend_class.supported_categories[idx].
                Otherwise a random value from backend_class.supported_categories will be applied.
            public: should the gpxfiles be public or private?
            start_time: If given, assign it to the first point and adjust all following times
            end_time: explicit time for the last point. If None: See above.

        Returns:
            (~gpxity.gpxfile.GpxFile): A new gpxfile not bound to a backend

        """
        # pylint: disable=too-many-locals
        result = cls._get_track_from_test_file('test')
        if start_time is not None:
            if not start_time.tzinfo:
                start_time = start_time.replace(tzinfo=datetime.timezone.utc)
            result.adjust_time(start_time - result.first_time)
        last_point = result.last_point()
        if end_time is None:
            end_time = last_point.time + datetime.timedelta(hours=10, seconds=idx)
        if not end_time.tzinfo:
            end_time = end_time.replace(tzinfo=datetime.timezone.utc)
        new_point = GPXTrackPoint(
            latitude=last_point.latitude, longitude=last_point.longitude + 0.001, time=end_time)
        _ = gpxpy.geo.LocationDelta(distance=1000, angle=360 * idx / count)
        new_point.move(_)
        result.add_points([new_point])

        # now set all times such that they are in order with this gpxfile and do not overlap
        # with other test gpxfiles
        _ = result.first_time
        duration = new_point.time - _ + datetime.timedelta(seconds=10)
        for point in result.gpx.walk(only_points=True):
            point.time += duration * idx

        result.title = 'Random GPX # {}'.format(idx)
        result.description = 'Description to {}'.format(result.title)
        if backend_class is None:
            cat_source = GpxFile.categories
        else:
            cat_source = backend_class.supported_categories
            cat_source = [backend_class.decode_category(x) for x in cat_source]
        if category:
            result.category = category
        elif count == len(GpxFile.categories):
            result.category = cat_source[idx]
        else:
            result.category = random.choice(cat_source)
        result.public = public
        return result

    @staticmethod
    def _random_datetime():
        """random datetime between now() - 10 days and now().

        Returns:
            A random datetime

        """
        end = datetime.datetime.now().replace(microsecond=0, tzinfo=datetime.timezone.utc)
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
    def _random_points(cls, count=100, root=None):
        """Get some random points.

        Distance between two points will never exceed 200m.

        Returns:
            A list with count points

        """

        start_time = cls._random_datetime()
        if root is None:
            root = GPXTrackPoint(
                latitude=random.uniform(-90.0, 90.0),
                longitude=random.uniform(-180.0, 180.0),
                elevation=0,
                time=start_time)
        result = [root]

        angle = 50
        for _ in range(1, count):
            angle = angle + random.uniform(-20, 20)
            delta = LocationDelta(distance=random.randrange(200), angle=angle)
            point = GPXTrackPoint(latitude=result[-1].latitude, longitude=result[-1].longitude)
            point.move(delta)
            point.elevation = _
            point.time = start_time + datetime.timedelta(seconds=10 * _)
            result.append(point)
        return result

    def assertBackendLength(self, backend, length): # noqa pylint: disable=invalid-name
        """Check length of backend."""
        if len(backend) != length:
            message = ','.join(str(x) for x in backend)
            self.assertEqual(len(backend), length, '{} should have {} gpxfiles: {}'.format(backend, length, message))

    def assertHasKeywords(self, gpxfile, expected):  # noqa pylint: disable=invalid-name
        """MMT shows keywords on the website lowercase but internally it capitalizes them."""
        if isinstance(gpxfile.backend, MMT):
            original = expected
            expected = []
            for _ in original:
                expected.append(' '.join(x.capitalize() for x in _.split(' ')))
        self.assertEqual(gpxfile.keywords, sorted(expected))

    def assertSameTracks(self, backend1, backend2, msg=None, with_category=True, with_last_time=None):  # noqa pylint: disable=invalid-name
        """both backends must hold identical gpxfiles."""
        self.maxDiff = None  # pylint: disable=invalid-name
        if with_last_time is None:
            with_last_time = not (
                isinstance(backend1, (Openrunner, GPSIES)) or isinstance(backend2, (Openrunner, GPSIES)))
        if backend1 != backend2:
            precision = min(backend1.point_precision, backend2.point_precision)
            keys1 = sorted(x.key(with_category, with_last_time, precision=precision) for x in backend1)
            keys2 = sorted(x.key(with_category, with_last_time, precision=precision) for x in backend2)
            self.assertEqual(keys1, keys2, msg)

    def assertEqualTracks(self, gpxfile1, gpxfile2, msg=None, xml: bool = False, with_category: bool = True):  # noqa pylint: disable=invalid-name
        """both gpxfiles must be identical. We test more than necessary for better test coverage.

        Args:

            xml: if True, also compare xml()"""
        self.maxDiff = None

        # GPSIES: when uploading gpxfiles. GPSIES sometimes assigns new times to all points,
        # starting at 2010-01-01 00:00. Until I find the reason, ignore point times for comparison.
        # Openrunner always does.
        # MMT now seems to convert times between utc and local time. UP- and downloading
        # the same gpxfile changes the point times.
        no_time_backend = (GPSIES, Openrunner, MMT)
        with_last_time = not (
            isinstance(gpxfile1.backend, no_time_backend) or isinstance(gpxfile2.backend, no_time_backend))
        precision = Backend.point_precision
        if gpxfile1.backend and gpxfile1.backend.point_precision < precision:
            precision = gpxfile1.backend.precision
        if gpxfile2.backend and gpxfile2.backend.point_precision < precision:
            precision = gpxfile2.backend.precision
        self.assertEqual(
            gpxfile1.key(with_category, with_last_time, precision=precision),
            gpxfile2.key(with_category, with_last_time, precision=precision), msg)
        self.assertTrue(gpxfile1.points_equal(gpxfile2), msg)
        if xml:
            self.assertEqual(gpxfile1.gpx.xml(), gpxfile2.gpx.xml(), msg)

    def assertNotEqualTracks(self, gpxfile1, gpxfile2, msg=None, with_category: bool = True):  # noqa pylint: disable=invalid-name
        """both gpxfiles must be different. We test more than necessary for better test coverage."""
        self.assertNotEqual(gpxfile1.key(with_category), gpxfile2.key(with_category), msg)
        self.assertFalse(gpxfile1.points_equal(gpxfile2), msg)
        self.assertNotEqual(gpxfile1.gpx.xml(), gpxfile2.gpx.xml(), msg)

    def assertTrackFileContains(self, gpxfile, string, msg=None):  # noqa pylint: disable=invalid-name
        """Assert that string is in the physical file. Works only for Directory backend."""
        with open(gpxfile.backend.gpx_path(gpxfile.id_in_backend), encoding='utf8') as trackfile:
            data = trackfile.read()
        self.assertIn(string, data, msg)

    def setup_backend(  # noqa pylint: disable=too-many-arguments
            self, cls_, test_name: str = None, url: str = None, count: int = 0,
            clear_first: bool = None, category: str = None,
            public: bool = None):
        """set up an instance of a backend with count gpxfiles.

        If count == len(:attr:`GpxFile.categories <gpxity.gpxfile.GpxFile.categories>`),
        the list of gpxfiles will always be identical. For an example
        see :meth:`TestBackends.test_all_category <gpxity.backends.test.test_backends.TestBackends.test_all_category>`.

        Args:
            cls_ (Backend): the class of the backend to be created
            username: use this to for a specific accout name. Default is 'gpxitytest'.
                Special case WPTrackserver: pass the IP address of the mysql test server
            url: for the backend, only for Directory
            count: how many random gpxfiles should be inserted?
            clear_first: if True, first remove all existing gpxfiles. None: do if the backend supports it.
            category: The wanted category, one out of GpxFile.categories. But this is a problem because we do the same
                call for all backend classes and they support different categories. So: If category is int, this is an
                index into Backend.supported_categories which will be decoded into GpxFile.categories

            public: should the gpxfiles be public or private? Default is False.
                Exception: MMT with subscription free has default True

        Returns:
            the prepared Backend

        """
        # pylint: disable=too-many-branches
        if clear_first is None:
            clear_first = 'remove' in cls_.supported
        if isinstance(category, int):
            category = cls_.decode_category(cls_.supported_categories[category])

        if cls_ is Memory:
            account = MemoryAccount()
        elif cls_ is Directory:
            account = DirectoryAccount(url)
        else:
            assert url is None
            kwargs = dict()
            if cls_ is WPTrackserver:
                if not self.find_mysql_docker():
                    self.create_temp_mysqld()  # only once for all tests
                self.create_db_for_wptrackserver()  # recreate for each test
                kwargs['Url'] = self.mysql_ip_address
            if test_name:
                account_name = '{}_{}_unittest'.format(cls_.__name__, test_name)
            else:
                account_name = '{}_unittest'.format(cls_.__name__)
            account = Account(account_name, **kwargs)
        result = cls_(account)
        if clear_first and'scan' in cls_.supported and 'write' in cls_.supported:
            result.remove_all()
        if public is None:
            public = cls_ is MMT and result.subscription == 'free'

        if count:
            # if count == 0, skip this. Needed for write-only backends like Mailer.
            while count > len(result):
                gpxfile = self.create_test_track(cls_, count, len(result), category=category, public=public)
                result.add(gpxfile)
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
            Directory(DirectoryAccount(directory)).remove_all()
            process.kill()

    def start_mailserver(self):
        """Start an smptd server for mail testing."""
        self.mailserver_process = Popen(
            'aiosmtpd -u -n -d -l 127.0.0.1:8025'.split(),
            stdout=open('{}/smtpd_stdout'.format(DirectoryAccount.prefix), 'w'),
            stderr=open('{}/smtpd_stderr'.format(DirectoryAccount.prefix), 'w'))
        time.sleep(1)  # give the server time to start

    def stop_mailserver(self):
        """Stop the smtp server for mail testing."""
        self.mailserver_process.kill()
        for _ in ('out', 'err'):
            filename = '{}/smtpd_std{}'.format(DirectoryAccount.prefix, _)
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
                     cleanup=True, clear_first=None, category=None,
                     public: bool = None, test_name=None):
        """Just like setup_backend but usable as a context manager. which will call detach() when done."""
        tmp_backend = self.setup_backend(cls_, test_name, url, count, clear_first, category, public)
        try:
            yield tmp_backend
        finally:
            if cleanup and 'remove' in cls_.supported:
                tmp_backend.remove_all()
            tmp_backend.detach()

    @contextmanager
    def temp_directory(self, url=None, count=0,  # pylint: disable=too-many-arguments
                       cleanup=True, clear_first=None, category=None,
                       public: bool = None, test_name=None):
        """Temp directory backend."""
        tmp_backend = self.setup_backend(Directory, test_name, url, count, clear_first, category, public)
        try:
            yield tmp_backend
        finally:
            if cleanup:
                tmp_backend.remove_all()
            tmp_backend.detach()

    @classmethod
    def create_db_for_wptrackserver(cls):
        """Create the mysql database for the WPTrackserver tests."""
        count = 0
        while True:
            try:
                server = MySQLdb.connect(
                    host=cls.mysql_ip_address, user='root', passwd=cls.test_passwd, connect_timeout=2,
                    autocommit=True, charset='utf8',
                    sql_mode='ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION')
                break
            except MySQLdb._exceptions.OperationalError:
                # wait until the docker instance is ready
                count += 1
                if count > 50:
                    raise
                time.sleep(1)
        cursor = server.cursor()
        cursor._defer_warnings = True
        cursor.execute('drop database if exists gpxitytest_db')
        cursor._defer_warnings = False
        cursor.execute('create database gpxitytest_db')
        cursor.execute('use gpxitytest_db')
        cursor.execute("""
            CREATE TABLE wp_ts_locations (
            id int NOT NULL AUTO_INCREMENT,
            trip_id int NOT NULL,
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
            id int NOT NULL AUTO_INCREMENT,
            user_id int NOT NULL,
            name varchar({title_length}) NOT NULL,
            updated timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created timestamp NOT NULL default '0000-00-00 00:00:00',
            source varchar(255) NOT NULL default '',
            comment varchar({descr_length}) NOT NULL default '',
            distance int NOT NULL,
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
            user_status int NOT NULL DEFAULT '0',
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
