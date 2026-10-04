"""Small native viewport checks and screenshots of the real Designer/workflow UI."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def main():
    from PyQt6.QtWidgets import QApplication

    from composition.designer.project_host import DesignerProjectHost
    from styles.components import global_style
    from styles.theme import apply_theme
    from workflow.node_settings import StepDialog
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=True)
    app=QApplication([])
    app.setOrganizationName("PDFDocuEdit QA")
    app.setApplicationName("Workflow viewport checks")
    host=DesignerProjectHost()
    host.show()
    metrics=[]
    for theme in ("dark","light"):
        apply_theme(app,theme)
        app.setStyleSheet(global_style())
        host.resize(960,640)
        app.processEvents()
        assert host.width()==960
        assert all(host.start.grid.getItemPosition(i)[1]==0 for i in range(3))
        host.grab().save(str(output/f"designer-home-{theme}.png"))
        workflow=host.new_mail_merge_workflow()
        workflow.select_node(workflow.spec.node("template").id)
        workflow.insert_step("clean_fields")
        workflow.duplicate_node(workflow.spec.node("clean_fields"))
        from workflow.chrome import auto_layout
        auto_layout(workflow)
        for width in (1280,960):
            host.resize(width,720 if width==1280 else 640)
            app.processEvents()
            assert host.width()==width
            assert workflow.canvas.viewport().height()>350
            for button in (workflow.next_step,workflow.settings_toggle,workflow.library_toggle):
                assert button.isVisible()
                assert button.mapTo(host,button.rect().topRight()).x()<width
            host.grab().save(str(output/f"workflow-v3-{theme}-{width}.png"))
            metrics.append({"theme":theme,"width":width,"canvas_height":workflow.canvas.viewport().height(),
                "scale":host.devicePixelRatioF(),"steps":len(workflow.spec.chain())})
        dialog=StepDialog(workflow.spec.node("clean_fields"),["Name","Account_No"],host)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output/f"workflow-settings-{theme}.png"))
        dialog.close()
        workflow.undo.setClean()
        host.close_project(workflow)
        app.processEvents()
    host.shutdown()
    host.close()
    (output/"viewport-checks.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
    print(json.dumps(metrics))


if __name__=="__main__":
    main()
