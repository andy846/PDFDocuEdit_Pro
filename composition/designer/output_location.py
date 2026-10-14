"""Production destination preference, independent from asset/profile browsing."""
from PyQt6.QtCore import QSettings, QStandardPaths
from PyQt6.QtWidgets import QFileDialog


def choose_output_directory(parent, *, settings=None, title="Production output folder: a new job subfolder will be created"):
    if settings is None:
        settings=QSettings()
        settings.beginGroup("document_designer")
    directory=settings.value("production/output_directory", "", type=str)
    if not directory:
        directory=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    selected=QFileDialog.getExistingDirectory(parent,title,directory)
    if selected:
        settings.setValue("production/output_directory",selected)
    return selected
