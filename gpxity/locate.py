#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""This module defines :class:`~gpxity.locate.Locate`."""

import logging

import geocoder
from gpxpy.gpx import GPXTrackPoint

__all__ = ['Locate']


class Locate:

    """Locates tracks using https://github.com/DenisCarriere/geocoder#overview .

    Args:
        places: A list of places that the tracks should pass
        tracks: The tracks to be searched
        provider: The data provider for geolocation

    Attributes:
        locations: The list of found places. For each given value in arg **places**,
            locations holds one result, even if the provider returns more than one.
        distances: A list with a tuple for every track. The tuple holds the track
            and a list of distances between that track and places.

    """

    # pylint: disable=too-few-public-methods

    def __init__(self, places, tracks, provider='osm'):
        """See class docstring."""
        self.places = places
        self.tracks = tracks
        self.provider = provider
        self.locations = list()
        for place in places:
            _ = geocoder.get(place, provider=provider)
            if not _:
                raise Exception('Place not found: {}'.format(place))
            self.locations.append(_[0])
        logging.info('using locations:')
        for _ in self.locations:
            logging.info('  %s', _.address)
        self.distances = list()
        gpx_points = [GPXTrackPoint(latitude=x.lat, longitude=x.lng) for x in self.locations]
        for track in tracks:
            self.distances.append(
                (track, [track.gpx.get_nearest_location(x).location.distance_2d(x) for x in gpx_points]))
        self.distances.sort(key=lambda x: sum(x[1]))

    def found(self, max_away: float = 1e10):
        """The list of tracks sorted by affinity to the given places.

        Args:
            max_away: The maximum distance in kilometers

        Returns: list(tracks)

        """
        return [x[0] for x in self.distances if sum(x[1]) < max_away * 1000]
