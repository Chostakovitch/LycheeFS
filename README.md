# LycheeFS

LycheeFS is a FUSE-based filesystem for [Lychee](https://github.com/LycheeOrg/Lychee), a photo management system.

## Features

## Installation

Requirements :
- FUSE v2 and FUSE v2 headers (`fuse` + `libfuse-dev` on Debian-like, `fuse2` on Arch)

[PEP 517](https://www.python.org/dev/peps/pep-0517/) is used to specify the build system (`setuptools`) so there is no need for `setup.py`.
Simply use `pip>19` and :

```bash
pip install .
```

The script will be installed in `$HOME/.local/bin`, unless you run the command as superuser, in which case it will be installed in `/usr/local/bin`.

To uninstall, simply :

```bash
pip uninstall lycheefs
```

## Configuration

Configuration file is parsed by [configparser](https://docs.python.org/3/library/configparser.html) and looks like this :

```ini
[pi]
url = lychee1.example.com

[vps]
url = lychee2.example.com
user = foo
password = bar
```

You define one instance per section (here, `pi` and `vps`) and then specify :
- `url` : URL of your instance. Scheme is not mandatory.
- `user` and `password` : optional credentials. Not supplying them means that you will only be able to browse public albums.

## Usage

```
Usage: lycheefs.py [mountpoint] [options]

Options:
    -h, --help             show this help message and exit
    -o opt,[opt...]        mount options
    -c FILE, --config=FILE
                           path to the configuration file [default:
                           settings.ini]
    -i INSTANCE, --instance=INSTANCE
                           section to use in the configuration file
                           [default: first section of configuration]
    -q LEVEL, --quality=LEVEL
                           lowest quality to use when downloading an image
                           (one of ['THUMB', 'THUMB2X', 'SMALL', 'SMALL2X',
                           'MEDIUM', 'MEDIUM2X', 'FULL']) [default: SMALL]
```

Example :

```bash
lycheefs.py -i pi /mnt/lychee
```

In that case :
- default `settings.ini` file will be used,
- instance `pi` will be used,
- albums will be mounted inside `/mnt/lychee`.

Note that the mountpoint must exist.

To umount :

```bash
umount /mnt/lychee
```

## Implementation choices

TODO : why all structure is fetched at the beginning, explain how storage is done.
To this at the end because it will probably change : right now cache is growing forever and duplicate names won't work (we should find a way to use IDs).

Note : extension is guessed from MIME type and added to photo titles fetched from server. This helps file managers to show the content of folder with placeholders while downloading image. Without extensions, most of file managers will show an empty folder until all images are downloaded, because they cannot rely on name to guess the content and must wait the content itself.

## TODO

- handle write, rename, mkdir etc operations
- type hints, better variable naming, clean doc
- manage O_CREAT in `open()`
- implement locking for writes (at least think about it...)
- symlinks to real photos in smart albums like `recent` instead of downloading twice
- more realistic values for creation date of smart albums
- fix size when downloading lower quality images (probably must be done on Lychee API side). read() calls are really slow because of wrong size.
- GIF are not working, probably an issue on my computer ?
