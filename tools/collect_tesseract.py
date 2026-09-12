"""Copy tesseract, and only what it needs, into ./tesseract for the build.

Windows carries its own recognition, because a Windows machine has no package
manager to ask. Linux takes it from the one it has: bundling it there meant a
second copy of ICU, 35 MB of it, beside the one Qt already brings, to spare
one apt install.

Windows installs carry the training tools' dependencies alongside the program
itself -- ICU, cairo, pango, fontconfig -- and copying every DLL in the folder
took all of them: 91 MB, of which recognising text needs 45. What tesseract.exe
needs is read from its own import tables, and theirs in turn, so the list stays
right when a new release changes what links against what.

    python tools/collect_tesseract.py [install folder]

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import os
import shutil
import sys

SOURCE = sys.argv[1] if len(sys.argv) > 1 else None
TARGET = "tesseract"

def windows_imports(path):
    """The DLL names a file loads at start, delay-loaded ones included."""
    import pefile       # installed with PyInstaller on Windows

    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    names = [entry.dll.decode("ascii", "replace")
             for table in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
             for entry in getattr(pe, table, [])]
    pe.close()
    return names


def collect_windows(source):
    present = {name.lower(): name for name in os.listdir(source)}
    needed, stack = set(), ["tesseract.exe"]
    while stack:
        name = stack.pop().lower()
        if name in needed or name not in present:
            continue                # already taken, or part of Windows itself
        needed.add(name)
        stack.extend(windows_imports(os.path.join(source, present[name])))
    for name in sorted(needed):
        shutil.copy2(os.path.join(source, present[name]), TARGET)
    return os.path.join(source, "tessdata", "eng.traineddata")


os.makedirs(os.path.join(TARGET, "tessdata"), exist_ok=True)
trained = collect_windows(SOURCE or r"C:\Program Files\Tesseract-OCR")
shutil.copy2(trained, os.path.join(TARGET, "tessdata"))

size = lambda paths: sum(os.path.getsize(p) for p in paths) / 2**20
taken = [os.path.join(root, f) for root, _, files in os.walk(TARGET) for f in files]
print("collected %d files, %.1f MB into %s/" % (len(taken), size(taken), TARGET))
