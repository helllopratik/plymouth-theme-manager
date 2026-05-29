#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SCRIPT="$ROOT_DIR/plymouth-theme-manager.py"
PACKAGE_NAME="plymouth-theme-manager"
VERSION="$(python3 - <<'PY' "$APP_SCRIPT"
import ast
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    tree = ast.parse(handle.read())

for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if getattr(target, "id", None) == "APP_VERSION":
                print(ast.literal_eval(node.value))
                raise SystemExit

raise SystemExit("APP_VERSION not found")
PY
)"

BUILD_ROOT="$ROOT_DIR/build/deb/${PACKAGE_NAME}_${VERSION}_all"
DIST_DIR="$ROOT_DIR/dist"
DEB_PATH="$DIST_DIR/${PACKAGE_NAME}_${VERSION}_all.deb"

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/DEBIAN"
mkdir -p "$BUILD_ROOT/usr/bin"
mkdir -p "$BUILD_ROOT/usr/share/applications"
mkdir -p "$BUILD_ROOT/usr/share/doc/$PACKAGE_NAME"

install -m 0755 "$APP_SCRIPT" "$BUILD_ROOT/usr/bin/plymouth-theme-manager"
install -m 0644 "$ROOT_DIR/plymouth-theme-manager.desktop" "$BUILD_ROOT/usr/share/applications/plymouth-theme-manager.desktop"
install -m 0644 "$ROOT_DIR/README.md" "$BUILD_ROOT/usr/share/doc/$PACKAGE_NAME/README.md"
install -m 0644 "$ROOT_DIR/LICENSE" "$BUILD_ROOT/usr/share/doc/$PACKAGE_NAME/LICENSE"

cat > "$BUILD_ROOT/DEBIAN/control" <<CONTROL
Package: $PACKAGE_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Plymouth Theme Manager Maintainers <helllopratik@users.noreply.github.com>
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, python3-requests, plymouth, plymouth-themes, grub-common, initramfs-tools, policykit-1 | polkitd, unzip
Recommends: xdg-utils
Homepage: https://github.com/helllopratik/plymouth-theme-manager
Description: Manage Plymouth animations and GRUB themes
 Plymouth Theme Manager is a GTK4 desktop app for installing and applying
 Plymouth boot animations, GRUB background images, and complete GRUB themes.
CONTROL

cat > "$BUILD_ROOT/DEBIAN/postinst" <<'POSTINST'
#!/usr/bin/env bash
set -e

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

exit 0
POSTINST

chmod 0755 "$BUILD_ROOT/DEBIAN/postinst"
find "$BUILD_ROOT" -type d -exec chmod 0755 {} +

mkdir -p "$DIST_DIR"
dpkg-deb --build --root-owner-group "$BUILD_ROOT" "$DEB_PATH"
rm -rf "$BUILD_ROOT"
echo "$DEB_PATH"
