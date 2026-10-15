"""Explicit, scroll-safe paper substitution and late-driver confirmation."""
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton

from dialogs.base import ToolDialog
from ui.combo_popup import WideComboBox
from ui.print_layout import PaperDecision, size_label


class PrintPaperDialog(ToolDialog):
    def __init__(self, issue, choices, batch=False, parent=None, *, area_text=None):
        super().__init__("Confirm print paper", "print_paper_confirmation", parent)
        self.resize(620, 410)
        self.decision = PaperDecision("cancel")
        if area_text:
            text = area_text
        else:
            text = (f"PDF / requested paper: {size_label(issue.requested)}\n"
                    f"Printer's previous setting: {size_label(issue.current)}\n\n{issue.reason}")
        heading = QLabel(text)
        heading.setWordWrap(True)
        self._root.addWidget(heading)
        note = QLabel("Printer settings are reported by the driver; they do not confirm which paper is loaded in the tray.")
        note.setWordWrap(True)
        self._root.addWidget(note)
        self.paper = WideComboBox()
        for index, size in enumerate(choices):
            label = size_label(size)
            self.paper.addItem(("Printer settings — " if index == 0 else "") + label, size)
        if choices:
            self._root.addWidget(QLabel("Confirmed output paper"))
            self._root.addWidget(self.paper)
        self.remember = QCheckBox("Use this choice for identical cases in this batch")
        self.remember.setVisible(batch)
        self._root.addWidget(self.remember)
        self._root.addStretch(1)
        actions = QHBoxLayout()
        self.use_button = QPushButton("Use reported area" if area_text else "Use selected paper")
        self.use_button.clicked.connect(lambda: self._choose("use"))
        actions.addWidget(self.use_button)
        if batch:
            self.skip_button = QPushButton("Skip this file")
            self.skip_button.clicked.connect(lambda: self._choose("skip"))
            actions.addWidget(self.skip_button)
        cancel = QPushButton("Cancel batch" if batch else "Cancel print")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._root.addLayout(actions)

    def _choose(self, action):
        self.decision = PaperDecision(action, self.paper.currentData(), self.remember.isChecked())
        self.accept()


def choose_paper(parent, issue, choices, batch):
    dialog = PrintPaperDialog(issue, choices, batch, parent)
    return dialog.decision if dialog.exec() == QDialog.DialogCode.Accepted else PaperDecision("cancel")


def confirm_area(parent, before, after, batch):
    mode = "Fit will be recalculated" if after.scale_mode == 0 else "Your Actual Size / Custom Scale choice remains unchanged and may extend beyond the printable area"
    text = (f"The driver changed the printable area after starting the print job.\n"
            f"Before: {before.width} × {before.height} px at {before.dpi} dpi\n"
            f"Now: {after.width} × {after.height} px at {after.dpi} dpi\n\n{mode}.\n"
            "No page content has been drawn for this page. Cancelling cannot guarantee that a queued sheet is retracted.")
    dialog = PrintPaperDialog(None, [], batch, parent, area_text=text)
    return dialog.decision if dialog.exec() == QDialog.DialogCode.Accepted else PaperDecision("cancel")
