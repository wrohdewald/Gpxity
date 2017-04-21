#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This implements only a minimum of what MMT can do:
upload entire tracks and extend a track. That is
what oruxmaps does - see examples/mmt_server.

Simple_MMT is used to test mmt_server.
"""

from xml.etree import ElementTree
import datetime

import requests

from .. import Backend, Activity


__all__ = ['UploadMMT']

def _convert_time(raw_time) ->datetime.datetime:
    """MMT uses Linux timestamps. Converts that into datetime

    Args:
        raw_time (int): The linux timestamp from the MMT server
    """
    return datetime.datetime.utcfromtimestamp(float(raw_time))


class MMTRawActivity:

    """raw data from mapmytracks.get_activities"""

    # pylint: disable=too-few-public-methods
    def __init__(self, xml):
        self.activity_id = xml.find('id').text
        self.title = xml.find('title').text
        self.time = _convert_time(xml.find('date').text)
        self.what = xml.find('activity_type').text


class UploadMMT(Backend):
    """The implementation for MapMyTracks.
    The activity ident is the number given by MapMyTracks.

    MMT knows tags. We map :attr:`Activity.keywords <gpxity.Activity.keywords>` to MMT tags. MMT will
    change keywords: It converts the first character to upper case. See
    :attr:`Activity.keywords <gpxity.Activity.keywords>` for how Gpxity handles this.

    Args:
        url (str): The Url of the server. Default is http://mapmytracks.com
        auth (tuple(str, str)): Username and password
        cleanup (bool): If True, :meth:`~gpxity.Backend.destroy` will remove all activities in the
            user account.
    """

    # pylint: disable=abstract-method

   #  skip_test = True

    _default_description = 'None yet. Let everyone know how you got on.'

    def __init__(self, url=None, auth=None, cleanup=False):
        if url is None:
            url = 'http://localhost:8080'
        super(UploadMMT, self).__init__(url, auth, cleanup)
        self.remote_known_whats = None
        self.__mid = -1 # member id at MMT for auth
        self.__tag_ids = dict()  # key: tag name, value: tag id in MMT. It seems that MMT
            # has a lookup table and never deletes there. So a given tag will always get
            # the same ID. We use this fact.
            # MMT internally capitalizes tags but displays them lowercase.
        self._last_response = None # only used for debugging

    def __post(self, url: str = None, data: str = None, expect: str = None, **kwargs):
        """Helper for the real function with some error handling.

        Args:
            url:  Will be appended to self.url. Default is api/. For the basic url, pass an empty  string.
            data: should be xml and will be encoded. May be None.
            expect: If given, raise an error if this string is not part of the server answer.
            kwargs: a dict for post(). May be None. data and kwargs must not both be passed.
        """
        if url is None:
            url = 'api/'
        full_url = self.url + url
        headers = {'DNT': '1'} # do not track
        if data:
            data = data.encode('ascii', 'xmlcharrefreplace')
        else:
            data = kwargs
        try:
            response = requests.post(full_url, data=data, headers=headers, auth=self.auth, timeout=(5, 300))
        except requests.exceptions.ReadTimeout:
            print('timeout for', data)
            raise
        self._last_response = response # for debugging
        if response.status_code != requests.codes.ok: # pylint: disable=no-member
            self.__handle_post_error(full_url, data, response)
            return
        result = response.text
        if expect and expect not in result:
            raise requests.exceptions.HTTPError('{}: expected {} in {}'.format(data, expect, result))
        if result.startswith('<?xml'):
            try:
                result = ElementTree.fromstring(result)
            except ElementTree.ParseError:
                print('POST {} has parse error: {}'.format(data, response.text))
                raise
            result_type = result.find('type')
            if result_type is not None and result_type.text == 'error':
                reason = result.find('reason').text if result.find('reason') else 'no reason given'
                raise requests.exceptions.HTTPError('{}: {}'.format(data, reason))
        return result

    @staticmethod
    def __handle_post_error(url, data, result):
        """we got status_code != ok"""
        try:
            result.raise_for_status()
        except BaseException as exc:
            if 'request' in data:
                _ = data['request']
            else:
                _ = data
            raise type(exc)('{}: {} {} {}'.format(exc, url, _, result.text))

    def get_time(self) ->datetime.datetime:
        """get MMT server time"""
        return _convert_time(self.__post(request='get_time').find('server_time').text)

    def _yield_activities(self):
        """get all activities for this user. If we do not use the generator
        created by yield_activity, unittest fails. Why?"""

        while True:
            old_len = len(self._activities)
            response = self.__post(
                request='get_activities', author=self.auth[0],
                offset=old_len)
            chunk = response.find('activities')
            if not chunk:
                return
            for _ in chunk:
                raw_data = MMTRawActivity(_)
                activity = Activity(self, raw_data.activity_id)
                with activity.decoupled():
                    activity.title = raw_data.title
                    activity.what = raw_data.what
                yield activity
            assert len(self._activities) > old_len

    def _write_all(self, activity, ident: str = None):
        """save full gpx track on the MMT server.
        Because we cannot upload the time, we set the activity time to the time
        of the first trackpoint."""

        if not activity.gpx.get_track_points_no():
            raise Exception('UploadMMT does not accept an activity without trackpoints:{}'.format(activity))
        mmt_status = 'public' if activity.public else 'private'
        if activity.id_in_backend:
            # we cannot change an MMT activity in-place, we need to re-upload and then
            # remove the previous instance.
            self._remove_activity_in_backend(activity)
        response = self.__post(
            request='upload_activity', gpx_file=activity.to_xml(),
            status=mmt_status, description=activity.description, activity=activity.what)
        activity.id_in_backend = response.find('id').text

    def update(self, activity, points):
        """append points in the backend. activity already has them.
        points are GPXTrackPoint"

        Todo:
            Doc is wrong, must rethink this.
        """
        activity.add_points(points)
        self.__post(
            request='update_activity', activity_id=activity.id_in_backend,
            points=points)

UploadMMT._define_support() # pylint: disable=protected-access
