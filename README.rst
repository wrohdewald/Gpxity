Gpxity is a Python - library making it easy to move activities between different backends.
In this context, a backend is a place where activities can be stored.

Implemented backends are:

  * :class:`~gpxity.backends.directory`: Directory for .gpx files on an accessible file system
  * :class:`~gpxity.backends.server_directory`: Directory suited for server implementations
  * :class:`~gpxity.backends.mmt`: For activities on http://mapmytracks.com

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
