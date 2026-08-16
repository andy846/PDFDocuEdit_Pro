"""Headless core package.

The GUI is intentionally not imported here so PDF services can be used in
scripts and tests without loading Qt platform plugins.
"""

from .pdf_engine import PdfEngine, parse_page_range
from .settings import RecentFilesManager, SettingsManager

__all__ = ["PdfEngine", "RecentFilesManager", "SettingsManager", "parse_page_range"]
