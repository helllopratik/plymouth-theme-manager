# Plymouth Theme Manager

GTK4 desktop app to install, preview, apply, and remove Plymouth boot themes on Linux.

## Features

- View installed Plymouth themes from `/usr/share/plymouth/themes`
- Preview theme screenshots when available
- Apply selected theme using `update-alternatives` + `update-initramfs`
- Install themes from GitHub (search + one-click install)
- Manually install themes from a local `.zip`
- Read included theme `README` details
- Delete installed themes (keeps at least one theme)
- Configure a safe display-manager delay via systemd override

## Requirements

- Linux distribution with Plymouth
- Python 3
- GTK 4 Python bindings (`gi`)
- `requests`
- `pkexec` access for privileged operations
- `unzip`

## Install dependencies

Use the included installer:

```bash
python3 install.py
```

Or install manually:

- Ubuntu/Debian:
```bash
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-requests plymouth plymouth-themes unzip
```
- Fedora:
```bash
sudo dnf install -y python3-gobject gtk4 python3-requests plymouth plymouth-system-theme unzip
```
- Arch:
```bash
sudo pacman -S --noconfirm python-gobject gtk4 python-requests plymouth unzip
```

## Run

From this repository:

```bash
python3 plymouth-theme-manager.py
```

## Desktop launcher

This repo includes `plymouth-theme-manager.desktop`.

1. Edit the `Exec` path in the file so it matches your local repository path.
2. (Optional) set a custom icon path in `Icon`.
3. Install launcher:

```bash
mkdir -p ~/.local/share/applications
cp plymouth-theme-manager.desktop ~/.local/share/applications/
chmod +x ~/.local/share/applications/plymouth-theme-manager.desktop
```

## Notes

- Applying/deleting themes and safe delay changes require admin authentication.
- Reboot after applying a theme to verify the boot animation.
