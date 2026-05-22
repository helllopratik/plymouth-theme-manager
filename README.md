# Plymouth Theme Manager

Modern GTK4 desktop app for managing the visual boot experience on Linux:
Plymouth boot animations, GRUB background images, and full GRUB themes.

## Features

- View, preview, apply, and delete installed Plymouth themes from `/usr/share/plymouth/themes`
- Install Plymouth themes from GitHub search results, direct URLs, or local archives
- Change the GRUB menu background image with PNG, JPG, JPEG, or TGA files
- Install and apply complete GRUB themes from GitHub, local archives, or extracted folders
- Search GRUB themes by name from GitHub or Pling/OpenDesktop
- Paste GitHub repository URLs and let the app resolve the default branch archive automatically
- Paste Pling/OpenDesktop product links and let the app resolve the direct download link when available
- Detect collection archives and install every Plymouth or GRUB theme found inside them
- Save online downloads to `~/Downloads/Plymouth Theme Manager` so the archive/image path is visible
- Ask for admin authorization once per app session, then reuse a constrained root helper for system changes
- Keep GRUB background-only mode simple by disabling `GRUB_THEME` when applying a plain background
- Check for app updates from GitHub Releases first, then Git tags
- Configure a safe display-manager delay for testing boot animations
- Modern GTK4 interface with quick import and online discovery pages

## Requirements

- Linux distribution with Plymouth and GRUB
- Python 3
- GTK 4 Python bindings (`gi`)
- `requests`
- `pkexec`/polkit access for privileged system writes
- `unzip` and tar support
- `update-grub` or `grub-mkconfig`

## Install dependencies

Use the included installer:

```bash
python3 install.py
```

Or install manually on Ubuntu/Debian:

```bash
sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-requests plymouth plymouth-themes grub-common policykit-1 unzip
```

## Run from source

```bash
python3 plymouth-theme-manager.py
```

## Build a Debian package

```bash
./packaging/build-deb.sh
```

The generated package is written to `dist/`.

Install it with:

```bash
sudo apt install ./dist/plymouth-theme-manager_2.0.1_all.deb
```

After package installation, launch it from your app menu or run:

```bash
plymouth-theme-manager
```

## Update checks

The app checks `hellopratik/plymouth-theme-manager` by default:

1. `https://api.github.com/repos/<owner>/<repo>/releases/latest`
2. `https://api.github.com/repos/<owner>/<repo>/tags`

To check a fork or custom repository, change the repository in the Updates page
or start the app with:

```bash
PLYMOUTH_THEME_MANAGER_UPDATE_REPO=owner/repo plymouth-theme-manager
```

Use semantic tags such as `v2.1.0` so the app can compare versions cleanly.

## Notes

- The first system-changing action starts a `pkexec` helper. After you approve it, the same helper is reused until the app exits.
- Applying Plymouth themes rebuilds initramfs with `update-initramfs -u`.
- Applying GRUB backgrounds or themes updates `/etc/default/grub`, creates a timestamped backup beside it, then runs `update-grub` or `grub-mkconfig`.
- If the helper exits or authorization is cancelled, the next system-changing action asks again.
- Reboot after applying Plymouth or GRUB changes to verify the result.
