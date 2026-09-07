"""Point a frozen process at its bundled Tcl/Tk libraries before GUI imports."""

from __future__ import annotations

import os
import sys
from pathlib import Path


bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
os.environ["TCL_LIBRARY"] = str(bundle_root / "_tcl_data")
os.environ["TK_LIBRARY"] = str(bundle_root / "_tk_data")
