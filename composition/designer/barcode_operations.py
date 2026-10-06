"""Atomic template barcode edits and same-position sheet-front placement."""
from __future__ import annotations

import copy
import sqlite3

from composition.engine.barcode_profiles import INSERTER_I25, BarcodeProfile, BarcodeToken, profile_values
from composition.engine.inserter_production import validate_size
from composition.media.planner import build_print_plan
from composition.template.model import CompositionError, Template, parse_value

from .repeat_objects import append_exact_copies


def apply_template_profile(value, page_id, object_id, profile, duplex, repeat):
    after = copy.deepcopy(value)
    page = next(p for p in after["pages"] if p["id"] == page_id)
    element = next(e for e in page["elements"] if e["id"] == object_id)
    if after["media"].get("enabled") and bool(after["media"].get("duplex")) != duplex:
        raise CompositionError("Printing follows the active Media settings.")
    after["media"]["duplex"] = duplex
    element["barcode_profile"] = profile.to_dict()
    if profile.preset == INSERTER_I25:
        element["type"] = "i25"
        if element["rules"].get("alternative") is not None:
            raise CompositionError("Remove alternative barcode content before applying a production profile.")
        validate_size(Template.from_dict(after).pages[after["pages"].index(page)].elements[
            page["elements"].index(element)], "0"*18)
    parsed = Template.from_dict(after)
    if profile.preset == INSERTER_I25:
        controls = [e for e in page["elements"] if e.get("barcode_profile", {}).get("preset") == INSERTER_I25]
        if len(controls) > 1:
            raise CompositionError("The current template page already has another inserter barcode. Resolve the conflict first.")
    targets, copied, updated = [], 0, 0
    if profile.preset == INSERTER_I25 and repeat:
        plan = build_print_plan(parsed, 1)
        roles = sorted({p.role for p in plan.pages() if p.source_page is not None and p.fields()["Side"] == "Front"})
        for index in roles:
            target = after["pages"][index]
            targets.append(index+1)
            if target["id"] == page_id:
                continue
            existing = [e for e in target["elements"] if e.get("barcode_profile", {}).get("preset") == INSERTER_I25]
            if len(existing) > 1:
                raise CompositionError(f"Template page {index+1} has multiple inserter barcodes. Resolve the conflict first.")
            if existing:
                replacement = copy.deepcopy(element)
                replacement["id"] = existing[0]["id"]
                target["elements"][target["elements"].index(existing[0])] = replacement
                updated += 1
            else:
                append_exact_copies([element], target)
                copied += 1
    Template.from_dict(after)
    return after, f"Sheet-front template pages: {', '.join(map(str, targets)) or 'current object only'}. " \
                  f"{copied} added, {updated} existing inserter barcode(s) updated. Same X / Y and dimensions; one Undo restores all pages."


def edit_template_barcode(window, selected_preset=None):
    try:
        _edit_template_barcode(window, selected_preset)
    except (ValueError, KeyError, OSError, sqlite3.DatabaseError) as exc:
        window._error(str(exc))
        if not window.content_invalid:
            window._selection("")


def _edit_template_barcode(window, selected_preset=None):
    if not window._rules_editable() or not window.properties.element:
        return
    element = window.properties.element
    if element.type not in {"qr", "code128", "i25"}:
        return
    from .barcode_setup import BarcodeSetupDialog
    info = window._store() or {}
    fields = {name: "" for name in info.get("metadata", {}).get("fields", [])}
    if info.get("store"):
        from composition.data.source import RecordStore
        fields.update(RecordStore(info["store"]).record(window.record.value()))
    from composition.data.sequences import sequence_record
    fields.update(sequence_record(window.template, fields, window.record.value(), window.page_index))
    def preview_context(duplex):
        value = window.template.to_dict()
        value["media"]["duplex"] = duplex
        count = max(window.record.value(), info.get("metadata", {}).get("record_count", 1))
        plan = build_print_plan(Template.from_dict(value), count)
        page = next(plan.page(1, index) for index in range(1, plan.settings_for(1).output_pages_per_envelope+1)
                    if plan.page(1, index).source_page is not None and plan.page(1, index).role == window.page_index)
        page = plan.page(window.record.value(), page.print_page)
        return {**profile_values(fields), **page.fields()}
    fields = preview_context(bool(window.template.media.get("duplex")))
    if element.barcode_profile:
        profile = BarcodeProfile.from_dict(element.barcode_profile)
    else:
        profile = BarcodeProfile(tokens=[BarcodeToken(kind, text) for kind, text in parse_value(element.value)])
    before = window.template.to_dict()
    dialog = BarcodeSetupDialog(profile, fields, window, symbology=element.type,
        duplex=bool(window.template.media.get("duplex")), printing_locked=bool(window.template.media.get("enabled")),
        template=True, selected_preset=selected_preset)
    def check_placement():
        if dialog.preset.currentData() != INSERTER_I25:
            return "Generic profile applies to the current object."
        _, summary = apply_template_profile(before, window.page.id, element.id, dialog.candidate(),
            bool(dialog.printing.currentData()), dialog.repeat.isChecked())
        return summary
    dialog.preview_context = preview_context
    dialog.placement_check = check_placement
    dialog.refresh()
    if dialog.exec():
        try:
            after, summary = apply_template_profile(before, window.page.id, element.id, dialog.profile,
                                                     dialog.duplex, dialog.repeat.isChecked())
        except ValueError as exc:
            window._error(str(exc))
            return
        window._commit(before, after, "Configure barcode and sheet-front placement", element.id)
        window.message.setText(summary)
    window._selection("")
    dialog.deleteLater()
