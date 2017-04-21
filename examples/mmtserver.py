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

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

import gpxpy

# This uses not the installed copy but the development files
sys.path.insert(0, '..')

# pylint: disable=wrong-import-position

from gpxity import Activity
from gpxity import ServerDirectory # pylint: disable=no-name-in-module

class Handler(BaseHTTPRequestHandler):
    """handles all HTTP requests"""
    users = None
    directory = ServerDirectory('serverdir')

    def check_pw(self):
        """basic http authentication"""
        if self.users is None:
            self.load_users()
        for pair in self.users.items():
            expect = b'Basic ' + base64.b64encode(':'.join(pair).encode('utf-8'))
            expect = expect.decode('utf-8')
            if expect == self.headers['Authorization']:
                return True
        return False

    def load_users(self):
        """load legal user auth from serverdirectory/.users"""
        self.users = dict()
        with open(os.path.join(self.directory.url, '.users')) as user_file:
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
        data_length = int(self.headers['Content-Length'])
        data = self.rfile.read(data_length).decode('utf-8')
        parsed = parse_qs(data)
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
        xml = getattr(self, 'xml_{}'.format(parsed['request']))(parsed)
        self.send_header('Content-Type', 'text/xml; charset=UTF-8')
        xml = '<?xml version="1.0" encoding="UTF-8"?><message>{}</message>'.format(xml)
        self.send_header('Content-Length', len(xml))
        self.end_headers()
        self.wfile.write(bytes(xml.encode('utf-8')))

    @staticmethod
    def xml_get_time(_):
        """as defined by the mapmytracks API"""
        return '<type>time</type><server_time>{}</server_time>'.format(
            int(datetime.datetime.now().timestamp()))

    def xml_get_activities(self, parsed):
        """as defined by the mapmytracks API"""
        a_list = list()
        if parsed['offset'] != '0':
            for idx, _ in enumerate(self.directory):
                a_list.append(
                    '<activity{}><id>{}</id>'
                    '<title><![CDATA[ {} ]]></title>'
                    '<activity_type>{}</activity_type>'
                    '<date>{}</date>'
                    '</activity{}>'.format(
                        idx + 1, _.id_in_backend, _.title, _.what,
                        int(_.time.timestamp()), idx + 1))
        return '<activities>{}</activities>'.format(''.join(a_list))

    def xml_upload_activity(self, parsed):
        """as defined by the mapmytracks API"""
        activity = Activity(gpx=gpxpy.parse(parsed['gpx_file']))
        self.directory.save(activity)
        return '<type>success</type><id>{}</id>'.format(activity.id_in_backend)

def main():
    """main"""
    httpd = HTTPServer(("", int(sys.argv[1])), Handler)
    httpd.serve_forever()

main()
