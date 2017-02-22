Gpxity is a Python - library making it easy to move activities between different backends.
In this context, a backend is a place where activities can be stored.

Gpxity is work in progress. If you want to save yourself time, please wait
a few weeks.

Implemented backends are:

  * :class:`~gpxity.backends.directory`: Directory for .gpx files on an accessible file system:
  * :class:`~gpxity.backends.mmt`: For activities on http://mapmytracks.com

Some backends do not support everything we would like to have, you might get the
exception NotImplementedError(). Some backends simply do not offer everything we
want.

Sometimes you might just change a harmless thing like the description but
the backend does not allow changing this separately, so we have to re-upload
the whole activity. If it is is big and the remote server slow, this might
take 10 minutes or more. Right now this library has no asynchronous interface,
so it can really take some time until your program continues.

Sometimes Gpxity uses undocumented ways to access a backend - this is done
when there is no documented way or when the official API implementation is
buggy or too slow for real-life use.

Backends might change their behaviour, and Gpxity will have to be updated.

This documentation is meant for the user of this library. If you want to add
a new backend, you will need to know more - please read the source code or
remove the lines like :literal:`:exclude-members:` in :literal:`doc/source/*.rst` and
rebuild the documentation.

Todo: Write all class references in the shortest form how an application could
import them.
