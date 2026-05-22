#!/usr/bin/env python3
import gi
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


APP_ID = "com.plymouth.theme.manager"
APP_NAME = "Plymouth Theme Manager"
APP_VERSION = "2.0.1"
ROOT_HELPER_FLAG = "--root-helper"
UPDATE_REPO = os.environ.get(
    "PLYMOUTH_THEME_MANAGER_UPDATE_REPO",
    "hellopratik/plymouth-theme-manager",
)

THEME_BASE = "/usr/share/plymouth/themes"
PROTECTED_PLYMOUTH = {
    "text",
    "ubuntu-text",
    "details",
    "script",
    "spinner",
    "bgrt",
    "default.plymouth",
}

GRUB_DEFAULT = "/etc/default/grub"
GRUB_THEME_BASE = "/boot/grub/themes"
GRUB_BACKGROUND_DIR = "/boot/grub/backgrounds/plymouth-theme-manager"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga"}
DOWNLOAD_DIR = Path.home() / "Downloads" / "Plymouth Theme Manager"
ADMIN_SESSION = None

CSS = """
window {
  background: #101419;
  color: #edf3f7;
}

headerbar {
  background: rgba(20, 25, 32, 0.92);
  color: #edf3f7;
  border-bottom: 1px solid rgba(255, 255, 255, 0.10);
}

.app-shell {
  background-image: linear-gradient(135deg, #111820 0%, #17151f 45%, #10201c 100%);
}

.side-rail {
  background: rgba(255, 255, 255, 0.07);
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}

.brand-title {
  font-size: 22px;
  font-weight: 800;
}

.brand-subtitle, .muted {
  color: rgba(237, 243, 247, 0.68);
}

.page-title {
  font-size: 26px;
  font-weight: 800;
}

.section-title {
  font-size: 17px;
  font-weight: 800;
}

.glass-card {
  background: rgba(255, 255, 255, 0.085);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 18px;
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.22);
}

.soft-card {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 14px;
}

.accent-card {
  background-image: linear-gradient(135deg, rgba(77, 201, 255, 0.20), rgba(54, 211, 153, 0.15));
  border: 1px solid rgba(143, 232, 213, 0.28);
  border-radius: 18px;
}

.danger-card {
  background: rgba(255, 100, 110, 0.12);
  border: 1px solid rgba(255, 150, 160, 0.25);
  border-radius: 14px;
}

.rich-row {
  border-radius: 12px;
  margin: 4px;
  padding: 8px;
}

.rich-row:hover {
  background: rgba(255, 255, 255, 0.08);
}

.rich-row:selected {
  background: rgba(77, 201, 255, 0.19);
}

.badge {
  background: rgba(54, 211, 153, 0.16);
  border: 1px solid rgba(54, 211, 153, 0.34);
  color: #bff8df;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 700;
}

.warning-badge {
  background: rgba(255, 196, 87, 0.16);
  border: 1px solid rgba(255, 196, 87, 0.34);
  color: #ffe2a3;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 700;
}

button {
  border-radius: 10px;
}

entry, searchentry, spinbutton, dropdown {
  border-radius: 10px;
}

progressbar trough {
  border-radius: 999px;
}

progressbar progress {
  border-radius: 999px;
  background: #36d399;
}
"""


def set_margins(widget, value):
    widget.set_margin_start(value)
    widget.set_margin_end(value)
    widget.set_margin_top(value)
    widget.set_margin_bottom(value)


def add_margins(widget, horizontal=0, vertical=0):
    widget.set_margin_start(horizontal)
    widget.set_margin_end(horizontal)
    widget.set_margin_top(vertical)
    widget.set_margin_bottom(vertical)


def label(text, css_class=None, xalign=0, wrap=False, markup=False):
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, use_markup=markup)
    if css_class:
        widget.add_css_class(css_class)
    return widget


def safe_name(value, fallback="theme"):
    base = Path(str(value)).name.strip()
    if not base:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-_").lower()
    return cleaned[:80] or fallback


def escape_grub_value(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def version_key(version):
    parts = re.findall(r"\d+", version or "")
    return tuple(int(part) for part in parts[:4]) or (0,)


def is_newer_version(latest, current):
    latest_key = version_key(latest)
    current_key = version_key(current)
    max_len = max(len(latest_key), len(current_key))
    latest_key += (0,) * (max_len - len(latest_key))
    current_key += (0,) * (max_len - len(current_key))
    return latest_key > current_key


def summarize_names(names, singular="theme", plural="themes"):
    if isinstance(names, str):
        names = [names]
    names = list(names or [])
    if not names:
        return f"No {plural} installed."
    if len(names) == 1:
        return f"Installed {singular}: {names[0]}"
    preview = ", ".join(names[:10])
    if len(names) > 10:
        preview += f", +{len(names) - 10} more"
    return f"Installed {len(names)} {plural}: {preview}"


def find_command(*names):
    candidates = []
    for name in names:
        candidates.append(name)
        candidates.append(f"/usr/sbin/{name}")
        candidates.append(f"/sbin/{name}")
    for candidate in candidates:
        path = shutil.which(candidate) if "/" not in candidate else candidate
        if path and os.path.exists(path):
            return path
    return None


def get_installed_themes():
    themes = []
    if os.path.exists(THEME_BASE):
        for item in os.listdir(THEME_BASE):
            if item in PROTECTED_PLYMOUTH:
                continue
            path = os.path.join(THEME_BASE, item)
            if os.path.isdir(path) and glob.glob(os.path.join(path, "*.plymouth")):
                themes.append((item, path))
    return sorted(themes, key=lambda item: item[0].lower())


def current_plymouth_theme_path():
    default_path = os.path.join(THEME_BASE, "default.plymouth")
    if os.path.exists(default_path):
        try:
            return os.path.realpath(default_path)
        except OSError:
            return None
    return None


def is_current_plymouth_theme(path):
    current = current_plymouth_theme_path()
    if not current:
        return False
    for plymouth_file in glob.glob(os.path.join(path, "*.plymouth")):
        if os.path.realpath(plymouth_file) == current:
            return True
    return False


def get_installed_grub_themes():
    themes = []
    if not os.path.exists(GRUB_THEME_BASE):
        return themes
    for root, dirs, files in os.walk(GRUB_THEME_BASE):
        if "theme.txt" in files:
            theme_path = os.path.join(root, "theme.txt")
            themes.append((Path(root).name, theme_path, root))
            dirs[:] = []
    return sorted(themes, key=lambda item: item[0].lower())


def read_grub_default():
    try:
        with open(GRUB_DEFAULT, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return "# Created by Plymouth Theme Manager\n"
    except PermissionError:
        return ""


def get_grub_value(option):
    content = read_grub_default()
    pattern = re.compile(rf"^\s*{re.escape(option)}=(.*)$", re.MULTILINE)
    match = pattern.search(content)
    if not match:
        return ""
    return strip_quotes(match.group(1))


def get_update_grub_command():
    update_grub = find_command("update-grub")
    if update_grub:
        return [update_grub]
    grub_mkconfig = find_command("grub-mkconfig")
    if grub_mkconfig:
        return [grub_mkconfig, "-o", "/boot/grub/grub.cfg"]
    raise RuntimeError("Could not find update-grub or grub-mkconfig.")


def run_root_process(command):
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"Command failed: {' '.join(command)}")
    return completed.stdout.strip()


def ensure_inside(path, base, allow_base=False):
    real_path = os.path.realpath(path)
    real_base = os.path.realpath(base)
    if allow_base and real_path == real_base:
        return real_path
    if not real_path.startswith(real_base + os.sep):
        raise RuntimeError(f"Refusing to modify path outside {base}: {path}")
    return real_path


def write_grub_options_root(updates):
    content = read_grub_default()
    lines = content.splitlines()
    seen = set()
    new_lines = []
    pattern = re.compile(r"^\s*#?\s*(GRUB_[A-Z0-9_]+)=")

    for line in lines:
        match = pattern.match(line)
        if match and match.group(1) in updates:
            option = match.group(1)
            new_lines.append(f'{option}="{escape_grub_value(updates[option])}"')
            seen.add(option)
        else:
            new_lines.append(line)

    for option, value in updates.items():
        if option not in seen:
            new_lines.append(f'{option}="{escape_grub_value(value)}"')

    fd, tmp_path = tempfile.mkstemp(prefix="boot-theme-grub-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(new_lines).rstrip() + "\n")

        if os.path.exists(GRUB_DEFAULT):
            backup = f"{GRUB_DEFAULT}.plymouth-theme-manager-{int(time.time())}.bak"
            shutil.copy2(GRUB_DEFAULT, backup)
        shutil.copy2(tmp_path, GRUB_DEFAULT)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


def set_grub_options(updates):
    return admin_request("set_grub_options", {"updates": updates})


def run_grub_update():
    return admin_request("update_grub", {})


def copy_theme_root(source, destination, base):
    ensure_inside(destination, base)
    if not os.path.isdir(source):
        raise RuntimeError(f"Theme folder not found: {source}")
    os.makedirs(base, exist_ok=True)
    if os.path.exists(destination):
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def root_install_plymouth_theme(payload):
    source = payload["source"]
    theme_id = safe_name(payload["theme_id"], "plymouth-theme")
    destination = os.path.join(THEME_BASE, theme_id)
    copy_theme_root(source, destination, THEME_BASE)
    return theme_id


def root_install_grub_theme(payload):
    source = payload["source"]
    theme_id = safe_name(payload["theme_id"], "grub-theme")
    destination = os.path.join(GRUB_THEME_BASE, theme_id)
    copy_theme_root(source, destination, GRUB_THEME_BASE)
    installed_theme = os.path.join(destination, "theme.txt")
    if not os.path.exists(installed_theme):
        raise RuntimeError("Installed GRUB theme has no theme.txt.")
    if payload.get("apply", True):
        write_grub_options_root({"GRUB_THEME": installed_theme})
        run_root_process(get_update_grub_command())
    return theme_id


def root_install_grub_background(payload):
    image_path = payload["image"]
    extension = Path(image_path).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        raise RuntimeError("GRUB background images must be PNG, JPG, JPEG, or TGA.")
    destination_name = safe_name(payload["dest_name"], "background") + extension
    destination = os.path.join(GRUB_BACKGROUND_DIR, destination_name)
    ensure_inside(destination, GRUB_BACKGROUND_DIR)
    os.makedirs(GRUB_BACKGROUND_DIR, exist_ok=True)
    shutil.copy2(image_path, destination)
    updates = {"GRUB_BACKGROUND": destination}
    if payload.get("disable_theme", True):
        updates["GRUB_THEME"] = ""
    write_grub_options_root(updates)
    run_root_process(get_update_grub_command())
    return destination


def root_apply_plymouth(payload):
    plymouth_file = payload["plymouth_file"]
    ensure_inside(plymouth_file, THEME_BASE)
    if not os.path.exists(plymouth_file):
        raise RuntimeError(f"Plymouth file not found: {plymouth_file}")
    run_root_process(
        [
            "update-alternatives",
            "--install",
            os.path.join(THEME_BASE, "default.plymouth"),
            "default.plymouth",
            plymouth_file,
            "100",
        ]
    )
    run_root_process(["update-alternatives", "--set", "default.plymouth", plymouth_file])
    run_root_process(["update-initramfs", "-u"])
    return Path(plymouth_file).stem


def root_delete_plymouth_theme(payload):
    path = ensure_inside(payload["path"], THEME_BASE)
    if os.path.exists(path):
        shutil.rmtree(path)
    return path


def root_delete_grub_theme(payload):
    path = ensure_inside(payload["path"], GRUB_THEME_BASE)
    active_theme = get_grub_value("GRUB_THEME")
    if os.path.exists(path):
        shutil.rmtree(path)
    if active_theme and os.path.realpath(active_theme).startswith(path + os.sep):
        write_grub_options_root({"GRUB_THEME": ""})
        run_root_process(get_update_grub_command())
    return path


def root_safe_delay(payload):
    seconds = max(0, min(20, int(payload["seconds"])))
    override_dir = "/etc/systemd/system/display-manager.service.d"
    conf_file = f"{override_dir}/delay.conf"
    os.makedirs(override_dir, exist_ok=True)
    with open(conf_file, "w", encoding="utf-8") as handle:
        handle.write(f"[Service]\nExecStartPre=/bin/sleep {seconds}\n")
    run_root_process(["systemctl", "daemon-reload"])
    return seconds


def handle_root_command(command, payload):
    if command == "set_grub_options":
        write_grub_options_root(payload["updates"])
        return True
    if command == "update_grub":
        run_root_process(get_update_grub_command())
        return True
    if command == "install_plymouth_theme":
        return root_install_plymouth_theme(payload)
    if command == "install_grub_theme":
        return root_install_grub_theme(payload)
    if command == "install_grub_background":
        return root_install_grub_background(payload)
    if command == "apply_plymouth":
        return root_apply_plymouth(payload)
    if command == "delete_plymouth_theme":
        return root_delete_plymouth_theme(payload)
    if command == "delete_grub_theme":
        return root_delete_grub_theme(payload)
    if command == "safe_delay":
        return root_safe_delay(payload)
    raise RuntimeError(f"Unknown privileged command: {command}")


def root_helper_loop():
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = handle_root_command(request.get("command"), request.get("payload") or {})
            response = {"ok": True, "result": result}
        except Exception as error:
            response = {"ok": False, "error": str(error)}
        print(json.dumps(response), flush=True)


class AdminSession:
    def __init__(self, script_path):
        self.script_path = script_path
        self.process = None
        self.lock = threading.Lock()

    def start(self):
        python_path = sys.executable if os.path.isabs(sys.executable) else shutil.which(sys.executable)
        python_path = python_path or "/usr/bin/python3"
        self.process = subprocess.Popen(
            ["pkexec", python_path, self.script_path, ROOT_HELPER_FLAG],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def request(self, command, payload):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                self.start()
            message = json.dumps({"command": command, "payload": payload})
            try:
                self.process.stdin.write(message + "\n")
                self.process.stdin.flush()
                line = self.process.stdout.readline()
            except BrokenPipeError as error:
                self.process = None
                raise RuntimeError("Admin authorization was cancelled or the helper exited.") from error
            if not line:
                self.process = None
                raise RuntimeError("Admin authorization was cancelled or the helper did not start.")
            response = json.loads(line)
            if not response.get("ok"):
                raise RuntimeError(response.get("error") or "Privileged action failed.")
            return response.get("result")

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.close()
            except Exception:
                pass
            self.process.terminate()
        self.process = None


def admin_request(command, payload):
    if os.geteuid() == 0:
        return handle_root_command(command, payload)
    if ADMIN_SESSION:
        return ADMIN_SESSION.request(command, payload)
    fallback = AdminSession(os.path.abspath(__file__))
    try:
        return fallback.request(command, payload)
    finally:
        fallback.close()


def safe_extract_zip(archive_path, destination):
    destination_root = os.path.abspath(destination)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = os.path.abspath(os.path.join(destination, member.filename))
            if not target.startswith(destination_root + os.sep):
                raise RuntimeError("Archive contains an unsafe path.")
        archive.extractall(destination)


def safe_extract_tar(archive_path, destination):
    destination_root = os.path.abspath(destination)
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            target = os.path.abspath(os.path.join(destination, member.name))
            if not target.startswith(destination_root + os.sep):
                raise RuntimeError("Archive contains an unsafe path.")
        archive.extractall(destination)


def extract_archive(archive_path):
    tmp_dir = tempfile.mkdtemp(prefix="boot-theme-archive-")
    try:
        if zipfile.is_zipfile(archive_path):
            safe_extract_zip(archive_path, tmp_dir)
        elif tarfile.is_tarfile(archive_path):
            safe_extract_tar(archive_path, tmp_dir)
        else:
            raise RuntimeError("Unsupported archive. Use .zip, .tar, .tar.gz, .tgz, .tar.xz, or .tar.bz2.")
        return tmp_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def find_preview_image(folder):
    for root, _, files in os.walk(folder):
        for file_name in sorted(files):
            if Path(file_name).suffix.lower() in IMAGE_EXTENSIONS:
                return os.path.join(root, file_name)
    return None


def find_plymouth_theme_dirs(root):
    matches = []
    for current_root, _, files in os.walk(root):
        plymouth_files = [file_name for file_name in files if file_name.endswith(".plymouth")]
        if plymouth_files:
            matches.append((current_root, sorted(plymouth_files)[0]))
    return matches


def find_plymouth_theme_dir(root):
    matches = find_plymouth_theme_dirs(root)
    if matches:
        return matches[0]
    return None, None


def find_grub_theme_dirs(root):
    matches = []
    for current_root, dirs, files in os.walk(root):
        if "theme.txt" in files:
            matches.append(current_root)
            dirs[:] = []
    return matches


def install_plymouth_archive(archive_path):
    tmp_dir = extract_archive(archive_path)
    try:
        matches = find_plymouth_theme_dirs(tmp_dir)
        if not matches:
            raise RuntimeError("No .plymouth theme file was found in the archive.")

        installed = []
        used = set()
        for theme_dir, theme_file in matches:
            theme_id = safe_name(Path(theme_file).stem, safe_name(Path(theme_dir).name, "plymouth-theme"))
            original_id = theme_id
            counter = 2
            while theme_id in used:
                theme_id = f"{original_id}-{counter}"
                counter += 1
            used.add(theme_id)
            installed.append(admin_request("install_plymouth_theme", {"source": theme_dir, "theme_id": theme_id}))
        return installed
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def install_grub_theme_dir(theme_dir):
    theme_file = os.path.join(theme_dir, "theme.txt")
    if not os.path.exists(theme_file):
        raise RuntimeError("The selected folder does not contain theme.txt.")

    theme_id = safe_name(Path(theme_dir).name, "grub-theme")
    destination = os.path.join(GRUB_THEME_BASE, theme_id)
    if not os.path.realpath(destination).startswith(os.path.realpath(GRUB_THEME_BASE) + os.sep):
        raise RuntimeError("Refusing to install outside the GRUB theme directory.")

    return admin_request("install_grub_theme", {"source": theme_dir, "theme_id": theme_id, "apply": True})


def install_grub_theme_archive(archive_path):
    tmp_dir = extract_archive(archive_path)
    try:
        matches = find_grub_theme_dirs(tmp_dir)
        if not matches:
            raise RuntimeError("No GRUB theme.txt file was found in the archive.")
        installed = []
        used = set()
        for index, theme_dir in enumerate(matches):
            theme_id = safe_name(Path(theme_dir).name, "grub-theme")
            original_id = theme_id
            counter = 2
            while theme_id in used:
                theme_id = f"{original_id}-{counter}"
                counter += 1
            used.add(theme_id)
            installed.append(
                admin_request(
                    "install_grub_theme",
                    {"source": theme_dir, "theme_id": theme_id, "apply": index == 0},
                )
            )
        return installed
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def install_grub_background(image_path, disable_theme=True):
    extension = Path(image_path).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        raise RuntimeError("GRUB background images must be PNG, JPG, JPEG, or TGA.")

    return admin_request(
        "install_grub_background",
        {
            "image": image_path,
            "dest_name": safe_name(Path(image_path).stem, "background"),
            "disable_theme": disable_theme,
        },
    )


def normalize_online_url(url, kind):
    url = url.strip()
    if not url:
        raise RuntimeError("Enter a URL first.")

    parsed = urlparse(url)
    if parsed.netloc in {"www.opendesktop.org", "opendesktop.org", "www.pling.com", "pling.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "p" and kind != "background":
            content = fetch_ocs_content(parts[1])
            download = content.get("downloadlink1")
            if download:
                return download
            raise RuntimeError("This Pling/OpenDesktop item has no direct download link.")

    if parsed.netloc == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 5 and parts[2] == "blob":
            raw_path = "/" + "/".join([parts[0], parts[1], parts[3]] + parts[4:])
            return urlunparse(("https", "raw.githubusercontent.com", raw_path, "", "", ""))
        if len(parts) >= 2 and kind != "background":
            owner, repo = parts[0], parts[1]
            api_url = f"https://api.github.com/repos/{owner}/{repo}"
            response = requests.get(api_url, timeout=12, headers={"User-Agent": APP_NAME})
            response.raise_for_status()
            branch = response.json().get("default_branch", "main")
            return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"

    return url


def fetch_ocs_content(content_id):
    response = requests.get(
        f"https://api.opendesktop.org/ocs/v1/content/data/{content_id}",
        params={"format": "json"},
        timeout=14,
        headers={"User-Agent": APP_NAME},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def search_github_themes(query, kind):
    if kind == "plymouth":
        search = f"{query} plymouth theme" if query else "plymouth theme"
    else:
        search = f"{query} grub theme theme.txt" if query else "grub theme theme.txt"
    response = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": search, "sort": "stars", "per_page": 18},
        timeout=14,
        headers={"User-Agent": APP_NAME},
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("items", []):
        results.append(
            {
                "name": item["name"],
                "author": item["owner"]["login"],
                "description": item.get("description") or "",
                "score": item.get("stargazers_count", 0),
                "score_label": "stars",
                "source": "GitHub",
                "kind": kind,
                "zip": f"{item['html_url']}/archive/refs/heads/{item['default_branch']}.zip",
            }
        )
    return results


def search_pling_grub_themes(query):
    search = query if query else "grub theme"
    response = requests.get(
        "https://api.opendesktop.org/ocs/v1/content/data",
        params={"search": search, "pagesize": 18, "format": "json"},
        timeout=14,
        headers={"User-Agent": APP_NAME},
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("data", []):
        if "grub" not in f"{item.get('typename', '')} {item.get('name', '')}".lower():
            continue
        results.append(
            {
                "name": item.get("name") or f"Pling item {item.get('id')}",
                "author": item.get("personid") or "unknown",
                "description": item.get("summary") or "",
                "score": item.get("downloads") or "0",
                "score_label": "downloads",
                "source": "Pling",
                "kind": "grub",
                "zip": item.get("downloadlink1") or "",
                "page": item.get("detailpage") or f"https://www.opendesktop.org/p/{item.get('id')}",
            }
        )
    return results


def suffix_from_url(url, fallback=".download"):
    suffix = Path(urlparse(url).path).suffix
    if suffix:
        return suffix[:16]
    return fallback


def download_name_from_url(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "github.com" and len(parts) >= 2 and "archive" in parts:
        branch = Path(parsed.path).stem or "download"
        return f"{safe_name(parts[0])}-{safe_name(parts[1])}-{safe_name(branch)}.zip"
    name = Path(parsed.path).name
    if not name or "." not in name:
        name = f"{safe_name(parsed.netloc or 'theme')}{suffix_from_url(url)}"
    return safe_name(name, "theme-download")


def unique_download_path(file_name):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_DIR / file_name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = DOWNLOAD_DIR / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def download_to_downloads(url, progress_callback=None):
    response = requests.get(
        url,
        stream=True,
        timeout=(12, 90),
        headers={"User-Agent": APP_NAME},
    )
    response.raise_for_status()
    download_path = unique_download_path(download_name_from_url(url))
    if progress_callback:
        progress_callback(0.0, f"Saving to {download_path}")
    total = int(response.headers.get("content-length", 0) or 0)
    downloaded = 0
    started = time.time()
    with open(download_path, "wb") as handle:
        for chunk in response.iter_content(1024 * 64):
            if not chunk:
                continue
            handle.write(chunk)
            downloaded += len(chunk)
            if progress_callback and total:
                elapsed = max(time.time() - started, 0.1)
                speed = downloaded / 1024 / elapsed
                progress_callback(downloaded / total, f"{speed:.1f} KB/s -> {download_path}")
    if progress_callback:
        progress_callback(1.0, f"Saved: {download_path}")
    return str(download_path)


def check_latest_release_or_tag(repo):
    headers = {"User-Agent": APP_NAME}
    release_url = f"https://api.github.com/repos/{repo}/releases/latest"
    response = requests.get(release_url, timeout=12, headers=headers)
    if response.ok:
        payload = response.json()
        version = payload.get("tag_name") or payload.get("name")
        return {
            "version": version,
            "url": payload.get("html_url") or f"https://github.com/{repo}/releases",
            "source": "latest release",
        }

    tags_url = f"https://api.github.com/repos/{repo}/tags"
    response = requests.get(tags_url, timeout=12, headers=headers)
    response.raise_for_status()
    tags = response.json()
    if not tags:
        raise RuntimeError("No releases or tags were found for this repository.")

    tag = tags[0]
    return {
        "version": tag.get("name"),
        "url": f"https://github.com/{repo}/releases/tag/{tag.get('name')}",
        "source": "newest tag",
    }


class OnlineRow(Gtk.ListBoxRow):
    def __init__(self, item, download_callback):
        super().__init__(selectable=False)
        self.item = item
        self.download_callback = download_callback
        self.add_css_class("rich-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        set_margins(box, 8)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title = html.escape(item["name"])
        target = "Plymouth" if item["kind"] == "plymouth" else "GRUB"
        title_lbl = label(f"<b>{title}</b>", markup=True)
        meta = item.get("author", "unknown")
        score = item.get("score", item.get("stars", 0))
        score_label = item.get("score_label", "stars")
        source = item.get("source", "GitHub")
        meta_lbl = label(f"{target} theme by {meta}  |  {score} {score_label}  |  {source}", "muted")
        desc = label(item.get("description") or "No description provided.", "muted", wrap=True)
        text_box.append(title_lbl)
        text_box.append(meta_lbl)
        text_box.append(desc)

        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.progress = Gtk.ProgressBar(visible=False, show_text=True)
        self.speed_lbl = label("", "muted", xalign=1)
        progress_box.append(self.progress)
        progress_box.append(self.speed_lbl)

        self.install_btn = Gtk.Button(label="Install" if item.get("zip") else "Open")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.connect("clicked", self.start_download)

        box.append(text_box)
        box.append(progress_box)
        box.append(self.install_btn)
        self.set_child(box)

    def start_download(self, _button):
        self.install_btn.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.progress.set_text("Starting")
        self.download_callback(self.item, self)

    def update_progress(self, fraction, speed_text):
        GLib.idle_add(self.progress.set_fraction, max(0.0, min(1.0, fraction)))
        GLib.idle_add(self.progress.set_text, f"{int(fraction * 100)}%")
        GLib.idle_add(self.speed_lbl.set_text, speed_text)

    def mark_done(self, message="Installed"):
        GLib.idle_add(self.progress.set_fraction, 1.0)
        GLib.idle_add(self.progress.set_text, message)
        GLib.idle_add(self.speed_lbl.set_text, "")

    def mark_failed(self, message="Failed"):
        GLib.idle_add(self.progress.set_text, message)
        GLib.idle_add(self.install_btn.set_sensitive, True)


class ThemeManager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        global ADMIN_SESSION
        ADMIN_SESSION = AdminSession(os.path.abspath(__file__))
        self.selected_theme = None
        self.selected_grub_theme = None
        self.selected_grub_background = None
        self.latest_update_url = None

    def do_shutdown(self):
        if ADMIN_SESSION:
            ADMIN_SESSION.close()
        Gtk.Application.do_shutdown(self)

    def do_activate(self):
        self.load_css()

        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title(APP_NAME)
        self.win.set_default_size(1120, 760)

        header = Gtk.HeaderBar()
        header.set_title_widget(label(APP_NAME, "section-title", xalign=0.5))
        import_btn = Gtk.Button(label="Import")
        import_btn.connect("clicked", lambda _button: self.stack.set_visible_child_name("imports"))
        update_btn = Gtk.Button(label="Check Updates")
        update_btn.connect("clicked", lambda _button: self.stack.set_visible_child_name("updates"))
        header.pack_start(import_btn)
        header.pack_end(update_btn)
        self.win.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.add_css_class("app-shell")

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        sidebar_box.set_size_request(235, -1)
        sidebar_box.add_css_class("side-rail")
        set_margins(sidebar_box, 18)

        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        brand.append(label(APP_NAME, "brand-title"))
        brand.append(label(f"v{APP_VERSION}  |  Plymouth + GRUB", "brand-subtitle"))
        sidebar_box.append(brand)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.set_vexpand(True)
        sidebar_box.append(sidebar)

        self.stack.add_titled(self.create_plymouth_page(), "plymouth", "Plymouth")
        self.stack.add_titled(self.create_grub_page(), "grub", "GRUB")
        self.stack.add_titled(self.create_online_page(), "online", "Online")
        self.stack.add_titled(self.create_import_page(), "imports", "Imports")
        self.stack.add_titled(self.create_updates_page(), "updates", "Updates")
        self.stack.add_titled(self.create_safety_page(), "safety", "Safety")

        root.append(sidebar_box)
        root.append(self.stack)
        self.win.set_child(root)
        self.win.present()

        self.refresh_installed()
        self.refresh_grub()
        self.perform_online_search()

    def load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def make_page(self, title, subtitle):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        set_margins(page, 24)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading.append(label(title, "page-title"))
        heading.append(label(subtitle, "muted", wrap=True))
        page.append(heading)
        return page

    def make_card(self, title=None, subtitle=None, accent=False, danger=False):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("accent-card" if accent else "danger-card" if danger else "glass-card")
        set_margins(card, 18)
        if title:
            card.append(label(title, "section-title"))
        if subtitle:
            card.append(label(subtitle, "muted", wrap=True))
        return card

    # Plymouth page

    def create_plymouth_page(self):
        page = self.make_page(
            "Plymouth boot animations",
            "Install, preview, apply, and remove the animation that appears after GRUB while Linux boots.",
        )

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _button: self.refresh_installed())
        import_btn = Gtk.Button(label="Import Plymouth archive")
        import_btn.add_css_class("suggested-action")
        import_btn.connect("clicked", self.on_import_plymouth_clicked)
        toolbar.append(refresh_btn)
        toolbar.append(import_btn)
        page.append(toolbar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(380)
        paned.set_vexpand(True)

        list_card = self.make_card("Installed themes")
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.installed_list = Gtk.ListBox()
        self.installed_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.installed_list.connect("row-selected", self.on_plymouth_row_selected)
        scroller.set_child(self.installed_list)
        list_card.append(scroller)

        preview_card = self.make_card("Preview and actions", "Images are shown when a theme includes a PNG/JPG preview or asset.")
        self.preview_img = Gtk.Image(pixel_size=360)
        self.preview_img.set_from_icon_name("image-x-generic")
        preview_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        preview_wrap.set_size_request(420, 300)
        preview_wrap.add_css_class("soft-card")
        set_margins(preview_wrap, 12)
        preview_wrap.append(self.preview_img)
        preview_card.append(preview_wrap)

        self.plymouth_selected_lbl = label("Select a theme to see actions.", "muted", wrap=True)
        preview_card.append(self.plymouth_selected_lbl)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.connect("clicked", self.on_apply_plymouth_clicked)

        self.details_btn = Gtk.Button(label="Details")
        self.details_btn.set_sensitive(False)
        self.details_btn.connect("clicked", self.on_plymouth_details_clicked)

        self.delete_btn = Gtk.Button(label="Delete")
        self.delete_btn.add_css_class("destructive-action")
        self.delete_btn.set_sensitive(False)
        self.delete_btn.connect("clicked", self.on_delete_plymouth_clicked)

        btn_box.append(self.apply_btn)
        btn_box.append(self.details_btn)
        btn_box.append(self.delete_btn)
        preview_card.append(btn_box)

        self.status_lbl = label("Ready.", "muted", wrap=True)
        preview_card.append(self.status_lbl)

        paned.set_start_child(list_card)
        paned.set_end_child(preview_card)
        page.append(paned)
        return page

    def refresh_installed(self):
        if not hasattr(self, "installed_list"):
            return
        while child := self.installed_list.get_first_child():
            self.installed_list.remove(child)

        themes = get_installed_themes()
        if not themes:
            row = Gtk.ListBoxRow(selectable=False)
            row.add_css_class("rich-row")
            row.set_child(label("No custom Plymouth themes found.", "muted", wrap=True))
            self.installed_list.append(row)
            return

        for name, path in themes:
            row = Gtk.ListBoxRow()
            row.data = (name, path)
            row.add_css_class("rich-row")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            set_margins(box, 8)
            title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
            title_box.append(label(name, "section-title"))
            title_box.append(label(path, "muted"))
            box.append(title_box)
            if is_current_plymouth_theme(path):
                badge = label("ACTIVE", "badge", xalign=0.5)
                box.append(badge)
            row.set_child(box)
            self.installed_list.append(row)

    def on_plymouth_row_selected(self, _list, row):
        if not row or not hasattr(row, "data"):
            return
        self.selected_theme = row.data
        name, path = self.selected_theme
        self.apply_btn.set_sensitive(True)
        self.delete_btn.set_sensitive(True)
        self.details_btn.set_sensitive(True)
        self.plymouth_selected_lbl.set_text(f"{name}\n{path}")

        preview = find_preview_image(path)
        if preview:
            self.load_image(self.preview_img, preview, 420, 300)
        else:
            self.preview_img.set_from_icon_name("image-x-generic")

    def on_apply_plymouth_clicked(self, _button):
        if not self.selected_theme:
            return
        name, path = self.selected_theme

        def task():
            plymouth_files = glob.glob(os.path.join(path, "*.plymouth"))
            if not plymouth_files:
                raise RuntimeError("Selected theme has no .plymouth file.")
            plymouth_file = plymouth_files[0]
            admin_request("apply_plymouth", {"plymouth_file": plymouth_file})
            return name

        self.run_task(
            self.status_lbl,
            f"Applying {name} and rebuilding initramfs...",
            task,
            lambda result: f"{result} applied. Reboot to see the new boot animation.",
            refresh=self.refresh_installed,
        )

    def on_plymouth_details_clicked(self, _button):
        if not self.selected_theme:
            return
        path = self.selected_theme[1]
        readmes = glob.glob(os.path.join(path, "README*"))
        if readmes:
            try:
                with open(readmes[0], "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
            except OSError as error:
                content = str(error)
        else:
            content = "No README is included with this theme."
        self.show_text_window("Theme details", content)

    def on_delete_plymouth_clicked(self, _button):
        if not self.selected_theme:
            return
        name, path = self.selected_theme
        if len(get_installed_themes()) <= 1:
            self.show_msg("Cannot delete", "Keep at least one custom Plymouth theme installed.")
            return
        real_path = os.path.realpath(path)
        if not real_path.startswith(os.path.realpath(THEME_BASE) + os.sep):
            self.show_msg("Cannot delete", "The selected path is outside the Plymouth theme directory.")
            return

        def task():
            admin_request("delete_plymouth_theme", {"path": path})
            return name

        self.run_task(
            self.status_lbl,
            f"Deleting {name}...",
            task,
            lambda result: f"{result} deleted.",
            refresh=self.refresh_installed,
        )

    # GRUB page

    def create_grub_page(self):
        page = self.make_page(
            "GRUB backgrounds and themes",
            "Change the boot menu background, install complete GRUB themes, and rebuild the GRUB config safely.",
        )

        status = self.make_card("Current GRUB configuration", accent=True)
        self.grub_theme_value_lbl = label("Theme: checking...", "muted", wrap=True)
        self.grub_bg_value_lbl = label("Background: checking...", "muted", wrap=True)
        status.append(self.grub_theme_value_lbl)
        status.append(self.grub_bg_value_lbl)
        page.append(status)

        search_card = self.make_card(
            "Find GRUB themes online",
            "Type a theme name and search installable GitHub repositories or Pling/OpenDesktop GRUB theme listings.",
        )
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.grub_quick_source = Gtk.DropDown.new_from_strings(["GitHub", "Pling"])
        self.grub_quick_search = Gtk.SearchEntry(hexpand=True)
        self.grub_quick_search.set_placeholder_text("GRUB theme name")
        self.grub_quick_search.connect("activate", self.on_grub_quick_search)
        grub_search_btn = Gtk.Button(label="Search GRUB")
        grub_search_btn.add_css_class("suggested-action")
        grub_search_btn.connect("clicked", self.on_grub_quick_search)
        search_row.append(self.grub_quick_source)
        search_row.append(self.grub_quick_search)
        search_row.append(grub_search_btn)
        search_card.append(search_row)
        page.append(search_card)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18, vexpand=True)

        bg_card = self.make_card(
            "Background image",
            "Choose a PNG, JPG, JPEG, or TGA image. GRUB themes can override backgrounds, so background-only mode disables GRUB_THEME.",
        )
        bg_card.set_hexpand(True)
        choose_bg = Gtk.Button(label="Choose image")
        choose_bg.connect("clicked", self.on_choose_grub_background_clicked)
        self.grub_bg_preview = Gtk.Image(pixel_size=240)
        self.grub_bg_preview.set_from_icon_name("image-x-generic")
        self.grub_bg_file_lbl = label("No image selected.", "muted", wrap=True)
        self.disable_theme_switch = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        switch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        switch_row.append(label("Background-only mode", xalign=0))
        switch_row.append(self.disable_theme_switch)
        self.apply_bg_btn = Gtk.Button(label="Apply background")
        self.apply_bg_btn.add_css_class("suggested-action")
        self.apply_bg_btn.set_sensitive(False)
        self.apply_bg_btn.connect("clicked", self.on_apply_grub_background_clicked)
        self.grub_bg_status = label("Ready.", "muted", wrap=True)
        bg_card.append(choose_bg)
        bg_card.append(self.grub_bg_preview)
        bg_card.append(self.grub_bg_file_lbl)
        bg_card.append(switch_row)
        bg_card.append(self.apply_bg_btn)
        bg_card.append(self.grub_bg_status)

        theme_card = self.make_card("Installed GRUB themes", "Themes live under /boot/grub/themes and contain theme.txt.")
        theme_card.set_hexpand(True)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        import_archive = Gtk.Button(label="Import archive")
        import_archive.connect("clicked", self.on_import_grub_archive_clicked)
        import_folder = Gtk.Button(label="Import folder")
        import_folder.connect("clicked", self.on_import_grub_folder_clicked)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _button: self.refresh_grub())
        controls.append(import_archive)
        controls.append(import_folder)
        controls.append(refresh)
        theme_card.append(controls)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.grub_theme_list = Gtk.ListBox()
        self.grub_theme_list.connect("row-selected", self.on_grub_theme_row_selected)
        scroller.set_child(self.grub_theme_list)
        theme_card.append(scroller)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.apply_grub_theme_btn = Gtk.Button(label="Apply theme")
        self.apply_grub_theme_btn.add_css_class("suggested-action")
        self.apply_grub_theme_btn.set_sensitive(False)
        self.apply_grub_theme_btn.connect("clicked", self.on_apply_grub_theme_clicked)
        self.delete_grub_theme_btn = Gtk.Button(label="Delete")
        self.delete_grub_theme_btn.add_css_class("destructive-action")
        self.delete_grub_theme_btn.set_sensitive(False)
        self.delete_grub_theme_btn.connect("clicked", self.on_delete_grub_theme_clicked)
        btn_box.append(self.apply_grub_theme_btn)
        btn_box.append(self.delete_grub_theme_btn)
        theme_card.append(btn_box)
        self.grub_theme_status = label("Ready.", "muted", wrap=True)
        theme_card.append(self.grub_theme_status)

        body.append(bg_card)
        body.append(theme_card)
        page.append(body)
        return page

    def on_grub_quick_search(self, _widget):
        query = self.grub_quick_search.get_text().strip()
        if hasattr(self, "online_kind"):
            self.online_kind.set_selected(1)
            self.online_grub_source.set_selected(self.grub_quick_source.get_selected())
            self.search_entry.set_text(query)
            self.stack.set_visible_child_name("online")
            self.perform_online_search()

    def refresh_grub(self):
        if not hasattr(self, "grub_theme_list"):
            return
        active_theme = get_grub_value("GRUB_THEME")
        active_bg = get_grub_value("GRUB_BACKGROUND")
        self.grub_theme_value_lbl.set_text(f"Theme: {active_theme or 'not set'}")
        self.grub_bg_value_lbl.set_text(f"Background: {active_bg or 'not set'}")

        while child := self.grub_theme_list.get_first_child():
            self.grub_theme_list.remove(child)

        themes = get_installed_grub_themes()
        if not themes:
            row = Gtk.ListBoxRow(selectable=False)
            row.add_css_class("rich-row")
            row.set_child(label("No installed GRUB themes found yet.", "muted", wrap=True))
            self.grub_theme_list.append(row)
            return

        for name, theme_file, root in themes:
            row = Gtk.ListBoxRow()
            row.data = (name, theme_file, root)
            row.add_css_class("rich-row")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            set_margins(box, 8)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
            text_box.append(label(name, "section-title"))
            text_box.append(label(theme_file, "muted"))
            box.append(text_box)
            if active_theme and os.path.realpath(active_theme) == os.path.realpath(theme_file):
                box.append(label("ACTIVE", "badge"))
            row.set_child(box)
            self.grub_theme_list.append(row)

    def on_grub_theme_row_selected(self, _list, row):
        if not row or not hasattr(row, "data"):
            return
        self.selected_grub_theme = row.data
        self.apply_grub_theme_btn.set_sensitive(True)
        self.delete_grub_theme_btn.set_sensitive(True)

    def on_choose_grub_background_clicked(self, _button):
        self.choose_path("Choose GRUB background image", self.on_grub_background_path)

    def on_grub_background_path(self, path):
        if Path(path).suffix.lower() not in IMAGE_EXTENSIONS:
            self.show_msg("Unsupported image", "Choose a PNG, JPG, JPEG, or TGA image.")
            return
        self.selected_grub_background = path
        self.grub_bg_file_lbl.set_text(path)
        self.apply_bg_btn.set_sensitive(True)
        self.load_image(self.grub_bg_preview, path, 320, 220)

    def on_apply_grub_background_clicked(self, _button):
        if not self.selected_grub_background:
            return
        disable_theme = self.disable_theme_switch.get_active()

        def task():
            return install_grub_background(
                self.selected_grub_background,
                disable_theme,
            )

        self.run_task(
            self.grub_bg_status,
            "Copying background and updating GRUB...",
            task,
            lambda result: f"Background applied: {result}",
            refresh=self.refresh_grub,
        )

    def on_apply_grub_theme_clicked(self, _button):
        if not self.selected_grub_theme:
            return
        name, theme_file, _root = self.selected_grub_theme

        def task():
            set_grub_options({"GRUB_THEME": theme_file})
            run_grub_update()
            return name

        self.run_task(
            self.grub_theme_status,
            f"Applying GRUB theme {name}...",
            task,
            lambda result: f"{result} applied. Reboot to see the GRUB menu theme.",
            refresh=self.refresh_grub,
        )

    def on_delete_grub_theme_clicked(self, _button):
        if not self.selected_grub_theme:
            return
        name, _theme_file, root = self.selected_grub_theme
        real_root = os.path.realpath(root)
        if not real_root.startswith(os.path.realpath(GRUB_THEME_BASE) + os.sep):
            self.show_msg("Cannot delete", "The selected path is outside the GRUB theme directory.")
            return

        def task():
            admin_request("delete_grub_theme", {"path": root})
            return name

        self.run_task(
            self.grub_theme_status,
            f"Deleting GRUB theme {name}...",
            task,
            lambda result: f"{result} deleted.",
            refresh=self.refresh_grub,
        )

    # Online page

    def create_online_page(self):
        page = self.make_page(
            "Online theme gallery",
            "Search GitHub, install Plymouth boot animations, import GRUB themes, or paste a direct URL.",
        )

        search_card = self.make_card("Search")
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.online_kind = Gtk.DropDown.new_from_strings(["Plymouth themes", "GRUB themes"])
        self.online_grub_source = Gtk.DropDown.new_from_strings(["GitHub", "Pling"])
        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.set_placeholder_text("Search theme name")
        self.search_entry.connect("activate", lambda _entry: self.perform_online_search())
        search_btn = Gtk.Button(label="Search")
        search_btn.add_css_class("suggested-action")
        search_btn.connect("clicked", lambda _button: self.perform_online_search())
        search_row.append(self.online_kind)
        search_row.append(self.online_grub_source)
        search_row.append(self.search_entry)
        search_row.append(search_btn)
        self.search_progress = Gtk.ProgressBar(visible=False)
        search_card.append(search_row)
        search_card.append(self.search_progress)
        search_card.append(label(f"Downloads are saved in: {DOWNLOAD_DIR}", "muted", wrap=True))
        page.append(search_card)

        url_card = self.make_card("Install from URL")
        url_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.url_kind = Gtk.DropDown.new_from_strings(
            ["Plymouth archive/repo", "GRUB theme archive/repo", "GRUB background image"]
        )
        self.url_entry = Gtk.Entry(hexpand=True)
        self.url_entry.set_placeholder_text("https://github.com/user/theme or a direct archive/image URL")
        url_btn = Gtk.Button(label="Install URL")
        url_btn.connect("clicked", self.on_install_url_clicked)
        url_row.append(self.url_kind)
        url_row.append(self.url_entry)
        url_row.append(url_btn)
        self.url_status = label("Ready.", "muted", wrap=True)
        url_card.append(url_row)
        url_card.append(self.url_status)
        page.append(url_card)

        results_card = self.make_card("Results")
        results_card.set_vexpand(True)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self.online_list = Gtk.ListBox()
        scroller.set_child(self.online_list)
        results_card.append(scroller)
        page.append(results_card)
        return page

    def perform_online_search(self):
        if not hasattr(self, "online_list"):
            return
        self.search_progress.set_visible(True)
        self.search_progress.pulse()
        query = self.search_entry.get_text().strip()
        kind = "plymouth" if self.online_kind.get_selected() == 0 else "grub"
        source = "pling" if kind == "grub" and self.online_grub_source.get_selected() == 1 else "github"

        def worker():
            try:
                if source == "pling":
                    results = search_pling_grub_themes(query)
                else:
                    results = search_github_themes(query, kind)
                GLib.idle_add(self.update_online_ui, results, None)
            except Exception as error:
                GLib.idle_add(self.update_online_ui, [], str(error))

        threading.Thread(target=worker, daemon=True).start()

    def update_online_ui(self, results, error):
        self.search_progress.set_visible(False)
        while child := self.online_list.get_first_child():
            self.online_list.remove(child)
        if error:
            row = Gtk.ListBoxRow(selectable=False)
            row.add_css_class("rich-row")
            row.set_child(label(f"Search failed: {error}", "muted", wrap=True))
            self.online_list.append(row)
            return
        if not results:
            row = Gtk.ListBoxRow(selectable=False)
            row.add_css_class("rich-row")
            row.set_child(label("No matching repositories found.", "muted", wrap=True))
            self.online_list.append(row)
            return
        for item in results:
            self.online_list.append(OnlineRow(item, self.start_online_install))

    def start_online_install(self, item, row):
        if not item.get("zip"):
            self.open_uri(item.get("page", "https://www.opendesktop.org/"))
            row.mark_done("Opened in browser")
            return

        def worker():
            tmp_path = None
            try:
                tmp_path = download_to_downloads(item["zip"], row.update_progress)
                if item["kind"] == "plymouth":
                    installed = install_plymouth_archive(tmp_path)
                    GLib.idle_add(self.refresh_installed)
                    row.mark_done(summarize_names(installed, "Plymouth theme", "Plymouth themes"))
                else:
                    installed = install_grub_theme_archive(tmp_path)
                    GLib.idle_add(self.refresh_grub)
                    row.mark_done(summarize_names(installed, "GRUB theme", "GRUB themes"))
            except Exception as error:
                row.mark_failed("Failed")
                GLib.idle_add(self.show_msg, "Install failed", str(error))

        threading.Thread(target=worker, daemon=True).start()

    def on_install_url_clicked(self, _button):
        selection = self.url_kind.get_selected()
        kind = ["plymouth", "grub", "background"][selection]
        url = self.url_entry.get_text().strip()

        def task():
            normalized = normalize_online_url(url, kind)
            tmp_path = download_to_downloads(
                normalized,
                lambda _fraction, message: GLib.idle_add(self.url_status.set_text, message),
            )
            if kind == "plymouth":
                return install_plymouth_archive(tmp_path)
            if kind == "grub":
                return install_grub_theme_archive(tmp_path)
            return install_grub_background(tmp_path, True)

        def done(result):
            if kind == "background":
                return f"GRUB background applied: {result}"
            if kind == "plymouth":
                return summarize_names(result, "Plymouth theme", "Plymouth themes")
            return summarize_names(result, "GRUB theme", "GRUB themes")

        refresh = self.refresh_installed if kind == "plymouth" else self.refresh_grub
        self.run_task(self.url_status, "Downloading and installing URL...", task, done, refresh=refresh)

    # Imports page

    def create_import_page(self):
        page = self.make_page(
            "Imports",
            "Bring in local archives, folders, or images without hunting through settings.",
        )

        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        grid.set_vexpand(True)
        grid.set_hexpand(True)

        cards = [
            (
                "Plymouth archive",
                "Install a local ZIP or tar archive that contains a .plymouth file.",
                "Choose archive",
                self.on_import_plymouth_clicked,
            ),
            (
                "GRUB theme archive",
                "Install a local ZIP or tar archive that contains a GRUB theme.txt file.",
                "Choose archive",
                self.on_import_grub_archive_clicked,
            ),
            (
                "GRUB theme folder",
                "Import an already extracted folder with theme.txt in its root.",
                "Choose folder",
                self.on_import_grub_folder_clicked,
            ),
            (
                "GRUB background image",
                "Apply a local PNG, JPG, JPEG, or TGA image to the GRUB menu.",
                "Choose image",
                self.on_choose_grub_background_clicked,
            ),
        ]

        for index, (title, subtitle, button_text, callback) in enumerate(cards):
            card = self.make_card(title, subtitle)
            button = Gtk.Button(label=button_text)
            button.add_css_class("suggested-action")
            button.connect("clicked", callback)
            card.append(button)
            grid.attach(card, index % 2, index // 2, 1, 1)

        self.import_status = label("Ready.", "muted", wrap=True)
        page.append(grid)
        page.append(self.import_status)
        return page

    def on_import_plymouth_clicked(self, _button):
        self.choose_path("Import Plymouth theme archive", self.on_plymouth_archive_path)

    def on_plymouth_archive_path(self, path):
        def task():
            return install_plymouth_archive(path)

        self.run_task(
            getattr(self, "import_status", self.status_lbl),
            "Installing Plymouth archive...",
            task,
            lambda result: summarize_names(result, "Plymouth theme", "Plymouth themes"),
            refresh=self.refresh_installed,
        )

    def on_import_grub_archive_clicked(self, _button):
        self.choose_path("Import GRUB theme archive", self.on_grub_archive_path)

    def on_grub_archive_path(self, path):
        def task():
            return install_grub_theme_archive(path)

        self.run_task(
            getattr(self, "import_status", self.grub_theme_status),
            "Installing GRUB theme archive...",
            task,
            lambda result: summarize_names(result, "GRUB theme", "GRUB themes") + " (first theme applied).",
            refresh=self.refresh_grub,
        )

    def on_import_grub_folder_clicked(self, _button):
        self.choose_path("Import GRUB theme folder", self.on_grub_folder_path, folder=True)

    def on_grub_folder_path(self, path):
        def task():
            return install_grub_theme_dir(path)

        self.run_task(
            getattr(self, "import_status", self.grub_theme_status),
            "Installing GRUB theme folder...",
            task,
            lambda result: summarize_names(result, "GRUB theme", "GRUB themes") + " (applied).",
            refresh=self.refresh_grub,
        )

    # Updates page

    def create_updates_page(self):
        page = self.make_page(
            "App updates",
            "Checks GitHub releases first, then falls back to tags. Change the repository if you fork the app.",
        )

        card = self.make_card("Update source", accent=True)
        card.append(label(f"Current version: {APP_VERSION}", "section-title"))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.update_repo_entry = Gtk.Entry(hexpand=True)
        self.update_repo_entry.set_text(UPDATE_REPO)
        check_btn = Gtk.Button(label="Check now")
        check_btn.add_css_class("suggested-action")
        check_btn.connect("clicked", self.on_check_updates_clicked)
        self.open_update_btn = Gtk.Button(label="Open releases")
        self.open_update_btn.set_sensitive(False)
        self.open_update_btn.connect("clicked", self.on_open_update_clicked)
        row.append(self.update_repo_entry)
        row.append(check_btn)
        row.append(self.open_update_btn)
        self.update_status = label("Ready to check.", "muted", wrap=True)
        card.append(row)
        card.append(self.update_status)
        page.append(card)

        note = self.make_card(
            "How it works",
            "For packaged installs, publish a GitHub Release with a newer tag such as v2.1.0 and attach the .deb. This checker reports the version and opens the release page.",
        )
        page.append(note)
        return page

    def on_check_updates_clicked(self, _button):
        repo = self.update_repo_entry.get_text().strip()
        if not repo or "/" not in repo:
            self.update_status.set_text("Enter a repository as owner/name.")
            return

        def worker():
            GLib.idle_add(self.update_status.set_text, "Checking GitHub releases and tags...")
            try:
                latest = check_latest_release_or_tag(repo)
                latest_version = latest.get("version") or ""
                self.latest_update_url = latest.get("url")
                if is_newer_version(latest_version, APP_VERSION):
                    message = (
                        f"Update available: {latest_version} from {latest['source']} "
                        f"(current: {APP_VERSION})."
                    )
                    GLib.idle_add(self.open_update_btn.set_sensitive, True)
                else:
                    message = (
                        f"You are up to date. Newest {latest['source']} is "
                        f"{latest_version or 'unknown'}."
                    )
                    GLib.idle_add(self.open_update_btn.set_sensitive, bool(self.latest_update_url))
                GLib.idle_add(self.update_status.set_text, message)
            except Exception as error:
                GLib.idle_add(self.update_status.set_text, f"Update check failed: {error}")

        threading.Thread(target=worker, daemon=True).start()

    def on_open_update_clicked(self, _button):
        if self.latest_update_url:
            self.open_uri(self.latest_update_url)

    # Safety page

    def create_safety_page(self):
        page = self.make_page(
            "Safety tools",
            "Small boot helpers for testing animations without editing unrelated system files.",
        )

        card = self.make_card(
            "Safe display-manager delay",
            "Adds a systemd override that pauses the login screen, giving Plymouth a moment to show the animation.",
        )
        adjustment = Gtk.Adjustment(lower=0, upper=20, step_increment=1, value=0)
        self.delay_spin = Gtk.SpinButton(adjustment=adjustment, numeric=True)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.append(label("Delay seconds"))
        row.append(self.delay_spin)
        apply_btn = Gtk.Button(label="Apply safe delay")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self.on_save_safe_delay)
        self.delay_status = label("Ready.", "muted", wrap=True)
        card.append(row)
        card.append(apply_btn)
        card.append(self.delay_status)
        page.append(card)
        return page

    def on_save_safe_delay(self, _button):
        seconds = int(self.delay_spin.get_value())

        def task():
            return admin_request("safe_delay", {"seconds": seconds})

        self.run_task(
            self.delay_status,
            "Applying safe delay...",
            task,
            lambda result: f"Safe delay set to {result} seconds.",
        )

    # Shared helpers

    def choose_path(self, title, callback, folder=False):
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog(title=title)
            if folder:
                dialog.select_folder(
                    self.win,
                    None,
                    lambda dialog_obj, result: self.finish_file_dialog(dialog_obj, result, callback, True),
                )
            else:
                dialog.open(
                    self.win,
                    None,
                    lambda dialog_obj, result: self.finish_file_dialog(dialog_obj, result, callback, False),
                )
            return

        action = Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN
        dialog = Gtk.FileChooserNative(
            title=title,
            transient_for=self.win,
            action=action,
            accept_label="Choose",
            cancel_label="Cancel",
        )

        def on_response(native_dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file_obj = native_dialog.get_file()
                path = file_obj.get_path() if file_obj else None
                if path:
                    callback(path)
            native_dialog.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def finish_file_dialog(self, dialog, result, callback, folder):
        try:
            file_obj = dialog.select_folder_finish(result) if folder else dialog.open_finish(result)
        except GLib.Error:
            return
        path = file_obj.get_path() if file_obj else None
        if path:
            callback(path)

    def run_task(self, status_label, busy_text, task, done_text, refresh=None):
        def worker():
            GLib.idle_add(status_label.set_text, busy_text)
            try:
                result = task()
                message = done_text(result) if callable(done_text) else done_text
                GLib.idle_add(status_label.set_text, message)
                if refresh:
                    GLib.idle_add(refresh)
            except Exception as error:
                GLib.idle_add(status_label.set_text, f"Error: {error}")
                GLib.idle_add(self.show_msg, "Action failed", str(error))

        threading.Thread(target=worker, daemon=True).start()

    def load_image(self, image_widget, image_path, width, height):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(image_path, width, height, True)
            image_widget.set_from_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
        except Exception:
            image_widget.set_from_icon_name("image-missing")

    def show_text_window(self, title, content):
        window = Gtk.Window(title=title, default_width=640, default_height=460, transient_for=self.win)
        scroller = Gtk.ScrolledWindow()
        set_margins(scroller, 16)
        text_view = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD)
        text_view.get_buffer().set_text(content)
        scroller.set_child(text_view)
        window.set_child(scroller)
        window.present()

    def show_msg(self, title, message):
        dialog = Gtk.MessageDialog(transient_for=self.win, text=title, buttons=Gtk.ButtonsType.OK)
        dialog.set_markup(html.escape(message))
        dialog.connect("response", lambda widget, _response: widget.destroy())
        dialog.present()

    def open_uri(self, uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception as error:
            self.show_msg("Could not open link", str(error))


if __name__ == "__main__":
    if ROOT_HELPER_FLAG in sys.argv:
        root_helper_loop()
    else:
        app = ThemeManager()
        app.run(None)
