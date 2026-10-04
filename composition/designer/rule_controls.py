"""Designer hooks for object rules; engine remains independent of Qt."""

from __future__ import annotations

from dataclasses import asdict

from composition.template.model import ElementRules


def rules_summary(rules):
    parts = []
    for name, group in [
        ("Visible when", rules.visible_when),
        ("Alternative when", rules.alternative.when if rules.alternative else None),
    ]:
        if group:
            fields = [condition.field[:60] for condition in group.conditions]
            parts.append(f"{name}: {group.mode.title()} / " + ", ".join(fields))
    return "\n".join(parts) or "Always visible / normal content"


class RuleOperations:
    def _rules_editable(self):
        self.properties.apply()
        return not (
            self.content_invalid
            or self.production_worker
            or self.import_worker
            or self.font_requests
            or any(getattr(worker, "task", "") == "background" for worker in self.workers)
            or len(self.canvas.selected_ids()) != 1
            or self.canvas.mode_preview
        )

    def edit_object_rules(self):
        if not self._rules_editable() or not self.properties.element:
            return
        from .rules_dialog import RulesDialog

        info = self._store() or {}
        dialog = RulesDialog(
            self.properties.element, info.get("metadata", {}).get("fields", []), info.get("sample", []), self
        )
        if dialog.exec() and dialog.choice is not None:
            self.apply_object_rules(dialog.choice)

    def apply_object_rules(self, rules):
        if not self._rules_editable() or not self.properties.element:
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        object_id = self.properties.element.id
        target = next(element for element in self._page_dict(after)["elements"] if element["id"] == object_id)
        target["rules"] = asdict(rules)
        self._commit(before, after, "Edit object rules", object_id)

    def clear_object_rules(self):
        self.apply_object_rules(ElementRules())
