#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""implement a server using the mapmytracks protocol."""

# PYTHON_ARGCOMPLETE_OK
# for command line argument completion, put this into your .bashrc:
# eval "$(register-python-argcomplete gpxdo)"
# or see https://argcomplete.readthedocs.io/en/latest/


import os
import sys
import base64
import datetime
import argparse
import logging
import logging.handlers
import traceback

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

from gpxpy import gpx as mod_gpx

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXTrackPoint = mod_gpx.GPXTrackPoint
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException

# This uses not the installed copy but the development files
_ = os.path.dirname(sys.path[0] or sys.path[1])
if os.path.exists(os.path.join(_, 'gpxity', '__init__.py')):
    sys.path.insert(0, _)
# pylint: disable=wrong-import-position

from gpxity import Track, ServerDirectory, Lifetrack, Mailer  # pylint: disable=no-name-in-module

try:
    import argcomplete
    # pylint: disable=unused-import
    from argcomplete import ChoicesCompleter  # noqa
except ImportError:
    pass


class MMTHandler(BaseHTTPRequestHandler):

    """handles all HTTP requests."""

    users = None
    login_user = None
    uniqueid = 123

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Override: Redirect into logger."""
        self.server.logger.info(format % args)

    def log_error(self, format, *args):  # pylint: disable=redefined-builtin
        """Override: redirect into logger."""
        self.server.logger.error(format % args)

    def check_basic_auth_pw(self):
        """basic http authentication."""
        if self.users is None:
            self.load_users()
        for pair in self.users.items():
            expect = b'Basic ' + base64.b64encode(':'.join(pair).encode('utf-8'))
            expect = expect.decode('utf-8')
            if expect == self.headers['Authorization']:
                return True
        return False

    def load_users(self):
        """load legal user auth from serverdirectory/.users."""
        self.users = dict()
        with open(os.path.join(self.server.server_directory.url, '.users')) as user_file:
            for line in user_file:
                user, password = line.strip().split(':')
                self.users[user] = password

    def return_error(self, code, reason, exc=None):
        """Answer the clint with an xml formatted error message."""
        self.server.logger.error('return_error: {} {} {}'.format(
            code, reason, exc))
        self.send_response(code)
        xml = '<type>error</type><reason>{}</reason>'.format(reason)
        self.send_header('Content-Type', 'text/xml; charset=UTF-8')
        xml = '<?xml version="1.0" encoding="UTF-8"?><message>{}</message>'.format(xml)
        self.send_header('Content-Length', len(xml))
        self.end_headers()
        self.wfile.write(bytes(xml.encode('utf-8')))
        if exc is None:
            exc = ValueError
        raise exc(reason)

    def parseRequest(self):  # pylint: disable=invalid-name
        """Get interesting things."""
        if self.server.gpxdo_options.debug:
            self.server.logger.debug('got headers:')
            for key, value in self.headers.items():
                self.server.logger.debug('  {}:{}'.format(key, value))
        if 'Content-Length' in self.headers:
            data_length = int(self.headers['Content-Length'])
            data = self.rfile.read(data_length).decode('utf-8')
            parsed = parse_qs(data)
            if self.server.gpxdo_options.debug:
                self.server.logger.debug('got {}'.format(parsed))
            for key, value in parsed.items():
                if len(value) != 1:
                    self.return_error(400, '{} must appear only once'.format(key))
                parsed[key] = parsed[key][0]
            return parsed
        return None

    def homepage(self):
        """Return what the client needs."""
        self.load_users()
        names = list(sorted(self.users.keys()))
        return """
            <input type="hidden" value="{}" name="mid" id="mid" />
            """.format(names.index(self.login_user))

    @staticmethod
    def answer_with_categories():
        """Return all categories."""
        all_cat = Track.legal_categories
        return ''.join('<li><input name="add-activity-x">&nbsp;{}</li>'.format(x) for x in all_cat)

    def cookies(self):
        """send cookies."""
        if hasattr(self, 'uniqueid'):
            self.send_header('Set-Cookie', 'exp_uniqueid={}'.format(self.uniqueid))

    def do_GET(self):  # pylint: disable=invalid-name
        """Override standard."""
        # TODO: empfangene cookies verwenden
        if self.server.gpxdo_options.debug:
            self.server.logger.debug('GET {} {} {}'.format(self.client_address[0], self.server.server_port, self.path))
        self.parseRequest()  # side effect: may print debug info
        self.send_response(200, 'OK')
        self.send_header('WWW-Authenticate', 'Basic realm="MMTracks API"')
        if self.path == '/':
            xml = self.homepage()
        elif self.path.endswith('//explore/wall'):
            # the client wants to find out legal categories
            xml = self.answer_with_categories()
        elif self.path.startswith('//assets/php/gpx.php'):
            parameters = self.path.split('?')[1]
            request = parse_qs(parameters)
            wanted_id = request['tid'][0]
            xml = self.server.server_directory[wanted_id].to_xml()
        else:
            xml = ''
        self.send_header('Content-Type', 'text/xml; charset=UTF-8')
        if self.server.gpxdo_options.debug:
            self.server.logger.debug('returning {}'.format(xml))
        self.send_header('Content-Length', len(xml))
        self.cookies()
        self.end_headers()
        self.wfile.write(bytes(xml.encode('utf-8')))

    def do_POST(self):  # pylint: disable=invalid-name
        """override standard."""
        if self.server.gpxdo_options.debug:
            self.server.logger.debug(
                'POST {} {} {}'.format(self.client_address[0], self.server.server_port, self.path))
        parsed = self.parseRequest()
        if self.path.endswith('/api/') or self.path == '/' or self.path == '//':
            try:
                request = parsed['request']
            except KeyError:
                self.return_error(401, 'No request given in {}'.format(parsed))
            try:
                method = getattr(self, 'xml_{}'.format(request))
            except AttributeError:
                self.return_error(401, 'Unknown request {}'.format(parsed['request']))
            try:
                xml = method(parsed)
            except Exception:
                self.server.logger.error(traceback.format_exc())
                raise
            if xml is None:
                xml = ''
            xml = '<?xml version="1.0" encoding="UTF-8"?><message>{}</message>'.format(xml)
        else:
            xml = ''
        self.send_response(200, 'OK')
        self.send_header('WWW-Authenticate', 'Basic realm="MMTracks API"')
        self.send_header('Content-Type', 'text/xml; charset=UTF-8')
        if self.server.gpxdo_options.debug:
            self.server.logger.debug('returning {}'.format(xml))
        self.send_header('Content-Length', len(xml))
        self.cookies()
        self.end_headers()
        self.wfile.write(bytes(xml.encode('utf-8')))

    @staticmethod
    def xml_get_time(_):
        """Get server time as defined by the mapmytracks API."""
        return '<type>time</type><server_time>{}</server_time>'.format(
            int(datetime.datetime.now().timestamp()))

    def xml_get_tracks(self, parsed):
        """List all tracks as defined by the mapmytracks API."""
        a_list = list()
        if parsed['offset'] == '0':
            for idx, _ in enumerate(self.server.server_directory):
                a_list.append(
                    '<track{}><id>{}</id>'
                    '<title><![CDATA[ {} ]]></title>'
                    '<activity_type>{}</activity_type>'
                    '<date>{}</date>'
                    '</track{}>'.format(
                        idx + 1, _.id_in_backend, _.title, _.category,
                        int(_.time.timestamp()), idx + 1))
        return '<tracks>{}</tracks>'.format(''.join(a_list))

    def __points(self, raw):
        """convert raw data back into list(GPXTrackPoint)."""
        values = raw.split()
        if len(values) % 4:
            self.return_error(401, 'Point elements not a multiple of 4', TypeError)
        result = list()
        for idx in range(0, len(values), 4):
            point = GPXTrackPoint(
                latitude=float(values[idx]),
                longitude=float(values[idx+1]),
                elevation=float(values[idx+2]),
                time=datetime.datetime.utcfromtimestamp(float(values[idx+3])))
            result.append(point)
        return result

    def xml_upload_activity(self, parsed):
        """Upload an activity as defined by the mapmytracks API."""
        track = Track()
        track.parse(parsed['gpx_file'])
        self.server.server_directory.add(track)
        self.server.mailer.add(track)
        return '<type>success</type><id>{}</id>'.format(track.id_in_backend)

    def xml_start_activity(self, parsed):
        """start Lifetrack server."""
        if self.server.life:
            raise Exception('Currently I can handle only one lifetracker')
        self.server.life = Lifetrack([self.server.server_directory, self.server.mailer])
        if 'title' in parsed:
            self.server.set_title(parsed['title'])
        if 'privicity' in parsed:
            parsed['privacy'] = parsed['privicity']
        self.server.life.set_public(parsed['privacy'] == 'public')
        # the MMT API example uses cycling instead of Cycling,
        # and Oruxmaps does so too.
        self.server.life.set_category(parsed['activity'].capitalize())
        self.server.id_in_server = self.server.life.update(self.__points(parsed['points']))
        return '<type>activity_started</type><activity_id>{}</activity_id>'.format(
            self.server.id_in_server)

    def xml_update_activity(self, parsed):
        """Get new points."""
        if self.server.life is None:
            self.return_error(401, 'No lifetracker active')
            return ''
        if parsed['activity_id'] != self.server.id_in_server:
            self.return_error(401, 'wrong track id {}, expected {}'.format(
                parsed['activity_id'], self.server.id_in_server))
            return ''
        self.server.life.update(self.__points(parsed['points']))
        return '<type>activity_updated</type>'

    def xml_stop_activity(self, parsed):  # pylint: disable=unused-argument
        """Client says stop."""
        if self.server.life is None:
            self.return_error(401, 'No lifetracker active')
            return''
        self.server.life.end()
        self.server.life = None
        return '<type>activity_stopped</type>'


class LifeServerMMT:  # pylint: disable=too-few-public-methods

    """A simple MMT server for life tracking.

    Currently supports only one logged in connection.

    This is not ready for production usage, several important
    parts are still unimplemented.

    """

    def __init__(self, options, logger):
        httpd = HTTPServer((options.servername, options.port), MMTHandler)
        httpd.gpxdo_options = options
        # define the directory in auth.cfg, using the Url=value
        httpd.server_directory = ServerDirectory(url=options.directory)
        httpd.mailer = Mailer(url=options.mailto)
        httpd.life = None
        httpd.logger = logger
        httpd.serve_forever()


class Main:  # pylint: disable=too-few-public-methods

    """main."""

    def __init__(self):
        logger = logging.getLogger('mmtserver')
        logger.setLevel(logging.DEBUG)
        logfile = logging.FileHandler('mmtserver.log')
        logfile.setLevel(logging.DEBUG)
        logger.addHandler(logfile)
        parser = argparse.ArgumentParser('mmtserver')
        parser.add_argument(
            '--directory', required=True,
            help='Lookup the name of the server track directory in .config/Gpxity/auth.cfg')
        parser.add_argument('--servername', help='the name of this server', required=True)
        parser.add_argument('--port', help='listen on PORT', type=int, required=True)
        parser.add_argument('--mailto', help='mail new tracks to MAILTO')
        parser.add_argument('--verbose', action='store_true', help='verbose output', default=False)
        parser.add_argument('--debug', action='store_true', help='show debug outpus', default=False)
        parser.add_argument('--timeout', help="""
            Timeout: Either one value in seconds or two comma separated values: The first one is the connection timeout,
            the second one is the read timeout. Default is to wait forever.""", type=str, default=None)

        try:
            argcomplete.autocomplete(parser)
        except NameError:
            pass

        options = parser.parse_args()
        LifeServerMMT(options, logger)


Main()
