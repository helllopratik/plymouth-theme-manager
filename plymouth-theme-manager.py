#!/usr/bin/env python3
import gi
import os
import subprocess
import requests
import tempfile
import threading
import shutil
import glob
import time

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Gio, Gdk

# ==========================================================
# CONFIG & BACKEND (V2 LOGIC)
# ==========================================================

THEME_BASE = "/usr/share/plymouth/themes"
PROTECTED = {"text", "ubuntu-text", "details", "script", "spinner", "bgrt", "default.plymouth"}

def get_installed_themes():
    themes = []
    if os.path.exists(THEME_BASE):
        for item in os.listdir(THEME_BASE):
            if item in PROTECTED: continue
            path = os.path.join(THEME_BASE, item)
            if os.path.isdir(path) and glob.glob(os.path.join(path, "*.plymouth")):
                themes.append((item, path))
    return sorted(themes)

# ==========================================================
# UI COMPONENTS
# ==========================================================

class OnlineRow(Gtk.ListBoxRow):
    def __init__(self, item, download_callback):
        super().__init__(selectable=False)
        self.item = item
        self.download_callback = download_callback
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        # Explicit margins for older GTK4 versions
        self.box.set_margin_start(10); self.box.set_margin_end(10)
        self.box.set_margin_top(10); self.box.set_margin_bottom(10)
        
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        name_lbl = Gtk.Label(label=f"<b>{item['name']}</b>", xalign=0, use_markup=True)
        author_lbl = Gtk.Label(label=f"by {item['author']}", xalign=0)
        author_lbl.add_css_class("caption")
        text_box.append(name_lbl); text_box.append(author_lbl)
        
        self.prog_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.progress = Gtk.ProgressBar(visible=False, show_text=True)
        self.speed_lbl = Gtk.Label(label="", xalign=1)
        self.prog_box.append(self.progress); self.prog_box.append(self.speed_lbl)
        
        self.install_btn = Gtk.Button(label="Install")
        self.install_btn.connect("clicked", lambda b: self.start_dl(b))
        
        self.box.append(text_box); self.box.append(self.prog_box); self.box.append(self.install_btn)
        self.set_child(self.box)

    def start_dl(self, btn):
        btn.set_sensitive(False)
        self.progress.set_visible(True)
        self.download_callback(self.item, self)

    def update_progress(self, fraction, speed_text):
        GLib.idle_add(self.progress.set_fraction, fraction)
        GLib.idle_add(self.progress.set_text, f"{int(fraction * 100)}%")
        GLib.idle_add(self.speed_lbl.set_text, speed_text)

# ==========================================================
# MAIN APPLICATION
# ==========================================================

class ThemeManager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.plymouth.pro.v11")

    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title("Plymouth Pro Manager")
        self.win.set_default_size(950, 700)

        hb = Gtk.HeaderBar()
        manual_btn = Gtk.Button(label="Manual Install (.zip)")
        manual_btn.connect("clicked", self.on_manual_install)
        hb.pack_start(manual_btn)
        self.win.set_titlebar(hb)

        self.notebook = Gtk.Notebook()
        self.notebook.append_page(self.create_installed_tab(), Gtk.Label(label="Themes"))
        self.notebook.append_page(self.create_online_tab(), Gtk.Label(label="Online"))
        self.notebook.append_page(self.create_settings_tab(), Gtk.Label(label="Safe Delay"))

        self.win.set_child(self.notebook)
        self.win.present()
        self.refresh_installed()
        self.perform_search("")

    def create_installed_tab(self):
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=300)
        scroller = Gtk.ScrolledWindow()
        self.installed_list = Gtk.ListBox()
        self.installed_list.connect("row-selected", self.on_row_selected)
        scroller.set_child(self.installed_list)
        paned.set_start_child(scroller)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(20); box.set_margin_end(20); box.set_margin_top(20); box.set_margin_bottom(20)

        self.preview_img = Gtk.Image(pixel_size=350)
        box.append(self.preview_img)

        btn_box = Gtk.Box(spacing=10)
        self.apply_btn = Gtk.Button(label="Apply Theme", sensitive=False)
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self.on_apply_clicked)
        
        self.details_btn = Gtk.Button(label="Details", sensitive=False)
        self.details_btn.connect("clicked", self.on_details_clicked)

        self.delete_btn = Gtk.Button(label="Delete", sensitive=False)
        self.delete_btn.add_css_class("destructive-action")
        self.delete_btn.connect("clicked", self.on_delete_clicked)

        btn_box.append(self.apply_btn); btn_box.append(self.details_btn); btn_box.append(self.delete_btn)
        box.append(btn_box)
        self.status_lbl = Gtk.Label(label="Ready", wrap=True)
        box.append(self.status_lbl)
        paned.set_end_child(box)
        return paned

    def create_online_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        # Fixed set_margin_all replacement
        vbox.set_margin_start(15); vbox.set_margin_end(15); vbox.set_margin_top(15); vbox.set_margin_bottom(15)
        
        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.connect("search-changed", lambda e: self.perform_search(e.get_text()))
        self.search_progress = Gtk.ProgressBar(visible=False)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.online_list = Gtk.ListBox()
        scroller.set_child(self.online_list)
        vbox.append(self.search_entry); vbox.append(self.search_progress); vbox.append(scroller)
        return vbox

    def create_settings_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        vbox.set_margin_start(40); vbox.set_margin_end(40); vbox.set_margin_top(40); vbox.set_margin_bottom(40)

        vbox.append(Gtk.Label(label="<b>Safe Boot Delay (Systemd)</b>", use_markup=True, xalign=0))
        vbox.append(Gtk.Label(label="This method safely pauses the login screen to show your animation. It does NOT touch GRUB.", xalign=0, wrap=True))

        adj = Gtk.Adjustment(lower=0, upper=20, step_increment=1, value=0)
        self.delay_spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        
        row = Gtk.Box(spacing=15)
        row.append(Gtk.Label(label="Delay Seconds:")); row.append(self.delay_spin); vbox.append(row)

        save_btn = Gtk.Button(label="Apply Safe Delay")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save_safe_delay)
        vbox.append(save_btn)
        return vbox

    # --- SAFE DELAY ---

    def on_save_safe_delay(self, btn):
        sec = int(self.delay_spin.get_value())
        def worker():
            override_dir = "/etc/systemd/system/display-manager.service.d"
            conf_file = f"{override_dir}/delay.conf"
            content = f"[Service]\nExecStartPre=/bin/sleep {sec}\n"
            try:
                subprocess.run(["pkexec", "mkdir", "-p", override_dir], check=True)
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
                    tf.write(content); tmp_name = tf.name
                subprocess.run(["pkexec", "mv", tmp_name, conf_file], check=True)
                subprocess.run(["pkexec", "systemctl", "daemon-reload"], check=True)
                GLib.idle_add(self.show_msg, "Success", f"Safe delay of {sec}s applied!")
            except Exception as e: GLib.idle_add(self.show_msg, "Error", str(e))
        threading.Thread(target=worker, daemon=True).start()

    # --- THEME APPLY ---

    def on_apply_clicked(self, btn):
        name, path = self.selected_theme
        def worker():
            GLib.idle_add(self.status_lbl.set_text, "Updating Initramfs... Please wait.")
            ply = glob.glob(os.path.join(path, "*.plymouth"))[0]
            subprocess.run(["pkexec", "update-alternatives", "--install", f"{THEME_BASE}/default.plymouth", "default.plymouth", ply, "100"])
            subprocess.run(["pkexec", "update-alternatives", "--set", "default.plymouth", ply])
            subprocess.run(["pkexec", "update-initramfs", "-u"])
            GLib.idle_add(self.status_lbl.set_text, "Theme applied! Reboot to see.")
        threading.Thread(target=worker, daemon=True).start()

    # --- ONLINE & SEARCH ---

    def perform_search(self, q):
        self.search_progress.set_visible(True)
        def worker():
            try:
                term = f"{q} topic:plymouth-theme" if q else "plymouth theme"
                r = requests.get("https://api.github.com/search/repositories", params={"q": term, "sort": "stars"}, timeout=10)
                items = r.json().get("items", [])
                res = [{"name": i["name"], "author": i["owner"]["login"], "zip": f"{i['html_url']}/archive/refs/heads/{i['default_branch']}.zip"} for i in items]
                GLib.idle_add(self.update_online_ui, res)
            except: GLib.idle_add(self.update_online_ui, [])
        threading.Thread(target=worker, daemon=True).start()

    def update_online_ui(self, res):
        self.search_progress.set_visible(False)
        while child := self.online_list.get_first_child(): self.online_list.remove(child)
        for i in res: self.online_list.append(OnlineRow(i, self.start_download))

    def start_download(self, item, row):
        def worker():
            try:
                start = time.time(); r = requests.get(item['zip'], stream=True)
                total = int(r.headers.get('content-length', 0)); dl = 0
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk); dl += len(chunk)
                            if total > 0: row.update_progress(dl/total, f"{(dl/1024)/(time.time()-start):.1f} KB/s")
                    path = f.name
                self.extract_and_install(path)
                GLib.idle_add(self.refresh_installed)
            except: pass
        threading.Thread(target=worker, daemon=True).start()

    def extract_and_install(self, zip_path):
        tmp = os.path.join(tempfile.gettempdir(), f"ply_v11_{time.time()}")
        subprocess.run(["unzip", "-o", zip_path, "-d", tmp], check=True)
        for root, _, files in os.walk(tmp):
            if any(f.endswith(".plymouth") for f in files):
                ply = [f for f in files if f.endswith(".plymouth")][0]
                tid = os.path.splitext(ply)[0]; dest = f"{THEME_BASE}/{tid}"
                subprocess.run(["pkexec", "mkdir", "-p", dest], check=True)
                subprocess.run(["pkexec", "cp", "-r", f"{root}/.", dest], check=True)
                break
        shutil.rmtree(tmp); os.remove(zip_path)

    # --- UI HELPERS ---

    def on_row_selected(self, lb, row):
        if not row: return
        self.selected_theme = row.data
        self.apply_btn.set_sensitive(True); self.delete_btn.set_sensitive(True); self.details_btn.set_sensitive(True)
        for f in os.listdir(row.data[1]):
            if f.lower().endswith((".png", ".jpg")):
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(row.data[1], f), 450, 350, True)
                self.preview_img.set_from_paintable(Gdk.Texture.new_for_pixbuf(pix)); break

    def on_details_clicked(self, b):
        path = self.selected_theme[1]; readmes = glob.glob(f"{path}/README*")
        content = open(readmes[0]).read() if readmes else "No README available."
        win = Gtk.Window(title="Details", default_width=500, default_height=400)
        sw = Gtk.ScrolledWindow(); sw.set_margin_start(15); sw.set_margin_end(15); sw.set_margin_top(15); sw.set_margin_bottom(15)
        tv = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD); tv.get_buffer().set_text(content)
        sw.set_child(tv); win.set_child(sw); win.present()

    def refresh_installed(self):
        while child := self.installed_list.get_first_child(): self.installed_list.remove(child)
        for name, path in get_installed_themes():
            r = Gtk.ListBoxRow(); r.data = (name, path)
            lbl = Gtk.Label(label=name, xalign=0); lbl.set_margin_start(10); lbl.set_margin_top(10); lbl.set_margin_bottom(10)
            r.set_child(lbl); self.installed_list.append(r)

    def on_manual_install(self, b):
        d = Gtk.FileDialog(); d.open(self.win, None, lambda o, r: self.extract_and_install(d.open_finish(r).get_path()) or self.refresh_installed())

    def on_delete_clicked(self, b):
        if len(get_installed_themes()) > 1: subprocess.run(f"pkexec rm -rf '{self.selected_theme[1]}'", shell=True); self.refresh_installed()

    def show_msg(self, title, msg):
        m = Gtk.MessageDialog(transient_for=self.win, text=title, buttons=Gtk.ButtonsType.OK)
        m.set_markup(msg); m.connect("response", lambda d, r: d.destroy()); m.present()

if __name__ == "__main__":
    app = ThemeManager(); app.run(None)