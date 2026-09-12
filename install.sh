#!/bin/bash
# Install On-Call Scheduler for the current user: no root, nothing outside $HOME.
#
# Everything lands under the XDG user directories, so the desktop entry and the
# icon are picked up by any freedesktop-compliant launcher -- the Omarchy menu
# included -- without touching /usr.
#
# Copyright (C) 2026 Caden DeNike. Free software under the GNU General
# Public License, version 3 or later, with no warranty. See LICENSE.

set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="io.github.cdenike.OnCallScheduler"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

echo "==> Command: $BIN_DIR/oncall-scheduler"
# The checkout is baked in rather than installed into site-packages, so the
# command always runs the tree you installed from -- pull and it updates, with
# no reinstall step to forget.
cat > "$BIN_DIR/oncall-scheduler" <<EOF
#!/bin/bash
export PYTHONPATH="$REPO\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m oncall "\$@"
EOF
chmod +x "$BIN_DIR/oncall-scheduler"

echo "==> Icon: $ICON_DIR/$APP_ID.svg"
install -m644 "$REPO/data/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"

echo "==> Desktop entry: $APP_DIR/$APP_ID.desktop"
# Named for the app id so the launcher can tie the window to this entry, and
# StartupWMClass repeats it because that is what Wayland reports as the app id.
cat > "$APP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=On-Call Scheduler
GenericName=Rota Builder
Comment=Solve and export the monthly on-call calendar
Exec=$BIN_DIR/oncall-scheduler
Icon=$APP_ID
Terminal=false
Categories=Office;Calendar;ProjectManagement;
Keywords=on-call;oncall;rota;schedule;shift;calendar;
StartupNotify=true
StartupWMClass=$APP_ID
EOF

# Launchers cache both of these; without a refresh a fresh install can take a
# session restart to show up.
command -v update-desktop-database >/dev/null && \
  update-desktop-database "$APP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "Installed."
echo "  oncall-scheduler        open the window"
echo "  oncall-scheduler --help command line options"
echo
echo 'It should also appear in your app launcher as "On-Call Scheduler".'

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo
     echo "WARNING: $BIN_DIR is not on your PATH; the command will not be found."
     echo "         Add it to your shell profile:"
     echo '           export PATH="$HOME/.local/bin:$PATH"' ;;
esac
