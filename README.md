# Linux Ramdisk Manager

A GTK3 desktop app for managing Linux ramdisks (tmpfs mounts) — create, unmount, delete, clear and resize ramdisks, and copy data to and from RAM, all without touching the terminal.

![Status: Linux-only](https://img.shields.io/badge/platform-Linux-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Ramdisk management** — create, unmount, delete, clear and resize tmpfs mounts
- **rsync integration** — copy directories to RAM or back to disk with live progress output
- **Live overview** — auto-refreshing list of all active tmpfs mounts with usage bars
- **Multi-language** — English and German, switchable in the app with system language auto-detection

## Requirements

System packages (Debian/Ubuntu/Mint):

```
sudo apt install python3-gi gir1.2-gtk-3.0 rsync
```

Fedora:
```
sudo dnf install python3-gobject gtk3 rsync
```

Arch:
```
sudo pacman -S python-gobject gtk3 rsync
```

`sudo` access is required for mount/umount operations.

## Installation

```
git clone https://github.com/NoCoderGHG/ramdisk-manager.git
cd ramdisk-manager
python3 ramdisk_manager.py
```

No pip dependencies. No virtual environment needed.

## Configuration

Language preference is stored in `~/.config/ramdisk-manager/config.json`.

## License

MIT — see [LICENSE](LICENSE).
