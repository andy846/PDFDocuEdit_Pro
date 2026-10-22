"""Keep complete native and optional 2.x runtime resources in offline QA builds."""
from importlib.metadata import version

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

datas = collect_data_files("pymupdf", excludes=["mupdf-devel/**", "**/__pycache__/**"])
datas += copy_metadata("PyMuPDF")
binaries = collect_dynamic_libs("pymupdf")
hiddenimports = ["pymupdf.mupdf", "pymupdf.extra"]

if version("PyMuPDF").split(".")[0] == "2":
    # Do not make a no-deps / stripped-model candidate appear representative
    # of the official distribution. The application disables layout use, not
    # its installed dependency requirements or offline resources.
    hiddenimports += ["pymupdf4llm", "pymupdf.layout", "onnxruntime"]
    datas += collect_data_files("pymupdf4llm")
    for package in ("pymupdf4llm", "pymupdf-layout", "onnxruntime", "networkx", "pyyaml", "psutil", "tabulate"):
        datas += copy_metadata(package)
