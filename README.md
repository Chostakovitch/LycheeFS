# LycheeFS

LycheeFS is a FUSE-based filesystem for [Lychee](https://github.com/LycheeOrg/Lychee), a photo management system.

## Features

## Installation

Requirements :
- FUSE and FUSE headers (`fuse` + `libfuse-dev` on Debian-like, `fuse3` on Arch)

[PEP 517](https://www.python.org/dev/peps/pep-0517/) is used to specify the build system (`setuptools`) so there is no need for `setup.py`.
Simply use `pip>19` and :

```bash
pip install .
```

The script will be installed in `$HOME/.local/bin`, unless you run the command as superuser, in which case it will be installed in `/usr/local/bin`.

To uninstall, simply :

```bash
pip uninstall lychee_fuse
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
Usage: lychee_fuse.py [mountpoint] [options]

Options:
    -h, --help             show this help message and exit
    -o opt,[opt...]        mount options
    -c FILE, --config=FILE
                           path to the configuration file [default:
                           settings.ini]
    -i INSTANCE, --instance=INSTANCE
                           section to use in the configuration file [default:
                           first section of configuration]
```

Example :

```bash
lychee_fuse.py -i pi /mnt/lychee
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
