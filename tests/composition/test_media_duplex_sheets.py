"""Four-page letters on two physical Stocks, explicit UI choices and output checks."""
import csv
import json
from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import QDialog, QTableWidgetItem

from composition.designer.media_dialog import MediaDialog
from composition.designer.media_sheet_dialog import DuplexSheetDialog
from composition.media.model import default_media
from composition.media.planner import build_print_plan
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, Element, PageSpec, Template
from tests.composition.test_postscript import ps_media
from tests.composition.test_workspace import wait_until


def four_page_template(backend="canon_prismasync",stocks=2):
    media=ps_media("tray",duplex=True) if backend=="postscript" else default_media()
    media.update(duplex=True,blank_policy="block")
    media["stocks"]=media["stocks"][:stocks]
    ids=[stock["id"] for stock in media["stocks"]]
    media["assignments"]={str(page):ids[0 if page<=2 or stocks==1 else 1] for page in range(1,5)}
    media["printer_profile"]["mappings"]={key:media["printer_profile"]["mappings"][key] for key in ids}
    return Template(pages=[PageSpec(name=f"Page {i+1}",elements=[Element(value=f"Letter page {i+1}")]) for i in range(4)],
                    media=media,record_mode="generated",generated_count=3)


@pytest.mark.parametrize("backend",["canon_prismasync","postscript"])
@pytest.mark.parametrize("stocks",[1,2])
def test_four_page_duplex_plan_accepts_one_or_two_stocks(backend,stocks):
    plan=build_print_plan(four_page_template(backend,stocks),300)
    assert (plan.output_pages,plan.sheets,plan.inserted_blanks)==(1200,600,0)
    assert plan.stock_sheets==({"LH_A":600} if stocks==1 else {"LH_A":300,"LH_B":300})
    expected=["LH_A"]*4 if stocks==1 else ["LH_A","LH_A","LH_B","LH_B"]
    assert [plan.page(300,i).stock for i in range(1,5)]==expected
    assert [plan.page(300,i).fields()["Side"] for i in range(1,5)]==["Front","Back","Front","Back"]


@pytest.mark.parametrize("backend",["canon_prismasync","postscript"])
def test_four_page_duplex_production_preserves_pages_and_stock_pairs(backend,tmp_path):
    result=generate(ProductionJob(four_page_template(backend).to_dict(),"",str(tmp_path)))
    assert result.status=="completed",result.error
    assert result.generated_pages==12
    folder=Path(result.report_dir)
    with fitz.open(result.output_pdf) as pdf:
        assert len(pdf)==12
        for index,page in enumerate(pdf):
            assert f"Letter page {index%4+1}" in page.get_text()
    with (folder/"media-plan.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    assert [r["Stock"] for r in rows]==["LH_A","LH_A","LH_B","LH_B"]*3
    if backend=="postscript":
        assert Path(result.output_ps).is_file()
        with (folder/"postscript-pages.csv").open(encoding="utf-8-sig",newline="") as stream:
            audit=list(csv.DictReader(stream))
        requests=[json.loads(r["Request JSON"]) for r in audit if r["Selection programmed"]=="True"]
        assert [r["MediaPosition"] for r in requests]==[0,1]*3
        assert requests[0]["Duplex"] is True
        assert result.media_summary["postscript_pages"]==12
    else:
        assert (folder/"default_ticket.jdf").is_file()


def test_duplex_stock_conflict_still_requires_explicit_blank_insertion():
    model=four_page_template()
    model.media["assignments"].update({"2":"LH_B","3":"LH_A"})
    with pytest.raises(CompositionError,match="Front and back must use the same Stock"):
        build_print_plan(model,1)
    model.media["blank_policy"]="insert"
    plan=build_print_plan(model,1)
    assert (plan.output_pages,plan.sheets,plan.inserted_blanks)==(8,4,4)


@pytest.mark.parametrize("mode",["template","page"])
def test_sheet_ui_updates_both_sides_and_passes_background_preview(qt_application,monkeypatch,mode):
    model=four_page_template()
    # Missing page four must remain visible and repairable, with no guessed Stock.
    model.media["assignments"].pop("4")
    dialog=MediaDialog(model.media,{"kind":"template","project":model.to_dict(),"records":300})
    try:
        assert dialog.assignments.rowCount()==4
        dialog.mode.setCurrentIndex(dialog.mode.findData(mode))
        assert dialog.sheet_button.isEnabled()
        before=dialog.value()
        def cancel(sheet):
            assert sheet.table.rowCount()==2
            sheet.reject()
            return QDialog.DialogCode.Rejected
        monkeypatch.setattr(DuplexSheetDialog,"exec",cancel)
        dialog.sheet_button.click()
        assert dialog.value()==before
        def choose(sheet):
            sheet.accept()
            assert sheet.result()!=QDialog.DialogCode.Accepted  # Missing back-page choice is explicit.
            assert "Sheet 2" in sheet.error.text()
            for row,stock in enumerate(("LH_A","LH_B")):
                box=sheet.table.cellWidget(row,2)
                box.setCurrentIndex(box.findData(stock))
            sheet.accept()
            return sheet.result()
        monkeypatch.setattr(DuplexSheetDialog,"exec",choose)
        dialog.sheet_button.click()
        keys=[page.id for page in model.pages] if mode=="template" else ["1","2","3","4"]
        assert dialog.value()["assignments"]==dict(zip(keys,["LH_A","LH_A","LH_B","LH_B"],strict=True))
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        assert dialog.checked==dialog.value(),dialog.error.text()
        assert dialog.total==1200 and "600 sheets" in dialog.summary.text() and "0 blank backs" in dialog.summary.text()
        dialog.accept()
        assert dialog.result()==QDialog.DialogCode.Accepted
    finally:
        dialog.reject()


def test_new_template_has_every_page_and_sheet_editor_does_not_guess_stocks(qt_application):
    model=four_page_template()
    dialog=MediaDialog({}, {"kind":"template","project":model.to_dict(),"records":1})
    try:
        assert dialog.assignments.rowCount()==4 and not dialog.value()["assignments"]
        assert not dialog.sheet_button.isEnabled()
        dialog.duplex.setChecked(True)
        sheet=dialog.create_sheet_dialog()
        try:
            assert sheet.table.rowCount()==2
            assert all(not box.currentData() for _,box in sheet.pairs)
        finally:
            sheet.deleteLater()
        dialog.mode.setCurrentIndex(dialog.mode.findData("role"))
        assert not dialog.sheet_button.isEnabled()  # Dynamic roles do not promise fixed pairing.
    finally:
        dialog.reject()


def test_odd_template_shows_blank_back_and_preserves_existing_stock(qt_application):
    model=four_page_template()
    model.pages.pop()
    model.media["assignments"].pop("4")
    dialog=MediaDialog(model.media,{"kind":"template","project":model.to_dict(),"records":1})
    try:
        sheet=dialog.create_sheet_dialog()
        try:
            assert "Blank back" in sheet.table.item(1,1).text()
            sheet.accept()
            assert sheet.assignments==model.media["assignments"]
        finally:
            sheet.deleteLater()
        dialog.stocks.setItem(1,0,QTableWidgetItem("LH_A"))
        with pytest.raises(ValueError,match="unique valid IDs"):
            dialog.create_sheet_dialog()
    finally:
        dialog.reject()
