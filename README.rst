Gpxity is a Python - library making it easy to move GPS-based tracks between different backends.
In this context, a backend is a place where gpxfiles can be stored.

And there is a command line utility **gpxdo** helping you organize your gpxfiles.
It lets you list, copy, merge, remove, edit, fix, compare backends and gpxfiles.

Find the documentation here: https://gpxity.readthedocs.io/en/latest/

The library currently implements those backends:

  * :class:`~gpxity.backends.directory.Directory`: Directory for .gpx files on an accessible file system
  * :class:`~gpxity.backends.server_directory.ServerDirectory`: Directory suited for server implementations
  * :class:`~gpxity.backends.gpsies.GPSIES`: For gpxfiles on https://gpsies.com
  * :class:`~gpxity.backends.openrunner.Openrunner`: For gpxfiles on https://openrunner.com
  * :class:`~gpxity.backends.mmt.MMT`: For gpxfiles on http://mapmytracks.com
  * :class:`~gpxity.backends.trackmmt.TrackMMT`: For gpxfiles on a very simple server emulating a
    few MMT commands (just what oruxmaps uses for uploading)
  * :class:`~gpxity.backends.wptrackserver.WPTrackserver`: For the Wordpress plugin Trackserver
  * :class:`~gpxity.backends.mailer.Mailer`: Mails gpxfiles
  * :class:`~gpxity.backends.memory.Memory`: Keep everything in RAM only

Some backends might not support everything Gxpity wants and you will get the
exception NotImplementedError().

Sometimes you might just change a harmless thing like the description but
the backend does not allow changing this separately, so we have to re-upload
the whole track. If it is is big and the remote server slow, this might
take some time. Right now this library has no asynchronous interface,
so it can really take some time until your program continues.

Sometimes Gpxity uses undocumented ways to access a backend - this is done
when there is no documented way or when the official API implementation is
buggy or too slow for real-life use.

Backends might change their behaviour, I intend to update Gpxity quickly
in that case. The unittests of gpxity should notice all relevant changes.
