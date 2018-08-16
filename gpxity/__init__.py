# -*- coding: utf-8 -*-

# Copyright (c) Wolfgang Rohdewald <wolfgang@rohdewald.de>
# See LICENSE for details.

"""define things that should be visible to the user."""

# pylint: disable=wildcard-import, missing-docstring
from .track import *
from .lifetrack import *
from .backend import *
from .diff import *
from .backends import *
from .version import *

__all__ = ['Track', 'Lifetrack', 'Directory', 'GPSIES', 'MMT', 'TrackMMT', 'ServerDirectory', 'BackendDiff', 'VERSION']


def prepare_backends():
    """Initialize the attribute "supported" for all backends."""
    for key in globals().keys():
        cls = globals()[key]
        if hasattr(cls, "__mro__") and cls is not Backend:
            if cls.__mro__[-2] == Backend:
                cls._define_support()  # pylint: disable=protected-access


prepare_backends()
