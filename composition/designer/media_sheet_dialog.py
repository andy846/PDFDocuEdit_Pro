"""Explicit Stock choices for fixed template front/back pairs; no template mutation."""
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from composition.media.model import valid_id


class DuplexSheetDialog(QDialog):
    def __init__(self,pages,stocks,assignments,fallback,mode,parent=None):
        ids=[row[0] for row in stocks]
        if not ids or len(set(ids))!=len(ids) or any(not valid_id(key) for key in ids):
            raise ValueError("Add Stocks with unique valid IDs before assigning sheets.")
        super().__init__(parent)
        self.setWindowTitle("Duplex sheets · assign paper to front and back")
        self.resize(640,420)
        self.assignments=None
        self.pairs=[]
        root=QVBoxLayout(self)
        note=QLabel("Each row is one physical sheet per record. The same Stock is used on both sides. This updates page rules only; no pages are reordered or added here.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.table=QTableWidget((len(pages)+1)//2,3)
        self.table.setHorizontalHeaderLabels(["Front template page","Back template page","Stock"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table,1)
        for index in range(0,len(pages),2):
            pair=pages[index:index+2]
            keys=[p["id"] if mode=="template" else str(index+i+1) for i,p in enumerate(pair)]
            current=[assignments.get(key) or fallback for key in keys]
            box=QComboBox()
            box.addItem("Choose Stock…","")
            for key,name,*_ in stocks:
                box.addItem(f"{key} · {name}",key)
            if len(set(current))==1 and current[0] in ids:
                box.setCurrentIndex(box.findData(current[0]))
            elif len(set(current))>1:
                box.setToolTip("Current front/back rules differ: "+" / ".join(value or "unassigned" for value in current))
            row=index//2
            for side in range(2):
                label=f"{index+side+1} · {pair[side].get('name','Page')}" if side<len(pair) else "Blank back (end of record)"
                item=QTableWidgetItem(label)
                item.setToolTip(label)
                self.table.setItem(row,side,item)
            self.table.setCellWidget(row,2,box)
            self.pairs.append((keys,box))
        self.error=QLabel()
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def accept(self):
        assignments={}
        for row,(keys,box) in enumerate(self.pairs,1):
            stock=box.currentData()
            if not stock:
                self.error.setText(f"Sheet {row}: select a Stock for its front/back pages.")
                return
            assignments.update(dict.fromkeys(keys,stock))
        self.assignments=assignments
        super().accept()
