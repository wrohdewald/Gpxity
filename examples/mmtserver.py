#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

implement a server using the mapmytracks protocol

next: ein weiterer Prozess:

import BaseHTTPServer, SimpleHTTPServer
import ssl

httpd = BaseHTTPServer.HTTPServer(('localhost', 4443), SimpleHTTPServer.SimpleHTTPRequestHandler)
httpd.socket = ssl.wrap_socket (httpd.socket, certfile='path/to/localhost.pem', server_side=True)
httpd.serve_forever()

"""

import os
import sys
import base64
import datetime
from optparse import OptionParser

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

from subprocess import Popen, PIPE

# This uses not the installed copy but the development files
sys.path.insert(0, '..')

from gpxpy import gpx as mod_gpx

GPX = mod_gpx.GPX
GPXTrack = mod_gpx.GPXTrack
GPXTrackSegment = mod_gpx.GPXTrackSegment
GPXTrackPoint = mod_gpx.GPXTrackPoint
GPXXMLSyntaxException = mod_gpx.GPXXMLSyntaxException



# pylint: disable=wrong-import-position

from gpxity import Track
from gpxity import ServerDirectory # pylint: disable=no-name-in-module

class Handler(BaseHTTPRequestHandler):
    """handles all HTTP requests"""
    users = None
    directory = ServerDirectory(auth='mmtserver') # define the directory in auth.cfg, using the Url=value
    tracking_track = None

    def send_mail(self, reason,  track):
        """if a mail address is known, send new GPX there"""
        if OPT.mailto:
            msg = b'GPX is attached'
            subject = 'New GPX: {} {}'.format(reason, track)
            process  = Popen(
                ['mutt', '-s', subject, '-a', track.backend.gpx_path(track),  '--', OPT.mailto],
                stdin=PIPE)
            process.communicate(msg)

    def check_pw(self):
        """basic http authentication"""
        if self.users is None:
            self.load_users()
        for pair in self.users.items():
            expect = b'Basic ' + base64.b64encode(':'.join(pair).encode('utf-8'))
            expect = expect.decode('utf-8')
            if expect == self.headers['Authorization']:
                return True
        return True

    def load_users(self):
        """load legal user auth from serverdirectory/.users"""
        self.users = dict()
        with open(os.path.join(Handler.directory.url, '.users')) as user_file:
            for line in user_file:
                user, password = line.strip().split(':')
                self.users[user] = password

    def return_error(self, code, reason):
        """returns an xml formatted error message"""
        self.send_response(code)
        xml = '<type>error</type><reason>{}</reason>'.format(reason)
        self.send_header('Content-Type', 'text/xml; charset=UTF-8')
        xml = '<?xml version="1.0" encoding="UTF-8"?><message>{}</message>'.format(xml)
        self.send_header('Content-Length', len(xml))
        self.end_headers()
        self.wfile.write(bytes(xml.encode('utf-8')))

    def parseRequest(self): # pylint: disable=invalid-name
        """as the name says. Why do I have to implement this?"""
        if OPT.debug:
            print('got headers:')
            for k,v in self.headers.items():
                print('  ',k,v)
        data_length = int(self.headers['Content-Length'])
        data = self.rfile.read(data_length).decode('utf-8')
        parsed = parse_qs(data)
        if OPT.debug:
            print('got',parsed)
        for key, value in parsed.items():
            if len(value) != 1:
                self.return_error(400, '{} must appear only once'.format(key))
            parsed[key] = parsed[key][0]
        return parsed

    def do_POST(self): # pylint: disable=invalid-name
        """override standard"""
        if not self.check_pw():
            self.return_error(401, 'unauthorised')
            return
        self.send_response(200)
        self.send_header('WWW-Authenticate', 'Basic realm="MMTracks API"')
        self.send_header('Connection', 'close')
        parsed = self.parseRequest()
        try:
            request = parsed['request']
        except KeyError:
            self.return_error(401, 'No request given in {}'.format(parsed))
            return
        try:
            method = getattr(self, 'xml_{}'.format(request))
        except AttributeError:
            self.return_error(401, 'Unknown request {}'.format(parsed['request']))
            return
        xml = method(parsed)
        if xml is None:
            return

        self.send_header('Content-Type', 'text/xml; charset=UTF-8')
        if OPT.debug:
            print('returning',xml)
        xml = '<?xml version="1.0" encoding="UTF-8"?><message>{}</message>'.format(xml)
        self.send_header('Content-Length', len(xml))
        self.end_headers()
        self.wfile.write(bytes(xml.encode('utf-8')))

    @staticmethod
    def xml_get_time(_):
        """as defined by the mapmytracks API"""
        return '<type>time</type><server_time>{}</server_time>'.format(
            int(datetime.datetime.now().timestamp()))

    def xml_get_tracks(self, parsed):
        """as defined by the mapmytracks API"""
        a_list = list()
        if parsed['offset'] == '0':
            for idx, _ in enumerate(Handler.directory):
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
        """convert raw data back into list(GPXTrackPoint)"""
        values = raw.split()
        if len(values) % 4:
            self.return_error(401, 'Point elements not a multiple of 4')
            raise TypeError
        result = list()
        for idx in range(0, len(values), 4):
            point = GPXTrackPoint(
                latitude=float(values[idx]),
                longitude=float(values[idx+1]),
                elevation=float(values[idx+2]),
                time=datetime.datetime.utcfromtimestamp(float(values[idx+3])))
            result.append(point)
        return result

    def __starting_Gpx(self, parsed):
        """builds an initial Gpx object"""
        segment = GPXTrackSegment()
        segment.points = self.__points(parsed['points'])
        track = GPXTrack()
        track.segments.append(segment)
        result =GPX()
        result.tracks.append(track)
        return result

    def xml_upload_track(self, parsed):
        """as defined by the mapmytracks API"""
        track = Track()
        track.parse(parsed['gpx_file'])
        Handler.directory.add(track)
        self.send_mail('upload_track', track)
        return '<type>success</type><id>{}</id>'.format(track.id_in_backend)

    def xml_start_track(self, parsed):
        try:
            Handler.tracking_track = Track(gpx=self.__starting_Gpx(parsed))
        except TypeError:
            return
        Handler.tracking_track.title = parsed['title']
        if 'privicity' in parsed:
            parsed['privacy'] = parsed['privicity']
        Handler.tracking_track.public = parsed['privacy'] == 'public'
        Handler.tracking_track.category = parsed['activity']
        Handler.directory.add(Handler.tracking_track)
        self.send_mail('start_track', Handler.tracking_track)
        return '<type>activity_started</type><activity_id>{}</activity_id>'.format(
            Handler.tracking_track.id_in_backend)

    def xml_update_track(self, parsed):
        if parsed['activity_id'] != Handler.tracking_track.id_in_backend:
            self.return_error(401,  'wrong track id {}, expected {}'.format(
                parsed['activity_id'], Handler.tracking_track.id_in_backend))
        else:
            Handler.tracking_track.add_points(self.__points(parsed['points']))
            if OPT.debug:
                print('update_track:',Handler.tracking_track)
                print('  last time:',Handler.tracking_track.last_time)
            return '<type>activity_updated</type>'

    def xml_stop_track(self, parsed):
        if Handler.tracking_track is None:
            self.return_error(401,  'No track in tracking mode')
        else:
            self.send_mail('stop_track', Handler.tracking_track)
            Handler.tracking_track = None
            return '<type>activity_stopped</type>'


def options():
    parser = OptionParser()
    parser.add_option(
        '', '--port', dest='port', metavar='PORT',
        type=int, default=8080, help='Listen on PORT')
    parser.add_option(
        '', '--mailto', dest='mailto', metavar='MAIL',
        default=None, help='mail new tracks to MAIL')
    parser.add_option(
        '', '--debug', action='store_true',
        help='show debug output', dest='debug',
        default=False)
    return  parser.parse_args()[0]

def main():
    """main"""
    global OPT
    OPT = options()
    httpd = HTTPServer(("", OPT.port), Handler)
    httpd.serve_forever()

main()
