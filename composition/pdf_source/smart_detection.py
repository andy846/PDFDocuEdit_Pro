"""Spatial, declarative mailpiece analysis. No Qt, executable rules or ML scores."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import fitz

from composition.production.generator import check_cancel
from composition.template.model import MM_TO_PT, CompositionError

from .detection import DetectionConfig
from .model import EnvelopeSettings
from .planner import EnvelopePlan
from .source import _hash, _stat, inspect_source

COUNTERS = [re.compile(p, re.I) for p in (
    r"\bPage\s*(\d{1,6})\s*(?:of|/)\s*(\d{1,6})\b",
    r"第\s*(\d{1,6})\s*[頁页]\s*(?:[/／,，]?\s*(?:共|總共|总共))\s*(\d{1,6})\s*[頁页]",
    r"(?<![\d/／])(\d{1,6})\s*[/／]\s*(\d{1,6})(?![\d/／])",
)]
ID_LABEL = re.compile(r"(?:(?:MPF|ORSO|Employer|Member|Transaction|Document|Scheme|Primary|Secondary|Recipient)\s+)?(?:Account|Member|Document|Customer|Policy|Reference)\s*(?:No\.?|Number|ID)\b\.?\s*[:：]?|(?:帳戶|账户|戶口|會員|会员|客戶|客户|文件)\s*(?:編號|编号|號碼|号码)\s*[:：]?", re.I)
MARKERS = ("Dear", "敬啟者", "敬启者", "親愛的", "亲爱的", "Statement", "Invoice", "通知書", "通知书")


def normalized(value):
    return unicodedata.normalize("NFKC", value)


def label_key(value):
    return re.sub(r"[\s.:：]", "", normalized(value)).casefold()


def validate_config(config):
    from .detection import _pattern
    if type(config.version) is not int or config.version != 2 or config.combine not in ("any", "all"):
        raise CompositionError("Unsupported detection configuration.")
    if not isinstance(config.profile_name, str) or len(config.profile_name) > 120:
        raise CompositionError("Invalid detection profile name.")
    if not isinstance(config.rules, list) or not 1 <= len(config.rules) <= 3:
        raise CompositionError("Choose one to three spatial detection signals.")
    kinds = set()
    for rule in config.rules:
        if not isinstance(rule, dict) or rule.get("kind") not in ("page_number", "first_text", "document_id"):
            raise CompositionError("Unsupported spatial signal.")
        kind = rule["kind"]
        if kind in kinds:
            raise CompositionError("Use one signal of each type; combine identity fields in one signal.")
        kinds.add(kind)
        allowed = {"kind", "region_mm"} | ({"terms"} if kind == "first_text" else {"fields"} if kind == "document_id" else {"pattern", "auto"})
        if set(rule) - allowed:
            raise CompositionError("Unexpected spatial signal options.")
        _region(rule.get("region_mm"))
        if kind == "first_text":
            terms = rule.get("terms")
            if not isinstance(terms, list) or not 1 <= len(terms) <= 10 or any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in terms):
                raise CompositionError("Choose literal first-page markers.")
        elif kind == "document_id":
            fields = rule.get("fields")
            if not isinstance(fields, list) or not 1 <= len(fields) <= 8:
                raise CompositionError("Choose one to eight identity fields.")
            for item in fields:
                if (not isinstance(item, dict) or set(item) - {"label", "region_mm"}
                        or not isinstance(item.get("label"), str) or not item["label"].strip() or len(item["label"]) > 100):
                    raise CompositionError("Invalid identity label.")
                _region(item.get("region_mm"))
            if len({(label_key(f["label"]), str(f.get("region_mm"))) for f in fields}) != len(fields):
                raise CompositionError("Duplicate identity field.")
        elif rule.get("auto") is True:
            if "pattern" in rule:
                raise CompositionError("Choose automatic counters or a literal pattern.")
        else:
            _pattern(rule.get("pattern", ""), "page_number")
    _region(config.region_mm)
    if config.region_mm is not None or config.remove_separators is not True:
        raise CompositionError("Spatial detection uses individual signal regions and retains all pages.")


def _region(value):
    if value is not None:
        from .detection import DetectionConfig
        # Reuse the established finite-number and geometry validation.
        DetectionConfig(region_mm=value).validate()


def spatial_lines(words):
    """Join horizontally separated PDF blocks sharing the same visible baseline."""
    rows = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center = (word[1] + word[3]) / 2
        if not rows or abs(rows[-1][0] - center) > max(2, (word[3] - word[1]) * .22):
            rows.append((center, [word]))
        else:
            rows[-1][1].append(word)
    return [{"text": " ".join(normalized(w[4]) for w in sorted(row, key=lambda w: w[0])),
             "words": [{"text": normalized(w[4]), "box": list(w[:4])} for w in sorted(row, key=lambda w: w[0])],
             "box": [min(w[0] for w in row), min(w[1] for w in row), max(w[2] for w in row), max(w[3] for w in row)]}
            for _, row in rows]


def text_in(lines, region):
    if region is None:
        return "\n".join(line["text"] for line in lines)
    rect = fitz.Rect(region[0], region[1], region[0] + region[2], region[1] + region[3]) * MM_TO_PT
    return "\n".join(" ".join(w["text"] for w in line["words"] if rect.contains(
                        fitz.Point((w["box"][0]+w["box"][2])/2, (w["box"][1]+w["box"][3])/2)))
                     if "words" in line else line["text"] for line in lines if rect.intersects(fitz.Rect(line["box"])))


def identity_fields(lines, region=None):
    fields = []
    for line in lines:
        text = text_in([line], region)
        matches = list(ID_LABEL.finditer(text))
        for i, match in enumerate(matches):
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            value = text[match.end():end].lstrip(" .:：").strip()
            # Only recognized static labels are persisted; preceding recipient text
            # on the same baseline must never become a profile field name.
            label = match.group().strip(" .:：")
            if value and len(label) <= 100 and len(value) <= 256:
                fields.append((label, value, line["box"]))
    return fields


def identity(lines, rule):
    values = []
    for field in rule["fields"]:
        matches = {v for label, v, _ in identity_fields(lines, field.get("region_mm", rule.get("region_mm")))
                   if label_key(label) == label_key(field["label"])}
        if len(matches) != 1:
            return None, "ambiguous_identity" if matches else "missing_identity"
        values.append(next(iter(matches)))
    return tuple(values), ""


def page_number(lines, rule):
    from .detection import _pattern
    text = text_in(lines, rule.get("region_mm"))
    if rule.get("auto"):
        matches = set()
        for pattern in COUNTERS:
            matches.update(tuple(map(int, pair)) for pair in pattern.findall(text))
    else:
        pattern = _pattern(rule["pattern"], "page_number")
        order = re.findall(r"\{(CURRENT|TOTAL)\}", rule["pattern"])
        matches = {(int(dict(zip(order, pair, strict=True))["CURRENT"]), int(dict(zip(order, pair, strict=True))["TOTAL"]))
                   for pair in pattern.findall(text)}
    return next(iter(matches)) if len(matches) == 1 else None


def marker_hit(lines, rule):
    text = text_in(lines, rule.get("region_mm")).casefold()
    return all(normalized(term).casefold() in text for term in rule["terms"])


class PageIndex:
    """Task-owned disk index: page data is loaded one page at a time."""
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)

    def close(self):
        self.db.close()

    def pages(self):
        for page, payload in self.db.execute("SELECT page,lines FROM pages ORDER BY page"):
            yield page, json.loads(payload)

    def metadata(self):
        return json.loads(self.db.execute("SELECT value FROM meta").fetchone()[0])


def index_pdf(path, cache_path, *, expected_sha256=None, progress=None, is_cancelled=None):
    source = inspect_source(path, EnvelopeSettings(pages_per_envelope=1), uniform=True,
                            progress=progress, is_cancelled=is_cancelled)
    if expected_sha256 and source.sha256 != expected_sha256:
        raise CompositionError("Source PDF changed. Reinspect before detecting mailpieces.")
    cache_path = Path(cache_path)
    if cache_path.exists():
        cached = PageIndex(cache_path)
        try:
            if cached.metadata() == {**asdict(source), "index_version": 2}:
                return source, cached
        except (sqlite3.Error, ValueError, TypeError):
            pass
        cached.close()
        cache_path.unlink()
    cached = PageIndex(cache_path)
    try:
        cached.db.executescript("CREATE TABLE meta(value TEXT); CREATE TABLE pages(page INTEGER PRIMARY KEY,lines TEXT);")
        with fitz.open(source.path) as pdf:
            for number, page in enumerate(pdf, 1):
                check_cancel(is_cancelled)
                words = page.get_text("words")
                if page.rotation:
                    words = [(*list(fitz.Rect(w[:4]) * page.rotation_matrix), *w[4:]) for w in words]
                lines = spatial_lines(words)
                cached.db.execute("INSERT INTO pages VALUES (?,?)", (number, json.dumps(lines, ensure_ascii=False)))
                if progress and (number % 50 == 0 or number == source.pages):
                    progress(number, source.pages, f"Analyzing text positions {number:,} / {source.pages:,}")
        if _stat(Path(source.path)) != (source.size, source.mtime_ns) or _hash(Path(source.path), is_cancelled) != source.sha256:
            raise CompositionError("Source changed during analysis. Scan again.")
        cached.db.execute("INSERT INTO meta VALUES (?)", (json.dumps({**asdict(source), "index_version": 2}),))
        cached.db.commit()
        return source, cached
    except Exception:
        cached.close()
        cache_path.unlink(missing_ok=True)
        raise


def analyze_index(index, *, is_cancelled=None):
    count = index.metadata()["pages"]
    anchors, boxes, ids, first_labels = Counter(), {}, Counter(), []
    counter_pages, counter_starts, counter_boxes = 0, [], []
    examples = {}
    for number, lines in index.pages():
        check_cancel(is_cancelled)
        if page_number(lines, {"auto": True}) is not None:
            counter_pages += 1
            if page_number(lines, {"auto": True})[0] == 1:
                counter_starts.append(number)
            for line in lines:
                if page_number([line], {"auto": True}):
                    counter_boxes.append(line["box"])
        fields = identity_fields(lines)
        for label, _, _ in fields:
            ids[label] += 1
            if number == 1 and label not in first_labels:
                first_labels.append(label)
        for line in lines:
            for term in MARKERS:
                if not line["text"].casefold().startswith(term.casefold()):
                    continue
                key = (term, round(line["box"][0]/6), round(line["box"][1]/6))
                anchors[key] += 1
                word_box = next((w["box"] for w in line.get("words", []) if w["text"].casefold() == term.casefold()), line["box"])
                boxes[key] = list(fitz.Rect(boxes[key]) | fitz.Rect(word_box)) if key in boxes else word_box
                examples.setdefault(key, [])
                if len(examples[key]) < 4:
                    examples[key].append(number)
    suggestions = []
    labels = [label for label in first_labels if ids[label] > 1]
    accounts = [label for label in labels if "account" in label_key(label) or any(t in label for t in ("帳戶", "账户", "戶口"))]
    id_rule = {"kind": "document_id", "fields": [{"label": label} for label in (accounts or labels)[:8]]}
    counter_rule = None
    if counter_starts and counter_starts[0] == 1 and counter_pages >= count*.8:
        region = _box_region(counter_boxes)
        counter_rule = {"kind": "page_number", "auto": True, "region_mm": region}
        suggestions.append({"title": "Printed page sequence", "reason": f"Counters on {counter_pages:,} pages; sequence restarts on {len(counter_starts):,} pages.",
                            "examples": counter_starts[:4], "config": asdict(DetectionConfig(
                                rules=[counter_rule] + ([id_rule] if id_rule["fields"] else []), version=2))})
    proposed_regions = set()
    for key, _ in anchors.most_common():
        # Address blocks can shift a salutation by a few lines. Include the
        # observed nearby positions of the same static feature, retaining its
        # narrow horizontal anchor rather than the recipient-name extent.
        related = [other for other in boxes if other[0] == key[0]
                   and abs(other[1]-key[1]) <= 2 and abs(other[2]-key[2]) <= 4]
        hits = sum(anchors[other] for other in related)
        if hits < 2 or hits >= count or not any(1 in examples[other] for other in related):
            continue
        nearby = [boxes[other] for other in related]
        region = _box_region(nearby)
        signature = (key[0], *region)
        if signature in proposed_regions:
            continue
        proposed_regions.add(signature)
        rules = [{"kind": "first_text", "terms": [key[0]], "region_mm": region}]
        matching_pages = []
        for number, lines in index.pages():
            check_cancel(is_cancelled)
            if marker_hit(lines, rules[0]):
                matching_pages.append(number)
        if len(matching_pages) >= count:
            continue
        if id_rule["fields"]:
            rules.append(id_rule)
        if counter_rule:
            rules.append(counter_rule)
        suggestion = {"title": f"First-page marker: {key[0]}",
                            "reason": f"Fixed-position marker on {len(matching_pages):,} pages; {len(id_rule['fields'])} identity field(s) available for cross-checking. Ends are inferred from the next start.",
                            "examples": matching_pages[:4], "config": asdict(DetectionConfig(rules=rules, version=2))}
        if counter_rule:
            suggestion["reason"] += " Printed counters are also checked against these boundaries."
            suggestions.insert(0, suggestion)
        else:
            suggestions.append(suggestion)
        if len(suggestions) >= 8:
            break
    if not suggestions and id_rule["fields"]:
        suggestions.append({"title": "Document identity changes", "reason": "Identity labels found. Boundaries need review without an independent first-page signal.",
                            "examples": [1], "config": asdict(DetectionConfig(rules=[id_rule], version=2))})
    return suggestions


def _box_region(boxes):
    box = fitz.Rect(min(b[0] for b in boxes)-2, min(b[1] for b in boxes)-2,
                    max(b[2] for b in boxes)+2, max(b[3] for b in boxes)+2)
    return [max(0, box.x0/MM_TO_PT), max(0, box.y0/MM_TO_PT), box.width/MM_TO_PT, box.height/MM_TO_PT]


def detect_index(index, config, *, is_cancelled=None, progress=None):
    config.validate()
    rules = {r["kind"]: r for r in config.rules}
    starts, evidence, findings = [], [], []
    previous_id = previous_number = None
    seen_ids = set()
    pages = index.metadata()["pages"]
    def warn(page, code, message):
        findings.append({"page": page, "code": code, "message": message})
    for number, lines in index.pages():
        check_cancel(is_cancelled)
        marker = marker_hit(lines, rules["first_text"]) if "first_text" in rules else False
        ident, issue = identity(lines, rules["document_id"]) if "document_id" in rules else (None, "")
        counter = page_number(lines, rules["page_number"]) if "page_number" in rules else None
        changed = ident is not None and (previous_id is None or ident != previous_id)
        hits = []
        if marker:
            hits.append("first_text")
        if changed:
            hits.append("document_id")
        if counter and counter[0] == 1:
            hits.append("page_number")
        new = bool(hits) if config.combine == "any" else len(hits) == len(rules)
        if config.combine == "all" and hits and not new:
            warn(number, "conflicting_signals", "Start signals disagree under the all-signals rule. Review this possible boundary.")
        if number == 1:
            new = True
            if not hits:
                warn(number, "unmarked_start", "First source page has no confirmed start evidence.")
        if new:
            starts.append(number)
            if counter and counter[0] != 1:
                warn(number, "start_counter_conflict", "A new-letter feature/identity occurs without a printed page sequence restarting at 1.")
            corroborated = len(hits) >= 2 or (hits == ["page_number"] and "first_text" not in rules and "document_id" not in rules)
            if not corroborated:
                warn(number, "single_signal", "Boundary supported by one signal only. Review neighbouring pages.")
            if "document_id" in rules and (ident is None or (marker and not changed and number != 1)):
                warn(number, issue or "repeated_identity", "First-page evidence and identity data do not agree; check whether this is a separate letter.")
            if ident in seen_ids:
                warn(number, "repeated_identity", "A previously seen identity combination reappears. Separate letters are retained; review duplicates/order.")
            if ident:
                seen_ids.add(ident)
            evidence.append({"page": number, "matched": hits, "end_basis": "printed_sequence" if counter else "next_start_inferred"})
        elif issue == "ambiguous_identity":
            warn(number, issue, "More than one value matches an identity field. Select its exact region.")
        if "first_text" in rules and changed and not marker and number != 1:
            warn(number, "missing_start_marker", "Identity changes without the configured first-page marker; boundary proposed for review.")
        if "page_number" in rules:
            if counter is None:
                warn(number, "missing_page_number", "No unique counter found in the configured page-number region.")
            else:
                current, total = counter
                if not 1 <= current <= total:
                    warn(number, "invalid_page_number", "Invalid printed page/total values.")
                if current == 1 and previous_number and previous_number[0] != previous_number[1]:
                    warn(number-1, "incomplete_sequence", "Previous letter ends before its declared final page.")
                elif current != 1 and (not previous_number or current != previous_number[0]+1 or total != previous_number[1]):
                    warn(number, "page_sequence", "Printed page sequence is missing, duplicated or inconsistent.")
                previous_number = counter
        if not lines:
            warn(number, "blank_page", "Blank/textless page retained. Review which letter it belongs to.")
        if ident is not None:
            previous_id = ident
        if progress and number % 100 == 0:
            progress(number, pages, f"Checking mailpiece signals {number:,} / {pages:,}")
    if previous_number and previous_number[0] != previous_number[1]:
        warn(pages, "incomplete_sequence", "Final letter ends before its declared final page.")
    established = bool(evidence and evidence[0]["matched"]) and (len(starts) > 1 or bool(previous_number and previous_number == (pages, pages)))
    groups = [[start, starts[i+1]-1 if i+1 < len(starts) else pages] for i, start in enumerate(starts)]
    if not established:
        groups = []
    else:
        EnvelopePlan(pages, EnvelopeSettings(groups=groups))
        if evidence[-1]["end_basis"] == "next_start_inferred":
            evidence[-1]["end_basis"] = "pdf_end_inferred"
    return {"config": asdict(config), "pages": pages, "groups": groups, "excluded_pages": [], "findings": findings,
            "evidence": evidence, "distribution": dict(Counter(str(min(4, b-a+1)) for a, b in groups)),
            "accepted": False, "edits": [], "established": established,
            "status": "unresolved" if not established else "needs_review" if findings else "consistent",
            "message": "Review proposed boundaries before production." if established else "Unable to establish boundaries. Teach a first-page feature or choose another signal."}


def analyze_pdf(path, cache_path, *, expected_sha256=None, progress=None, is_cancelled=None):
    source, index = index_pdf(path, cache_path, expected_sha256=expected_sha256, progress=progress, is_cancelled=is_cancelled)
    try:
        suggestions = analyze_index(index, is_cancelled=is_cancelled)
        return {"source": asdict(source), "suggestions": suggestions, "cache": str(index.path),
                "message": "Choose a suggested rule and scan cached pages." if suggestions else "Unable to establish boundaries. Teach a first-page feature."}
    finally:
        index.close()


def scan_pdf(path, config, *, cache_path=None, expected_sha256=None, progress=None, is_cancelled=None):
    import tempfile
    if cache_path is None:
        with tempfile.TemporaryDirectory(prefix="mailpiece-analysis-") as directory:
            return scan_pdf(path, config, cache_path=Path(directory)/"pages.sqlite", expected_sha256=expected_sha256,
                            progress=progress, is_cancelled=is_cancelled)
    source, index = index_pdf(path, cache_path, expected_sha256=expected_sha256, progress=progress, is_cancelled=is_cancelled)
    try:
        result = detect_index(index, config, is_cancelled=is_cancelled, progress=progress)
        result["source_sha256"] = source.sha256
        return {"source": asdict(source), "detection": result}
    finally:
        index.close()


def teach_pdf(path, cache_path, first_page, continuation_page, marker_region, id_regions=(), marker_terms=None, **kwargs):
    source, index = index_pdf(path, cache_path, **kwargs)
    try:
        if (type(first_page) is not int or type(continuation_page) is not int or first_page == continuation_page
                or not 1 <= first_page <= source.pages or not 1 <= continuation_page <= source.pages):
            raise CompositionError("Choose different first and continuation pages from this PDF.")
        _region(marker_region)
        first = json.loads(index.db.execute("SELECT lines FROM pages WHERE page=?", (first_page,)).fetchone()[0])
        continuation = json.loads(index.db.execute("SELECT lines FROM pages WHERE page=?", (continuation_page,)).fetchone()[0])
        terms = [line for line in text_in(first, marker_region).splitlines() if line.strip()]
        if not terms or len(terms) > 10 or any(len(t) > 200 for t in terms):
            raise CompositionError("Select a small static first-page feature, excluding customer values.")
        # Never persist a recipient name, address or number as the learnt marker.
        known = marker_terms or [m for m in MARKERS if any(t.casefold().startswith(m.casefold()) for t in terms)]
        if not known:
            raise CompositionError("Enter a static marker explicitly for this region; no customer text is saved automatically.")
        rule = {"kind": "first_text", "terms": known, "region_mm": marker_region}
        if not marker_hit(first, rule):
            raise CompositionError("The static marker does not match the selected first-page region.")
        if marker_hit(continuation, rule):
            raise CompositionError("That feature also appears on the continuation page. Choose a more distinctive region.")
        fields = []
        for region in id_regions:
            _region(region)
            found = identity_fields(first, region)
            if len(found) != 1:
                raise CompositionError("Each identity region must contain one labelled value.")
            fields.append({"label": found[0][0], "region_mm": region})
        config = DetectionConfig(rules=[rule] + ([{"kind": "document_id", "fields": fields}] if fields else []), version=2)
        config.validate()
        return {"source": asdict(source), "cache": str(index.path), "config": asdict(config),
                "detection": {**detect_index(index, config, is_cancelled=kwargs.get("is_cancelled")), "source_sha256": source.sha256}}
    finally:
        index.close()
