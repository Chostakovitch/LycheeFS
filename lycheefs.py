#!/usr/bin/env python
# coding=utf-8
"""
# lycheefs: a FUSE-based filesystem for Lychee, a photo management system.

For additonal information, visit :
- [Lychee](https://github.com/LycheeOrg/Lychee)
- [lycheefs](https://github.com/Chostakovitch/LycheeFS)
"""

# Skeleton taken from this example : https://github.com/libfuse/python-fuse/blob/master/example/xmp.py
import configparser
import fuse
import logging
import os, errno, stat, sys
import time
from abc import ABC, abstractmethod
from collections.abc import MutableSequence
from enum import Enum
from datetime import datetime
from fuse import Fuse
from pychee import pychee

#TODO type hints, better variable naming, clean doc

if not hasattr(fuse, '__version__'):
    raise RuntimeError("your fuse-py doesn't know of fuse.__version__, probably it's too old.")

fuse.fuse_python_api = (0, 2)
fuse.feature_assert('stateful_files', 'has_init')

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%d-%b-%y %H:%M:%S')

"""
Quality mode available for Lychee images, from lowest to highest.

Not all images have all quality available.
For example, low-resolution images will only get thumbs generated.
Thus, we cannot ask the Lychee server for medium quality for all images.

However, we can keep track of available resolutions thanks to Photo::get API
which returns available resolutions for a given image, and choose
the closer upper quality (which should be close to the asked quality,
otherwise it would have been generated).
"""
class LycheeQuality(Enum):
    THUMB = 0
    THUMB2X = 1
    SMALL = 2
    SMALL2X = 3
    MEDIUM = 4
    MEDIUM2X = 5
    FULL = 6

    """
    Returns closest upper quality.
    """
    def next(self):
        if self.value == 6:
            return LycheeQuality(self.value)
        return LycheeQuality(self.value + 1)

    """
    Returns closest lower quality.
    """
    def prev(self):
        if self.value == 0:
            return LycheeQuality(self.value)
        return LycheeQuality(self.value - 1)

class LycheeFS(Fuse):
    # Keys to look for in configuration
    _URL_KEY = 'url'
    _USER_KEY = 'user'
    _PASSWORD_KEY = 'password'

    # Parser 'default' does not work, do it ourselves
    _DEFAULT_OPTIONS = {
        'config': 'settings.ini',
        'quality': 'SMALL'
    }

    # Path of virtual root album
    _ROOT_PATH = '/'

    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        self.version = "%prog " + fuse.__version__ + ", pychee " + str(pychee.__version__)
        self.usage = "Exposes a Lychee server as a Filesystem in USErspace." + Fuse.fusage
        self.dash_s_do = "setsingle"

        # Correspondance between a path and its corresponding object
        # (LycheeAlbum or LycheeImage). Use path instead of ids to
        # make things readable and ignore duplicates for now.
        self.objects = {}

        # As per examples (eg https://github.com/libfuse/python-fuse/blob/master/example/xmp.py),
        # __init__ should be the method to setup filesystem.
        self._get_options()
        self._create_lychee_session()
        self._fetch_root_structure()

    """
    Return a suitable stat object for given path or ENOENT if path does not exist.
    """
    def getattr(self, path):
        if path in self.objects:
            return self.objects[path].stats
        return -errno.ENOENT

    """
    Enumerate albums and photos inside an album or :
        - ENOENT if path does not exist,
        - ENOTDIR if path is not a directory.

    This function ignores the offset parameter and list all album at once.
    See https://github.com/libfuse/libfuse/blob/b9e3ea01dbbbba9518da216dd29c042af871ae31/include/fuse.h#L545
    """
    def readdir(self, path, offset):
        if not path in self.objects:
            return -errno.ENOENT

        album = self.objects[path]
        if not isinstance(album, LycheeAlbum):
            return -errno.ENOTDIR

        for child_path in album.children_path:
            child = self.objects[child_path]
            type = stat.S_IFDIR if isinstance(child, LycheeAlbum) else stat.S_IFREG
            yield fuse.Direntry(child.title, type=type)

    """
    Returns nothing or :
        - ENOENT if path not found
        - EACCES if not opened in r, rw or w mode.
        - EISDIR is trying to open an album with writing involved.
    """
    def open(self, path, flags):
        if path not in self.objects:
            return -errno.ENOENT
        accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
        #TODO manage O_CREAT
        if (flags & accmode) != 0:
            return -errno.EACCES
        object = self.objects[path]
        if isinstance(object, LycheeAlbum) and (flags & (os.O_WRONLY | os.O_RDWR) != 0):
            return -errno.EISDIR
        #TODO should we implement locking ?

    """
    Read $size bytes a photo from byte $offset.

    Returns :
        - EISDIR if path refers to an album.
        - EOVERFLOW is trying to read beyond limits.
    """
    def read(self, path, size, offset):
        # read can only be called on existing paths
        # in libfuse implementation, because open()
        # should be called first.
        photo = self.objects[path]
        if isinstance(photo, LycheeAlbum):
            return -errno.EISDIR

        if offset >= len(photo):
            return -errno.EOVERFLOW

        # With a tiny photo, read is often called
        # with offset + size exceeding lenght.
        # Fix it ourselves by returning only the
        # portion of photo in boundaries.
        if offset + size >= len(photo):
            size = len(photo) - offset

        return photo[offset:offset + size]

    def _get_options(self):
        # Add parser options to get Lychee URL and optional credentials
        self.parser.add_option('-c', '--config', metavar="FILE",
                                 help="path to the configuration file [default: %default]",
                                 default=self._DEFAULT_OPTIONS['config'])
        self.parser.add_option('-i', '--instance', metavar="INSTANCE",
                                 help="section to use in the configuration file \
                                 [default: first section of configuration]")
        self.parser.add_option('-q', '--quality', metavar="LEVEL",
                                 help=f"lowest quality to use when downloading an image \
                                 (one of {[q.name for q in LycheeQuality]}) [default: %default]",
                                 default=self._DEFAULT_OPTIONS['quality'])
        options = self.parse(values=self, errex=1)

        # Exit if help is printed anyway
        if options.modifiers['showhelp'] == True:
            sys.exit(0)

        # Set default value if option is missing
        for opt, default in self._DEFAULT_OPTIONS.items():
            if not(hasattr(self, opt)):
                setattr(self, opt, default)
                logging.info(f'{opt} not specified, use default : {default}')

    def _create_lychee_session(self):
        # Read configuration file
        instances = configparser.ConfigParser()
        instances.read(self.config)

        # Get suitable Lychee instance configuration
        if not hasattr(self, 'instance') and len(instances.sections()) > 0:
            self.instance = instances.sections()[0]
            logging.info(f'instance not specified, use first instance found : {self.instance}.')
        else:
            logging.error('instance is mandatory !\n')
            self.parser.print_help()
            sys.exit(1)

        if self.instance not in instances.sections():
            logging.error(f'instance {self.instance} not found in configuration.')
            sys.exit(1)

        # Get Lychee instance URL
        if not instances.has_option(self.instance, self._URL_KEY):
            logging.error(f'url is mandatory for instance {self.instance}.')
            sys.exit(1)
        host = instances.get(self.instance, self._URL_KEY)

        # This is the API client for the given URL
        logging.info(f'initializing connection to {host}...')
        self.client = pychee.LycheeClient(host)

        # Optional connection to access private albums and upload files
        if instances.has_option(self.instance, self._USER_KEY) and instances.has_option(self.instance, self._PASSWORD_KEY):
            logging.info(f'user and password found, logging to {host}...')
            user = instances.get(self.instance, self._USER_KEY)
            password = instances.get(self.instance, self._PASSWORD_KEY)
            self.client.login(user, password)

    """
    Browse all Lychee tree and store albums and photos information.

    This will take more time at the beginning, but as each Album::get API call
    send ALL information about inner pictures, it is way clearer than doing
    lazy loading of image metadata from a path : in that case, we would have
    to recursively fetch information from parent album while checking this
    is not already done... most of Lychee server can probably afford the
    initial downloading of metadata, while still deferring download of content.
    """
    def _fetch_root_structure(self):
        logging.info('fetching Lychee tree... this may take some time.')
        raw_albums = self.client.get_albums()
        # All albums visibles at the homepage
        albums = []
        albums.extend([v for (k, v) in raw_albums['smartalbums'].items()])
        albums.extend(raw_albums['albums'])
        albums.extend(raw_albums['shared_albums'])
        # Virtual "root album" with fake JSON infos
        #TODO symlinks to real photos instead of downloading twice
        fake_json = {
            'id': -1,
            'title': self._ROOT_PATH,
            #TODO more realistic values
            'created_at': time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            'updated_at': time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        root_album = LycheeAlbum(fake_json)
        # Fetch all subalbums information.
        # We need to pass the prebuilt list of subalbums
        # because there is not API call to fetch root albums.
        self._fetch_album_structure(root_album, self._ROOT_PATH, albums)
        logging.info('done!')

    """
    Recursively fetch information about a known album.

    album: LycheeAlbum with empty children_path.
    album_path: path of the album on the filesystem.
    root_albums: Optional list of JSON object (Album::get-like) representing root albums.
               If empty, subalbums will be fetched from server based on album id.
    """
    def _fetch_album_structure(self, album, album_path, root_albums = []):
        logging.debug(f'Fetching info for album at {album_path}...')
        if root_albums == []:
            album_json = self.client.get_album(album.id)
            subalbums = album_json.get('albums', [])
            photos =  album_json.get('photos', [])
        else:
            subalbums = root_albums
            photos = []
        for e in subalbums:
            # For each subalbum, create the object for the subalbum
            subalbum = LycheeAlbum(e)
            # Then record its path in the parent album
            subalbum_path = LycheeFS._join_path(album_path, subalbum.title)
            album.children_path.append(subalbum_path)
            # And recursively fetch sub-sub-album information
            self._fetch_album_structure(subalbum, subalbum_path)
        # Add all photos to album listing and record path <=> object
        for e in photos:
            photo = LycheeImage(e, self.client, self.quality)
            photo_path = LycheeFS._join_path(album_path, photo.title)
            album.children_path.append(photo_path)
            self.objects[photo_path] = photo
        # Finally, store the album in the path <=> object dictionary
        self.objects[album_path] = album

    """
    Join a path and a filename and normalize its components.
    """
    @staticmethod
    def _join_path(base, filename):
        return os.path.join(os.path.normpath(base), os.path.normpath(filename))

"""
Base class for representing an album or an image.

Albums and images have a similar data model on Lychee side, so
we can factorize a lot of code.

json_info: JSON object e.g. response for [Album|Photo]::get API call.
"""
class LycheeElement(ABC):
    @abstractmethod
    def __init__(self, json_info):
        self._json_info = json_info
        self.stats = json_info
        self._title = None
        self._id = None

    @property
    def id(self):
        if self._id is None:
            self._id = self._json_info['id']
        return self._id

    @property
    def title(self):
        if self._title is None:
            self._title = self._json_info['title']
            # Add extension to title if applicable
            if 'type' in self._json_info:
                type = self._json_info['type']
                # If type exists, it is a MIME type.
                # For any photo/video possible, the last component
                # of MIME type should be usable as an extension
                # This is a bit hackish but I cannot see another
                # way to make proper file names otherwise.
                self._title = f'{self._title}.{type.split("/")[-1]}'
        return self._title

    """
    Return a stat-like objectsuitable for getattr call.
    """
    @property
    def stats(self):
        return self._stats

    """
    Set stat-like object from JSON.

    value: JSON object e.g. response for [Album|Photo]::get API call.
    """
    @stats.setter
    def stats(self, value):
        st = fuse.Stat()
        st.st_uid = os.getuid()
        st.st_gid = os.getgid()
        st.st_nlink = 1
        creation_date = datetime.strptime(value['created_at'], "%Y-%m-%dT%H:%M:%S%z")
        mod_date = datetime.strptime(value['updated_at'], "%Y-%m-%dT%H:%M:%S%z")
        # If 'filesize' does not exist, probably an album, choose a default
        # Default size is default blocksize for extX filesystem, stick to that
        #TODO fix size when downloading lower quality images
        # will be harder because there is not filesize attribute for them
        st.st_size = value.get('filesize', 4096)
        st.st_ctime = datetime.timestamp(creation_date)
        st.st_mtime = datetime.timestamp(mod_date)
        st.st_atime = datetime.timestamp(datetime.now())
        self._stats = st

"""
Used to read and write an image on a Lychee server.
Image must exist (i.e. have an id).

Acts as a cache for content and metadata to avoid constantly
talking to the Lychee server.
Send updates only when required.
"""
class LycheeImage(MutableSequence, LycheeElement):
    """
    Initialize the image without downloading it Data will be fetched when necessary.

    client: instance of LycheeClient used to read/write image
    quality: FULL, MEDIUM2X, MEDIUM, SMALL2X, SMALL
             THUMB2X or THUMB (used for download)
    """
    def __init__(self, json_info, client, quality):
        super().__init__(json_info)
        self._client = client
        self.quality = quality
        # Bytes representing the image
        self._content = bytearray()
        self.stats.st_mode = stat.S_IFREG | 0o444

    def _fetch_content(self):
        #TODO read() calls are really slow because of wrong size :
        # we probably need to fix this directly in Lychee and
        # make the API send the filesize of variants
        #TODO GIF are not working, check why
        self._content = bytearray(self._client.get_photos_archive([self.id], self.quality))

    @property
    def quality(self):
        return self._quality

    """
    Determine and set the preferred download quality for image.

    Requested quality is compared with available resolutions.
    If not available, the closest upper resolution is choosen.
    """
    @quality.setter
    def quality(self, value):
        # Requested quality is original size, don't bother
        # enumerating available resolutions
        if LycheeQuality[value] == LycheeQuality.FULL:
            self._quality = value

        res_avail = []
        for res in LycheeQuality:
            # Check if there is an URL available for given resolution
            if self._json_info['sizeVariants'].get(res.name.lower(), None) != None:
                res_avail.append(res)

        quality = LycheeQuality[value]
        # Try increasing quality until available or original size
        while quality != LycheeQuality.FULL and quality not in res_avail:
            quality = quality.next()

        self._quality = quality.name

    """
    Return requested bytes of the image or ENOENT if image not found on server.
    """
    def __getitem__(self, index):
        # Content has not been fetched, download it
        if len(self._content) == 0:
            self._fetch_content()
        # Possibly out of range, but not our problem
        return bytes(self._content.__getitem__(index))

    def __setitem__(self, index, value):
        if len(self._content) == 0:
            self._fetch_content()
        end = index.stop if isinstance(index, slice) else index
        # Auto-extend array of bytes - we have no way to
        # know where this is going but probably not optimal
        if end > len(self._content):
            self._content.extend(b'\x00' * (end + 1 - len(self._content)))
        self._content.__setitem__(index, value)

    def __delitem__(self, index):
        if len(self._content) == 0:
            self._fetch_content()
        self._content.__delitem__(index)

    def __len__(self):
        # No need to download content, we already have metadata
        return self._stats.st_size

    def __repr__(self):
        if len(self._content) == 0:
            self._fetch_content()
        return self._content.__repr__()

    def insert(self, key, value):
        if len(self._content) == 0:
            self._fetch_content()
        self._content.insert(key, value)

"""
Used to store information about a Lychee album
and its photos/subalbums.
"""
class LycheeAlbum(LycheeElement):
    """
    Initialize an existant Lychee album.

    id: id of the album on the Lychee server
    path: path on the Lychee filesystem
    """
    def __init__(self, json_info):
        super().__init__(json_info)
        self.children_path = []
        self.stats.st_mode = stat.S_IFDIR | 0o755

def main():
    fuse = LycheeFS()
    fuse.main()

if __name__ == '__main__':
    main()
