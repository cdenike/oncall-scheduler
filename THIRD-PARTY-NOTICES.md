# Third-party notices

The released binaries carry other people's work inside them. This lists what,
under which licence, and what that asks of anyone redistributing a build. It
was written from the contents of a released Windows executable and the Linux
build beside it, not from a dependency list, so it says what actually ships.

Running from source carries none of this: `python -m oncall` uses the Qt,
Pillow and tesseract already installed on the machine, under whatever terms
those were installed.

## In both builds

| Component | Licence | Why it is there |
| --- | --- | --- |
| Qt 6 (Qt6Core, Qt6Gui, Qt6Widgets, Qt6Svg and the platform, style, image and icon plugins) | LGPL v3 | the window and everything in it |
| PySide6, shiboken6 | LGPL v3 | Qt, from Python |
| Pillow (`PIL._imaging`, `_imagingft`, `_imagingmath`) | MIT-CMU | draws the calendar, prepares scans |
| CPython 3.12 and its standard extension modules | Python Software Foundation License 2.0 | the language |
| PyInstaller's bootloader (`run`, `pyimod*`, `pyi_rth_*`) | GPL v2 or later, with an exception for the programs it bundles | starts the bundled program |
| FreeType, libpng, zlib (inside Pillow) | FreeType License / libpng License / zlib License | text and image handling |

Windows builds additionally carry Microsoft's Visual C++ runtime
(`VCRUNTIME140*.dll`, `MSVCP140*.dll`, `ucrtbase.dll`, the `api-ms-win-*`
stubs) under Microsoft's redistributable terms.

No fonts are bundled. The calendar is drawn with a font found on the machine
it runs on -- Liberation Sans, Arial, DejaVu, whichever is there.

## In the Windows build only

Windows has no package manager to ask for text recognition, so the build
carries it. Linux takes it from the distribution instead, and none of the
following is in the Linux build.

| Component | Licence |
| --- | --- |
| Tesseract (`libtesseract-5`, `tesseract.exe`) and the `eng` training data | Apache License 2.0 |
| Leptonica | BSD 2-clause |
| libtiff | libtiff License (BSD-like) |
| **JBIG-KIT** (`libjbig-0.dll`) | **GPL v2 or later** |
| libjpeg | IJG License |
| libpng, zlib, libdeflate, libwebp, libsharpyuv, libgif, OpenJPEG, LERC, zstd, lz4, brotli, bzip2, xz/liblzma, expat, libarchive, libpsl, libssh2, libcurl | permissive: BSD 2- and 3-clause, MIT, zlib, Apache 2.0, public domain |
| GCC runtime (`libgcc_s_seh-1`, `libstdc++-6`) | GPL v3 with the GCC Runtime Library Exception |
| libiconv, gettext runtime (`libintl-8`), libidn2, libunistring | LGPL v2.1 or v3 |
| mingw-w64 runtime (`libwinpthread-1`) | ZPL 2.1 / permissive |

## What this asks of a redistributor

**JBIG-KIT is the one that decides the licence of the Windows binary.**
JBIG-KIT is GPL v2 or later, and it is not optional here: libtiff imports it
outright, Leptonica and tesseract import libtiff, so removing it stops
recognition from loading at all. Nothing in this program ever asks for JBIG --
it reads and writes PNG -- and JBIG-KIT's author says in the accompanying
notes that he does not intend the GPL to reach a program that leaves the
feature alone, but that intent is not in the licence text. Taken at its word,
the Windows executable as a whole must be distributed under terms compatible
with the GPL. JBIG-KIT is "or later", so GPL v3 serves, and GPL v3 also
absorbs the LGPL v3 and Apache 2.0 pieces without conflict. The Linux build
has no such component.

**LGPL v3 (Qt, PySide6, and the small GNU libraries)** asks that whoever
receives a binary be able to run it against their own build of the library.
A single-file bundle does not let them swap a file, so what stands in for it
is the build itself: the source is public, and `.github/workflows/build.yml`
is the exact recipe, so anyone can rebuild the program against a Qt of their
own. Neither Qt nor any other LGPL component here has been modified.

**Apache 2.0 (tesseract)** asks that this notice travel with the binary.

**MIT-CMU, BSD, zlib, IJG, PSF and the rest** ask that the copyright notice
and licence text travel with the binary, which is what this file is for.

The full licence texts are not reproduced here. Each project ships its own,
and they are at the projects' own sites; a release that bundles this file
should link them.
