"""One headless engine configuration shared by editor and worker processes.

PyMuPDF 2 imports its structured-extraction stack by default. This application
uses native text / geometry APIs; keep their established extraction settings.
The fitz alias preserves existing type names without importing the deprecated
compatibility module. Importing core itself remains lazy and Qt-free.
"""
import sys
from importlib.metadata import version

# The Windows 2.0 distribution initializes ONNX while importing pymupdf. With
# Qt DLLs already loaded that can access-violate before Python can catch it.
# Fail explicitly for unsupported embedding order; application entrypoints
# initialize this module before Qt. Never leave a half-initialized PDF engine.
if (sys.platform == "win32" and "PyQt6.QtCore" in sys.modules and "pymupdf" not in sys.modules
        and version("PyMuPDF").split(".")[0] == "2"):
    raise RuntimeError("Initialize the PDF backend before Qt when using PyMuPDF 2 on Windows.")

import pymupdf as fitz  # noqa: E402

if tuple(fitz.VersionBind.split("."))[:1] == ("2",):
    fitz.use_layout(False)

# pymupdf4llm imports change this process-wide setting even when no structured
# extraction is requested. False is the pinned 1.26.6 native-quad default.
fitz.TOOLS.unset_quad_corrections(False)

__all__ = ["fitz"]
