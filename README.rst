Gpxity is a Python - library making it easy to move GPS-based activities between different backends.
In this context, a backend is a place where activities can be stored.

And there is a command line utility **gpxdo** helping you organize your activities.
It lets you list, copy, merge, remove, edit, fix, compare backends and activities.

The library currently implements those backends:

  * :class:`~gpxity.backends.directory.Directory`: Directory for .gpx files on an accessible file system
  * :class:`~gpxity.backends.server_directory.ServerDirectory`: Directory suited for server implementations
  * :class:`~gpxity.backends.gpsies.GPSIES`: For activities on https://gpsies.com
  * :class:`~gpxity.backends.mmt.MMT`: For activities on http://mapmytracks.com
  * :class:`~gpxity.backends.trackmmt.TrackMMT`: For activities on a very simple server emulating a
    few MMT commands (just what oruxmaps uses for uploading)

Some backends might not support everything Gxpity wants and you will get the
exception NotImplementedError().

Sometimes you might just change a harmless thing like the description but
the backend does not allow changing this separately, so we have to re-upload
the whole activity. If it is is big and the remote server slow, this might
take 10 minutes or more. Right now this library has no asynchronous interface,
so it can really take some time until your program continues.

Sometimes Gpxity uses undocumented ways to access a backend - this is done
when there is no documented way or when the official API implementation is
buggy or too slow for real-life use.

Backends might change their behaviour, and Gpxity will have to be updated.
