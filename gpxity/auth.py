# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""
This module defines :class:`~gpxity.Authenticate`
"""

import os
from configparser import ConfigParser

__all__ = ['Authenticate']

class Authenticate:

    """
    Get username and password from auth.cfg. If nothing is
    useable, sets them to None.

    auth.cfg is expected in :literal:`~/.config/Gpxity/auth.cfg`

    .. DANGER::
       auth.cfg is not encrypted. Better not use this unless you know what you are doing!

    Args:
        cls (Backend): The class of the backend
        sub_name (str): Be more specific. This can be used to define different data for some tests.

    Attributes:
        auth (tuple(str,str)): (username, password). Both are either str or None.
        url: If given, overrides the url given to the backend

    auth.cfg has sections
      * [default]             most general fallback
      * [ClassName]           the class name of a backend like MMT
      * [ClassName.sub_name]  can be used for a specific account

    A section can define
      * Username
      * Password
      * Url

    The sections are tried from most specific to default until
    both username and password are known. It is legal if a more
    specific section only defines username or password.

    """

    # pylint: disable=too-few-public-methods

    def __init__(self, cls, sub_name: str = None):

        self.cls = cls
        self.sub_name = sub_name
        self.auth = (None, None)

        path = os.path.expanduser('~/.config/Gpxity/auth.cfg')
        with open(path) as auth_file:
            self._parse_config(auth_file.read())
        return

    def _parse_config(self, data):
        """try to use data"""

        username = password = url = None

        config = ConfigParser()
        config.read_string(data)

        # try most specific section first, default last:
        try_sections = list([self.cls.__name__, 'default'])
        if self.sub_name:
            try_sections.insert(0, (try_sections[0] + '.' + self.sub_name))

        for check_section in try_sections:
            if check_section in config.sections():
                section = config[check_section]
                if username is None and 'Username' in section:
                    username = section['Username']
                if password is None and 'Password' in section:
                    password = section['Password']
                if url is None and 'Url' in section:
                    url = section['Url']
                if username and password:
                    break

        self.auth = (username, password)
        self.url = url

        if username is None:
            raise Exception('Authenticate: Nothing found for account {}'.format(username))
