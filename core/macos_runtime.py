"""Mac bundle bootstrap only; Windows imports and tool selection are untouched."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


def bootstrap():
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return
    if len(sys.argv) > 1 and sys.argv[1] in {"--print-worker", "--pdf-operations-worker", "--composition-worker"}:
        # Windowed Python clears sys streams, but Popen/QProcess still supplies
        # POSIX descriptors. Restore only worker streams, never GUI streams.
        for name, descriptor, mode in (("stdin", 0, "r"), ("stdout", 1, "w"), ("stderr", 2, "w")):
            if getattr(sys, name) is None:
                setattr(sys, name, os.fdopen(os.dup(descriptor), mode, encoding="utf-8", buffering=1))
    root = Path(sys._MEIPASS)
    gs = root / "ghostscript-resources"
    os.environ["GS_LIB"] = os.pathsep.join(str(gs / part) for part in ("Resource/Init", "Resource/Font", "lib"))
    os.environ["GS_FONTPATH"] = str(root / "build_assets/composition/fonts")
    # pyzbar's POSIX discovery does not look inside .app. Bind its loader to
    # the packaged dylib before wrapper.py allocates any scanner functions.
    library = root / "pyzbar" / "libzbar.dylib"
    if not library.is_file():
        raise RuntimeError("The Mac application is missing its barcode decoder.")
    from pyzbar import zbar_library
    zbar_library.load = lambda: (ctypes.CDLL(str(library)), [])


if __name__ == "__main__":
    bootstrap()
