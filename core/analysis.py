"""Document inspection, preflight and deterministic smart detection.

This module deliberately has no Qt imports.  It is safe to execute through
``FunctionTask`` and returns serialisable records for the UI layer.
"""

from __future__ import annotations

import math
import re
import tempfile
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import fitz
import numpy as np

from .capabilities import CapabilityId, detect_capabilities
from .platform_service import PlatformService
from .tools import scan_barcodes


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"

    INFO = "info"


class ValidationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_CHECKED = "not_checked"
    VALIDATOR_UNAVAILABLE = "validator_unavailable"
    ERROR = "error_during_validation"


class FindingStatus(StrEnum):
    ACTIVE = "active"
    IGNORED = "ignored"
    EXPECTED = "expected"
    RESOLVED = "resolved"


class FindingSource(StrEnum):
    PREFLIGHT = "preflight"
    DETECTION = "detection"
    STANDARD = "standard"


@dataclass(frozen=True)
class TextRule:
    query: str = ""
    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False


@dataclass(frozen=True)
class AnalysisRequest:
    pages: tuple[int, ...] | None = None
    detectors: frozenset[str] = frozenset()
    preflight_profile: str | None = None
    text_rule: TextRule | None = None
    barcode_value: str = ""
    barcode_match: str = "contains"
    scan_dpi: int = 200
    near_blank_threshold: float = 0.001
    ocr_fallback: bool = False
    standard_profile: str | None = None
    verapdf_path: str | None = None
    original_encrypted: bool = False


@dataclass(frozen=True)
class Finding:
    source: str
    rule_id: str
    severity: Severity
    page: int | None
    summary: str
    details: str = ""
    value: str = ""
    bbox: tuple[float, float, float, float] | None = None
    category: str = ""
    pages: tuple[int, ...] = ()
    object_ref: str = ""
    status: FindingStatus = FindingStatus.ACTIVE
    confidence: float | None = None
    raw_data: dict[str, Any] | None = None

    def dedup_key(self) -> tuple[object, ...]:
        """Stable exact-duplicate key; page/object occurrences remain distinct."""
        return (
            str(self.source),
            self.rule_id,
            str(self.severity),
            self.page,
            self.summary,
            self.details,
            self.value,
            self.bbox,
            self.pages,
            self.object_ref,
        )

    def all_pages(self) -> tuple[int, ...]:
        values = set(self.pages)
        if self.page is not None:
            values.add(self.page)
        return tuple(sorted(values))


@dataclass(frozen=True)
class ValidationSummary:
    standard: str
    profile: str
    compliant: bool | None
    failed_rule_count: int = 0
    passed_rule_count: int = 0
    failed_check_count: int = 0
    validator: str = "veraPDF"
    validator_version: str = ""
    message: str = ""
    status: ValidationStatus = ValidationStatus.NOT_CHECKED


@dataclass(frozen=True)
class FindingGroup:
    group_id: str
    category: str
    source: str
    rule_id: str
    severity: Severity
    summary: str
    details: str
    findings: tuple[Finding, ...]
    pages: tuple[int, ...] = ()
    status: FindingStatus = FindingStatus.ACTIVE
    object_ref: str = ""

    @property
    def count(self) -> int:
        return len(self.findings)


@dataclass
class FindingSet:
    document_id: str
    revision: int
    request: AnalysisRequest
    findings: list[Finding] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def normalize(self) -> FindingSet:
        """Remove parser noise and exact duplicates without merging occurrences."""
        has_rules = any(
            item.source == FindingSource.STANDARD
            and item.rule_id not in {"verapdf.check", "verapdf.non_compliant"}
            for item in self.findings
        )
        seen: set[tuple[object, ...]] = set()
        normalized: list[Finding] = []
        for item in self.findings:
            if has_rules and item.rule_id in {"verapdf.check", "verapdf.non_compliant"}:
                continue
            key = item.dedup_key()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        self.findings = normalized
        return self

    def classify_blank_pages(
        self,
        total_pages: int,
        page_records: list[dict[str, Any]] | None = None,
    ) -> FindingSet:
        blank_rules = {"page.blank", "detect.exact_blank"}
        blank_pages = sorted(
            {
                page
                for item in self.findings
                if item.rule_id in blank_rules
                for page in item.all_pages()
            }
        )
        if len(blank_pages) < 2:
            return self
        one_based = [page + 1 for page in blank_pages]
        parity = {page % 2 for page in one_based}
        if len(parity) != 1:
            return self

        side = "even" if next(iter(parity)) == 0 else "odd"
        frequency = len(blank_pages) / max(1, total_pages)
        gaps = [
            right - left
            for left, right in zip(blank_pages, blank_pages[1:], strict=False)
        ]
        if gaps and len(set(gaps)) == 1:
            spacing = f"regular spacing every {gaps[0]} pages"
        else:
            spacing = "variable spacing"
        neighbour_note = ""
        if page_records:
            blank_by_page = {
                int(record["page"]): bool(record.get("exact_blank"))
                for record in page_records
            }
            preceded = sum(
                page > 0 and not blank_by_page.get(page - 1, True)
                for page in blank_pages
            )
            followed = sum(
                page + 1 < total_pages and not blank_by_page.get(page + 1, True)
                for page in blank_pages
            )
            neighbour_note = (
                f" Neighbouring content: {preceded} preceded and {followed} "
                "followed by a non-blank page."
            )
        position_note = (
            " Includes the final page." if total_pages - 1 in blank_pages else ""
        )
        pattern = (
            f"All {len(blank_pages)} detected blank pages are {side}-numbered "
            f"({frequency:.1%} of the document), with {spacing}.{neighbour_note}"
            f"{position_note} Likely intentional duplex padding / reverse-side pages."
        )
        self.findings = [
            (
                replace(
                    item,
                    severity=Severity.INFO,
                    category=item.category or "Blank Page",
                    details=" | ".join(
                        value for value in (item.details, pattern) if value
                    ),
                )
                if item.rule_id in blank_rules
                else item
            )
            for item in self.findings
        ]
        return self

    def groups(self) -> tuple[FindingGroup, ...]:
        """Return UI groups while preserving every underlying detailed finding."""
        self.normalize()
        blank_rules = {"page.blank", "detect.exact_blank"}
        blanks = tuple(item for item in self.findings if item.rule_id in blank_rules)
        groups: list[FindingGroup] = []
        if blanks:
            pages = tuple(
                sorted({page for item in blanks for page in item.all_pages()})
            )
            details = next((item.details for item in blanks if item.details), "")
            severity = max(
                (item.severity for item in blanks),
                key=lambda value: {
                    Severity.INFO: 0,
                    Severity.WARNING: 1,
                    Severity.ERROR: 2,
                }[value],
            )
            statuses = {item.status for item in blanks}
            status = statuses.pop() if len(statuses) == 1 else FindingStatus.ACTIVE
            groups.append(
                FindingGroup(
                    "blank-pages",
                    "Blank Page",
                    "preflight / detection",
                    "page.blank",
                    severity,
                    f"{len(pages)} blank page{'s' if len(pages) != 1 else ''} detected",
                    details,
                    blanks,
                    pages,
                    status,
                )
            )

        buckets: dict[tuple[str, str, str, FindingStatus], list[Finding]] = {}
        for item in self.findings:
            if item.rule_id in blank_rules:
                continue
            category = item.category or _category_for_finding(item)
            key = (
                category,
                str(item.source),
                item.rule_id,
                item.status,
            )
            buckets.setdefault(key, []).append(item)

        for index, (key, members) in enumerate(buckets.items()):
            category, source, rule_id, status = key
            member_tuple = tuple(members)
            severity = max(
                (item.severity for item in member_tuple),
                key=lambda value: {
                    Severity.INFO: 0,
                    Severity.WARNING: 1,
                    Severity.ERROR: 2,
                }[value],
            )
            summary = member_tuple[0].summary
            pages = tuple(
                sorted({page for item in member_tuple for page in item.all_pages()})
            )
            details = list(
                dict.fromkeys(item.details for item in member_tuple if item.details)
            )
            if len(details) <= 1:
                grouped_details = details[0] if details else ""
            else:
                preview = " | ".join(details[:3])
                remaining = len(details) - 3
                grouped_details = (
                    f"{preview} | +{remaining} more detail variant(s)"
                    if remaining > 0
                    else preview
                )
            if rule_id == "image.rgb":
                summary = "RGB images detected"
                grouped_details = (
                    "RGB / Indexed RGB images are present in the document."
                )
            elif rule_id == "image.low_dpi":
                dpi_values = [
                    float(data["effective_dpi"])
                    for item in member_tuple
                    if (data := item.raw_data)
                    and isinstance(data.get("effective_dpi"), (int, float))
                ]
                thresholds = [
                    float(data["threshold"])
                    for item in member_tuple
                    if (data := item.raw_data)
                    and isinstance(data.get("threshold"), (int, float))
                ]
                xrefs = {
                    int(data["xref"])
                    for item in member_tuple
                    if (data := item.raw_data)
                    and isinstance(data.get("xref"), int)
                    and int(data["xref"]) > 0
                }
                parts = [
                    f"{len(member_tuple)} objects across {len(pages)} "
                    f"page{'s' if len(pages) != 1 else ''}"
                ]
                if dpi_values:
                    parts.extend(
                        (
                            f"Minimum: {_display_number(min(dpi_values))} DPI",
                            "Maximum below threshold: "
                            f"{_display_number(max(dpi_values))} DPI",
                        )
                    )
                if thresholds:
                    parts.append(
                        f"Threshold: {_display_number(max(thresholds))} DPI"
                    )
                if xrefs:
                    parts.append(f"Unique images: {len(xrefs)}")
                grouped_details = " · ".join(parts)
            object_refs = list(
                dict.fromkeys(
                    item.object_ref for item in member_tuple if item.object_ref
                )
            )
            groups.append(
                FindingGroup(
                    f"{rule_id}:{index}",
                    category,
                    source,
                    rule_id,
                    severity,
                    summary,
                    grouped_details,
                    member_tuple,
                    pages,
                    status,
                    ", ".join(object_refs[:10]),
                )
            )
        return tuple(groups)

    def set_status(self, findings: tuple[Finding, ...], status: FindingStatus) -> None:
        identities = {id(item) for item in findings}
        self.findings = [
            replace(item, status=status) if id(item) in identities else item
            for item in self.findings
        ]

    def pages(
        self,
        *,
        source: str | None = None,
        rule_id: str | None = None,
        severity: Severity | None = None,
    ) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    page
                    for item in self.findings
                    if (source is None or item.source == source)
                    and (rule_id is None or item.rule_id == rule_id)
                    and (severity is None or item.severity == severity)
                    for page in item.all_pages()
                }
            )
        )

    def is_stale(self, document_id: str, revision: int) -> bool:
        return self.document_id != document_id or self.revision != revision


@dataclass
class InspectionReport:
    overview: dict[str, Any]
    pages: list[dict[str, Any]]
    fonts: list[dict[str, Any]]
    images: list[dict[str, Any]]
    colors: dict[str, int]
    finding_set: FindingSet
    standard_profile: str = ""
    standard_status: str = "Not run"
    validation_summary: ValidationSummary | None = None
    standard_raw_xml: str = ""


def _category_for_finding(item: Finding) -> str:
    rule = item.rule_id.casefold()
    if "blank" in rule:
        return "Blank Page"
    if "font" in rule:
        return "Fonts"
    if "color" in rule or "rgb" in rule or "cmyk" in rule:
        return "Color"
    if "image" in rule:
        return "Images"
    if "annotation" in rule:
        return "Annotation"
    if "security" in rule or "encrypt" in rule:
        return "Security"
    if rule.startswith("page."):
        return "Pages"
    if item.source == FindingSource.STANDARD:
        return "PDF/A Compliance"
    return "Document"


PREFLIGHT_PROFILES: dict[str, dict[str, Any]] = {
    "general": {
        "label": "General Office",
        "dpi_error": 72.0,
        "dpi_warning": 96.0,
        "rgb_severity": Severity.INFO,
        "font_severity": Severity.WARNING,
        "production_boxes": False,
    },
    "digital": {
        "label": "Digital Print",
        "dpi_error": 150.0,
        "dpi_warning": 200.0,
        "rgb_severity": Severity.INFO,
        "font_severity": Severity.WARNING,
        "production_boxes": False,
    },
    "production": {
        "label": "Production Print",
        "dpi_error": 200.0,
        "dpi_warning": 300.0,
        "rgb_severity": Severity.WARNING,
        "font_severity": Severity.ERROR,
        "production_boxes": True,
    },
}


def _progress(callback, current: int, total: int, message: str) -> None:
    if callback:
        callback(current, total, message)


def _cancelled(callback) -> bool:
    return bool(callback and callback())


def _box_tuple(value: fitz.Rect) -> tuple[float, float, float, float]:
    return tuple(round(float(part), 3) for part in value)  # type: ignore[return-value]


def _display_number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _rect_mm(value: fitz.Rect) -> tuple[float, float]:
    return round(value.width * 25.4 / 72, 2), round(value.height * 25.4 / 72, 2)


def _page_size_name(width_mm: float, height_mm: float) -> str:
    short, long = sorted((width_mm, height_mm))
    for name, expected in (
        ("A5", (148.0, 210.0)),
        ("A4", (210.0, 297.0)),
        ("A3", (297.0, 420.0)),
        ("Letter", (215.9, 279.4)),
    ):
        if abs(short - expected[0]) <= 1.5 and abs(long - expected[1]) <= 1.5:
            return name
    return "Custom"


def _iter_annots(page: fitz.Page) -> list[Any]:
    try:
        return list(page.annots() or [])
    except Exception:
        return []


def _iter_widgets(page: fitz.Page) -> list[Any]:
    try:
        return list(page.widgets() or [])
    except Exception:
        return []


def _page_components(page: fitz.Page) -> dict[str, Any]:
    text = page.get_text("text")
    try:
        images = list(page.get_image_info(xrefs=True))
    except Exception:
        images = []
    try:
        drawings = list(page.get_drawings())
    except Exception:
        drawings = []
    annots = _iter_annots(page)
    widgets = _iter_widgets(page)
    return {
        "text": text,
        "images": images,
        "drawings": drawings,
        "annots": annots,
        "widgets": widgets,
    }


def _is_exact_blank(components: dict[str, Any]) -> bool:
    return not (
        str(components["text"]).strip()
        or components["images"]
        or components["drawings"]
        or components["annots"]
        or components["widgets"]
    )


def _ink_coverage(page: fitz.Page, dpi: int = 72) -> float:
    pixmap = page.get_pixmap(
        dpi=max(36, min(150, dpi)),
        colorspace=fitz.csGRAY,
        alpha=False,
        annots=True,
    )
    pixels = np.frombuffer(pixmap.samples, dtype=np.uint8)
    if not pixels.size:
        return 0.0
    pixels = pixels.reshape(pixmap.height, pixmap.width)
    if pixmap.width > 4 and pixmap.height > 4:
        pixels = pixels[2:-2, 2:-2]
    return float(np.count_nonzero(pixels < 245) / max(1, pixels.size))


def _text_matches(text: str, rule: TextRule) -> bool:
    if not rule.query:
        return False
    flags = 0 if rule.case_sensitive else re.IGNORECASE
    if rule.regex:
        try:
            return re.search(rule.query, text, flags) is not None
        except re.error:
            return False
    needle = re.escape(rule.query)
    if rule.whole_word:
        needle = rf"(?<!\w){needle}(?!\w)"
    return re.search(needle, text, flags) is not None


def _ocr_page_text(page: fitz.Page, dpi: int, is_cancelled=None) -> str:
    capability = detect_capabilities()[CapabilityId.OCR]
    if not capability.available or not capability.path:
        return ""
    executable = Path(capability.path)
    tessdata = executable.parent / "tessdata"
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-detect-ocr-") as folder:
        image = Path(folder) / "page.png"
        page.get_pixmap(dpi=max(150, min(400, dpi)), alpha=False).save(image)
        command = [
            str(executable),
            str(image),
            "stdout",
            "-l",
            "eng+chi_tra",
            "--tessdata-dir",
            str(tessdata),
        ]
        result = PlatformService.run_cancellable(
            command, is_cancelled=is_cancelled, timeout=180
        )
        return result.stdout if result.returncode == 0 else ""


def _font_embedded(document: fitz.Document, xref: int, extension: str) -> bool:
    if xref <= 0:
        return False
    try:
        info = document.extract_font(xref, info_only=True)
        if isinstance(info, dict):
            return str(info.get("ext", "")).casefold() not in {"", "n/a"}
        if isinstance(info, tuple) and len(info) > 1:
            return str(info[1]).casefold() not in {"", "n/a"}
    except Exception:
        pass
    return extension.casefold() not in {"", "n/a"}


def _rendered_image_size(info: dict[str, Any]) -> tuple[float, float]:
    try:
        transform = info.get("transform")
        if isinstance(transform, (tuple, list)) and len(transform) >= 4:
            a, b, c, d = (float(transform[index]) for index in range(4))
            return math.hypot(a, b), math.hypot(c, d)
        bbox = fitz.Rect(info.get("bbox"))
        return abs(float(bbox.width)), abs(float(bbox.height))
    except (TypeError, ValueError, AttributeError):
        return 0.0, 0.0


def _effective_dpi(info: dict[str, Any]) -> tuple[float, float]:
    """Return placement DPI using the actual image transform vectors.

    get_image_info supplies a matrix that maps the image unit square to the
    painted page parallelogram. Axis-aligned bounding-box dimensions are not
    equivalent when an image is rotated or skewed, so they are only a fallback
    for older PyMuPDF records without a transform.
    """

    try:
        pixel_width = float(info.get("width", 0))
        pixel_height = float(info.get("height", 0))
        if not all(
            math.isfinite(value) and value > 0
            for value in (pixel_width, pixel_height)
        ):
            return 0.0, 0.0

        rendered_width, rendered_height = _rendered_image_size(info)
        if not all(
            math.isfinite(value) and value > 1e-6
            for value in (rendered_width, rendered_height)
        ):
            return 0.0, 0.0
        xdpi = pixel_width * 72.0 / rendered_width
        ydpi = pixel_height * 72.0 / rendered_height
        if not all(math.isfinite(value) and value > 0 for value in (xdpi, ydpi)):
            return 0.0, 0.0
        return round(xdpi, 1), round(ydpi, 1)
    except (TypeError, ValueError, AttributeError):
        return 0.0, 0.0


def _image_classification(document: fitz.Document, info: dict[str, Any]) -> str:
    """Classify image paint operations without treating masks as artwork."""

    xref = int(info.get("xref", 0) or 0)
    if xref > 0:
        try:
            kind, value = document.xref_get_key(xref, "ImageMask")
            if kind == "bool" and str(value).casefold() == "true":
                return "stencil mask"
        except Exception:
            return "unknown raster object"
    elif (
        int(info.get("bpc", 0) or 0) == 1
        and int(info.get("colorspace", 0) or 0) <= 0
    ):
        return "image mask"
    if _effective_dpi(info) == (0.0, 0.0):
        return "unknown raster object"
    return "visible raster image"


def _image_compression(document: fitz.Document, xref: int) -> str:
    if xref <= 0:
        return "Inline/Unknown"
    try:
        kind, value = document.xref_get_key(xref, "Filter")
    except Exception:
        return "Unknown"
    if kind == "null" or not value:
        return "Unfiltered"
    names = re.findall(r"/[A-Za-z0-9]+", str(value))
    return ", ".join(name[1:] for name in names) or str(value)


def _document_feature_flags(document: fitz.Document) -> dict[str, bool]:
    javascript = launch = False
    # Catalog-level actions are normally small.  A bounded object scan also
    # catches name-tree JavaScript without turning malformed huge PDFs into a
    # multi-minute preflight step.
    for xref in range(1, min(document.xref_length(), 50_000)):
        try:
            raw = document.xref_object(xref, compressed=True)
        except Exception:
            continue
        javascript = javascript or "/JavaScript" in raw or "/JS" in raw
        launch = launch or "/Launch" in raw
        if javascript and launch:
            break
    try:
        attachments = document.embfile_count() > 0
    except Exception:
        attachments = False
    return {"javascript": javascript, "launch": launch, "attachments": attachments}


def _claimed_standard(document: fitz.Document) -> str:
    try:
        xmp = document.get_xml_metadata() or ""
    except Exception:
        return ""
    part = re.search(r"pdfaid:part[^>]*>\s*([1-4])\s*<", xmp, re.IGNORECASE)
    conformance = re.search(
        r"pdfaid:conformance[^>]*>\s*([A-Z])\s*<", xmp, re.IGNORECASE
    )
    if part:
        suffix = conformance.group(1).lower() if conformance else ""
        return f"PDF/A-{part.group(1)}{suffix}"
    ua = re.search(r"pdfuaid:part[^>]*>\s*([12])\s*<", xmp, re.IGNORECASE)
    return f"PDF/UA-{ua.group(1)}" if ua else ""


def _has_linearization_header(source: Path) -> bool:
    try:
        with source.open("rb") as handle:
            return b"/Linearized" in handle.read(2048)
    except OSError:
        return False


def _profile_for(request: AnalysisRequest) -> dict[str, Any] | None:
    if not request.preflight_profile:
        return None
    return PREFLIGHT_PROFILES.get(
        request.preflight_profile, PREFLIGHT_PROFILES["general"]
    )


def inspect_and_analyze(
    source_path: str | Path,
    document_id: str,
    revision: int,
    request: AnalysisRequest,
    *,
    progress=None,
    is_cancelled=None,
) -> InspectionReport:
    """Inspect a PDF and return both inventory records and actionable findings."""

    source = Path(source_path).expanduser().resolve()
    finding_set = FindingSet(
        document_id=document_id, revision=revision, request=request
    )
    profile = _profile_for(request)
    page_records: list[dict[str, Any]] = []
    image_records: list[dict[str, Any]] = []
    font_usage: dict[tuple[int, str, str, str, bool, bool], set[int]] = {}
    colors: dict[str, int] = {}

    with fitz.open(source) as document:
        metadata = dict(document.metadata or {})
        selected = (
            [page for page in request.pages if 0 <= page < document.page_count]
            if request.pages is not None
            else list(range(document.page_count))
        )
        feature_flags = _document_feature_flags(document)
        overview: dict[str, Any] = {
            "file": str(source),
            "file_size": source.stat().st_size if source.exists() else 0,
            "pages": document.page_count,
            "pdf_format": metadata.get("format") or "PDF",
            "encrypted": bool(request.original_encrypted or document.needs_pass),
            "title": metadata.get("title") or "",
            "author": metadata.get("author") or "",
            "subject": metadata.get("subject") or "",
            "creator": metadata.get("creator") or "",
            "producer": metadata.get("producer") or "",
            "created": metadata.get("creationDate") or "",
            "modified": metadata.get("modDate") or "",
            "tagged": bool(getattr(document, "markinfo", {}).get("Marked", False)),
            "forms": bool(document.is_form_pdf),
            "attachments": feature_flags["attachments"],
            "javascript": feature_flags["javascript"],
            "launch_actions": feature_flags["launch"],
            "claimed_standard": _claimed_standard(document) or "Not declared",
            "linearized": _has_linearization_header(source),
        }

        if profile:
            for flag, rule, summary in (
                (overview["encrypted"], "document.encrypted", "Document is encrypted"),
                (
                    feature_flags["javascript"],
                    "document.javascript",
                    "JavaScript action detected",
                ),
                (feature_flags["launch"], "document.launch", "Launch action detected"),
                (
                    feature_flags["attachments"],
                    "document.attachments",
                    "Embedded files detected",
                ),
            ):
                if flag:
                    finding_set.findings.append(
                        Finding(
                            FindingSource.PREFLIGHT,
                            rule,
                            Severity.WARNING,
                            None,
                            summary,
                        )
                    )

        total = len(selected)
        for position, page_number in enumerate(selected):
            if _cancelled(is_cancelled):
                break
            _progress(progress, position, total, f"Inspecting page {page_number + 1}")
            page = document.load_page(page_number)
            components = _page_components(page)
            media = fitz.Rect(page.mediabox)
            crop = fitz.Rect(page.cropbox)
            bleed = fitz.Rect(page.bleedbox)
            trim = fitz.Rect(page.trimbox)
            art = fitz.Rect(page.artbox)
            width_mm, height_mm = _rect_mm(page.rect)
            exact_blank = _is_exact_blank(components)
            record = {
                "page": page_number,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "size_name": _page_size_name(width_mm, height_mm),
                "dimensions": f"{width_mm}×{height_mm}",
                "orientation": "Landscape" if width_mm > height_mm else "Portrait",
                "rotation": int(page.rotation),
                "media_box": _box_tuple(media),
                "crop_box": _box_tuple(crop),
                "bleed_box": _box_tuple(bleed),
                "trim_box": _box_tuple(trim),
                "art_box": _box_tuple(art),
                "text_characters": len(str(components["text"])),
                "images": len(components["images"]),
                "vectors": len(components["drawings"]),
                "annotations": len(components["annots"]),
                "form_fields": len(components["widgets"]),
                "exact_blank": exact_blank,
            }
            page_records.append(record)

            if profile and exact_blank:
                finding_set.findings.append(
                    Finding(
                        FindingSource.PREFLIGHT,
                        "page.blank",
                        Severity.WARNING,
                        page_number,
                        "Blank page detected",
                    )
                )
            if "exact_blank" in request.detectors and exact_blank:
                finding_set.findings.append(
                    Finding(
                        FindingSource.DETECTION,
                        "detect.exact_blank",
                        Severity.INFO,
                        page_number,
                        "Exact blank page",
                    )
                )
            if "near_blank" in request.detectors:
                coverage = _ink_coverage(page)
                record["ink_coverage"] = coverage
                if coverage < max(0.0, min(1.0, request.near_blank_threshold)):
                    finding_set.findings.append(
                        Finding(
                            FindingSource.DETECTION,
                            "detect.near_blank",
                            Severity.INFO,
                            page_number,
                            "Near blank page",
                            f"Ink coverage {coverage:.3%}",
                            f"{coverage:.6f}",
                        )
                    )

            text = str(components["text"])
            if "text" in request.detectors and text.strip():
                finding_set.findings.append(
                    Finding(
                        FindingSource.DETECTION,
                        "detect.text",
                        Severity.INFO,
                        page_number,
                        "Text layer detected",
                        f"{len(text)} characters",
                        str(len(text)),
                    )
                )
            if "specific_text" in request.detectors and request.text_rule:
                searchable = text
                if not searchable.strip() and request.ocr_fallback:
                    searchable = _ocr_page_text(page, request.scan_dpi, is_cancelled)
                if _text_matches(searchable, request.text_rule):
                    finding_set.findings.append(
                        Finding(
                            FindingSource.DETECTION,
                            "detect.specific_text",
                            Severity.INFO,
                            page_number,
                            "Specific text matched",
                            request.text_rule.query,
                            request.text_rule.query,
                        )
                    )
            for detector, items, rule, label in (
                (
                    "vector",
                    components["drawings"],
                    "detect.vector",
                    "Vector graphics detected",
                ),
                (
                    "annotation",
                    components["annots"],
                    "detect.annotation",
                    "Annotations detected",
                ),
                ("form", components["widgets"], "detect.form", "Form fields detected"),
            ):
                if detector in request.detectors and items:
                    finding_set.findings.append(
                        Finding(
                            FindingSource.DETECTION,
                            rule,
                            Severity.INFO,
                            page_number,
                            label,
                            f"{len(items)} occurrence(s)",
                            str(len(items)),
                        )
                    )

            for image in components["images"]:
                xdpi, ydpi = _effective_dpi(image)
                classification = _image_classification(document, image)
                colorspace = str(
                    image.get("cs-name") or image.get("colorspace") or "Unknown"
                )
                colors[colorspace] = colors.get(colorspace, 0) + 1
                try:
                    bbox = fitz.Rect(image.get("bbox"))
                    visible_on_page = not (bbox & page.rect).is_empty
                except (TypeError, ValueError):
                    bbox = fitz.Rect()
                    visible_on_page = False
                rendered_width, rendered_height = _rendered_image_size(image)
                image_record = {
                    "page": page_number,
                    "number": int(image.get("number", 0) or 0),
                    "xref": int(image.get("xref", 0) or 0),
                    "width": int(image.get("width", 0) or 0),
                    "height": int(image.get("height", 0) or 0),
                    "pixels": f"{int(image.get('width', 0) or 0)}×{int(image.get('height', 0) or 0)}",
                    "compression": _image_compression(
                        document, int(image.get("xref", 0) or 0)
                    ),
                    "bpc": int(image.get("bpc", 0) or 0),
                    "colorspace": colorspace,
                    "xdpi": xdpi,
                    "ydpi": ydpi,
                    "dpi": f"{xdpi:.1f}×{ydpi:.1f}",
                    "bbox": _box_tuple(bbox),
                    "rendered_width": round(rendered_width, 3),
                    "rendered_height": round(rendered_height, 3),
                    "classification": classification,
                    "has_mask": bool(
                        image.get("has-mask", False) or image.get("smask", 0)
                    ),
                }
                image_records.append(image_record)
                if "image" in request.detectors:
                    finding_set.findings.append(
                        Finding(
                            FindingSource.DETECTION,
                            "detect.image",
                            Severity.INFO,
                            page_number,
                            "Raster image detected",
                            f"{image_record['width']}×{image_record['height']} px | "
                            f"{min(xdpi, ydpi):.1f} DPI | {classification}",
                            str(image_record["xref"]),
                            image_record["bbox"],
                        )
                    )
                if profile:
                    effective = min(xdpi, ydpi)
                    is_printable_image = (
                        classification == "visible raster image"
                        and visible_on_page
                        and effective > 0
                    )
                    if is_printable_image and effective < float(profile["dpi_error"]):
                        severity = Severity.ERROR
                    elif is_printable_image and effective < float(profile["dpi_warning"]):
                        severity = Severity.WARNING
                    else:
                        severity = None
                    if severity:
                        finding_set.findings.append(
                            Finding(
                                FindingSource.PREFLIGHT,
                                "image.low_dpi",
                                severity,
                                page_number,
                                "Low effective image resolution",
                                f"{effective:.1f} DPI | {xdpi:.1f}×{ydpi:.1f} DPI | "
                                f"{image_record['width']}×{image_record['height']} px | "
                                f"{rendered_width:.1f}×{rendered_height:.1f} pt | "
                                f"{colorspace}",
                                f"{effective:.1f}",
                                image_record["bbox"],
                                object_ref=(
                                    f"{image_record['xref']} 0 obj / image operation "
                                    f"{image_record['number'] + 1}"
                                    if image_record["xref"] > 0
                                    else f"inline image {image_record['number'] + 1}"
                                ),
                                category="Images",
                                raw_data={
                                    "effective_dpi": effective,
                                    "effective_dpi_x": xdpi,
                                    "effective_dpi_y": ydpi,
                                    "width_px": image_record["width"],
                                    "height_px": image_record["height"],
                                    "rendered_width_pt": rendered_width,
                                    "rendered_height_pt": rendered_height,
                                    "colorspace": colorspace,
                                    "classification": classification,
                                    "xref": image_record["xref"],
                                    "occurrence": image_record["number"],
                                    "threshold": float(profile["dpi_warning"]),
                                },
                            )
                        )
                    if is_printable_image and "RGB" in colorspace.upper():
                        finding_set.findings.append(
                            Finding(
                                FindingSource.PREFLIGHT,
                                "image.rgb",
                                profile["rgb_severity"],
                                page_number,
                                "RGB image detected",
                                colorspace,
                                str(image_record["xref"]),
                                image_record["bbox"],
                                category="Color",
                                object_ref=(
                                    f"{image_record['xref']} 0 obj / image operation "
                                    f"{image_record['number'] + 1}"
                                    if image_record["xref"] > 0
                                    else f"inline image {image_record['number'] + 1}"
                                ),
                                raw_data={
                                    "colorspace": colorspace,
                                    "classification": classification,
                                    "xref": image_record["xref"],
                                    "occurrence": image_record["number"],
                                },
                            )
                        )

            try:
                fonts = document.get_page_fonts(page_number, full=True)
            except Exception:
                fonts = []
            for font in fonts:
                xref = int(font[0] or 0)
                extension = str(font[1] or "")
                type_ = str(font[2] or "Unknown")
                basefont = str(font[3] or font[4] or "Unknown")
                encoding = str(font[5] or "")
                embedded = _font_embedded(document, xref, extension)
                subset = bool(re.match(r"^[A-Z]{6}\+", basefont))
                key = (xref, basefont, type_, encoding, embedded, subset)
                font_usage.setdefault(key, set()).add(page_number)
                if profile and not embedded:
                    finding_set.findings.append(
                        Finding(
                            FindingSource.PREFLIGHT,
                            "font.not_embedded",
                            profile["font_severity"],
                            page_number,
                            "Font is not embedded",
                            f"{basefont} | {type_}",
                            basefont,
                        )
                    )
                if profile and type_.casefold() == "type3":
                    finding_set.findings.append(
                        Finding(
                            FindingSource.PREFLIGHT,
                            "font.type3",
                            Severity.WARNING,
                            page_number,
                            "Type 3 font detected",
                            basefont,
                            basefont,
                        )
                    )

            if profile:
                try:
                    blocks = page.get_text("dict").get("blocks", [])
                    minimum = min(
                        float(span.get("size", 999))
                        for block in blocks
                        for line in block.get("lines", [])
                        for span in line.get("spans", [])
                        if str(span.get("text", "")).strip()
                    )
                except (ValueError, TypeError):
                    minimum = 999.0
                if minimum < 6.0:
                    finding_set.findings.append(
                        Finding(
                            FindingSource.PREFLIGHT,
                            "font.small_text",
                            Severity.WARNING,
                            page_number,
                            "Very small text detected",
                            f"Minimum {minimum:.1f} pt",
                            f"{minimum:.1f}",
                        )
                    )
                if not media.contains(crop) or not crop.contains(trim):
                    finding_set.findings.append(
                        Finding(
                            FindingSource.PREFLIGHT,
                            "page.box_relationship",
                            Severity.ERROR,
                            page_number,
                            "Abnormal page box relationship",
                            "Expected MediaBox ⊇ CropBox ⊇ TrimBox",
                        )
                    )
                if profile["production_boxes"]:
                    for key_name, rule_id, label in (
                        (
                            "TrimBox",
                            "page.missing_trimbox",
                            "TrimBox is not explicitly defined",
                        ),
                        (
                            "BleedBox",
                            "page.missing_bleedbox",
                            "BleedBox is not explicitly defined",
                        ),
                    ):
                        try:
                            kind, _value = document.xref_get_key(page.xref, key_name)
                        except Exception:
                            kind = "null"
                        if kind == "null":
                            finding_set.findings.append(
                                Finding(
                                    FindingSource.PREFLIGHT,
                                    rule_id,
                                    Severity.WARNING,
                                    page_number,
                                    label,
                                )
                            )
            _progress(
                progress, position + 1, total, f"Inspected page {page_number + 1}"
            )

        if profile and page_records:
            sizes = {(row["width_mm"], row["height_mm"]) for row in page_records}
            rotations = {row["rotation"] for row in page_records}
            if len(sizes) > 1:
                finding_set.findings.append(
                    Finding(
                        FindingSource.PREFLIGHT,
                        "document.mixed_page_sizes",
                        Severity.WARNING,
                        None,
                        "Mixed page sizes detected",
                        f"{len(sizes)} distinct sizes",
                    )
                )
            if len(rotations) > 1:
                finding_set.findings.append(
                    Finding(
                        FindingSource.PREFLIGHT,
                        "document.mixed_rotations",
                        Severity.INFO,
                        None,
                        "Mixed page rotations detected",
                        ", ".join(f"{value}°" for value in sorted(rotations)),
                    )
                )

    # Reuse the existing, packaged barcode implementation after the structural
    # pass.  It owns its own fitz.Document and is therefore thread-safe here.
    if {"barcode", "qr"} & set(request.detectors) and not _cancelled(is_cancelled):
        allowed = None
        if "qr" in request.detectors and "barcode" not in request.detectors:
            allowed = ["QRCODE"]
        barcode_results = scan_barcodes(
            source,
            request.pages,
            request.scan_dpi,
            is_cancelled,
            allowed,
            progress,
        )
        for item in barcode_results:
            type_ = str(item.get("type", "Unknown"))
            value = str(item.get("data", ""))
            if request.barcode_value:
                exact = request.barcode_match == "exact"
                if (exact and value != request.barcode_value) or (
                    not exact and request.barcode_value not in value
                ):
                    continue
            bbox_value = item.get("bbox")
            bbox = tuple(float(value) for value in bbox_value) if bbox_value else None
            finding_set.findings.append(
                Finding(
                    FindingSource.DETECTION,
                    "detect.qr" if "QR" in type_.upper() else "detect.barcode",
                    Severity.INFO,
                    int(item.get("page", 1)) - 1,
                    "QR code detected" if "QR" in type_.upper() else "Barcode detected",
                    type_,
                    value,
                    bbox,  # type: ignore[arg-type]
                )
            )

    font_records = [
        {
            "xref": xref,
            "name": name,
            "type": type_,
            "encoding": encoding,
            "embedded": embedded,
            "subset": subset,
            "pages": tuple(sorted(pages)),
        }
        for (xref, name, type_, encoding, embedded, subset), pages in sorted(
            font_usage.items(), key=lambda item: (item[0][1].casefold(), item[0][0])
        )
    ]
    finding_set.classify_blank_pages(
        int(overview.get("pages", len(page_records))),
        page_records,
    )
    finding_set.normalize()
    finding_set.finished_at = time.time()
    return InspectionReport(
        overview=overview,
        pages=page_records,
        fonts=font_records,
        images=image_records,
        colors=dict(sorted(colors.items())),
        finding_set=finding_set,
    )


__all__ = [
    "AnalysisRequest",
    "Finding",
    "FindingGroup",
    "FindingSet",
    "FindingSource",
    "FindingStatus",
    "InspectionReport",
    "PREFLIGHT_PROFILES",
    "Severity",
    "TextRule",
    "ValidationStatus",
    "ValidationSummary",
    "inspect_and_analyze",
]
