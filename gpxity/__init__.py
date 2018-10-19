# -*- coding: utf-8 -*-

# Copyright (c) 2018 Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""define things that should be visible to the user."""

# pylint: disable=wildcard-import, missing-docstring,protected-access

from .track import *
from .lifetrack import *
from .backend import *
from .diff import *
from .locate import *
from .backends import *
from .version import *
from .auth import *

__all__ = [
    'Track', 'Fences', 'Lifetrack', 'Locate', 'Directory', 'GPSIES', 'MMT', 'TrackMMT',
    'Authenticate', 'ServerDirectory', 'BackendDiff', 'WPTrackserver', 'Mailer', 'VERSION']


def prepare_backends():
    """Initialize the attribute "supported" for all backends."""
    for key in globals().keys():
        cls = globals()[key]
        if hasattr(cls, "__mro__") and cls is not Backend:
            if cls.__mro__[-2] == Backend:
                cls._define_support()


prepare_backends()
