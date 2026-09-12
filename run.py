"""Entry point for the packaged builds.

PyInstaller needs a script rather than a module to start from, and this is that
script: it does nothing the `python3 -m oncall` route does not.

Copyright (C) 2026 Caden DeNike. Free software under the GNU General
Public License, version 3 or later, with no warranty. See LICENSE.
"""

import sys

from oncall.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
