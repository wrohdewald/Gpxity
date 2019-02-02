# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
implements test classes for GpxFile.

They only use backend Directory, so there is no network traffic involved
(unless Directory is a network file system, of course).

"""

# pylint: disable=protected-access

import logging
import unittest

from gpxpy import gpx as mod_gpx


from .. import Gpx

# pylint: disable=attribute-defined-outside-init

GPXTrackPoint = mod_gpx.GPXTrackPoint


class GpxTests(unittest.TestCase):

    """Gpx tests."""

    xml = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
        <gpx xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" creator="OruxMaps v.6.5.10" version="1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">
        <metadata>
        <name><![CDATA[2016-09-04 07:56]]></name>
        <desc><![CDATA[]]></desc>
        <link href="http://www.oruxmaps.com">
        <text>OruxMaps</text>
        </link>
        <time>2016-09-04T05:56:53Z</time><bounds maxlat="52.5493442" maxlon="13.3860810" minlat="52.5168438" minlon="13.2123302"/>
        </metadata>
        <wpt lat="52.5468688" lon="13.2125601">
        <ele>36.50</ele>
        <time>2016-09-04T05:57:04Z</time>
        <name><![CDATA[0004075]]></name>
        <desc><![CDATA[]]></desc>
        <sym>Waypoint</sym>
        <type>Startpunkt</type>
        <extensions>
        <om:oruxmapsextensions xmlns:om="http://www.oruxmaps.com/oruxmapsextensions/1/0">
        <om:ext type="ICON" subtype="0">38</om:ext>
        </om:oruxmapsextensions>
        </extensions>
        </wpt>
        <trk>
        <name><![CDATA[2016-09-04 07:56]]></name>
        <desc><![CDATA[<p>Startzeit: 09/04/2016 07:57</p><p>Zielzeit: 09/04/2016 10:16</p><p>Strecke: 20,4 km (01:57)</p><p>Bewegungszeit: 01:33</p><p>Ø-Geschwindigkeit: 10,42 km/h</p><p>Netto-Geschwindigkeit: 13,08 km/h</p><p>Max. Geschwindigkeit: 33,93km/h</p><p>Minimale Höhe: 13 m</p><p>Maximale Höhe: 54 m</p><p>Steig-Geschw.: 378,1 m/h</p><p>Sink-Geschw.: -455,8 m/h</p><p>Aufstieg: 340 m</p><p>Abstieg: -346 m</p><p>Steigzeit: 00:53</p><p>Sinkzeit: 00:45</p><hr align="center" width="480" style="height: 2px; width: 517px"/>]]></desc>
        <type>Fahrrad/ Strasse</type>
        <cmt>Track 0 comment</cmt>
        <extensions>
        <om:oruxmapsextensions xmlns:om="http://www.oruxmaps.com/oruxmapsextensions/1/0">
        <om:ext type="TYPE" subtype="0">8</om:ext>
        <om:ext type="DIFFICULTY">0</om:ext>
        </om:oruxmapsextensions>
        </extensions>
        <trkseg>
        <trkpt lat="52.5192692" lon="13.3803910">
        <ele>42.50</ele>
        <time>2016-09-04T08:13:15Z</time>
        </trkpt>
        </trkseg>
        </trk>
        <trk>
        <name>Name for track 2</name>
        <desc></desc>
        <type>other/ Strasse</type>
        <cmt>Track 0 comment</cmt>
        <extensions>
        <om:oruxmapsextensions xmlns:om="http://www.oruxmaps.com/oruxmapsextensions/1/0">
        <om:ext type="TYPE" subtype="1">8</om:ext>
        <om:ext type="DIFFICULTY">0</om:ext>
        </om:oruxmapsextensions>
        </extensions>
        <trkseg>
        <trkpt lat="53.5192692" lon="13.3803910">
        <ele>42.50</ele>
        <time>2016-09-05T08:13:15Z</time>
        </trkpt>
        </trkseg>
        </trk>
        </gpx>
    """

    def setUp(self):  # noqa
        self.logger = logging.getLogger()
        self.logger.level = logging.DEBUG

    def test_gpx_join_tracks(self):
        """Test joining tracks."""

        gpx1 = Gpx.parse(self.xml)
        losing = gpx1.join_tracks()
        self.assertTrue(losing[-1].startswith('extensions: '))
        self.assertEqual(losing[:-1], ['name: Name for track 2', 'type: other/ Strasse'])
        gpx1.tracks[1].extensions = []
        gpx1.tracks[0].name = ''
        losing = gpx1.join_tracks()
        self.assertEqual(losing, ['type: other/ Strasse'])
        losing = gpx1.join_tracks(force=True)
        self.assertEqual(losing, ['type: other/ Strasse'])
        self.assertEqual(len(gpx1.tracks), 1)
        self.assertEqual(gpx1.tracks[0].name, 'Name for track 2')
        self.assertEqual(gpx1.tracks[0].type, 'Fahrrad/ Strasse')

        gpx1 = Gpx.parse(self.xml)
        gpx1.tracks[0].extensions = []
        gpx1.tracks[0].name = ''
        gpx1.tracks[0].type = None
        self.assertEqual(len(gpx1.tracks), 2)
        gpx1.join_tracks()
        self.assertEqual(len(gpx1.tracks), 1)
        gpx2 = Gpx.parse(self.xml)
        self.assertEqual(gpx1.tracks[0].name, gpx2.tracks[1].name)
        self.assertEqual(gpx1.tracks[0].type, gpx2.tracks[1].type)
