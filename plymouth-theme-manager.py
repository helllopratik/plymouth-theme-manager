#!/usr/bin/env python3

import gi
import os
import subprocess
import zipfile
import requests
import tempfile
import json
import threading
import shutil

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


# ==========================================================
# CONFIG
# ==========================================================

THEME_PATHS = [
    "/usr/share/plymouth/themes",
    "/lib/plymouth/themes"
]

ONLINE_INDEX = "themes.json"  # local JSON store

EXCLUDE_THEMES = {
    "text",
    "ubuntu-text",
    "details",
    "script"
}


# ==========================================================
# BACKEND FUNCTIONS
# ==========================================================

def get_theme_dirs():
    themes = []

    for base_path in THEME_PATHS:
        if not os.path.exists(base_path):
            continue

        for item in os.listdir(base_path):

            if item.lower() in EXCLUDE_THEMES:
                continue

            theme_path = os.path.join(base_path, item)

            if not os.path.isdir(theme_path):
                continue

            plymouth_files = [
                f for f in os.listdir(theme_path)
                if f.endswith(".plymouth")
            ]

            if not plymouth_files:
                continue

            assets = os.listdir(theme_path)

            has_graphics = any(
                f.endswith((".png", ".jpg", ".jpeg", ".svg"))
                for f in assets
            )

            if has_graphics:
                themes.append((item, theme_path))

    return sorted(themes, key=lambda x: x[0].lower())


import shutil

def apply_theme(theme):
    
    theme_file = f"/usr/share/plymouth/themes/{theme}/{theme}.plymouth"

    if not os.path.exists(theme_file):
        print("Theme file missing")
        return

    # Try modern method
    subprocess.run([
        "pkexec",
        "update-alternatives",
        "--set",
        "default.plymouth",
        theme_file
    ])

    # Rebuild initramfs
    subprocess.run([
        "pkexec",
        "update-initramfs",
        "-u"
    ])






def import_theme(zip_path):
    
    with tempfile.TemporaryDirectory() as tmp:

        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(tmp)

        for root, dirs, files in os.walk(tmp):

            # Look for .plymouth file
            if any(f.endswith(".plymouth") for f in files):

                subprocess.run([
                    "pkexec",
                    "cp",
                    "-r",
                    root,
                    "/usr/share/plymouth/themes/"
                ])

                return


def fetch_online_themes():
    try:
        with open(ONLINE_INDEX) as f:
            return json.load(f)
    except:
        return []


def download_and_install(url):

    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        data = requests.get(url).content
        tmp.write(data)
        tmp.flush()
        import_theme(tmp.name)


# ==========================================================
# GUI
# ==========================================================

class ThemeManager(Gtk.Application):

    def __init__(self):
        super().__init__(application_id="com.plymouth.manager")

    # ------------------------------------------------------

    def do_activate(self):

        win = Gtk.ApplicationWindow(application=self)
        win.set_title("Plymouth Theme Manager")
        win.set_default_size(900, 500)

        notebook = Gtk.Notebook()

        # ---------------- INSTALLED TAB ----------------

        installed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self.listbox = Gtk.ListBox()
        self.populate_installed()

        apply_btn = Gtk.Button(label="Apply Selected Theme")
        apply_btn.connect("clicked", self.on_apply)

        import_btn = Gtk.Button(label="Import Theme ZIP")
        import_btn.connect("clicked", self.on_import)

        installed_box.append(self.listbox)
        installed_box.append(apply_btn)
        installed_box.append(import_btn)

        notebook.append_page(installed_box, Gtk.Label(label="Installed"))

        # ---------------- ONLINE TAB ----------------

        online_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self.online_list = Gtk.ListBox()
        self.populate_online()

        online_box.append(self.online_list)

        notebook.append_page(online_box, Gtk.Label(label="Online"))

        win.set_child(notebook)
        win.present()

    # ------------------------------------------------------

    def populate_installed(self):

        for theme, path in get_theme_dirs():

            row = Gtk.ListBoxRow()
            row.theme_name = theme

            row.set_child(Gtk.Label(label=theme))

            self.listbox.append(row)

    # ------------------------------------------------------

    def populate_online(self):

        themes = fetch_online_themes()

        for t in themes:

            row = Gtk.ListBoxRow()

            box = Gtk.Box(spacing=10)

            label = Gtk.Label(label=t.get("name", "Unknown"))

            btn = Gtk.Button(label="Download & Install")
            btn.connect("clicked", self.on_download, t.get("download"))

            box.append(label)
            box.append(btn)

            row.set_child(box)
            self.online_list.append(row)

    # ------------------------------------------------------

    def on_apply(self, btn):

        row = self.listbox.get_selected_row()

        if not row:
            self.show_message("Please select a theme first.")
            return

        theme = row.theme_name

        apply_theme(theme)

        self.show_message(f"Theme '{theme}' applied successfully.")

    # ------------------------------------------------------

def on_import(self, btn):
    
    dialog = Gtk.FileChooserNative(
        title="Select Plymouth Theme ZIP",
        transient_for=self.get_active_window(),
        modal=True,
        action=Gtk.FileChooserAction.OPEN,
        accept_label="Import",
        cancel_label="Cancel"
    )

    # File filter
    filter_zip = Gtk.FileFilter()
    filter_zip.set_name("ZIP files")
    filter_zip.add_pattern("*.zip")

    dialog.set_filter(filter_zip)

    dialog.connect("response", self.on_import_response)

    dialog.show() 



    # ------------------------------------------------------

    def on_import_response(self, dialog, response):

        if response == Gtk.ResponseType.ACCEPT:

            file = dialog.get_file()

            if file:
                path = file.get_path()
                import_theme(path)

                # Refresh list
                self.listbox.remove_all()
                self.populate_installed()

        dialog.destroy()

    # ------------------------------------------------------

    def on_download(self, btn, url):
        self.show_message("Downloading and installing theme…")

        threading.Thread(
            target=self.download_worker,
            args=(url,),
            daemon=True
        ).start()

        self.listbox.remove_all()
        self.populate_installed()

    def download_worker(self, url):
        try:
            download_and_install(url)
            GLib.idle_add(self.refresh_installed)
        except Exception as e:
            print(f"Error downloading theme: {e}")
        
    
    def refresh_installed(self):
        self.listbox.remove_all()
        self.populate_installed()
    # ------------------------------------------------------

    def show_message(self, text):
        win = self.get_active_window()

        dialog = Gtk.MessageDialog(
            transient_for=self.get_active_window(),
            modal=True,
            buttons=Gtk.ButtonsType.OK,
            message_type=Gtk.MessageType.INFO,
            text=text
        )

        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()



# ==========================================================
# RUN
# ==========================================================

app = ThemeManager()
app.run()