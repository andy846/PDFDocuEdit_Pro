"""Offscreen layout evidence at normal and 200% scaling; does not touch user settings."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from PyQt6.QtCore import QSettings
    from PyQt6.QtGui import QFont, QFontDatabase
    from PyQt6.QtWidgets import QApplication

    from styles.components import global_style
    from styles.theme import apply_theme
    from workflow.branch_graph import add_route
    from workflow.branch_ui import BranchWorkflowWindow
    output=ROOT/"build"/"branch-ui-qa"
    output.mkdir(parents=True,exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(output/"settings"))
    app=QApplication([])
    # Qt offscreen does not enumerate the Windows system font collection.
    from composition.engine.assets import asset_root
    font_id=QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    families=QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError("Unable to load QA UI font")
    app.setFont(QFont(families[0],9))
    apply_theme(app,"dark")
    window=BranchWorkflowWindow()
    window.apply_spec(add_route(window.spec,"Additional letters",{"conditions":[{"field":"Scheme","operator":"eq","value":"B"}]}).to_dict())
    window.arrange_graph()
    window.show()
    for theme in ("dark","light"):
        apply_theme(app,theme)
        app.setStyleSheet(global_style())
        for width,height in ((1280,800),(960,640)):
            window.resize(width,height)
            for tab in range(3):
                window.tabs.setCurrentIndex(tab)
                app.processEvents()
                if tab==0 and width==960:
                    window.compact.setCurrentWidget(window.details)
                app.processEvents()
                window.grab().save(str(output/f"{theme}-{width}-{tab}-{os.getenv('QT_SCALE_FACTOR','1')}.png"))
                if window.width()>width or window.height()>height:
                    raise RuntimeError(f"Layout minimum exceeds {width}×{height}: {window.size()}")
            window.tabs.setCurrentIndex(0)
            if width==960:
                window.compact.setCurrentWidget(window.canvas)
            app.processEvents()
            window.grab().save(str(output/f"{theme}-{width}-canvas-{os.getenv('QT_SCALE_FACTOR','1')}.png"))
    window._close_approved=True
    window.close()
    app.processEvents()
    print(str(output))


if __name__=="__main__":
    main()
