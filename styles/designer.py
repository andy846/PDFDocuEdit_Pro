"""Designer surfaces use the same palette, spacing and corners as PDF Workspace."""
from __future__ import annotations

from .tokens import F, R, S


def designer_style(c):
    return f"""
        QToolBar#designerMainToolbar {{
            background: {c['bg_surface']};
            border: none; border-bottom: 1px solid {c['separator']};
            padding: {S.XXS}px {S.XS}px; spacing: {S.XXS}px;
        }}
        QToolBar#designerMainToolbar QToolButton {{
            background: transparent; border: 1px solid transparent;
            border-radius: {R.SM}px; padding: 3px;
            min-height: 0px; min-width: 0px;
        }}
        QToolBar#designerMainToolbar QToolButton:hover {{
            background: {c['bg_hover']}; border-color: {c['border']};
        }}
        QToolBar#designerMainToolbar QToolButton:checked {{
            background: {c['primary_soft']}; color: {c['primary']};
            border-color: {c['primary']};
        }}
        QToolBar#designerMainToolbar QToolButton[primary="true"] {{
            background: {c['primary']}; color: {c['on_primary']};
            padding: 3px {S.SM}px;
        }}
        QToolBar#designerMainToolbar QToolButton[primary="true"]:disabled {{
            background: {c['bg_hover']}; color: {c['text_disabled']};
        }}
        QToolBar#designerMainToolbar QPushButton {{
            padding: 3px {S.SM}px; min-height: 0px;
        }}
        QToolBar#designerMainToolbar QComboBox,
        QToolBar#designerMainToolbar QDoubleSpinBox {{
            padding: 2px 5px; min-height: 0px;
        }}
        QToolBar#designerMainToolbar QLineEdit {{
            padding: 0; min-height: 0; border: none; background: transparent;
        }}
        QTabWidget#designerProjectTabs::pane {{
            border: none; border-top: 1px solid {c['separator']};
            background: {c['bg_base']};
        }}
        QTabBar#designerProjectTabBar::tab {{
            background: {c['bg_sidebar']}; color: {c['text_secondary']};
            border: 1px solid {c['border']}; border-bottom: none;
            border-top-left-radius: {R.LG}px; border-top-right-radius: {R.LG}px;
            padding: {S.XS}px {S.LG}px; margin: {S.XS}px {S.XS}px 0 0;
            min-width: 100px; max-width: 220px; font-weight: {F.MEDIUM};
        }}
        QTabBar#designerProjectTabBar::tab:selected {{
            background: {c['bg_elevated']}; color: {c['text_primary']};
            border-color: {c['border_strong']};
        }}
        QTabBar#designerProjectTabBar::tab:hover:!selected {{
            background: {c['primary_soft']}; color: {c['primary']};
        }}
        QTabBar#designerProjectTabBar::close-button:hover {{ background: {c['error_soft']}; }}
        QTabWidget#designerPanelTabs::pane {{
            border: none; background: {c['bg_sidebar']};
        }}
        QTabWidget#designerPanelTabs QTabBar::tab,
        QTabBar#designerModeTabs::tab {{
            background: transparent; color: {c['text_secondary']};
            border: none; border-bottom: 2px solid transparent;
            padding: 5px {S.SM}px; min-height: 0px;
        }}
        QTabWidget#designerPanelTabs QTabBar::tab:selected,
        QTabBar#designerModeTabs::tab:selected {{
            color: {c['primary']}; border-bottom-color: {c['primary']};
            background: {c['primary_soft']};
        }}
        QTabWidget#designerPanelTabs QTabBar::tab:hover:!selected,
        QTabBar#designerModeTabs::tab:hover:!selected {{ background: {c['bg_hover']}; }}
        QWidget#designerSidePanel, QScrollArea#designerInspector, QScrollArea#designerDataPanel,
        QWidget#designerProperties {{ background: {c['bg_sidebar']}; }}
        QScrollArea#designerInspector {{ border: none; border-left: 1px solid {c['separator']}; }}
        QScrollArea#designerDataPanel {{ border: none; }}
        QWidget#designerSidePanel QPushButton {{ padding: 2px {S.XS}px; }}
        QWidget#designerProperties QPushButton {{
            padding: 3px {S.XS}px; min-height: 24px;
        }}
        QWidget#designerProperties QComboBox, QWidget#designerProperties QLineEdit {{
            min-height: 26px; padding-top: 2px; padding-bottom: 2px;
        }}
        QDockWidget#designerDock {{ color: {c['text_secondary']}; font-weight: {F.MEDIUM}; }}
        QDockWidget#designerDock::title {{
            background: {c['bg_sidebar']}; padding: {S.XS}px {S.SM}px;
            border-bottom: 1px solid {c['separator']};
        }}
        QStatusBar#designerStatusBar {{
            background: {c['bg_surface']}; border-top: 1px solid {c['separator']};
            padding: 0; min-height: 0;
        }}
        QStatusBar#designerStatusBar::item {{ border: none; }}
    """
