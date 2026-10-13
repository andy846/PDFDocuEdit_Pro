"""Persistent, headless print rasterizer. MuPDF objects never leave this process."""
from __future__ import annotations

import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path

import fitz


def _windows_pipe_stream(number, mode):
    """Bind inherited Popen pipes when a windowed bootloader clears sys streams."""
    if sys.platform != "win32":
        raise RuntimeError("Print worker requires redirected standard streams.")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_handle = ctypes.WinDLL("kernel32", use_last_error=True).GetStdHandle
    get_handle.argtypes = [wintypes.DWORD]
    get_handle.restype = wintypes.HANDLE
    handle = get_handle(number)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise RuntimeError("Print worker pipe handle is unavailable.")
    flags = (os.O_RDONLY if mode == "r" else os.O_WRONLY) | os.O_BINARY
    descriptor = msvcrt.open_osfhandle(handle, flags)
    return os.fdopen(descriptor, mode, encoding="utf-8", newline="\n")


def main(argv=None):
    from auth.guard import require_worker_access
    require_worker_access()
    with ExitStack() as streams:
        stdin = sys.stdin if sys.stdin is not None else streams.enter_context(_windows_pipe_stream(-10, "r"))
        stdout = sys.stdout if sys.stdout is not None else streams.enter_context(_windows_pipe_stream(-11, "w"))
        return _serve(argv, stdin, stdout)


def _serve(argv, stdin, stdout):
    directory = Path((argv or sys.argv[1:])[0]).resolve()
    cancel = directory / "cancel"
    document = None
    pages = ()
    print(json.dumps({"event": "ready", "pid": os.getpid()}), file=stdout, flush=True)
    try:
        for line in stdin:
            request = json.loads(line)
            ident = request["id"]
            try:
                command = request["command"]
                if command == "shutdown":
                    break
                if cancel.exists() and command != "close_document":
                    raise RuntimeError("Print cancelled.")
                if command == "prepare":
                    if document is not None:
                        raise RuntimeError("Previous print document was not closed.")
                    source = Path(request["source"])
                    snapshot = directory / "input.pdf"
                    if source.resolve() != snapshot:
                        before = source.stat()
                        with source.open("rb") as src, snapshot.open("wb") as dst:
                            while chunk := src.read(1024 * 1024):
                                if cancel.exists():
                                    raise RuntimeError("Print cancelled.")
                                dst.write(chunk)
                        after = source.stat()
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise RuntimeError("PDF changed while preparing print input; try again.")
                    document = fitz.open(snapshot)
                    if document.needs_pass:
                        raise ValueError("The PDF requires a password.")
                    pages = tuple(request["pages"] if request["pages"] is not None else range(len(document)))
                    if not pages or any(type(p) is not int or not 0 <= p < len(document) for p in pages):
                        raise ValueError("No valid printable pages were selected.")
                    rect = document[pages[0]].rect
                    value = {"pages": pages, "first_size": [rect.width, rect.height]}
                elif command == "render_page":
                    page = document[pages[request["index"]]]
                    pix = page.get_pixmap(dpi=min(600, max(72, int(request["dpi"]))), alpha=False,
                                          colorspace=fitz.csRGB)
                    if cancel.exists():
                        raise RuntimeError("Print cancelled.")
                    frame = directory / "page.rgb"
                    frame.write_bytes(pix.samples)
                    value = {"width": pix.width, "height": pix.height, "stride": pix.stride,
                             "page_size": [page.rect.width, page.rect.height]}
                    del pix
                elif command == "close_document":
                    if document is not None:
                        document.close()
                        document = None
                    (directory / "input.pdf").unlink(missing_ok=True)
                    (directory / "page.rgb").unlink(missing_ok=True)
                    value = None
                else:
                    raise ValueError("Unknown print command.")
                response = {"id": ident, "result": value}
            except Exception as exc:
                if request["command"] == "prepare" and document is not None:
                    document.close()
                    document = None
                response = {"id": ident, "error": str(exc)}
            print(json.dumps(response), file=stdout, flush=True)
    finally:
        if document is not None:
            document.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
