"""Single application-wide Qt stylesheet."""

from __future__ import annotations

from core.resources import resource_path

from .theme import get_colors, is_dark
from .tokens import D, F, R, S


def _rgba(hex_color: str, alpha: int) -> str:
    """Hex colour → rgba() string with a 0-255 alpha for translucent panels."""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha / 255:.2f})"


def global_style() -> str:
    c = get_colors()
    spin_theme = "dark" if is_dark() else "light"
    spin_plus = resource_path("App_icon", f"spin_plus_{spin_theme}.svg").as_posix()
    spin_minus = resource_path("App_icon", f"spin_minus_{spin_theme}.svg").as_posix()
    combo_down = resource_path(
        "App_icon", f"combo_down_{spin_theme}.svg"
    ).as_posix()
    return f"""
        QMainWindow, QDialog, QWidget {{
            color: {c['text_primary']};
        }}
        QMainWindow {{ background: {c['bg_base']}; }}
        QDialog {{ background: {c['bg_surface']}; }}
        QWidget#commandBar, QWidget#statusBar {{
            background: {c['bg_surface']};
        }}
        QLabel#organizerTitle {{
            font-size: 20px;
            font-weight: 700;
        }}
        QScrollArea#organizerToolsScroll, QWidget#organizerToolsPanel {{
            background: transparent;
        }}
        QDialog#advancedOrganizer QGroupBox {{
            border: 1px solid {c['border']};
            border-radius: 8px;
            margin-top: 10px;
            padding: 6px 8px 6px 8px;
            font-weight: 600;
        }}
        QDialog#advancedOrganizer QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 4px;
            color: {c['text_secondary']};
        }}
        QPushButton#organizerAction {{
            background: {c['bg_elevated']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 5px 9px;
            min-height: 22px;
            font-size: 12px;
        }}
        QPushButton#organizerAction:hover {{
            background: {c['primary_soft']};
            border-color: {c['primary']};
        }}
        QPushButton#organizerAction:disabled {{
            color: {c['text_secondary']};
            background: transparent;
        }}
        QWidget#organizerGridContainer {{
            background: transparent;
        }}
        QWidget#organizerPageWidget {{
            background: {c['bg_surface']};
            border: 2px solid transparent;
            border-radius: {R.LG}px;
        }}
        QWidget#organizerPageWidget:hover {{
            border-color: {c['border_strong']};
        }}
        QWidget#organizerPageWidget[selected="true"] {{
            border-color: {c['primary']};
            background: {c['primary_soft']};
        }}
        QWidget#organizerPageWidget:focus {{
            border-color: {c['primary']};
            background: {_rgba(c['primary_soft'], 180)};
        }}
        QLabel#organizerSelectionBadge {{
            color: {c['on_primary']};
            background: {c['primary']};
            border: 2px solid {c['bg_surface']};
            border-radius: 12px;
            font-weight: 700;
        }}
        QFrame#organizerInsertionLine {{
            background: {c['primary']};
            border-radius: 1px;
        }}
        QWidget#organizerPageWidget[lifted="true"] {{
            border-color: {c['primary']};
            background: {c['bg_elevated']};
        }}
        QLabel#organizerPageThumb {{
            background: {c['page']};
            border: 1px solid {c['border']};
            border-radius: {R.SM}px;
        }}
        QLabel#organizerPageCaption {{
            color: {c['text_secondary']};
            font-size: {F.SM}px;
        }}
        /* App-wide chrome: rounded translucent cards in the sidebar's design
           language. Margins float each bar over the window background. */
        QWidget#commandBar {{
            background: {_rgba(c['bg_surface'], 245)};
            border: 1px solid {c['border']};
            border-radius: 12px;
            margin: {S.SM}px {S.SM}px 0 {S.SM}px;
        }}
        QWidget#commandBar[integratedTitleBar="true"] {{
            background: {c['bg_surface']};
            border: none;
            border-bottom: 1px solid {c['separator']};
            border-radius: 0;
            margin: 0;
        }}
        QWidget#windowControls {{
            background: transparent;
        }}
        QToolButton#windowControlButton {{
            min-width: 46px;
            max-width: 46px;
            min-height: {D.COMMAND_H - 2 * S.XS}px;
            max-height: {D.COMMAND_H - 2 * S.XS}px;
            padding: 0;
            border: none;
            border-radius: 0;
            background: transparent;
        }}
        QToolButton#windowControlButton:hover,
        QToolButton#windowControlButton[hovered="true"] {{
            color: {c['text_primary']};
            background: {c['bg_active']};
            border: none;
        }}
        QToolButton#windowControlButton[closeButton="true"]:hover,
        QToolButton#windowControlButton[closeButton="true"][hovered="true"] {{
            color: #ffffff;
            background: {c['error']};
        }}
        QWidget#statusBar {{
            background: {_rgba(c['bg_surface'], 245)};
            border: none;
            border-top: 1px solid {c['separator']};
            border-radius: 0;
            margin: 0;
        }}
        QFrame#commandDivider {{
            color: {c['separator']};
            min-width: 1px;
            max-width: 1px;
            margin: 7px 0;
        }}
        QLabel#workStatus {{
            color: {c['success']};
            background: {c['success_soft']};
            border: 1px solid {c['success']};
            border-radius: {R.LG}px;
            padding: 3px {S.MD}px;
            font-size: {F.SM}px;
            font-weight: {F.MEDIUM};
        }}
        QLabel#workStatus[busy="true"] {{
            color: {c['primary']};
            background: {c['primary_soft']};
            border-color: {c['primary']};
        }}
        QComboBox#themeSelector {{
            min-height: 30px;
            max-height: 30px;
            border-color: transparent;
            background: {c['bg_sidebar']};
        }}
        QComboBox#themeSelector:hover {{
            color: {c['primary']};
            border-color: {c['primary_glow']};
            background: {c['primary_soft']};
        }}
        QComboBox#layoutSelector, QToolButton#fitButton, QToolButton#rotateButton {{
            min-height: 26px;
            max-height: 26px;
            border-color: transparent;
            background: {c['bg_sidebar']};
            padding: 0 {S.SM}px;
        }}
        QComboBox#layoutSelector {{
            min-width: 112px;
        }}
        QFrame#statusSeparator {{
            color: {c['separator']};
            min-width: 1px;
            max-width: 1px;
            margin: 4px {S.XS}px;
        }}
        QComboBox#layoutSelector:hover, QToolButton#fitButton:hover, QToolButton#rotateButton:hover {{
            color: {c['primary']};
            border-color: {c['primary_glow']};
            background: {c['primary_soft']};
        }}
        /* Bottom status bar: one consistent compact typography and height
           across labels, inputs, combos and buttons. */
        QWidget#statusBar QLabel,
        QWidget#statusBar QLineEdit,
        QWidget#statusBar QComboBox,
        QWidget#statusBar QToolButton {{
            font-size: {F.MD}px;
            min-height: 28px;
            max-height: 28px;
        }}
        QWidget#statusBar QToolButton#commandButton {{
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
        }}
        QWidget#statusBar QComboBox#layoutSelector,
        QWidget#statusBar QToolButton#fitButton,
        QWidget#statusBar QToolButton#rotateButton {{
            min-height: 28px;
            max-height: 28px;
        }}
        QLabel#pageCaption {{
            color: {c['text_secondary']};
            font-size: {F.XS}px;
            background: transparent;
        }}
        QLabel#magnifierPopup {{
            background: {c['page']};
            border: 2px solid {c['primary']};
        }}
        QWidget#pageView {{ background: transparent; }}
        QFrame#taskBar {{
            background: {_rgba(c['bg_surface'], 245)};
            border: none;
            border-bottom: 1px solid {c['separator']};
            border-radius: 0;
            margin: 0;
        }}
        /* Document tabs: rounded translucent tab cards over the workspace. */
        QTabWidget#documentTabs::pane {{
            border: none;
            border-top: 1px solid {c['separator']};
            background: transparent;
        }}
        QTabWidget#documentTabs QTabBar {{
            background: transparent;
        }}
        QTabWidget#documentTabs QTabBar::tab {{
            background: {_rgba(c['bg_sidebar'], 235)};
            color: {c['text_secondary']};
            border: 1px solid {c['border']};
            border-bottom: none;
            border-top-left-radius: {R.LG}px;
            border-top-right-radius: {R.LG}px;
            padding: {S.XS}px {S.LG}px;
            margin-right: {S.XS}px;
            margin-top: {S.XS}px;
            font-weight: {F.MEDIUM};
            min-width: 110px;
            max-width: 220px;
        }}
        QTabWidget#documentTabs QTabBar::tab:hover:!selected {{
            background: {_rgba(c['primary_soft'], 210)};
            color: {c['primary']};
        }}
        QTabWidget#documentTabs QTabBar::tab:selected {{
            background: {_rgba(c['bg_elevated'], 250)};
            color: {c['text_primary']};
            border-color: {c['border_strong']};
        }}
        QTabWidget#documentTabs QTabBar::close-button {{
            subcontrol-position: right;
            border-radius: {R.SM}px;
            margin-left: {S.SM}px;
        }}
        QTabWidget#documentTabs QTabBar::close-button:hover {{
            background: {c['error_soft']};
        }}
        QToolButton#tabCloseButton {{
            min-height: 24px;
            max-height: 24px;
            min-width: 24px;
            max-width: 24px;
            padding: 0;
            margin-left: {S.SM}px;
            border-radius: 12px;
        }}
        QToolButton#tabCloseButton:hover {{
            background: {c['error_soft']};
            color: {c['error']};
        }}

        QTabWidget#documentTabs QTabBar::scroller {{
            width: 58px;
        }}
        QTabWidget#documentTabs QToolButton#ScrollLeftButton,
        QTabWidget#documentTabs QToolButton#ScrollRightButton,
        QToolButton#documentTabListButton {{
            background: {_rgba(c['bg_elevated'], 245)};
            color: {c['text_secondary']};
            border: 1px solid {c['border']};
            border-radius: {R.SM}px;
            padding: 0;
        }}
        QTabWidget#documentTabs QToolButton#ScrollLeftButton,
        QTabWidget#documentTabs QToolButton#ScrollRightButton {{
            min-width: 27px;
            max-width: 27px;
            min-height: 28px;
            max-height: 28px;
        }}
        QTabWidget#documentTabs QToolButton#ScrollLeftButton:hover,
        QTabWidget#documentTabs QToolButton#ScrollRightButton:hover,
        QToolButton#documentTabListButton:hover {{
            background: {c['primary_soft']};
            border-color: {c['primary']};
            color: {c['primary']};
        }}
        QToolButton#documentTabListButton::menu-indicator {{
            image: none;
            width: 0;
        }}

        QFrame#splitPane {{
            background: transparent;
            border: none;
        }}
        QFrame#splitPaneHeader {{
            min-height: 38px;
            max-height: 38px;
            background: {_rgba(c['bg_surface'], 245)};
            border: none;
            border-bottom: 1px solid {c['separator']};
        }}
        QLabel#splitPaneLabel {{
            color: {c['text_secondary']};
            font-size: {F.XS}px;
            font-weight: {F.SEMIBOLD};
        }}
        QComboBox#splitDocumentSelector {{
            min-height: 28px;
            max-height: 28px;
            border-radius: {R.MD}px;
            background: {c['bg_sidebar']};
        }}
        QLabel#splitModeBadge {{
            color: {c['success']};
            background: {c['success_soft']};
            border: 1px solid {c['success']};
            border-radius: {R.MD}px;
            padding: 3px {S.SM}px;
            font-size: {F.XS}px;
        }}
        QFrame#splitPane[externalDocument="true"] QLabel#splitModeBadge {{
            color: {c['warning']};
            background: {c['warning_soft']};
            border-color: {c['warning']};
        }}
        QToolButton#splitPaneButton {{
            min-height: 28px;
            max-height: 28px;
            padding: 0 {S.SM}px;
            border-radius: {R.MD}px;
            background: {c['bg_sidebar']};
        }}

        QFrame#leftPanel, QFrame#contextPanel {{
            background: {_rgba(c['bg_sidebar'], 225)};
            border: none;
        }}
        QFrame#leftPanel {{
            background: {_rgba(c['bg_surface'], 235)};
        }}
        QFrame#contextPanel {{
            background: {_rgba(c['bg_surface'], 235)};
        }}
        QWidget#contextPage {{
            background: {_rgba(c['bg_elevated'], 188)};
            border: 1px solid {c['border']};
            border-radius: {R.XL}px;
        }}
        QTabWidget#annotationTabs::pane {{
            background: {_rgba(c['bg_surface'], 205)};
            border: 1px solid {c['border']};
            border-radius: {R.LG}px;
        }}
        QTabWidget#annotationTabs QTabBar::tab {{
            min-height: 30px;
            margin: 0 {S.XXS}px {S.XS}px 0;
            padding: 0 {S.MD}px;
            background: transparent;
            border: 1px solid transparent;
            border-radius: {R.MD}px;
        }}
        QTabWidget#annotationTabs QTabBar::tab:hover:!selected {{
            color: {c['primary']};
            background: {c['bg_hover']};
        }}
        QTabWidget#annotationTabs QTabBar::tab:selected {{
            color: {c['primary']};
            background: {c['primary_soft']};
            border-color: {c['primary_glow']};
        }}
        QWidget#sidebarHeader {{
            background: {_rgba(c['bg_elevated'], 200)};
            border: 1px solid {c['border']};
            border-radius: {R.LG}px;
        }}
        QWidget#sidebarContent, QWidget#sidebarSectionBody {{
            background: transparent;
        }}
        QLabel#sidebarBrandMark {{
            background: {c['primary_soft']};
            border: 1px solid {c['primary_glow']};
            border-radius: {R.LG}px;
        }}
        QLabel#sidebarTitle {{
            font-size: {F.MD}px;
            font-weight: {F.SEMIBOLD};
        }}
        QLabel#sidebarSubtitle, QLabel#sidebarFooterText {{
            color: {c['text_secondary']};
            font-size: {F.XS}px;
        }}
        QLabel#sidebarStatusDot {{
            color: {c['success']};
            font-size: 9px;
        }}
        QWidget#sidebarFooter {{
            background: {_rgba(c['bg_elevated'], 200)};
            border: 1px solid {c['border']};
            border-radius: {R.LG}px;
        }}
        QScrollArea#sidebarScroll {{
            background: transparent;
            border: none;
        }}
        QScrollArea#sidebarScroll > QWidget > QWidget {{ background: transparent; }}
        QScrollArea#sidebarScroll QScrollBar:vertical {{
            width: 5px;
            margin: 2px 0;
        }}
        QScrollArea#sidebarScroll QScrollBar::handle:vertical {{
            min-height: 36px;
            border-radius: 2px;
        }}
        QLineEdit#sidebarSearch {{
            min-height: 34px;
            background: {_rgba(c['bg_elevated'], 210)};
            border: 1px solid {c['border']};
            border-radius: {R.LG}px;
            padding: 0 {S.SM}px;
        }}
        QLineEdit#sidebarSearch:hover {{ border-color: {c['border']}; }}
        QLineEdit#sidebarSearch:focus {{
            background: {c['bg_surface']};
            border-color: {c['primary']};
        }}
        QToolButton#sidebarCollapseButton {{
            min-width: 30px;
            max-width: 30px;
            min-height: 30px;
            max-height: 30px;
            padding: 0;
            border-radius: {R.MD}px;
        }}
        QToolButton#sidebarSectionButton {{
            min-height: 30px;
            color: {c['legacy_green_text']};
            font-size: {F.XS}px;
            font-weight: {F.SEMIBOLD};
            text-align: left;
            padding: 0 {S.SM}px;
            border: none;
            border-radius: {R.MD}px;
        }}
        QToolButton#sidebarSectionButton:hover {{
            color: {c['legacy_green_text']};
            background: {c['legacy_green_soft']};
        }}
        QPushButton#sidebarNavButton {{
            min-height: 44px;
            max-height: 44px;
            margin: 0 {S.XXS}px;
            padding: 0 {S.SM}px;
            text-align: left;
            border: none;
            border: 1px solid transparent;
            border-left: 3px solid transparent;
            border-radius: {R.LG}px;
            font-size: {F.MD}px;
        }}
        QPushButton#sidebarNavButton:hover,
        QPushButton#sidebarNavButton[hovered="true"],
        QPushButton#sidebarNavButton[active="true"] {{
            color: {c['text_primary']};
            background: {c['primary_soft']};
            border-color: {c['primary_glow']};
            border-left-color: {c['primary']};
            font-weight: {F.SEMIBOLD};
        }}
        QPushButton#sidebarNavButton:pressed {{
            background: {c['bg_active']};
            border-color: {c['primary']};
            border-left-color: {c['primary']};
        }}
        QPushButton#sidebarNavButton[collapsed="true"] {{
            margin: 0;
            padding: 0;
            border-left: none;
            border-radius: {R.MD}px;
        }}
        QPushButton#sidebarNavButton:focus {{
            border-color: {c['primary']};
        }}
        QPushButton#sidebarNavButton:disabled {{
            background: transparent;
        }}
        QLabel#appTitle {{ font-size: {F.XL}px; font-weight: {F.SEMIBOLD}; }}
        QLabel#sectionTitle {{
            color: {c['text_secondary']};
            font-size: {F.XS}px;
            font-weight: {F.SEMIBOLD};
            padding: {S.MD}px {S.SM}px {S.XS}px {S.SM}px;
        }}
        QLabel#secondary, QLabel#fileInfo, QLabel#pageInfo {{ color: {c['text_secondary']}; }}
        QLabel#deepSearchCurrentFile {{ color: {c['primary']}; font-style: italic; }}
        QLabel#deepSearchTip {{ color: {c['text_disabled']}; font-style: italic; font-size: {F.XS}px; }}
        QLineEdit#deepSearchQuery {{ font-size: {F.MD}px; }}
        QLabel#validationError {{
            color: {c['error']};
            background: {c['bg_sidebar']};
            border-left: 3px solid {c['error']};
            border-radius: {R.SM}px;
            padding: {S.SM}px {S.MD}px;
        }}
        QLabel#pageRangeStatus {{
            color: {c['success']};
            background: {c['bg_sidebar']};
            border-left: 3px solid {c['success']};
            border-radius: {R.SM}px;
            padding: {S.SM}px {S.MD}px;
        }}
        QLabel#fontInspectorSample {{
            color: {c['text_primary']};
            background: {c['bg_surface']};
            border: 1px solid {c['border']};
            border-radius: {R.LG}px;
            padding: {S.LG}px;
            min-height: 52px;
        }}
        QLabel#fontInspectorWarning {{
            color: {c['warning']};
            background: {c['warning_soft']};
            border-left: 3px solid {c['warning']};
            border-radius: {R.SM}px;
            padding: {S.SM}px {S.MD}px;
        }}
        QLabel#infoBarBadge {{
            color: {c['on_primary']};
            background: {c['primary']};
            border-radius: 10px;
            padding: 1px 7px;
            font-size: {F.XS}px;
            font-weight: {F.BOLD};
            min-width: 20px;
        }}
        QLineEdit#zoomInput {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: {R.SM}px;
            color: {c['text_primary']};
            padding: 0 {S.XS}px;
            font-size: {F.SM}px;
        }}
        QLineEdit#zoomInput:hover {{
            border-color: {c['border']};
        }}
        QLineEdit#zoomInput:focus {{
            border-color: {c['primary']};
            background: {c['bg_surface']};
        }}
        QFrame#thumbnailPanel {{
            background: {c['bg_sidebar']};
            border-right: 1px solid {c['border']};
        }}
        QLabel#thumbnailPageNumber {{
            color: {c['text_secondary']};
            font-size: {F.XS}px;
            padding: {S.XS}px 0;
        }}
        QLabel#thumbnailImage {{
            background: {c['bg_surface']};
            border: 1px solid {c['border']};
            border-radius: {R.SM}px;
        }}
        QLabel#thumbnailImage[placeholder="true"] {{
            border: 1px dashed {c['border_strong']};
        }}
        QListWidget#thumbnailList {{
            background: transparent;
            border: none;
        }}
        QListWidget#thumbnailList::item:selected {{
            background: {c['primary_soft']};
            border-radius: {R.SM}px;
        }}
        QFrame#navPanel {{
            background: {c['bg_sidebar']};
            border-right: 1px solid {c['border']};
        }}
        QFrame#navSubPanel {{
            background: transparent;
            border: none;
        }}
        QWidget#navTabStrip {{
            background: {c['bg_surface']};
            border-bottom: 1px solid {c['border']};
        }}
        QToolButton#navTabButton {{
            min-width: 34px;
            max-width: 34px;
            min-height: {D.NAV_TAB_H}px;
            max-height: {D.NAV_TAB_H}px;
            padding: 0;
            border: none;
            border-radius: {R.MD}px;
        }}
        QToolButton#navTabButton:checked {{
            color: {c['primary']};
            background: {c['primary_soft']};
            border-color: {c['primary_glow']};
        }}
        QLabel#navEmpty {{
            color: {c['text_secondary']};
            font-size: {F.SM}px;
            padding: {S.MD}px {S.SM}px;
        }}
        QTreeWidget#outlineTree, QListWidget#navList {{
            background: transparent;
            border: none;
            outline: none;
        }}
        QTreeWidget#outlineTree::item, QListWidget#navList::item {{
            min-height: 30px;
            padding: 0 {S.XS}px;
            border-radius: {R.SM}px;
        }}
        QTreeWidget#outlineTree::item:hover, QListWidget#navList::item:hover {{
            background: {c['bg_hover']};
        }}
        QTreeWidget#outlineTree::item:selected, QListWidget#navList::item:selected {{
            color: {c['primary']};
            background: {c['primary_soft']};
        }}
        QLineEdit#searchQuery {{
            min-height: 32px;
            background: {c['bg_surface']};
            border: 1px solid {c['border_strong']};
            border-radius: {R.LG}px;
            padding: 0 {S.MD}px;
        }}
        QLineEdit#searchQuery:focus {{ border-color: {c['primary']}; }}
        QDialog#commandPalette {{
            background: {c['bg_elevated']};
            border: 1px solid {c['border_strong']};
            border-radius: {R.LG}px;
        }}
        QLineEdit#paletteInput {{
            min-height: 40px;
            border: none;
            border-bottom: 1px solid {c['border']};
            border-radius: 0;
            background: transparent;
            font-size: {F.LG}px;
            padding: 0 {S.MD}px;
        }}
        QTreeWidget#paletteList {{
            background: transparent;
            border: none;
        }}
        QTreeWidget#paletteList::item {{
            min-height: 36px;
            padding: 0 {S.MD}px;
            border-radius: {R.SM}px;
        }}
        QTreeWidget#paletteList::item:selected {{
            color: {c['on_primary']};
            background: {c['primary']};
        }}
        QLabel#paletteShortcut {{
            color: {c['text_secondary']};
            font-size: {F.SM}px;
        }}
        QLineEdit[invalid="true"] {{
            border: 1px solid {c['error']};
        }}
        QTableWidget[dragActive="true"] {{
            border: 2px dashed {c['primary']};
            border-radius: {R.MD}px;
        }}
        QLabel#emptyTitle {{ font-size: {F.TITLE}px; font-weight: {F.SEMIBOLD}; }}
        QLabel#emptyDescription {{ color: {c['text_secondary']}; font-size: {F.LG}px; }}
        QLabel#emptyEyebrow {{
            color: {c['primary']};
            font-size: {F.XS}px;
            font-weight: {F.BOLD};
        }}
        QLabel#emptyIconBadge {{
            background: {c['primary_soft']};
            border: 1px solid {c['primary_glow']};
            border-radius: 22px;
        }}
        QLabel#dropHint {{ color: {c['text_secondary']}; font-size: {F.SM}px; }}
        QFrame#emptyDropZone {{
            background: {c['bg_surface']};
            border: 1px dashed {c['border_strong']};
            border-radius: 18px;
        }}
        QFrame#emptyDropZone[dragActive="true"] {{
            background: {c['primary_soft']};
            border: 2px solid {c['primary']};
        }}
        QFrame#emptyDropZone[dragActive="true"] QLabel#emptyTitle,
        QFrame#emptyDropZone[dragActive="true"] QLabel#dropHint {{ color: {c['primary']}; }}
        QFrame#emptyDropZone QListWidget {{
            background: transparent;
            border: none;
        }}
        QFrame#emptyDropZone QListWidget::item {{
            min-height: 32px;
            border-radius: {R.MD}px;
            padding: 0 {S.SM}px;
        }}
        QFrame#emptyDropZone QListWidget::item:hover {{
            color: {c['primary']};
            background: {c['primary_soft']};
        }}
        QToolButton, QPushButton {{
            min-height: {D.CONTROL_H}px;
            border: 1px solid transparent;
            border-radius: {R.SM}px;
            padding: 0 {S.MD}px;
            background: transparent;
        }}
        QToolButton:hover, QPushButton:hover {{
            color: {c['primary']};
            background: {c['primary_soft']};
            border-color: {c['primary_glow']};
        }}
        QToolButton:pressed, QPushButton:pressed {{ background: {c['bg_active']}; }}
        QToolButton:disabled, QPushButton:disabled {{ color: {c['text_disabled']}; }}
        QToolButton:focus, QPushButton:focus {{ border-color: {c['primary']}; }}
        QToolButton[compact="true"], QPushButton[compact="true"] {{
            min-height: 26px;
            max-height: 26px;
        }}
        QToolButton#swatchButton {{
            min-height: 28px;
            max-height: 28px;
            min-width: 28px;
            max-width: 28px;
            padding: 0;
        }}
        QPushButton[primary="true"] {{
            min-height: 38px;
            color: {c['on_primary']};
            background: {c['primary']};
            border-color: {c['primary']};
            border-radius: {R.MD}px;
            font-weight: {F.SEMIBOLD};
        }}
        QPushButton[primary="true"]:hover {{
            color: {c['on_primary']};
            background: {c['primary_hover']};
            border-color: {c['primary_glow']};
        }}
        QPushButton[primary="true"]:pressed {{ background: {c['primary_pressed']}; }}
        QPushButton[secondary="true"] {{
            background: {c['bg_surface']};
            border-color: {c['border_strong']};
        }}
        QToolButton#commandButton {{
            min-width: {D.ICON_BUTTON}px;
            max-width: {D.ICON_BUTTON}px;
            padding: 0;
            border-radius: {R.MD}px;
        }}
        QToolButton#commandButton:hover,
        QToolButton#commandButton[hovered="true"] {{
            background: {c['primary_soft']};
            border-color: {c['primary_glow']};
        }}
        QToolButton#commandButton:pressed {{
            background: {c['primary_glow']};
            border-color: {c['primary']};
        }}
        QToolButton#commandButton:checked {{
            color: {c['primary']};
            background: {c['primary_soft']};
            border-color: {c['primary']};
        }}
        QToolButton#commandButton::menu-indicator {{ image: none; width: 0; height: 0; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
            min-height: {D.CONTROL_H}px;
            color: {c['text_primary']};
            background: {c['bg_surface']};
            border: 1px solid {c['border_strong']};
            border-radius: {R.SM}px;
            padding: 0 {S.SM}px;
            selection-background-color: {c['primary']};
        }}
        QTextEdit {{ padding: {S.SM}px; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{
            border: 1px solid {c['primary']};
        }}
        /* Give spin-box +/- controls a generous, reliable hit target. Use
           explicit SVG glyphs: Qt's stylesheet style otherwise consumes the
           arrow primitive before the platform/proxy style can paint it. */
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            width: 28px;
            border-left: 1px solid {c['border_strong']};
            background: {c['bg_sidebar']};
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: {R.SM}px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: {R.SM}px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover,
        QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
            background: {c['primary_soft']};
        }}
        QSpinBox::up-arrow, QSpinBox::down-arrow,
        QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{
            width: 14px;
            height: 14px;
        }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{spin_plus}");
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{spin_minus}");
        }}
        /* Combo boxes embed a QLineEdit; the global 34px min-height would
           clip its text inside compact selectors (height overflow). */
        QComboBox QLineEdit {{
            min-height: 0px;
            max-height: 22px;
            padding: 0;
            background: transparent;
            border: none;
        }}
        QLineEdit#zoomInput, QLineEdit#pageInput {{
            min-height: 28px;
            max-height: 28px;
        }}
        QSlider#zoomSlider {{
            min-width: 90px;
            max-width: 140px;
        }}
        QSlider#zoomSlider::groove:horizontal {{
            height: 4px;
            background: {c['border']};
            border-radius: 2px;
        }}
        QSlider#zoomSlider::sub-page:horizontal {{
            background: {c['primary']};
            border-radius: 2px;
        }}
        QSlider#zoomSlider::handle:horizontal {{
            width: 12px;
            height: 12px;
            margin: -4px 0;
            background: {c['primary']};
            border-radius: 6px;
        }}
        /* Qt stops painting its native combo arrow once the subcontrol is
           styled. Supply a theme-aware glyph and a visible button surface so
           the control never becomes an invisible-but-clickable hit area. */
        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 30px;
            background: {c['bg_sidebar']};
            border: none;
            border-left: 1px solid {c['border_strong']};
            border-top-right-radius: {R.SM}px;
            border-bottom-right-radius: {R.SM}px;
        }}
        QComboBox::drop-down:hover {{
            background: {c['primary_soft']};
            border-left-color: {c['primary_glow']};
        }}
        QComboBox::down-arrow {{
            image: url("{combo_down}");
            width: 14px;
            height: 14px;
        }}
        QComboBox::down-arrow:on {{ top: 1px; }}
        /* Modern rounded, slightly translucent popup menus. The windows are
           made translucent by the proxy style so the corners are truly round. */
        QMenu {{
            background-color: {_rgba(c['bg_surface'], 246)};
            color: {c['text_primary']};
            border: 1px solid {c['border_strong']};
            border-radius: {R.LG}px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: {S.SM}px {S.XL}px;
            margin: 1px {S.XS}px;
            border-radius: {R.MD}px;
            background: transparent;
        }}
        QMenu::item:selected {{ color: {c['primary']}; background: {c['primary_soft']}; }}
        QMenu::item:disabled {{ color: {c['text_disabled']}; }}
        QMenu::separator {{ height: 1px; background: {c['border']}; margin: {S.XS}px {S.SM}px; }}
        QComboBox QAbstractItemView {{
            background-color: {_rgba(c['bg_surface'], 246)};
            color: {c['text_primary']};
            border: 1px solid {c['border_strong']};
            border-radius: {R.LG}px;
            padding: 4px;
            outline: none;
            selection-background-color: {c['primary_soft']};
            selection-color: {c['primary']};
        }}
        QToolTip {{
            color: {c['text_primary']};
            background: {c['bg_elevated']};
            border: 1px solid {c['border_strong']};
            padding: {S.XS}px {S.SM}px;
        }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {c['border_strong']}; min-height: 28px; border-radius: 4px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {c['border_strong']}; min-width: 28px; border-radius: 4px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QTableView, QTableWidget {{
            background: {c['bg_surface']};
            alternate-background-color: {c['bg_sidebar']};
            border: 1px solid {c['border']};
            border-radius: {R.MD}px;
            gridline-color: {c['border']};
            selection-background-color: {c['bg_active']};
        }}
        QTableWidget#deepSearchResultsTable,
        QTableWidget#deepSearchErrorTable {{
            selection-color: {c['on_primary']};
            selection-background-color: {c['primary']};
        }}
        QTableWidget#deepSearchResultsTable::item:selected,
        QTableWidget#deepSearchErrorTable::item:selected {{
            color: {c['on_primary']};
            background: {c['primary']};
            border: 1px solid {c['primary_pressed']};
        }}
        QHeaderView::section {{
            min-height: 32px;
            background: {c['bg_sidebar']};
            border: none;
            border-bottom: 1px solid {c['border']};
            padding: 0 {S.SM}px;
            font-weight: {F.MEDIUM};
        }}
        QTabWidget::pane {{ border: 1px solid {c['border']}; }}
        QTabBar::tab {{ padding: {S.SM}px {S.LG}px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: {c['primary']}; border-bottom-color: {c['primary']}; }}
        QGroupBox {{
            border: 1px solid {c['border']};
            border-radius: {R.LG}px;
            margin-top: {S.MD}px;
            padding: {S.LG}px {S.MD}px {S.MD}px {S.MD}px;
            font-weight: {F.MEDIUM};
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: {S.MD}px; padding: 0 {S.XS}px; }}
        QProgressBar {{
            min-height: 4px; max-height: 4px;
            border: none; border-radius: 2px;
            background: {c['border']}; text-align: center;
        }}
        QProgressBar::chunk {{ background: {c['primary']}; border-radius: 2px; }}
        QProgressBar#taskProgress {{ min-height: 6px; max-height: 6px; }}
        QSplitter::handle {{ background: {c['separator']}; }}
        QSplitter::handle:horizontal {{ width: 1px; }}
        QSplitter::handle:vertical {{ height: 1px; }}
        QSplitter::handle:hover {{ background: {c['border_strong']}; }}
    """


# Compatibility aliases retained while old imports are removed.
def toolbar() -> str: return global_style()
def menu() -> str: return global_style()
def scrollbar() -> str: return global_style()
def dock() -> str: return global_style()
def progress() -> str: return global_style()
def sidebar_btn() -> str: return global_style()
def icon_btn() -> str: return global_style()
def action_btn() -> str: return global_style()
def input_small() -> str: return global_style()
def combo_small() -> str: return global_style()
def capsule() -> str: return global_style()
def separator() -> str: return global_style()


def shadow(widget) -> None:
    # Native minimal styling deliberately avoids decorative drop shadows.
    widget.setGraphicsEffect(None)
