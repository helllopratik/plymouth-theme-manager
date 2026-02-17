# ==============================
# Script 1: install_dependencies.py
# ==============================

#!/usr/bin/env python3

import os
import subprocess
import shutil
from pathlib import Path

print("Plymouth Theme Manager — Dependency Installer\n")

# Detect package manager
if shutil.which("apt"):
    PKG_INSTALL = ["sudo", "apt", "install", "-y"]
    packages = [
        "python3-gi",
        "python3-gi-cairo",
        "gir1.2-gtk-4.0",
        "python3-requests",
        "plymouth",
        "plymouth-themes"
    ]

elif shutil.which("dnf"):
    PKG_INSTALL = ["sudo", "dnf", "install", "-y"]
    packages = [
        "python3-gobject",
        "gtk4",
        "python3-requests",
        "plymouth",
        "plymouth-system-theme"
    ]

elif shutil.which("pacman"):
    PKG_INSTALL = ["sudo", "pacman", "-S", "--noconfirm"]
    packages = [
        "python-gobject",
        "gtk4",
        "python-requests",
        "plymouth"
    ]

else:
    print("Unsupported distro. Install dependencies manually.")
    exit(1)

print("Installing dependencies...\n")

subprocess.run(PKG_INSTALL + packages)

print("\nDone.")
print("You can now run: python3 plymouth_theme_manager.py")

# Install desktop launcher
desktop_src = Path(__file__).resolve().parent / "plymouth-theme-manager.desktop"
desktop_dst_dir = Path.home() / ".local" / "share" / "applications"
desktop_dst = desktop_dst_dir / "plymouth-theme-manager.desktop"

if desktop_src.exists():
    desktop_dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(desktop_src, desktop_dst)
    os.chmod(desktop_dst, 0o755)
    print(f"Desktop launcher installed: {desktop_dst}")
else:
    print("Desktop launcher not installed: plymouth-theme-manager.desktop not found.")
