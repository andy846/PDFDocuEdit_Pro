import sys
import os
import fitz
import shutil
import tempfile
import pandas as pd
import math
import time
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QLabel, QLineEdit, QGridLayout, QMessageBox, QComboBox, QShortcut, QProgressBar, QDialog, QSplashScreen, QScrollArea, QRadioButton, QListWidget, QAbstractItemView, QDockWidget, QMenu, QAction, QToolBar, QToolButton, QInputDialog, QDialogButtonBox, QTabWidget, QGroupBox, QProgressDialog, QDoubleSpinBox, QSpinBox, QCheckBox
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from pdf2docx import Converter
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtGui import QPainter, QPen, QPalette, QColor, QFont
from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QSizePolicy
from openpyxl.utils import get_column_letter
from openpyxl import Workbook


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class LoadFontsThread(QThread):
    update_signal = pyqtSignal(str)

    def __init__(self, pdf_doc):
        super().__init__()
        self.pdf_doc = pdf_doc

    def run(self):
        font_set = set()
        for page in self.pdf_doc:
            if hasattr(page, 'get_fonts'):
                fontlist = page.get_fonts()
                for font in fontlist:
                    font_name, embedded_flag, font_type, base_font = font[4], font[1], font[2], font[3]
                    embedded = "(EMBEDDED)" if embedded_flag == 65535 else ""
                    font_info = f"名稱: {font_name}, 類型: {font_type}, 基礎字體: {base_font} {embedded}"
                    font_set.add(font_info)

        font_details = "文件字體種類:\n" + "\n".join(sorted(font_set))
        self.update_signal.emit(font_details)


class PDFInfoDialog(QDialog):
    def __init__(self, pdf_doc, parent=None):
        super().__init__(parent)
        self.pdf_doc = pdf_doc
        self.setWindowTitle("PDF内容")
        self.setMinimumSize(600, 380)
        self.layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.currentChanged.connect(self.tab_changed)
        
        self.create_general_info_tab()
        self.layout.addWidget(self.tab_widget)

        self.fonts_thread = LoadFontsThread(pdf_doc)
        self.fonts_thread.update_signal.connect(self.append_font_info)

        self.setup_style()

    def setup_style(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")

    def create_general_info_tab(self):
        # 創建一個QWidget作為標籤頁的主控件
        widget = QWidget()

        # 創建一個可滾動區域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # 創建布局管理器
        layout = QVBoxLayout()

        # 檔案屬性分組
        group_box_file = QGroupBox("檔案屬性")
        layout_file = QVBoxLayout()
        label_path = QLabel(f"文件路徑: {self.pdf_doc.name}")
        label_name = QLabel(f"文件名: {os.path.basename(self.pdf_doc.name)}")
        label_size = QLabel(f"文件大小: {self.format_file_size(os.path.getsize(self.pdf_doc.name))}")
        layout_file.addWidget(label_path)
        layout_file.addWidget(label_name)
        layout_file.addWidget(label_size)
        group_box_file.setLayout(layout_file)

        # 頁面資訊分組
        group_box_page = QGroupBox("頁面資訊")
        layout_page = QVBoxLayout()
        page_size = self.pdf_doc[0].rect
        width = round(page_size.width * 0.3528, 2)  # 將點數轉換為毫米
        height = round(page_size.height * 0.3528, 2)
        label_page_size = QLabel(f"頁面尺寸: {width}mm × {height}mm")
        label_page_count = QLabel(f"頁數: {self.pdf_doc.page_count}")
        layout_page.addWidget(label_page_size)
        layout_page.addWidget(label_page_count)
        group_box_page.setLayout(layout_page)

        # 文件元數據分組
        group_box_meta = QGroupBox("文件元數據")
        layout_meta = QVBoxLayout()
        info = self.pdf_doc.metadata
        label_creation_date = QLabel(f"創建日期: {info.get('CreationDate', '未知')}")
        label_mod_date = QLabel(f"修改日期: {info.get('ModDate', '未知')}")
        label_author = QLabel(f"作者: {info.get('Author', '未知')}")
        label_encrypted = QLabel(f"加密: {'是' if self.pdf_doc.is_encrypted else '否'}")
        label_producer = QLabel(f"生成器: {info.get('producer', '未知')}")
        layout_meta.addWidget(label_creation_date)
        layout_meta.addWidget(label_mod_date)
        layout_meta.addWidget(label_author)
        layout_meta.addWidget(label_encrypted)
        layout_meta.addWidget(label_producer)
        group_box_meta.setLayout(layout_meta)

        # 將分組框添加到布局
        layout.addWidget(group_box_file)
        layout.addWidget(group_box_page)
        layout.addWidget(group_box_meta)

        # 設置小部件的布局
        scroll_area.setWidget(widget)
        widget.setLayout(layout)

        # 在標籤頁控件中添加新的標籤頁
        self.tab_widget.addTab(scroll_area, "一般資訊")

        self.fonts_images_tab = QWidget()
        self.tab_widget.addTab(self.fonts_images_tab, "字體訊息")

    def tab_changed(self, index):
        if index == 1 and self.fonts_images_tab.layout() is None:
            self.setup_fonts_images_tab()
            self.fonts_thread.start()

    def setup_fonts_images_tab(self):
        # 创建一个QWidget作为标签页的主控件
        widget = QWidget()

        # 创建总布局管理器
        layout = QVBoxLayout(widget)  # 将布局直接绑定到widget上

        # 字体信息分组
        group_box_fonts = QGroupBox("字體信息")
        layout_fonts = QVBoxLayout()
        self.fonts_label = QLabel()
        self.fonts_label.setWordWrap(True)
        self.fonts_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fonts_label.setStyleSheet("QLabel { color: white; background-color: black; padding: 10px; }")
        layout_fonts.addWidget(self.fonts_label)
        group_box_fonts.setLayout(layout_fonts)

        # 将分组框添加到总布局
        layout.addWidget(group_box_fonts)

        # 创建一个可滚动区域并设置其内容部件
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(widget)  # 设置scroll_area的内容部件

        # 在标签页控件中设置scroll_area为tab的主内容
        self.fonts_images_tab.setLayout(QVBoxLayout())  # 确保tab有自己的布局
        self.fonts_images_tab.layout().addWidget(scroll_area)  # 将scroll_area添加到tab的布局中

    def append_font_info(self, font_info):
        if self.fonts_label.text():
            current_text = self.fonts_label.text()
            self.fonts_label.setText(current_text + '\n' + font_info)
        else:
            self.fonts_label.setText(font_info)

    def format_file_size(self, size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
    

class SortWidget(QDockWidget):
    sort_applied = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__("Page Sorting", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")


        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.page_list = QListWidget()
        self.page_list.itemDoubleClicked.connect(self.jump_to_page)
        self.page_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.page_list)

        button_layout = QHBoxLayout()
        self.move_up_button = QPushButton("Up")
        self.move_up_button.clicked.connect(self.move_item_up)
        button_layout.addWidget(self.move_up_button)

        self.move_down_button = QPushButton("Down")
        self.move_down_button.clicked.connect(self.move_item_down)
        button_layout.addWidget(self.move_down_button)

        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_sort)
        button_layout.addWidget(self.apply_button)

        layout.addLayout(button_layout)
        self.setWidget(widget)

    def update_page_list(self, page_count):
        self.page_list.clear()
        for i in range(page_count):
            self.page_list.addItem(f"Page {i+1}")

    def move_item_up(self):
        row = self.page_list.currentRow()
        if row > 0:
            item = self.page_list.takeItem(row)
            self.page_list.insertItem(row - 1, item)
            self.page_list.setCurrentRow(row - 1)

    def move_item_down(self):
        row = self.page_list.currentRow()
        if row < self.page_list.count() - 1:
            item = self.page_list.takeItem(row)
            self.page_list.insertItem(row + 1, item)
            self.page_list.setCurrentRow(row + 1)

    def apply_sort(self):
        order = []
        for i in range(self.page_list.count()):
            item_text = self.page_list.item(i).text()
            page_num = int(item_text.split()[1]) - 1
            order.append(page_num)
        self.sort_applied.emit(order)

    def jump_to_page(self, item):
        page_num = int(item.text().split()[1]) - 1
        self.parent().jump_to_page(page_num)

class DropArea(QWidget):
    # 自定義信號，用於當文件被拖放時發送文件路徑
    fileDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super(DropArea, self).__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(100)  # 設置 DropArea 的高度
        # 設置背景色
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor('light blue'))
        self.setPalette(palette)
        self.text = "將 PDF 文件拖拽到這裡"


    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toString().lower().endswith('.pdf')]
        self.fileDropped.emit(file_paths)  # 發送信號，附帶文件路徑

    def paintEvent(self, event):
        painter = QPainter(self)
        pen = QPen(Qt.black, 2, Qt.DashLine)
        painter.setPen(pen)
        rect = self.rect().adjusted(1, 1, -1, -1)  # 調整矩形以適應邊框寬度
        painter.drawRect(rect)

        # 設置文本的字體和顏色
        painter.setPen(QColor('black'))
        painter.setFont(QFont('Arial', 10, QFont.Bold))
        
        # 獲取控件中心點並根據文本大小調整位置
        text_rect = QRect(rect.left(), rect.top(), rect.width(), rect.height())
        painter.drawText(text_rect, Qt.AlignCenter, self.text)


class SearchWidget(QDockWidget):
    search_requested = pyqtSignal(str)  # 信号名字正确定义

    def __init__(self, parent=None):
        super().__init__("Searching Tools", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Enter search text")
        self.search_edit.returnPressed.connect(self.search)
        layout.addWidget(self.search_edit)

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search)
        layout.addWidget(self.search_button)

        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.jump_to_result)
        self.result_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.result_list)

        self.result_count_label = QLabel()
        self.result_count_label.setStyleSheet("color: white;")
        layout.addWidget(self.result_count_label)

        self.extract_ALL_button = QPushButton("Extract All Pages")
        self.extract_ALL_button.clicked.connect(self.extract_ALL_pages)
        layout.addWidget(self.extract_ALL_button)  # 修正变量名称错误

        self.delete_ALL_button = QPushButton("Delete All Pages")
        self.delete_ALL_button.clicked.connect(self.delete_ALL_pages)
        layout.addWidget(self.delete_ALL_button)  # 修正变量名称错误

        self.clear_button = QPushButton("Clear Result")
        self.clear_button.clicked.connect(self.clear_search)
        layout.addWidget(self.clear_button)

        self.setWidget(widget)

    def search(self):
        self.result_list.clear()
        text = self.search_edit.text()
        if text:
            self.search_requested.emit(text)
        else:
            self.result_count_label.setText("No input for search.")

    def update_results(self, results):
        self.result_list.clear()
        for page_num, _ in results:
            self.result_list.addItem(f"Page {page_num + 1}")
        self.result_count_label.setText(f"Found {len(results)} results")

    def clear_result_list(self):
        """清空搜索结果列表和相关显示内容。"""
        self.result_list.clear()
        self.result_count_label.setText("")

    def extract_pages(self):
        pages_to_extract = [int(item.text().split()[1]) - 1 for item in self.result_list.selectedItems()]
        self.parent().extract_pages_by_number(pages_to_extract)

    def delete_pages(self):
        try:
            pages_to_delete = [int(item.text().split()[1]) - 1 for item in self.result_list.selectedItems()]
            self.parent().delete_pages_by_number(pages_to_delete)
        except Exception as e:
            print(f"Error during deleting pages: {e}")

    def jump_to_result(self, item):
        page_num = int(item.text().split()[1]) - 1
        self.parent().jump_to_page(page_num)

    def clear_search(self):
        self.search_edit.clear()
        self.result_list.clear()
        self.result_count_label.setText("")
        self.parent().clear_highlights()
        self.parent().search_results.clear()

    def contextMenuEvent(self, event):
        selected_items = self.result_list.selectedItems()
        if selected_items:
            menu = QMenu(self)
            extract_action = menu.addAction("Extract Pages")
            delete_action = menu.addAction("Delete Pages")
            action = menu.exec_(event.globalPos())
            if action == extract_action:
                self.extract_pages()
            elif action == delete_action:
                self.delete_pages()

    def extract_ALL_pages(self):
        # 获取所有搜索结果页面编号
        pages_to_extract = [int(item.text().split()[1]) - 1 for item in self.result_list.findItems("*", Qt.MatchWildcard)]
        if pages_to_extract:
            self.parent().extract_pages_by_number(pages_to_extract)
        else:
            QMessageBox.information(self, "Information", "No pages to extract.")

    def delete_ALL_pages(self):
            # 获取所有搜索结果页面编号
            pages_to_delete = [int(item.text().split()[1]) - 1 for item in self.result_list.findItems("*", Qt.MatchWildcard)]
            if pages_to_delete:
                self.parent().delete_pages_by_number(pages_to_delete)
            else:
                QMessageBox.information(self, "Information", "No pages to delete.")

class MergePDFsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("合併PDF文件")
        self.setMinimumSize(500, 300)
        self.file_paths = []  # 用於存儲添加的PDF文件路徑
        self.initUI()

    def initUI(self):
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")


        layout = QVBoxLayout(self)

        # 創建 DropArea 並添加到佈局
        self.drop_area = DropArea()
        self.drop_area.fileDropped.connect(self.files_dropped)
        layout.addWidget(self.drop_area)

        # 創建列表部件
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("添加PDF")
        self.btn_add.clicked.connect(self.add_pdf)
        btn_layout.addWidget(self.btn_add)

        self.btn_remove = QPushButton("移除PDF")
        self.btn_remove.clicked.connect(self.remove_pdf)
        btn_layout.addWidget(self.btn_remove)

        self.btn_up = QPushButton("上移")
        self.btn_up.clicked.connect(self.move_up)
        btn_layout.addWidget(self.btn_up)

        self.btn_down = QPushButton("下移")
        self.btn_down.clicked.connect(self.move_down)
        btn_layout.addWidget(self.btn_down)

        layout.addLayout(btn_layout)
        

        self.btn_merge = QPushButton("合併PDF")
        self.btn_merge.clicked.connect(self.merge_pdfs)
        layout.addWidget(self.btn_merge)
        

    def files_dropped(self, file_paths):
        for path in file_paths:
            if path not in self.file_paths:
                self.file_paths.append(path)
                self.list_widget.addItem(path)

    def add_pdf(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "選擇PDF文件", "", "PDF files (*.pdf)")
        for path in file_paths:
            if path not in self.file_paths:
                self.file_paths.append(path)
                self.list_widget.addItem(path)

    def remove_pdf(self):
        for item in self.list_widget.selectedItems():
            self.file_paths.remove(item.text())
            self.list_widget.takeItem(self.list_widget.row(item))

    def move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self.file_paths.insert(row - 1, self.file_paths.pop(row))
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentItem(item)

    def move_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            self.file_paths.insert(row + 1, self.file_paths.pop(row))
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentItem(item)

    def merge_pdfs(self):
        if self.file_paths:
            merged_doc = fitz.open()
            for path in self.file_paths:
                with fitz.open(path) as doc:
                    merged_doc.insert_pdf(doc)
            save_path, _ = QFileDialog.getSaveFileName(self, "保存合併後的PDF文件", "", "PDF files (*.pdf)")
            if save_path:
                merged_doc.save(save_path)
                QMessageBox.information(self, "成功", "PDF文件已成功合併！")


class ExtractPagesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extract Page Options")
        self.setMinimumSize(400, 200)
        app.setStyle("Fusion")  # Use Fusion style for better dark mode support
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")
        
        layout = QVBoxLayout()

        # Extract odd pages option
        self.radio_odd_pages = QRadioButton("提取單數頁面")
        layout.addWidget(self.radio_odd_pages)

        # Extract even pages option
        self.radio_even_pages = QRadioButton("提取雙數頁面")
        layout.addWidget(self.radio_even_pages)

        # Extract multiple pages option
        self.radio_multiple_pages = QRadioButton("提取[N]為倍數的頁面")
        self.multiple_pages_edit = QLineEdit()
        self.multiple_pages_edit.setPlaceholderText("輸入倍數")
        self.multiple_pages_edit.setEnabled(False)
        self.radio_multiple_pages.toggled.connect(self.multiple_pages_edit.setEnabled)
        layout.addWidget(self.radio_multiple_pages)
        layout.addWidget(self.multiple_pages_edit)

        # Custom pages option
        self.radio_custom_pages = QRadioButton("自定義頁面")
        self.custom_pages_edit = QLineEdit()
        self.custom_pages_edit.setPlaceholderText("e.g., 1,3,5-7")
        self.custom_pages_edit.setEnabled(False)
        self.radio_custom_pages.toggled.connect(self.custom_pages_edit.setEnabled)
        layout.addWidget(self.radio_custom_pages)
        layout.addWidget(self.custom_pages_edit)

        # Confirm button
        confirm_button = QPushButton("確認")
        confirm_button.clicked.connect(self.accept)
        layout.addWidget(confirm_button, alignment=Qt.AlignRight)

        self.setLayout(layout)

    def get_extract_options(self):
        if self.radio_odd_pages.isChecked():
            return "odd"
        elif self.radio_even_pages.isChecked():
            return "even"
        elif self.radio_multiple_pages.isChecked() and self.multiple_pages_edit.text().isdigit():
            return "multiple", int(self.multiple_pages_edit.text())
        elif self.radio_custom_pages.isChecked():
            return "custom", self.custom_pages_edit.text()
        return None

class PDFConverter(QThread):
    progress_updated = pyqtSignal(int)
    
    def __init__(self, pdf_path, docx_path):
        super().__init__()
        self.pdf_path = pdf_path
        self.docx_path = docx_path

    def run(self):
        try:
            cv = Converter(self.pdf_path)
            cv.convert(self.docx_path, start=0, end=None)
            cv.close()
        except Exception as e:
            print(f"轉換失敗：{e}")

class DeletePagesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("刪除頁面選項")
        self.setMinimumSize(400, 200)
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")
        
        layout = QVBoxLayout()

        # 刪除單數頁碼選項
        self.radio_odd_pages = QRadioButton("刪除單數頁碼")
        layout.addWidget(self.radio_odd_pages)

        # 刪除雙數頁碼選項
        self.radio_even_pages = QRadioButton("刪除雙數頁碼")
        layout.addWidget(self.radio_even_pages)

        # 刪除倍數頁碼選項
        self.radio_multiple_pages = QRadioButton("刪除[N]倍數頁碼")
        self.multiple_pages_edit = QLineEdit()
        self.multiple_pages_edit.setPlaceholderText("輸入倍數")
        self.multiple_pages_edit.setEnabled(False)
        self.radio_multiple_pages.toggled.connect(self.multiple_pages_edit.setEnabled)
        layout.addWidget(self.radio_multiple_pages)
        layout.addWidget(self.multiple_pages_edit)

        # 自定義頁碼選項
        self.radio_custom_pages = QRadioButton("自定義頁碼")
        self.custom_pages_edit = QLineEdit()
        self.custom_pages_edit.setPlaceholderText("例如：1,3,5-7")
        self.custom_pages_edit.setEnabled(False)
        self.radio_custom_pages.toggled.connect(self.custom_pages_edit.setEnabled)
        layout.addWidget(self.radio_custom_pages)
        layout.addWidget(self.custom_pages_edit)

        # 確認按鈕
        confirm_button = QPushButton("確認")
        confirm_button.clicked.connect(self.accept)
        layout.addWidget(confirm_button, alignment=Qt.AlignRight)

        self.setLayout(layout)

    def get_delete_options(self):
        if self.radio_odd_pages.isChecked():
            return "odd"
        elif self.radio_even_pages.isChecked():
            return "even"
        elif self.radio_multiple_pages.isChecked() and self.multiple_pages_edit.text().isdigit():
            return "multiple", int(self.multiple_pages_edit.text())
        elif self.radio_custom_pages.isChecked():
            return "custom", self.custom_pages_edit.text()
        return None

class TextExtractorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提取PDF文本")
        self.setMinimumSize(600, 500)
        self.initUI()

    def mm_to_points(self, mm):
        return mm * 72 / 25.4

    def initUI(self):
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")

        layout = QVBoxLayout()

        # PDF文件路徑輸入框
        pdf_path_layout = QHBoxLayout()
        pdf_path_label = QLabel("PDF文件:")
        self.pdf_path_edit = QLineEdit()
        pdf_path_button = QPushButton("瀏覽...")
        pdf_path_button.clicked.connect(self.select_pdf_file)
        pdf_path_layout.addWidget(pdf_path_label)
        pdf_path_layout.addWidget(self.pdf_path_edit)
        pdf_path_layout.addWidget(pdf_path_button)
        layout.addLayout(pdf_path_layout)

        # 座標輸入框
        coords_layout = QGridLayout()
        coords_layout.addWidget(QLabel("x1:"), 0, 0)
        self.x1_edit = QLineEdit()
        coords_layout.addWidget(self.x1_edit, 0, 1)
        coords_layout.addWidget(QLabel("y1:"), 0, 2)
        self.y1_edit = QLineEdit()
        coords_layout.addWidget(self.y1_edit, 0, 3)
        coords_layout.addWidget(QLabel("x2:"), 1, 0)
        self.x2_edit = QLineEdit()
        coords_layout.addWidget(self.x2_edit, 1, 1)
        coords_layout.addWidget(QLabel("y2:"), 1, 2)
        self.y2_edit = QLineEdit()
        coords_layout.addWidget(self.y2_edit, 1, 3)
        layout.addLayout(coords_layout)

        # 頁碼輸入框
        page_layout = QHBoxLayout()
        page_label = QLabel("預覽頁碼:")
        page_label.setAlignment(Qt.AlignRight)
        page_layout.addWidget(page_label)

        self.prev_page_button = QPushButton("<")  # 添加“<”按钮
        self.prev_page_button.clicked.connect(self.show_prev_page)
        self.prev_page_button.setFixedWidth(30)
        page_layout.addWidget(self.prev_page_button)

        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(30)
        page_layout.addWidget(self.page_edit)

        self.next_page_button = QPushButton(">")  # 添加“>”按钮
        self.next_page_button.clicked.connect(self.show_next_page)
        self.next_page_button.setFixedWidth(30)
        page_layout.addWidget(self.next_page_button)
        layout.addLayout(page_layout)

        # 預覽按鈕
        self.preview_button = QPushButton("預覽")
        self.preview_button.clicked.connect(self.update_preview)
        layout.addWidget(self.preview_button)

        # 預覽區域
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.scroll_area = QScrollArea()
        self.scroll_area.setMinimumSize(400, 200)
        self.scroll_area.setWidgetResizable(True)  # 允許內容根據視窗大小調整
        self.scroll_area.setWidget(self.preview_label)  # 將預覽標籤添加到滾動區域
        
        layout.addWidget(self.scroll_area)  # 在佈局中添加滾動區域而不是僅僅添加預覽標籤
        

        # 提取按鈕
        self.extract_button = QPushButton("Extract to Excel")
        self.extract_button.clicked.connect(self.extract_to_excel)
        layout.addWidget(self.extract_button)

        self.setLayout(layout)


    def show_prev_page(self):
        try:
            current_page = int(self.page_edit.text())
            if current_page > 1:
                self.page_edit.setText(str(current_page - 1))
                self.update_preview()  # 更新预览
        except ValueError:
            pass  # 忽略无效输入

    def show_next_page(self):
        try:
            current_page = int(self.page_edit.text())
            pdf_path = self.pdf_path_edit.text()
            if pdf_path and current_page < fitz.open(pdf_path).page_count:
                self.page_edit.setText(str(current_page + 1))
                self.update_preview()  # 更新预览
        except ValueError:
            pass  # 忽略无效输入

    def select_pdf_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "選擇PDF文件", "", "PDF files (*.pdf)")
        if file_path:
            self.pdf_path_edit.setText(file_path)

    def update_preview(self):
        pdf_path = self.pdf_path_edit.text()
        try:
            page_num = int(self.page_edit.text()) - 1
        except ValueError:
            QMessageBox.warning(self, "警告", "請輸入有效的頁碼")
            return

        # 检查是否输入了坐标值
        if not all([self.x1_edit.text(), self.y1_edit.text(), self.x2_edit.text(), self.y2_edit.text()]):
            QMessageBox.warning(self, "警告", "請輸入所有座標值")
            return

        coords = (
            self.mm_to_points(float(self.x1_edit.text())),
            self.mm_to_points(float(self.y1_edit.text())),
            self.mm_to_points(float(self.x2_edit.text())),
            self.mm_to_points(float(self.y2_edit.text()))
        )

        try:
            page = fitz.open(pdf_path)[page_num]
            clip_rect = fitz.Rect(*coords)
            pix = page.get_pixmap(clip=clip_rect, matrix=fitz.Matrix(2, 2))
            qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            self.preview_label.setPixmap(QPixmap.fromImage(qimg))
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"生成預覽失敗：{e}")


    def extract_to_excel(self):
        pdf_path = self.pdf_path_edit.text()
        coords = (
            self.mm_to_points(float(self.x1_edit.text())),
            self.mm_to_points(float(self.y1_edit.text())),
            self.mm_to_points(float(self.x2_edit.text())),
            self.mm_to_points(float(self.y2_edit.text()))
        )

        try:
            doc = fitz.open(pdf_path)
            excel_path = os.path.splitext(pdf_path)[0] + "_extracted.xlsx"
            workbook = Workbook()
            sheet = workbook.active

            for page_num in range(doc.page_count):
                page = doc[page_num]
                text_blocks = page.get_text("blocks", clip=coords)
                sorted_blocks = sorted(text_blocks, key=lambda b: (b[1], b[0]))  # Sort text blocks by y1, x1 (top to bottom, then left to right)
                
                for block in sorted_blocks:
                    text = block[4].strip()  # Get the text from the block
                    lines = text.split('\n')  # Split the text into lines
                    
                    for line_num, line in enumerate(lines, start=1):  # Start counting from 1 (Excel rows start at 1)
                        if line:  # Avoid adding empty lines
                            cell_ref = f"{get_column_letter(line_num)}{page_num+1}"
                            sheet[cell_ref] = line  # Output each line to the corresponding cell

            workbook.save(excel_path)
            QMessageBox.information(self, "成功", f"提取的文本已保存到：{excel_path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"提取文本失敗：{e}")

class InsertPagesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()

    def initUI(self):
        # Set the window properties
        self.setWindowTitle("插入PDF頁面")
        self.setMinimumSize(400, 200)

        # Set the application style and color palette
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")

        # Main layout
        layout = QVBoxLayout()


        # Input for page range to insert
        page_range_layout = QHBoxLayout()
        page_range_label = QLabel("插入頁碼範圍:")
        self.page_range_edit = QLineEdit()
        page_range_layout.addWidget(page_range_label)
        page_range_layout.addWidget(self.page_range_edit)
        layout.addLayout(page_range_layout)

        # Selection for insertion position
        insert_pos_layout = QHBoxLayout()
        insert_pos_label = QLabel("插入位置:")
        self.insert_pos_combo = QComboBox()
        self.insert_pos_combo.addItems(["開頭", "結尾", "指定位置"])
        insert_pos_layout.addWidget(insert_pos_label)
        insert_pos_layout.addWidget(self.insert_pos_combo)
        layout.addLayout(insert_pos_layout)

        # Input for the page number at the insertion position
        insert_page_layout = QHBoxLayout()
        insert_page_label = QLabel("指定位置頁碼:")
        self.insert_page_edit = QLineEdit()
        insert_page_layout.addWidget(insert_page_label)
        insert_page_layout.addWidget(self.insert_page_edit)
        layout.addLayout(insert_page_layout)

        # Confirm button
        confirm_button = QPushButton("確認")
        confirm_button.clicked.connect(self.accept)
        layout.addWidget(confirm_button, alignment=Qt.AlignRight)

        # Set the layout to the dialog
        self.setLayout(layout)

class PrintOptionsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # 设置纸张大小选项
        self.setupPaperSize(layout)
        layout.addStretch(1)  # 添加弹性空间
        
        # 设置打印方向选项
        self.setupOrientation(layout)
        layout.addStretch(1)  # 添加弹性空间
        
        # 设置边距选项
        self.setupMargins(layout)
        # 设置全页打印选项（无边距）
        self.setupFullPage(layout)
        layout.addStretch(1)  # 添加弹性空间
        
        # 设置打印份数选项
        self.setupCopies(layout)
        layout.addStretch(5)  # 添加弹性空间
        
 
        # 设置打印按钮
        self.setupPrintButton(layout)
        layout.addStretch(1)
        
        # 应用布局
        self.setLayout(layout)

    def setupPaperSize(self, layout):
        group_box = QGroupBox("Paper Options")
        group_layout = QVBoxLayout()
        paper_size_label = QLabel("Paper Size:")
        self.paper_size_combo = QComboBox()
        self.paper_size_combo.addItems(["A4", "A3", "Letter", "Legal"])
        group_layout.addWidget(paper_size_label)
        group_layout.addWidget(self.paper_size_combo)
        group_box.setLayout(group_layout)
        layout.addWidget(group_box)
    
    def setupOrientation(self, layout):
        group_box = QGroupBox("Orientation")
        group_layout = QVBoxLayout()
        orientation_label = QLabel("Orientation:")
        self.portrait_radio = QRadioButton("Portrait")
        self.landscape_radio = QRadioButton("Landscape")
        self.portrait_radio.setChecked(True)
        orientation_layout = QHBoxLayout()
        orientation_layout.addWidget(self.portrait_radio)
        orientation_layout.addWidget(self.landscape_radio)
        group_layout.addWidget(orientation_label)
        group_layout.addLayout(orientation_layout)
        group_box.setLayout(group_layout)
        layout.addWidget(group_box)

    def setupMargins(self, layout):
        group_box = QGroupBox("Margins")
        group_layout = QVBoxLayout()
        margins_label = QLabel("Margins (mm):")
        margins_layout = QGridLayout()
        self.top_margin_spin = QDoubleSpinBox()
        self.bottom_margin_spin = QDoubleSpinBox()
        self.left_margin_spin = QDoubleSpinBox()
        self.right_margin_spin = QDoubleSpinBox()
        margins_layout.addWidget(QLabel("Top:"), 0, 0)
        margins_layout.addWidget(self.top_margin_spin, 0, 1)
        margins_layout.addWidget(QLabel("Bottom:"), 1, 0)
        margins_layout.addWidget(self.bottom_margin_spin, 1, 1)
        margins_layout.addWidget(QLabel("Left:"), 0, 2)
        margins_layout.addWidget(self.left_margin_spin, 0, 3)
        margins_layout.addWidget(QLabel("Right:"), 1, 2)
        margins_layout.addWidget(self.right_margin_spin, 1, 3)
        group_layout.addWidget(margins_label)
        group_layout.addLayout(margins_layout)
        group_box.setLayout(group_layout)
        layout.addWidget(group_box)

    def setupCopies(self, layout):
        group_box = QGroupBox("Number of Copies")
        group_layout = QVBoxLayout()
        copies_label = QLabel("Copies:")
        self.copies_spin = QSpinBox()
        self.copies_spin.setMinimum(1)
        group_layout.addWidget(copies_label)
        group_layout.addWidget(self.copies_spin)
        group_box.setLayout(group_layout)
        layout.addWidget(group_box)

    def setupFullPage(self, layout):
        self.full_page_checkbox = QCheckBox("Full Page (No Margins)")
        layout.addWidget(self.full_page_checkbox)

    def setupPrintButton(self, layout):
        self.print_button = QPushButton("Print")
        layout.addWidget(self.print_button)


class PDFViewer(QMainWindow):
    ZOOM_IN_FACTOR = 1.25  # 定义放大因子
    ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR  # 定义缩小因子
    def __init__(self):
        super().__init__()
        self.doc = None
        self.sort_widget = None
        self.current_page = 0
        self.zoom_ratio = 1.0
        self.min_zoom = 0.25
        self.max_zoom = 4.0
        self.original_pdf_path = None  # 原始PDF文件路徑
        self.temp_pdf_path = None  # 臨時PDF文件路徑
        self.setAcceptDrops(True)  # 啟用拖放功能
        self.search_widget = None
        self.search_results = []  
        self.open_windows = []  # Keep track of open windows 
        self.is_modified = False 
        self.initUI()

    def show_sort_widget(self):
        if not self.doc:
            self.show_warning("請先打開一個PDF文件。")
            return

        if self.sort_widget is None:
            # SortWidget 尚未创建，创建并显示
            self.sort_widget = SortWidget(self)
            self.sort_widget.sort_applied.connect(self.apply_page_sorting)
            self.addDockWidget(Qt.LeftDockWidgetArea, self.sort_widget)

        # 显示 SortWidget
        self.sort_widget.update_page_list(self.doc.page_count)
        self.sort_widget.show()

    def apply_page_sorting(self, order):
        if self.doc:
            self.doc.select(order)
            self.show_page(0)  # Show the first page after sorting
            self.show_success("Page order has been applied!")
        else:
            self.show_warning("Please open a PDF file first.")
        self.is_modified = True

    def merge_pdfs(self):
        merge_dialog = MergePDFsDialog(self)
        merge_dialog.exec_()  # 显示合并对话框

    def update_file_info(self, path):
        # 設置文件信息標籤
        if self.doc:
            file_info = f"文件路徑: {path} | 頁數: {self.doc.page_count}"
            self.file_info_label.setText(file_info)
        else:
            self.file_info_label.setText("未加載文件")


    def open_text_extractor(self):
        extractor_dialog = TextExtractorDialog(self)
        extractor_dialog.exec_()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        QApplication.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)
        self.setStyleSheet("QLabel { color: white; }")

        insert_action = menu.addAction("插入頁面")
        insert_action.triggered.connect(self.insert_pages_current)

        delete_action = menu.addAction("刪除頁面")
        delete_action.triggered.connect(self.delete_pages_current)

        extract_action = menu.addAction("提取頁面")
        extract_action.triggered.connect(self.extract_pages_current)

        rotate_action = menu.addAction("Rotate")
        rotate_action.triggered.connect(self.rotate_pages_current)
   
        pdf_info_action = menu.addAction("PDF 內容")
        pdf_info_action.triggered.connect(self.show_pdf_info)

        menu.exec_(event.globalPos())

    def insert_pages_current(self):
        if not self.doc:
            self.show_warning("請先打開一個PDF文件。")
            return

        insert_pdf_path, _ = QFileDialog.getOpenFileName(self, "選擇要插入的PDF文件", "", "PDF files (*.pdf)")
        if insert_pdf_path:
            try:
                page_range, ok = QInputDialog.getText(self, "頁碼範圍", "輸入要插入的頁碼範圍 (例如: 1,3,5-7):")
                if ok:
                    pages_to_insert = self.parse_page_range(page_range)
                    with fitz.open(insert_pdf_path) as insert_doc:
                        self.doc.insert_pdf(insert_doc, from_page=pages_to_insert[0], to_page=pages_to_insert[-1], start_at=self.current_page)
                    self.show_page(self.current_page)
                    self.show_success("頁面插入成功！")
            except Exception as e:
                self.show_error(str(e))
        self.is_modified = True

    def delete_pages_current(self):
        if not self.doc:
            self.show_warning("請先打開一個PDF文件。")
            return

        try:
            self.doc.delete_page(self.current_page)
            self.current_page = max(0, self.current_page - 1)  # Adjust current page index
            self.show_page(self.current_page)
            self.show_success("頁面已刪除！")
        except Exception as e:
            self.show_error(str(e))
        self.is_modified = True

    def extract_pages_current(self):
        if not self.doc:
            self.show_warning("請先打開一個PDF文件。")
            return

        extracted_doc = fitz.open()
        extracted_doc.insert_pdf(self.doc, from_page=self.current_page, to_page=self.current_page)
        save_path, _ = QFileDialog.getSaveFileName(self, "保存提取的頁面", "", "PDF files (*.pdf)")
        if save_path:
            extracted_doc.save(save_path)
            self.show_success("頁面已提取并保存！")
        self.is_modified = True

    def rotate_pages_current(self):
        if not self.doc:
            self.show_warning("請先打開一個PDF文件。")
            return

        angle, ok = QInputDialog.getInt(self, "旋轉角度", "輸入旋轉角度 (90, 180, 270):", min=0, max=360, step=90)
        if ok:
            try:
                page = self.doc.load_page(self.current_page)
                page.set_rotation(angle)
                self.show_page(self.current_page)
                self.show_success("頁面已旋轉！")
            except Exception as e:
                self.show_error(str(e))
        self.is_modified = True    
        
    def initUI(self):
        self.setWindowTitle('PDFDocuEdit Pro - 無檔案')
        self.setGeometry(100, 100, 1400, 800)

        print_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        print_shortcut.activated.connect(self.print_pdf)
        
        shortcut_first_page = QShortcut(QKeySequence("Ctrl+Home"), self)
        shortcut_first_page.activated.connect(self.goto_first_page)

        shortcut_last_page = QShortcut(QKeySequence("Ctrl+End"), self)
        shortcut_last_page.activated.connect(self.goto_last_page)

        shortcut_prev_page = QShortcut(QKeySequence("Page Up"), self)
        shortcut_prev_page.activated.connect(self.show_prev_page)

        shortcut_next_page = QShortcut(QKeySequence("Page Down"), self)
        shortcut_next_page.activated.connect(self.show_next_page)

        search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        search_shortcut.activated.connect(self.show_search_widget)

        # Create actions
        open_action = QAction('&Open', self)
        open_action.triggered.connect(self.open_pdf)
        open_action.setShortcut(QKeySequence("Ctrl+O"))

        # Add the new action for opening a new file
        open_new_action = QAction('Open a File in New Window', self)
        open_new_action.triggered.connect(self.open_new_pdf)  # Connect to a new method
        open_new_action.setShortcut(QKeySequence("Ctrl+N"))
        
        save_action = QAction('&Save', self)
        save_action.triggered.connect(self.save_file)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        

        save_as_action = QAction('Save &As', self)
        save_as_action.triggered.connect(self.save_as_file)
        

        print_action = QAction('&Print', self)
        print_action.triggered.connect(self.show_print_options)
        print_action.setShortcut(QKeySequence("Ctrl+P"))

        exit_action = QAction("&Exit", self)
        exit_action.triggered.connect(self.close)  # 连接到关闭窗口的函数

        # Create the window management action
        window_management_action = QAction('Window Management', self)
        window_management_action.triggered.connect(self.show_window_list)

        # Create a menu for window management
        window_menu = QMenu("&Window", self)
        window_menu.addAction(window_management_action)

        # Create a button for the window menu
        window_button = QToolButton(self)
        window_button.setText("&Window")
        window_button.setMenu(window_menu)
        window_button.setPopupMode(QToolButton.InstantPopup)

        # Create Print Options Dock Widget
        self.print_options_dock = QDockWidget("Print Options", self)
        self.print_options_widget = PrintOptionsWidget()
        self.print_options_dock.setWidget(self.print_options_widget)
        self.print_options_dock.setVisible(False)  # Set visibility to Hidden

        # Connect Print Button
        self.print_options_widget.print_button.clicked.connect(self.start_printing)

        
        # 設置深色主題
        self.setStyleSheet("""
            QMainWindow {
                background-color: #333333;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background-color: #FFFFFF;
                color: black;
                border: none;
                border-radius: 5px;           
                padding: 5px;
            }
            QMessageBox {
                background-color: #333333; /* 深灰色背景 */
                color: white; /* 白色文字 */
            }                           
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
       

        file_menu = QMenu("&File", self)
        file_menu.addAction(open_action)
        file_menu.addAction(open_new_action)  # Add the new action to the file menu
        file_menu.addAction(save_action)
        file_menu.addAction(save_as_action)
        file_menu.addSeparator()  # 添加分隔线
        file_menu.addAction(print_action)
        file_menu.addSeparator()  # 添加分隔线
        file_menu.addAction(exit_action)  # 添加 Exit 操作到菜单

        file_button = QToolButton(self)
        file_button.setText("&File")
        file_button.setMenu(file_menu)
        file_button.setPopupMode(QToolButton.InstantPopup)  # 设置为点击时立即弹出菜单


    
        toolbar = QToolBar("Main", self)
        toolbar.addWidget(file_button)
        self.addToolBar(toolbar)
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #272727; /* 深灰色背景 */
                border: none;         
            }
            QToolButton {
                color: white; /* 白色文字 */
                background-color: transparent; /* 透明背景 */
                border: none;
            }
            QToolButton:hover {
                background-color: #666666; /* 悬停时变暗 */
            }
            QToolButton::menu-indicator {
                image: none; /* 隐藏默认的下拉箭头 */
            }
        """)

        
        # 創建頂部按鈕區域
        top_button_widget = QWidget()
        top_button_layout = QHBoxLayout(top_button_widget)
        # 設置頂部按鈕區域的固定高度
        top_button_widget.setMinimumHeight(50)  # 設定最小高度為30像素
        top_button_widget.setMaximumHeight(80)  # 設定最大高度為100像素
        

        # 設置頂部按鈕區域的背景顏色
        top_button_widget.setStyleSheet("""
            QWidget {
                background-color: #080708;  /* 深灰色背景 */
                border: 1px solid #1f1e1e;
                border-radius: 10px; 
            }
        """)

        
        self.btn_open = QPushButton('Open', self)
        self.btn_open.clicked.connect(self.open_pdf)
        top_button_layout.addWidget(self.btn_open)
        self.btn_open.setStyleSheet("""
            QPushButton {
                background-color: #7a020a;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #a6020d;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        self.btn_save = QPushButton('Save', self)
        self.btn_save.clicked.connect(self.save_file)
        top_button_layout.addWidget(self.btn_save)
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_file)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #FF8C00;  /* 橙色 */
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #FFA500;  /* 深橙色 */
            }
            QPushButton:pressed {
                background-color: #FF6347;  /* 淺紅色 */
            }
        """)

        
        top_button_layout.addStretch()  # 添加彈性空間,使按鈕向左對齊

        # 添加插入頁面按鈕
        self.btn_insert_pages = QPushButton('插入頁面', self)
        self.btn_insert_pages.clicked.connect(self.insert_pages)
        top_button_layout.addWidget(self.btn_insert_pages)
        self.btn_insert_pages.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        self.btn_delete_pages = QPushButton('刪除頁面', self)
        self.btn_delete_pages.clicked.connect(self.delete_pages)
        top_button_layout.addWidget(self.btn_delete_pages)
        self.btn_delete_pages.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)
                                   
        
        self.btn_extract_pages = QPushButton('提取頁面', self)
        self.btn_extract_pages.clicked.connect(self.extract_pages)
        top_button_layout.addWidget(self.btn_extract_pages)
        self.btn_extract_pages.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        self.btn_sort_pages = QPushButton('頁面排序', self)
        self.btn_sort_pages.clicked.connect(self.show_sort_widget)
        top_button_layout.addWidget(self.btn_sort_pages)
        self.btn_sort_pages.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)    



        insert_pages_action = QAction('插入頁面', self)
        insert_pages_action.triggered.connect(self.btn_insert_pages.click)

        delete_pages_action = QAction('刪除頁面', self)
        delete_pages_action.triggered.connect(self.btn_delete_pages.click)

        extract_pages_action = QAction('提取頁面', self)
        extract_pages_action.triggered.connect(self.btn_extract_pages.click)

        sort_pages_action = QAction('頁面排序', self)
        sort_pages_action.triggered.connect(self.btn_sort_pages.click)

        # 创建 Edit 按钮和菜单
        edit_menu = QMenu("&Edit", self)
        edit_menu.addAction(insert_pages_action)
        edit_menu.addAction(delete_pages_action)
        edit_menu.addAction(extract_pages_action)
        edit_menu.addAction(sort_pages_action)

        edit_button = QToolButton(self)
        edit_button.setText("&Edit")
        edit_button.setMenu(edit_menu)
        edit_button.setPopupMode(QToolButton.InstantPopup)

        # 将 Edit 按钮添加到工具栏
        toolbar.addWidget(edit_button)
        file_menu.setStyleSheet("""
            QMenu {
                background-color: #272727; /* 深灰色背景 */
                color: white; /* 白色文字 */
                border: 1px solid #666666; /* 浅灰色边框 */
            }
            QMenu::item:selected {
                background-color: #666666; /* 选中时变暗 */
            }
        """)

        # 为 edit_menu 设置相同的样式
        edit_menu.setStyleSheet("""
            QMenu {
                background-color: #272727; /* 深灰色背景 */
                color: white; /* 白色文字 */
                border: 1px solid #666666; /* 浅灰色边框 */
            }
            QMenu::item:selected {
                background-color: #666666; /* 选中时变暗 */
            }
        """)

        # 设置工具栏样式
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #272727; /* 深灰色背景 */
                border: none;
            }
            QToolButton {
                color: white; /* 白色文字 */
                background-color: transparent; /* 透明背景 */
                border: none;
            }
            QToolButton:hover {
                background-color: #666666; /* 悬停时变暗 */
            }
            QToolButton::menu-indicator {
                image: none; /* 隐藏默认的下拉箭头 */
            }
        """)

        self.btn_convert = QPushButton('Pdf>>Word', self)
        self.btn_convert.clicked.connect(self.convert_to_word)
        top_button_layout.addWidget(self.btn_convert)
        self.btn_convert.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        top_button_layout.addStretch()  # 添加彈性空間,使按鈕向左對齊

        self.btn_page_count = QPushButton('統計頁數', self)
        self.btn_page_count.clicked.connect(self.count_pdf_pages)
        top_button_layout.addWidget(self.btn_page_count)
        self.btn_page_count.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        self.btn_extract_text = QPushButton('提取文本', self)
        self.btn_extract_text.clicked.connect(self.open_text_extractor)
        top_button_layout.addWidget(self.btn_extract_text)
        self.btn_extract_text.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)
        
        self.btn_merge_pdfs = QPushButton('合併PDF', self)
        self.btn_merge_pdfs.clicked.connect(self.merge_pdfs)
        top_button_layout.addWidget(self.btn_merge_pdfs)
        self.btn_merge_pdfs.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        convert_to_word_action = QAction('Pdf to Word', self)
        convert_to_word_action.triggered.connect(self.convert_to_word)

        count_pages_action = QAction('統計PDF頁數', self)
        count_pages_action.triggered.connect(self.count_pdf_pages)

        extract_text_action = QAction('PDF提取文本', self)
        extract_text_action.triggered.connect(self.open_text_extractor)

        merge_pdfs_action = QAction('合併多個PDF文件', self)
        merge_pdfs_action.triggered.connect(self.merge_pdfs)

        # 2. 创建 "PDF Management" 菜单
        pdf_management_menu = QMenu("&PDF Management", self)

        # 3. 添加 QAction 到菜单
        pdf_management_menu.addAction(convert_to_word_action)
        pdf_management_menu.addAction(count_pages_action)
        pdf_management_menu.addAction(extract_text_action)
        pdf_management_menu.addAction(merge_pdfs_action)

        # 4. 创建 "PDF Management" 按钮
        pdf_management_button = QToolButton(self)
        pdf_management_button.setText("&PDF Management")
        pdf_management_button.setMenu(pdf_management_menu)
        pdf_management_button.setPopupMode(QToolButton.InstantPopup)

        # 5. 添加按钮到工具栏
        toolbar.addWidget(pdf_management_button)

        # 6. 设置菜单样式
        pdf_management_menu.setStyleSheet("""
            QMenu {
                background-color: #272727; /* 深灰色背景 */
                color: white; /* 白色文字 */
                border: 1px solid #666666; /* 浅灰色边框 */
            }
            QMenu::item:selected {
                background-color: #666666; /* 选中时变暗 */
            }
        """)

        # Add the button to the toolbar
        toolbar.addWidget(window_button)
        window_menu.setStyleSheet("""
            QMenu {
                background-color: #272727; /* 深灰色背景 */
                color: white; /* 白色文字 */
                border: 1px solid #666666; /* 浅灰色边框 */
            }
            QMenu::item:selected {
                background-color: #666666; /* 选中时变暗 */
            }
        """)

        self.btn_pdf_info = QPushButton('PDF內容', self)
        self.btn_pdf_info.clicked.connect(self.show_pdf_info)
        top_button_layout.addWidget(self.btn_pdf_info)
        self.btn_pdf_info.setStyleSheet("""
            QPushButton {
                background-color: #050001;
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;                    
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #370da1;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)

        self.btn_print = QPushButton('PRINT', self)
        self.btn_print.setStyleSheet("""
            QPushButton {
                background-color: #005709;  /* 橙色 */
                color: white;
                border: 2px solid #CCCCCC;
                border-radius: 10px;
                padding: 5px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 70px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #01850f;  /* 深橙色 */
            }
            QPushButton:pressed {
                background-color: #012605;  /* 淺紅色 */
            }
        """)
        top_button_layout.addWidget(self.btn_print)

        # Connect PRINT button to show_print_options
        self.btn_print.clicked.connect(self.show_print_options) 
    
        close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_shortcut.activated.connect(self.close)
        
        layout.addLayout(top_button_layout)  # 將頂部按鈕區域添加到主佈局中
        layout.addWidget(top_button_widget)
        

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)
        layout.addWidget(self.progress_bar)

        progress_layout = QHBoxLayout()
        progress_layout.addStretch(1)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch(1)
        
        # 設置進度條的固定大小
        self.progress_bar.setFixedWidth(500)
        self.progress_bar.setFixedHeight(15)
        
        layout.addLayout(progress_layout)


        # Display area for PDF pages
        self.image_widget = QWidget()
        self.image_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.image_label = QLabel(self.image_widget)
        self.image_label.setAlignment(Qt.AlignCenter)

        image_layout = QVBoxLayout(self.image_widget)
        image_layout.addWidget(self.image_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)  # Set to true to allow widget resizing
        self.scroll_area.setWidget(self.image_widget)  # Add image_widget to the scroll area
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.scroll_area.setStyleSheet("background-color: #1c1c1c")


        layout.addWidget(self.scroll_area)  # Add the scroll area to the main layout instead of the image_widget


        # 創建底部信息區域
        bottom_info_widget = QWidget()
        bottom_info_layout = QHBoxLayout(bottom_info_widget)
        bottom_info_widget.setFixedHeight(30)  # 設置固定高度為30像素,可根據需要調整

        # 設置底部信息區域的背景顏色
        bottom_info_widget.setStyleSheet("""
            QWidget {
                background-color: #222222;  /* 深灰色背景 */
                border: none;
                border-radius: 5px; 
            }
        """)

        self.file_info_label = QLabel(self)
        self.file_info_label.setAlignment(Qt.AlignLeft)
        bottom_info_layout.addWidget(self.file_info_label)
        self.file_info_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                margin-left: 10px;
            }
        """)

        # 添加顯示頁面尺寸的標籤
        self.page_size_label = QLabel(self)
        self.page_size_label.setAlignment(Qt.AlignRight)
        bottom_info_layout.addWidget(self.page_size_label)
        self.page_size_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                margin-right: 10px;
            }
        """)


        bottom_info_layout.addStretch()  # 添加彈性空間,使頁碼標籤靠右對齊

        # 顯示當前頁碼
        self.page_label = QLabel(self)
        self.page_label.setAlignment(Qt.AlignRight)
        bottom_info_layout.addWidget(self.page_label)
        self.page_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                margin-right: 10px;
            }
        """)

        # 將底部信息區域添加到主佈局的底部
        layout.addWidget(bottom_info_widget)                           
                                      
        # 按鈕和輸入框的佈局
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_widget.setFixedHeight(45)

        button_widget.setStyleSheet("""
            QWidget {
                background-color: #222222;  /* 设置背景颜色为深灰色 */
                /* 或者使用背景图片 */
                /* background-image: url(path/to/image.png); */
                border-radius: 5px; 
    }
""")

        self.btn_rotate_pages = QPushButton('ROTATE', self)
        self.btn_rotate_pages.clicked.connect(self.rotate_pages)
        button_layout.addWidget(self.btn_rotate_pages)
        self.btn_rotate_pages.setStyleSheet("""
            QPushButton {
                background-color: #004C99;  
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 30px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #006C99; 
            }
            QPushButton:pressed {
                background-color: #003366;  
            }
        """)

        self.rotate_pages_edit = QLineEdit(self)
        self.rotate_pages_edit.setMinimumSize(80, 28)
        self.rotate_pages_edit.setMaximumSize(80, 28)
        self.rotate_pages_edit.setPlaceholderText("輸入頁碼")
        button_layout.addWidget(self.rotate_pages_edit)
        self.rotate_pages_edit.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 5px;
                padding: 5px;
                font-family: Arial;
                font-size: 12px;
            }
        """)

        self.rotate_angle_combo = QComboBox(self)
        self.rotate_angle_combo.addItems(['0','90', '180', '270'])
        button_layout.addWidget(self.rotate_angle_combo)
        self.rotate_angle_combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 5px;
                padding: 5px;
                font-family: Arial;
                font-size: 12px;
                min-Height: 10px;                             
            }
        """)

        button_layout.addStretch()

        self.btn_prev = QPushButton('<<', self)
        self.btn_prev.clicked.connect(self.show_prev_page)
        button_layout.addWidget(self.btn_prev)

        self.page_num_edit = QLineEdit(self)
        self.page_num_edit.setMinimumSize(40, 28)
        self.page_num_edit.setMaximumSize(40, 28)
        self.page_num_edit.setPlaceholderText("輸入頁碼")
        button_layout.addWidget(self.page_num_edit)
        self.page_num_edit.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 5px;
                padding: 5px;
                font-family: Arial;
                font-size: 12px;
            }
        """)

        
        self.btn_goto = QPushButton('GO', self)
        self.btn_goto.clicked.connect(self.goto_page)
        button_layout.addWidget(self.btn_goto)
        self.btn_goto.setStyleSheet("""
            QPushButton {
                background-color: #004C99;  
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
                font-family: Arial Black;
                font-weight: bold;
                min-width: 25px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #006C99; 
            }
            QPushButton:pressed {
                background-color: #003366;  
            }
        """)
        
        self.btn_next = QPushButton('>>', self)
        self.btn_next.clicked.connect(self.show_next_page)
        button_layout.addWidget(self.btn_next)

        button_layout.addStretch()


        self.btn_zoom_out = QPushButton('-', self)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        button_layout.addWidget(self.btn_zoom_out)
        self.btn_zoom_out.setStyleSheet("""
            QPushButton {
                background-color: #606060;  
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
                min-width: 20px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #808080; 
            }
            QPushButton:pressed {
                background-color: #404040;  
            }
        """)

        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        button_layout.addWidget(self.zoom_label)
        self.zoom_label.setStyleSheet("""
            QLabel {                          
            font-size: 12px;
            color: white;
            }
        """)

        self.btn_zoom_in = QPushButton('+', self)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        button_layout.addWidget(self.btn_zoom_in)
        zoom_in_shortcut = QShortcut(QKeySequence("Ctrl++"), self)
        zoom_in_shortcut.activated.connect(self.zoom_in)

        zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        zoom_out_shortcut.activated.connect(self.zoom_out)

        self.image_widget.wheelEvent = self.wheel_event
        self.btn_zoom_in.setStyleSheet("""
            QPushButton {
                background-color: #606060;  
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
                min-width: 20px;
                min-Height: 10px;
            }
            QPushButton:hover {
                background-color: #808080; 
            }
            QPushButton:pressed {
                background-color: #404040;  
            }
        """)

        layout.addWidget(button_widget)
        layout.addLayout(button_layout)
        
        self.show()

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇 PDF 文件", "", "PDF files (*.pdf)")
        if path:
            try:
                # 创建一个临时文件夹来存储临时副本
                temp_dir = tempfile.mkdtemp()
                temp_pdf_path = os.path.join(temp_dir, os.path.basename(path))
                shutil.copy2(path, temp_pdf_path)  # 将原始文件复制到临时文件夹
                
                self.load_pdf(temp_pdf_path)  # 加载临时副本进行编辑
                self.page_num_edit.setText(str(self.current_page + 1)) 
                
                # 存储原始文件路径和暂存文件路径
                self.original_pdf_path = path
                self.temp_pdf_path = temp_pdf_path
                
                # 更新UI显示文件信息
                file_info = f"文件路徑: {self.original_pdf_path} | 頁數: {self.doc.page_count}"
                self.file_info_label.setText(file_info)
                self.setWindowTitle(f'PDFDocuEdit Pro - {os.path.basename(path)}')
            except Exception as e:
                self.show_error(f"無法打開文件: {e}")

    def load_pdf(self, path):
        try:
            # Always create a temporary copy
            temp_dir = tempfile.mkdtemp()
            temp_pdf_path = os.path.join(temp_dir, os.path.basename(path))
            shutil.copy2(path, temp_pdf_path)

            # Load the temporary copy
            self.doc = fitz.open(temp_pdf_path)
            self.current_page = 0
            self.zoom_ratio = 1.0
            self.show_page(self.current_page)
            self.update_file_info(path)  # Update file info in the UI
            self.setWindowTitle(f'PDFDocuEdit Pro - {os.path.basename(path)}')

            # Store original and temporary paths
            self.original_pdf_path = path
            self.temp_pdf_path = temp_pdf_path

        except Exception as e:
            self.show_error(f"加載 PDF 時發生錯誤：{e}")

        if self.sort_widget:
            self.sort_widget.update_page_list(self.doc.page_count)

    def show_page(self, num):
        if not self.doc or num < 0 or num >= self.doc.page_count:
            return

        page = self.doc.load_page(num)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(self.zoom_ratio, self.zoom_ratio))
        qimage = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format_RGB888)
        self.image_label.setPixmap(QPixmap.fromImage(qimage))
        self.page_label.setText(f"第 {num + 1} 頁,共 {self.doc.page_count} 頁")

        # 獲取頁面尺寸
        page_rect = page.rect
        page_width_pts = page_rect.width
        page_height_pts = page_rect.height

        # 將點轉換為毫米並移除小數點後的數字
        page_width_mm = int(page_width_pts / 72 * 25.4)
        page_height_mm = int(page_height_pts / 72 * 25.4)

        # 更新頁碼和頁面尺寸標籤
        self.page_label.setText(f"第 {num + 1} 頁,共 {self.doc.page_count} 頁")
        self.page_size_label.setText(f"(尺寸: {page_width_mm} x {page_height_mm} mm)")

        if self.search_results:
            for page_num, instances in self.search_results.copy():
                if page_num == num:
                    for inst in instances:
                        highlight = page.add_highlight_annot(inst)
                        highlight.update()

        # 添加以下代码来更新 QLineEdit 显示
        self.page_num_edit.setText(str(num + 1))

    def extract_pixmap(self, image_obj):
        byte_array = image_obj.stream.get_rawdata()
        image = QImage.fromData(byte_array)
        pixmap = QPixmap.fromImage(image)
        return pixmap
    

    def rotate_pages(self):
        if self.doc:
            try:
                pages_to_rotate = self.parse_page_range(self.rotate_pages_edit.text())
                angle = int(self.rotate_angle_combo.currentText())
                for page_num in pages_to_rotate:
                    page = self.doc.load_page(page_num)
                    page.set_rotation(angle)
                self.show_page(self.current_page)
                self.show_success("頁面已成功旋轉！")
            except ValueError as e:
                self.show_error(str(e))
        self.is_modified = True

    def show_prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.show_page(self.current_page)

    def show_next_page(self):
        if self.doc and self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self.show_page(self.current_page)

    def zoom_in(self):
        if self.doc:
            self.zoom_ratio *= PDFViewer.ZOOM_IN_FACTOR
            self.zoom_ratio = min(self.zoom_ratio, 4.0)  # 限制最大縮放比例為400%
            self.show_page(self.current_page)
            self.update_zoom_label()

    def zoom_out(self):
        if self.doc:
            self.zoom_ratio *= PDFViewer.ZOOM_OUT_FACTOR
            self.zoom_ratio = max(self.zoom_ratio, 0.20)  # 限制最小縮放比例為20%
            self.show_page(self.current_page)
            self.update_zoom_label()

    def update_zoom_label(self):
        zoom_percent = int(self.zoom_ratio * 100)
        self.zoom_label.setText(f"{zoom_percent}%")

    def goto_page(self):
        if self.doc:
            try:
                page_num = int(self.page_num_edit.text())
                if 1 <= page_num <= self.doc.page_count:
                    self.current_page = page_num - 1
                    self.show_page(self.current_page)
                else:
                    self.show_error("頁碼超出範圍！")
            except ValueError:
                self.show_error("請輸入有效的頁碼！")

        # 更新 QLineEdit 顯示當前頁碼
        self.page_num_edit.setText(str(self.current_page + 1))

    def delete_pages(self):
        if not self.doc:
            QMessageBox.warning(self, "警告", "請先打開一個PDF文件")
            return
        
        try:
            dialog = DeletePagesDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                delete_option = dialog.get_delete_options()
                
                pages_to_delete = []
                if delete_option == "odd":
                    pages_to_delete = [i for i in range(self.doc.page_count) if (i + 1) % 2 != 0]
                elif delete_option == "even":
                    pages_to_delete = [i for i in range(self.doc.page_count) if (i + 1) % 2 == 0]
                elif delete_option and delete_option[0] == "multiple":
                    multiple = delete_option[1]
                    pages_to_delete = [i for i in range(self.doc.page_count) if (i + 1) % multiple == 0]
                elif delete_option and delete_option[0] == "custom":
                    pages_to_delete = self.parse_page_range(delete_option[1])
                
                for page_num in sorted(pages_to_delete, reverse=True):
                    self.doc.delete_page(page_num)
                
                # 更新顯示但不立即保存文件
                self.current_page = max(0, min(self.current_page, self.doc.page_count - 1))
                self.show_page(self.current_page)
                QMessageBox.information(self, "成功", "所選頁面已被標記為刪除")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"刪除頁面時發生錯誤：{e}")
        self.is_modified = True

    def merge_pdfs(self):
        merge_dialog = MergePDFsDialog(self)
        if merge_dialog.exec_() == QDialog.Accepted:
            merged_doc = fitz.open()
            for path in merge_dialog.file_paths:
                with fitz.open(path) as doc:
                    merged_doc.insert_pdf(doc)
            save_path, _ = QFileDialog.getSaveFileName(self, "保存合併後的PDF文件", "", "PDF files (*.pdf)")
            if save_path:
                merged_doc.save(save_path)
                QMessageBox.information(self, "成功", "PDF文件已成功合併！")
                self.load_pdf(save_path)  # 重新加载合併後的文檔
        self.is_modified = True

    def extract_pages_by_number(self, page_numbers):
        if self.doc:
            extracted_doc = fitz.open()
            for page_num in sorted(page_numbers):
                page = self.doc.load_page(page_num)
                extracted_doc.insert_pdf(self.doc, from_page=page_num, to_page=page_num)
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Extracted Pages", "", "PDF files (*.pdf)")
            if save_path:
                extracted_doc.save(save_path)
                QMessageBox.information(self, "成功", "提取的頁面已保存到：" + save_path)
        else:
            QMessageBox.warning(self, "警告", "請先打開一個PDF文件。")
        self.is_modified = True

    def delete_pages_by_number(self, page_numbers):
        try:
            if self.doc:
                for page_num in sorted(page_numbers, reverse=True):
                    self.doc.delete_page(page_num)
                # 检查当前页码是否仍然有效
                if self.current_page >= self.doc.page_count:
                    self.current_page = max(0, self.doc.page_count - 1)
                # 清除搜索结果
                self.search_results.clear()
                # 清空结果列表
                if self.search_widget:
                    self.search_widget.clear_result_list() 
                self.show_page(self.current_page)
                QMessageBox.information(self, "成功", "所選頁面已被標記為刪除")
                self.is_modified = True
            else:
                QMessageBox.warning(self, "警告", "請先打開一個PDF文件")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除页面时发生错误: {e}")
            print(f"Error deleting pages: {e}")
        self.is_modified = True

    def extract_pages(self):
        if self.doc:
            dialog = ExtractPagesDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                extract_option = dialog.get_extract_options()
                
                try:
                    pages_to_extract = []
                    if extract_option == "odd":
                        pages_to_extract = [i for i in range(self.doc.page_count) if (i + 1) % 2 != 0]
                    elif extract_option == "even":
                        pages_to_extract = [i for i in range(self.doc.page_count) if (i + 1) % 2 == 0]
                    elif extract_option and extract_option[0] == "multiple":
                        multiple = extract_option[1]
                        pages_to_extract = [i for i in range(self.doc.page_count) if (i + 1) % multiple == 0]
                    elif extract_option and extract_option[0] == "custom":
                        pages_to_extract = self.parse_page_range(extract_option[1])
                    
                    if pages_to_extract:
                        extracted_doc = fitz.open()
                        for page_num in sorted(pages_to_extract):
                            page = self.doc.load_page(page_num)
                            extracted_doc.insert_pdf(self.doc, from_page=page_num, to_page=page_num)
                        save_path, _ = QFileDialog.getSaveFileName(self, "Save Extracted Pages", "", "PDF files (*.pdf)")
                        if save_path:
                            extracted_doc.save(save_path)
                            QMessageBox.information(self, "成功", "提取的頁面已保存到：" + save_path)
                    else:
                        QMessageBox.warning(self, "警告", "沒有選擇頁面進行提取。")
                except Exception as e:
                    QMessageBox.critical(self, "錯誤", "提取頁面時發生錯誤：" + str(e))
        else:
            QMessageBox.warning(self, "警告", "請先打開一個PDF文件。")

        self.is_modified = True

    def parse_page_range(self, page_range):
        pages = []
        for part in page_range.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                pages.extend(range(start - 1, end))
            else:
                pages.append(int(part) - 1)
        return sorted(set(pages))

    def save_file(self):
        if self.doc:
            if self.original_pdf_path:
                try:
                    self.doc.save(self.original_pdf_path)
                    QMessageBox.information(self, "Success", "PDF saved successfully!")
                    self.update_file_info(self.original_pdf_path)
                except Exception as e:
                    self.show_error(f"Error saving PDF: {e}")
            else:
                self.save_as_file()
                self.is_modified = False

    def save_as_file(self):
        if self.doc:
            save_path, _ = QFileDialog.getSaveFileName(self, "Save PDF As", "", "PDF files (*.pdf)")
            if save_path:
                try:
                    self.doc.save(save_path)
                    QMessageBox.information(self, "Success", "PDF saved successfully!")
                    self.update_file_info(save_path)
                except Exception as e:
                    self.show_error(f"Error saving PDF: {e}")

    def closeEvent(self, event):
        if self.is_modified:
            # 创建QMessageBox实例
            reply = QMessageBox(self)
            reply.setWindowTitle('PDFDocuEdit Pro')
            reply.setText('文件已被修改，是否保存?')
            reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)

            # 设置QMessageBox样式
            reply.setStyleSheet("QLabel{ color: white; }")

            # 显示QMessageBox并等待用户响应
            user_reply = reply.exec_()

            # 根据用户的选择处理事件
            if user_reply == QMessageBox.Yes:
                self.save_file()
                event.accept()
            elif user_reply == QMessageBox.No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def insert_pages(self):
        if not self.doc:
            self.show_warning("請先打開一個PDF文件。")
            return

        insert_dialog = InsertPagesDialog(self)
        if insert_dialog.exec_() == QDialog.Accepted:
            page_range = insert_dialog.page_range_edit.text()
            insert_pos = insert_dialog.insert_pos_combo.currentIndex()
            insert_page = insert_dialog.insert_page_edit.text()

            try:
                pages_to_insert = self.parse_page_range(page_range)
                insert_before_page = None

                if insert_pos == 0:  # 插入到开头
                    insert_before_page = 0
                elif insert_pos == 1:  # 插入到结尾
                    insert_before_page = self.doc.page_count
                else:  # 插入到指定位置
                    if insert_page:
                        insert_before_page = int(insert_page)
                    else:
                        self.show_error("請输入插入位置頁碼。")
                        return

                if insert_before_page is not None:
                    insert_pdf_path, _ = QFileDialog.getOpenFileName(self, "選擇要插入的PDF文件", "", "PDF files (*.pdf)")
                    if insert_pdf_path:
                        with fitz.open(insert_pdf_path) as insert_doc:
                            self.doc.insert_pdf(insert_doc, from_page=pages_to_insert[0], to_page=pages_to_insert[-1], start_at=insert_before_page)
                        self.show_page(self.current_page)
                        self.show_success("頁面插入成功！")
            except Exception as e:
                self.show_error(str(e))
        self.is_modified = True

    def parse_page_range(self, page_range):
        pages = []
        for part in page_range.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                if start <= end:
                    pages.extend(range(start - 1, end))
                else:
                    raise ValueError("起始頁碼不能大于结束頁碼！")
            else:
                try:
                    page_num = int(part)
                    if page_num < 1:
                        raise ValueError("頁碼不能小于1！")
                    pages.append(page_num - 1)
                except ValueError:
                    raise ValueError("無效的頁碼格式！")
        return sorted(set(pages))
    

    def print_pdf(self):
        if self.doc:
            self.print_options_dock.show()  # Show the print options widget

    def show_print_options(self):
        if self.doc:
            self.addDockWidget(Qt.RightDockWidgetArea, self.print_options_dock)  # Add dock widget
            self.print_options_dock.show()
        else:
            self.show_warning("請先打開一個PDF文件。")


    def start_printing(self):
        # Get options from PrintOptionsWidget
        paper_size = self.print_options_widget.paper_size_combo.currentText()
        orientation = QPrinter.Portrait if self.print_options_widget.portrait_radio.isChecked() else QPrinter.Landscape
        top_margin = self.print_options_widget.top_margin_spin.value()
        bottom_margin = self.print_options_widget.bottom_margin_spin.value()
        left_margin = self.print_options_widget.left_margin_spin.value()
        right_margin = self.print_options_widget.right_margin_spin.value()
        copies = self.print_options_widget.copies_spin.value()
        full_page = self.print_options_widget.full_page_checkbox.isChecked()

        # Create QPrinter and set properties
        printer = QPrinter(QPrinter.HighResolution)
        if paper_size == "A4":
            printer.setPageSize(QPrinter.A4)
        elif paper_size == "A3":
            printer.setPageSize(QPrinter.A3)
        elif paper_size == "Letter":
            printer.setPageSize(QPrinter.Letter)
        elif paper_size == "Legal":
            printer.setPageSize(QPrinter.Legal)
        # ... 添加其他纸张尺寸 ...
        else:
            self.show_error(f"不支持的纸张尺寸: {paper_size}")
            return
        printer.setOrientation(orientation)
        printer.setPageMargins(left_margin, top_margin, right_margin, bottom_margin, QPrinter.Millimeter)
        printer.setCopyCount(copies)
        printer.setFullPage(full_page)

        # Call print_direct with the configured printer
        self.print_direct(printer)

        # Close the dock widget after printing
        self.print_options_dock.close()


    def print_direct(self, printer):
        painter = QPainter(printer)
        try:
            # 创建进度对话框，设置最小持续时间为2000毫秒（2秒）
            progress_dialog = QProgressDialog("Printing...", "Cancel", 0, self.doc.page_count, None)
            progress_dialog.setWindowTitle("Print Progress")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setMinimumDuration(2000)  # 对话框至少显示2秒
            progress_dialog.show()

            for page_num in range(self.doc.page_count):
                if progress_dialog.wasCanceled():
                    break

                progress_dialog.setValue(page_num)
                progress_dialog.setLabelText(f"Printing page {page_num + 1} of {self.doc.page_count}")
                QApplication.processEvents()  # 处理事件，确保UI更新

                # 打印逻辑
                page = self.doc.load_page(page_num)
                zoom = 4
                mat = fitz.Matrix(zoom, zoom)
                pixmap = page.get_pixmap(matrix=mat)
                qimage = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format_RGB888)
                scale_x = printer.pageRect().width() / qimage.width()
                scale_y = printer.pageRect().height() / qimage.height()
                scale = max(scale_x, scale_y)
                scaled_width = int(qimage.width() * scale)
                scaled_height = int(qimage.height() * scale)
                scaled_image = qimage.scaled(scaled_width, scaled_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                image_rect = QRect(0, 0, scaled_image.width(), scaled_image.height())
                image_rect.moveCenter(printer.pageRect().center())
                painter.drawImage(image_rect, scaled_image)
                if page_num < self.doc.page_count - 1:
                    printer.newPage()

                time.sleep(0.5)  # 添加0.5秒延迟以使进度条变化更明显

            progress_dialog.setValue(self.doc.page_count)
        except Exception as e:
            self.show_error(f"Direct printing error: {e}")
        finally:
            painter.end()
            progress_dialog.close()

    def convert_to_word(self):
        if self.doc:
            try:
                pdf_path = self.original_pdf_path
                docx_path = os.path.splitext(pdf_path)[0] + '.docx'
                self.thread = PDFConverter(pdf_path, docx_path)
                self.thread.finished.connect(self.conversion_finished)
                self.progress_bar.setVisible(True)
                self.thread.start()
            except Exception as e:
                self.show_error(f"轉換失敗：{e}")
        else:
            self.show_warning("請先打開一個PDF文件。")


    def conversion_finished(self):
        self.progress_bar.setVisible(False)
        self.show_success("PDF轉換為Word文件成功！")

    def auto_adjust_columns_width(self, writer, df, sheet_name):
        worksheet = writer.sheets[sheet_name]
        for column in df:
            column_width = max(df[column].astype(str).map(len).max(), len(column)) + 2
            col_idx = df.columns.get_loc(column) + 1
            worksheet.column_dimensions[get_column_letter(col_idx)].width = column_width

    def show_search_widget(self):
        if not self.search_widget:
            self.search_widget = SearchWidget(self)
            self.search_widget.search_requested.connect(self.search_text)
            self.addDockWidget(Qt.LeftDockWidgetArea, self.search_widget)
        self.search_widget.show()

    def clear_highlights(self):
        if self.doc:
            for page_num in range(self.doc.page_count):
                page = self.doc.load_page(page_num)
                annot = page.first_annot
                while annot:
                    if annot.type[0] == 8:  # 8 代表高亮注釋
                        page.delete_annot(annot)
                    annot = annot.next
            self.show_page(self.current_page)

    def search_text(self, text):
        if self.doc:
            self.clear_highlights()
            self.search_results.clear()
            for page_num in range(self.doc.page_count):
                page = self.doc.load_page(page_num)
                text_instances = page.search_for(text)
                if text_instances:
                    self.search_results.append((page_num, text_instances))
            self.search_widget.update_results(self.search_results)
            if not self.search_results:
                QMessageBox.information(self, "Search Results", "No matches found.")


    def jump_to_page(self, page_num):
        self.current_page = page_num
        self.show_page(self.current_page)

    def open_new_pdf(self):
        """Opens a new PDF file in a separate window."""
        new_viewer = PDFViewer()  # Create a new instance of PDFViewer
        new_viewer.show()  # Show the new window
        self.open_windows.append(new_viewer)  # Add the new window to the list
        
        # (Optional) Open the file dialog in the new window
        path, _ = QFileDialog.getOpenFileName(new_viewer, "選擇 PDF 文件", "", "PDF files (*.pdf)")
        if path:
            new_viewer.load_pdf(path)

    def show_window_list(self):
        """Displays a dialog with a list of open windows."""

        # 更新窗口列表
        self.open_windows = [window for window in self.open_windows if window.isVisible()]

        if not self.open_windows:
            self.show_info("沒有開啟其他視窗。")
            return

        window_list_dialog = QDialog(self)
        window_list_dialog.setWindowTitle("開啟的視窗")

        layout = QVBoxLayout()
        window_list = QListWidget()
        window_list.clear()  # 清空列表
        for window in self.open_windows:
            window_list.addItem(window.windowTitle())
        layout.addWidget(window_list)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(window_list_dialog.accept)
        layout.addWidget(button_box)

        window_list_dialog.setLayout(layout)

        if window_list_dialog.exec_() == QDialog.Accepted:
            selected_item = window_list.currentItem()
            if selected_item:
                selected_window_title = selected_item.text()
                for window in self.open_windows:
                    if window.windowTitle() == selected_window_title:
                        window.activateWindow()  # Bring the selected window to the front
                        break

    def count_pdf_pages(self):
        folder_path = QFileDialog.getExistingDirectory(self, "選擇PDF文件夾")
        if folder_path:
            try:
                file_data = []

                for root, dirs, files in os.walk(folder_path):
                    for filename in files:
                        if filename.lower().endswith('.pdf'):
                            filepath = os.path.join(root, filename)
                            try:
                                pdf = fitz.open(filepath)
                                num_pages = pdf.page_count
                                file_size = os.path.getsize(filepath)
                                modify_date = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
                                file_data.append({
                                    'Filename': filename,
                                    'PageCount': num_pages,
                                    'FileSize (bytes)': file_size,
                                    'Path': filepath.replace('\\', '/'),
                                    'Modify Date': modify_date
                                })
                                pdf.close()
                            except Exception as e:
                                self.show_error(f"處理{filename}時出錯。\n{e}")

                if file_data:
                    df = pd.DataFrame(file_data)
                    total_pages = df['PageCount'].sum()
                    total_row = pd.DataFrame([{'Filename': 'Total', 'PageCount': total_pages, 'FileSize (bytes)': '', 'Path': '', 'Modify Date': ''}])
                    df = pd.concat([df, total_row], ignore_index=True)

                    report_path = os.path.join(folder_path, 'PDF_report.xlsx')
                    with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name='Report')
                        self.auto_adjust_columns_width(writer, df, 'Report')

                    self.show_success(f"統計完成。報告已保存到：{report_path}")
                else:
                    self.show_info("指定文件夾及其子資料夾中未找到PDF文件。")
            except Exception as e:
                self.show_error(f"統計PDF頁數時出錯：{e}")
        else:
            self.show_warning("請選擇一個PDF文件夾。")

    def show_pdf_info(self):
        if self.doc:
            dialog = PDFInfoDialog(self.doc, self)
            dialog.exec_()
        else:
            QMessageBox.warning(self, "警告", "請先打開一個PDF文件。")

    def wheel_event(self, event):
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
    #    else:
    #        if event.angleDelta().y() > 0:
    #           self.show_prev_page()
    #        else:
    #            self.show_next_page()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.pdf'):
                self.load_pdf(file_path)


    # 新增跳轉到第一頁的方法
    def goto_first_page(self):
        if self.doc:
            self.current_page = 0
            self.show_page(self.current_page)

    # 新增跳轉到最後一頁的方法
    def goto_last_page(self):
        if self.doc:
            self.current_page = self.doc.page_count - 1
            self.show_page(self.current_page)

    def show_error(self, message):
        msg_box = QMessageBox(QMessageBox.Critical, "錯誤", message, parent=self)
        msg_box.setStyleSheet("QLabel{color: white;}")
        msg_box.exec_()

    def show_success(self, message):
        msg_box = QMessageBox(QMessageBox.Information, "成功", message, parent=self)
        msg_box.setStyleSheet("QLabel{color: white;}")
        msg_box.exec_()

    def show_warning(self, message):
        msg_box = QMessageBox(QMessageBox.Warning, "警告", message, parent=self)
        msg_box.setStyleSheet("QLabel{color: white;}")
        msg_box.exec_()

    def show_info(self, message):
        msg_box = QMessageBox(QMessageBox.Information, "信息", message, parent=self)
        msg_box.setStyleSheet("QLabel{color: white;}")
        msg_box.exec_()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application style to 'Fusion'
    QApplication.setStyle("Fusion")
    
    # Create and set the application palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    QApplication.setPalette(palette)
    
    # Set the application icon
    app_icon = QIcon('icon.ico')
    app.setWindowIcon(app_icon)
    
    # Create and display the splash screen
    splash_img_path = resource_path('splash.png')
    splash = QSplashScreen(QPixmap(splash_img_path))
    splash.show()
    app.processEvents()

    # Create the main window
    viewer = PDFViewer()
    viewer.setStyleSheet("QLabel { color: white; }")  # Set QLabel text color globally for the viewer
    splash.finish(viewer)
    viewer.show()

    # Load a PDF file if provided as a command line argument
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        viewer.load_pdf(pdf_path)

    sys.exit(app.exec_())

