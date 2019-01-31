# -*- coding: utf-8 -*-

# Copyright (c) 2019 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""define things that should be visible to the user."""

# pylint: disable=protected-access

from .accounts import *
from .track import *
from .lifetrack import *
from .backend import *
from .diff import *
from .locate import *
from .backends import *
from .version import *

__all__ = [
    'Track', 'Fences', 'Lifetrack', 'Locate', 'Directory', 'GPSIES', 'MMT', 'TrackMMT', 'Openrunner',
    'BackendDiff', 'WPTrackserver', 'Mailer', 'VERSION', 'Account', 'DirectoryAccount']


def prepare_backends():
    """Initialize the attribute "supported" for all backends."""
    for key in globals().keys():
        cls = globals()[key]
        if hasattr(cls, "__mro__") and cls is not Backend:
            if len(cls.__mro__) > 3 and cls.__mro__[-3] == Backend:
                cls._define_support()


prepare_backends()
