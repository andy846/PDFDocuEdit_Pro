"""Declarative mailpiece detection over PDF text layers; no Qt or executable rules."""
from __future__ import annotations

import copy
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz

from composition.production.generator import check_cancel
from composition.template.model import MM_TO_PT, CompositionError

from .model import EnvelopeSettings
from .planner import EnvelopePlan
from .source import _stat, inspect_source

KINDS = {"page_number", "document_id", "first_text", "region_present", "separator"}


@dataclass
class DetectionConfig:
    rules: list[dict] = field(default_factory=lambda: [{"kind": "page_number", "pattern": "Page {CURRENT} of {TOTAL}"}])
    combine: str = "any"
    region_mm: list[float] | None = None
    remove_separators: bool = True
    version: int = 1

    def validate(self):
        if type(self.version) is not int or self.version != 1 or self.combine not in ("any", "all"):
            raise CompositionError("Unsupported detection configuration.")
        if not isinstance(self.rules, list) or not 1 <= len(self.rules) <= 4:
            raise CompositionError("Choose one to four detection rules.")
        kinds = []
        for rule in self.rules:
            if not isinstance(rule, dict) or rule.get("kind") not in KINDS:
                raise CompositionError("Unsupported detection rule.")
            kind = rule["kind"]
            kinds.append(kind)
            if kind in ("page_number", "document_id"):
                _pattern(rule.get("pattern", ""), kind)
                if kind == "document_id" and type(rule.get("allow_missing_continuation", False)) is not bool:
                    raise CompositionError("Choose whether IDs may be absent from continuation pages.")
            elif kind in ("first_text", "separator"):
                terms = rule.get("terms")
                if (not isinstance(terms, list) or not 1 <= len(terms) <= 10 or
                        any(not isinstance(term, str) or not term.strip() or len(term) > 200 for term in terms)):
                    raise CompositionError("Enter one to ten nonempty literal text markers.")
        if len(kinds) != len(set(kinds)) or ("separator" in kinds and len(kinds) > 1):
            raise CompositionError("Separator detection is a separate mode; other rules may be combined once each.")
        if "region_present" in kinds and self.region_mm is None:
            raise CompositionError("Address/region presence requires a selected search region.")
        if self.region_mm is not None:
            if (not isinstance(self.region_mm, list) or len(self.region_mm) != 4 or
                    any(type(n) not in (int, float) or not math.isfinite(n) for n in self.region_mm) or
                    min(self.region_mm[:2]) < 0 or min(self.region_mm[2:]) <= 0):
                raise CompositionError("Search region must be X, Y, width, height in millimetres.")
        if type(self.remove_separators) is not bool:
            raise CompositionError("Choose whether separator pages are removed.")


def _pattern(value, kind):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise CompositionError("Enter a literal pattern with the required placeholders.")
    required = ("{CURRENT}", "{TOTAL}") if kind == "page_number" else ("{ID}",)
    if any(value.count(token) != 1 for token in required):
        raise CompositionError("Pattern requires exactly one " + " and ".join(required) + ".")
    if kind == "document_id" and not value.replace("{ID}", "").strip():
        raise CompositionError("Document ID pattern needs a literal label, e.g. Account No: {ID}.")
    escaped = re.escape(value.strip()).replace(r"\ ", r"\s+")
    for token in required:
        group = r"([^\n]{1,256})" if token == "{ID}" else r"([0-9]{1,6})"
        escaped = escaped.replace(re.escape(token), group)
    return re.compile(escaped, re.IGNORECASE)


def page_text(page, region_mm):
    if region_mm is None:
        return page.get_text(sort=True)
    x, y, w, h = region_mm
    rect = fitz.Rect(x*MM_TO_PT, y*MM_TO_PT, (x+w)*MM_TO_PT, (y+h)*MM_TO_PT)
    if not page.rect.contains(rect):
        raise CompositionError(f"Source page {page.number+1}: search region extends beyond the visible page.")
    return page.get_text(clip=rect*page.derotation_matrix, sort=True)


def detect_texts(texts, config, *, is_cancelled=None, progress=None):
    """Scan an iterator, retaining boundaries/QC metadata rather than rendered pages."""
    config.validate()
    patterns = {r["kind"]: _pattern(r["pattern"], r["kind"]) for r in config.rules if "pattern" in r}
    starts, excluded, findings, evidence = [], [], [], []
    previous_id = None
    previous_number = None
    count = 0
    last_separator = 0
    seen_ids = set()
    def warn(page, code, message):
        findings.append({"page": page, "code": code, "message": message})
    for count, text in enumerate(texts, 1):
        check_cancel(is_cancelled)
        signals = []
        for rule in config.rules:
            kind = rule["kind"]
            if kind in patterns:
                matches = patterns[kind].findall(text)
                matches = list(dict.fromkeys(matches))
                if len(matches) != 1:
                    if not matches and kind == "document_id" and previous_id is not None and rule.get("allow_missing_continuation", False):
                        signals.append(False)
                        continue
                    warn(count, "missing_signal" if not matches else "ambiguous_signal",
                         f"{kind}: expected one distinct match; found {len(matches)}.")
                    signals.append(False)
                    continue
                if kind == "document_id":
                    identity = " ".join(matches[0].split())
                    changed = previous_id is None or identity != previous_id
                    if changed and identity in seen_ids:
                        warn(count, "repeated_id", "Document ID reappears after another mailpiece. Check duplicate or reordered documents.")
                    signals.append(changed)
                    seen_ids.add(identity)
                    previous_id = identity
                else:
                    # Placeholder order can be chosen by the operator.
                    values = dict(zip(re.findall(r"\{(CURRENT|TOTAL)\}", rule["pattern"]), matches[0], strict=True))
                    current, total = int(values["CURRENT"]), int(values["TOTAL"])
                    if not 1 <= current <= total:
                        warn(count, "invalid_page_number", f"Printed page {current} of {total} is invalid.")
                    if current == 1:
                        if previous_number and previous_number[0] != previous_number[1]:
                            warn(count-1, "incomplete_sequence", f"Previous letter ended at {previous_number[0]} of {previous_number[1]}.")
                    elif previous_number is None or current != previous_number[0]+1 or total != previous_number[1]:
                        expected = previous_number[0]+1 if previous_number else 1
                        warn(count, "page_sequence", f"Expected printed page {expected}; found {current} of {total}. Check missing/duplicate pages.")
                    previous_number = (current, total)
                    signals.append(current == 1)
            else:
                match = bool(text.strip()) if kind == "region_present" else all(term.casefold() in text.casefold() for term in rule["terms"])
                signals.append(match)
        separator = config.rules[0]["kind"] == "separator"
        if separator and signals[0]:
            last_separator = count
            if config.remove_separators:
                excluded.append(count)
            if count == 1 and not config.remove_separators:
                starts.append(1)
                warn(1, "leading_separator", "Leading separator retained as a one-page mailpiece; review it.")
            evidence.append({"page": count, "matched": ["separator"]})
            continue
        if separator:
            new = not starts or count-1 == last_separator
        else:
            new = any(signals) if config.combine == "any" else all(signals)
            if any(signals) and not all(signals) and len(signals) > 1:
                warn(count, "rule_disagreement", "Boundary rules disagree. Check the proposed split/merge before accepting.")
        if not starts or new:
            starts.append(count)
            evidence.append({"page": count, "matched": [r["kind"] for r, hit in zip(config.rules, signals, strict=True) if hit]})
            if count == 1 and not new and not separator:
                warn(count, "unmarked_start", "First PDF page does not match the configured start rule.")
        if progress and count % 100 == 0:
            progress(count, 0, f"Scanning source page {count:,}")
    if count == 0 or not starts:
        raise CompositionError("No document pages detected. Choose a text-layer PDF and review the detection rules.")
    if previous_number and previous_number[0] != previous_number[1]:
        warn(count, "incomplete_sequence", f"Final letter ended at {previous_number[0]} of {previous_number[1]}.")
    groups = []
    excluded_set = set(excluded)
    for index, start in enumerate(starts):
        end = starts[index+1]-1 if index+1 < len(starts) else count
        while end in excluded_set:
            end -= 1
        if start <= end:
            groups.append([start, end])
    # A removed separator inside a range must also close that range.
    if config.rules[0]["kind"] == "separator" and config.remove_separators:
        groups = []
        cursor = 1
        for separator in excluded+[count+1]:
            if cursor <= separator-1:
                groups.append([cursor, separator-1])
            cursor = separator+1
    EnvelopePlan(count, EnvelopeSettings(groups=groups, excluded_pages=excluded))
    distribution = Counter(str(min(4, end-start+1)) for start, end in groups)
    return {"config": asdict(config), "pages": count, "groups": groups, "excluded_pages": excluded,
            "findings": findings, "evidence": evidence, "distribution": dict(distribution), "accepted": False,
            "edits": []}


def scan_pdf(path, config, *, expected_sha256=None, progress=None, is_cancelled=None):
    config.validate()
    source = inspect_source(path, EnvelopeSettings(pages_per_envelope=1), uniform=True,
                            progress=progress, is_cancelled=is_cancelled)
    if expected_sha256 and expected_sha256 != source.sha256:
        raise CompositionError("Source PDF changed. Reinspect it before detecting mailpieces.")
    with fitz.open(source.path) as pdf:
        result = detect_texts((page_text(pdf[n], config.region_mm) for n in range(pdf.page_count)),
                              config, progress=(lambda done, total, message: progress(done, source.pages, message)) if progress else None,
                              is_cancelled=is_cancelled)
    if _stat(Path(source.path)) != (source.size, source.mtime_ns):
        raise CompositionError("Source changed during detection. Reinspect and scan again.")
    result["source_sha256"] = source.sha256
    if progress:
        progress(source.pages, source.pages, f"Detected {len(result['groups']):,} mailpieces; review before applying")
    return {"source": asdict(source), "detection": result}


def edit_boundary(report, index, *, split_page=None, merge_previous=False):
    value = copy.deepcopy(report)
    groups = value["groups"]
    if not 0 <= index < len(groups):
        raise CompositionError("Select a detected mailpiece.")
    if merge_previous:
        if index == 0 or groups[index-1][1]+1 != groups[index][0]:
            raise CompositionError("Only adjacent mailpieces without an excluded separator can be merged.")
        groups[index-1][1] = groups.pop(index)[1]
        value["edits"].append({"action": "merge_previous", "index": index+1})
    elif split_page is not None:
        start, end = groups[index]
        if type(split_page) is not int or not start < split_page <= end:
            raise CompositionError("Split page must lie after the mailpiece start and at/before its end.")
        groups[index:index+1] = [[start, split_page-1], [split_page, end]]
        value["edits"].append({"action": "split", "source_page": split_page})
    value["accepted"] = False
    return value
