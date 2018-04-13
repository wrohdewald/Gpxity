# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Authenticate`
"""

import os
import tempfile
from configparser import ConfigParser

__all__ = ['Authenticate']

class Authenticate:

    """
    Get password and / or Url from auth.cfg.
    If nothing is useable, sets them to None.

    auth.cfg is expected in :literal:`~/.config/Gpxity/auth.cfg`

    .. DANGER::
       auth.cfg is not encrypted. Better not use this unless you know what you are doing!

    Args:
        cls (Backend): The class of the backend
        username (str): For the wanted account in the backend

    Attributes:
        auth (tuple(str,str)): (username, password). Both are either str or None.
        url: If given, overrides the url given to the backend

    For every specific account in a backend, auth.cfg has a section:
      * [ClassName.username]

    A section can define
      * Password
      * Url

    An example for user gpxitytest on gpsies.com:

    .. code-block:: guess

        [GPSIES:gpxitytest]
        Password = the_unencrypted_password


    """

    # pylint: disable=too-few-public-methods

    def __init__(self, cls, username: str = None):

        self.cls = cls
        self.__username = username
        self.auth = (None, None)
        if 'Directory' in cls.__name__  and username.startswith('gpxitytest'):
            self.url = tempfile.mkdtemp(prefix='gpxity')
            return
        self.path = os.path.expanduser('~/.config/Gpxity/auth.cfg')
        with open(self.path) as auth_file:
            self._parse_config(auth_file.read())
        return

    def _parse_config(self, data):
        """try to use data"""

        password = url = None

        config = ConfigParser()
        config.read_string(data)

        config_key = '{}:{}'.format(self.cls.__name__, self.__username)
        try:
            section = config[config_key]
        except KeyError:
            raise KeyError('Section [{}] not found in {}'.format(config_key, self.path))
        if 'Password' in section:
            password = section['Password']
        if 'Url' in section:
            url = section['Url']

        self.auth = (self.__username, password)
        self.url = url
