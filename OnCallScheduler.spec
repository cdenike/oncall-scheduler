# -*- mode: python ; coding: utf-8 -*-
"""The single-file build, and what is deliberately left out of it.

    pyinstaller --noconfirm --clean OnCallScheduler.spec

PyInstaller collects whatever the code could conceivably reach, and for Qt that
is far more than a window made of widgets ever touches: a theme plugin that
loads all of GTK 3 (and a second copy of ICU with it), an on-screen keyboard
built on QML, TLS backends, PDF and WebP decoders, translations for languages
the app is not in. Together they were more than half of what the build carried.

Two passes take them out. Python modules nothing imports are excluded before
analysis, so their native libraries are never collected at all. Qt plugins
nothing uses are dropped after it, and then every library that only they needed
goes too -- found by following what each remaining file actually links against,
so a library that something kept depends on cannot be removed by mistake.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import os
import sys

from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_submodules

WINDOWS = sys.platform == "win32"

# Nothing here opens a connection, uses bz2 or lzma, or needs Pillow's colour
# management, AVIF, WebP or Tk support. hashlib falls back to its built-in
# digests without OpenSSL, and zipfile and shutil treat bz2 and lzma as
# optional. Only modules that bring a native library with them are listed:
# excluding pure-Python ones saves almost nothing and risks breaking a path no
# check happens to take -- `fractions`, which Pillow loads, imports `decimal`.
EXCLUDES = [
    "ssl", "_ssl", "_hashlib",
    "bz2", "_bz2", "lzma", "_lzma",
    "PIL._avif", "PIL.AvifImagePlugin", "PIL._webp", "PIL.WebPImagePlugin",
    "PIL._imagingcms", "PIL.ImageCms", "PIL._imagingtk", "PIL.ImageTk",
    "PIL.ImageQt", "tkinter",
    # Qt's networking binding ends up collected although nothing imports it --
    # traced at runtime, it is never loaded -- and it keeps libQt6Network.
    "PySide6.QtNetwork",
]

# Qt plugins left out, by directory and name prefix, on either platform.
DROP_PLUGINS = (
    "platformthemes/libqgtk3",                           # GTK 3, and ICU again
    "platforminputcontexts/libqtvirtualkeyboardplugin",  # QtQuick and QML
    "platforminputcontexts/qtvirtualkeyboardplugin",
    "tls/", "networkinformation/",                       # networking
    "generic/", "egldeviceintegrations/",                # embedded input, displays
    "platforms/libqeglfs", "platforms/libqlinuxfb", "platforms/libqminimal",
    "platforms/libqvnc", "platforms/libqvkkhrdisplay",
    "platforms/qdirect2d", "platforms/qminimal",
)

# Of the image-format plugins, only SVG, for the window icon. Calendars are
# drawn by Pillow and shown as PNG, which Qt reads without a plugin.
KEEP_IMAGE_FORMATS = ("qsvg",)


def _left_out(dest):
    path = dest.replace("\\", "/").lower()
    if "/translations/" in path:
        return True                 # the app is in English and loads none
    if path.endswith("opengl32sw.dll"):
        return True                 # software OpenGL; widgets draw without it
    if "/plugins/imageformats/" in path:
        return not any(name in path for name in KEEP_IMAGE_FORMATS)
    return any("/plugins/" + plugin in path for plugin in DROP_PLUGINS)


def _reachable(binaries):
    """The binaries that something kept still links against, transitively.

    The search starts from every Python extension module, every Qt plugin that
    survived, and the Python runtime the bootloader loads. A library none of
    those reach is one that only a dropped plugin wanted.
    """
    by_name = {}
    for entry in binaries:
        if entry[2] != "SYMLINK":       # a link is not the library it points at
            by_name.setdefault(os.path.basename(entry[0]).lower(), entry)

    def is_root(entry):
        path = entry[0].replace("\\", "/").lower()
        return (entry[2] == "EXTENSION" or "/plugins/" in path
                or os.path.basename(path).startswith(("python3", "libpython3")))

    kept, stack = set(), [e for e in binaries if e[2] != "SYMLINK" and is_root(e)]
    while stack:
        entry = stack.pop()
        if entry[0] in kept:
            continue
        kept.add(entry[0])
        for name, _ in get_imports(entry[1]):
            dependency = by_name.get(os.path.basename(name).lower())
            if dependency is not None:
                stack.append(dependency)
    return [entry for entry in binaries if entry[0] in kept or entry[2] == "SYMLINK"]


def _live_links(toc, present):
    """Drop symlinks whose target was left out, rather than ship them dangling."""
    return [e for e in toc if e[2] != "SYMLINK" or e[1].replace("\\", "/") in present]


def _size(toc):
    return sum(os.path.getsize(e[1]) for e in toc if e[1] and os.path.isfile(e[1]))


a = Analysis(
    ["run.py"],
    hiddenimports=collect_submodules("oncall"),
    excludes=EXCLUDES,
)

collected = _size(a.binaries) + _size(a.datas)
a.binaries = _reachable([e for e in a.binaries if not _left_out(e[0])])
a.datas = [e for e in a.datas if not _left_out(e[0])]
present = {e[0].replace("\\", "/") for e in a.binaries + a.datas if e[2] != "SYMLINK"}
a.binaries = _live_links(a.binaries, present)
a.datas = _live_links(a.datas, present)
print("OnCallScheduler.spec: left out %.1f MB of the %.1f MB analysis collected"
      % ((collected - _size(a.binaries) - _size(a.datas)) / 2**20, collected / 2**20))

# Windows carries its own text recognition, gathered by tools/collect_tesseract.py.
# Added only now, after analysis, so PyInstaller does not follow the DLLs as
# well and put a second copy of each beside the app -- which it did, twice over
# for the largest of them.
if os.path.isdir("tesseract"):
    for root, _, files in os.walk("tesseract"):
        for name in files:
            path = os.path.join(root, name)
            a.datas.append((path, path, "DATA"))

# What Windows shows in the file's own properties: who wrote it, what it is,
# which version. This is not what the "unknown publisher" warning asks for --
# that is a signature, and no amount of metadata substitutes for one -- but an
# unsigned file with no author at all tells the person looking at it nothing,
# and this at least attributes it.
if WINDOWS:
    import oncall

    numbers = (list(int(n) for n in oncall.__version__.split(".")) + [0, 0, 0, 0])[:4]
    version_resource = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(v)s, prodvers=%(v)s, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable("040904B0", [
        StringStruct("CompanyName", "Caden DeNike"),
        StringStruct("FileDescription", "On-Call Scheduler"),
        StringStruct("FileVersion", "%(s)s"),
        StringStruct("InternalName", "OnCallScheduler"),
        StringStruct("LegalCopyright", "Copyright (C) 2026 Caden DeNike. GPL v3 or later."),
        StringStruct("OriginalFilename", "OnCallScheduler.exe"),
        StringStruct("ProductName", "On-Call Scheduler"),
        StringStruct("ProductVersion", "%(s)s")])]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])])
  ]
)
""" % {"v": tuple(numbers), "s": oncall.__version__}
    with open("version_info.txt", "w", encoding="utf-8") as handle:
        handle.write(version_resource)

pyz = PYZ(a.pure)

# Not compressed with UPX. It would take perhaps another third off, but
# UPX-packed executables are routinely flagged by antivirus software, and for
# an app passed round an office that is worse than a larger download.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OnCallScheduler",
    console=False,          # no console window behind the app on Windows
    icon="data/oncall-scheduler.ico" if WINDOWS else None,
    version="version_info.txt" if WINDOWS else None,
    upx=False,
    # Debug symbols off the Linux libraries. PyInstaller advises against
    # stripping on Windows, where it saves nothing and can break a DLL.
    strip=not WINDOWS,
)
