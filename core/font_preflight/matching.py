"""Conservative exact-face eligibility; never use fuzzy system-font matching."""

from pathlib import Path

from fontTools.ttLib import TTFont

from core.pdf_operations.analysis import check_cancel, file_hash, open_pdf

from .inventory import dereference, object_value
from .model import FontPreflightError, FontSource, MatchDecision


def font_source(path, *, authorized=False):
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size > 64 * 1024 * 1024:
        raise FontPreflightError("Font source is missing or exceeds 64 MB.")
    with TTFont(source, lazy=False) as font:
        if "glyf" not in font or any(
            key in font for key in ("fvar", "CFF ", "CFF2", "COLR", "CBDT", "sbix", "SVG ")
        ):
            raise FontPreflightError("Safe embedding currently supports static TrueType outline files only.")
        names = font["name"]
        postscript = names.getDebugName(6) or ""
        if not postscript:
            raise FontPreflightError("The font has no PostScript identity.")
        return FontSource(
            str(source),
            file_hash(source),
            postscript,
            names.getDebugName(5) or "Unknown",
            int(getattr(font.get("OS/2"), "fsType", 0)),
            bool(authorized),
        )


def evaluate_sources(source, inventory, selections, *, password="", is_cancelled=None):
    """Selections explicitly map font xref to {path, authorized}; no automatic guessing."""
    decisions = []
    with open_pdf(source, password) as doc:
        for item in inventory.resources:
            check_cancel(is_cancelled)
            selected = selections.get(str(item.xref), selections.get(item.xref))
            if item.status in {"EMBEDDED", "BASE14_POLICY_EXEMPT"}:
                continue
            status, reason, candidate = (
                "BLOCKED_MISSING_FONT",
                "Choose the authorized original font file.",
                None,
            )
            if inventory.protected:
                status, reason = "BLOCKED_PROTECTED", "Signed/encrypted/restricted PDFs are scan-only."
            elif not inventory.complete:
                status, reason = "REVIEW_REQUIRED", "Analysis is incomplete; native repair is blocked."
            elif item.subtype != "TrueType" or item.encoding != "WinAnsiEncoding" or not item.descriptor:
                status, reason = (
                    "UNSUPPORTED",
                    "Only simple TrueType with WinAnsi and an indirect FontDescriptor is supported.",
                )
            elif selected:
                try:
                    candidate = font_source(selected["path"], authorized=selected.get("authorized") is True)
                    if not candidate.authorized or candidate.fs_type & (0x0002 | 0x0200):
                        status, reason = (
                            "BLOCKED_LICENSE",
                            "Confirm authorized use; restricted/bitmap-only fonts cannot be embedded.",
                        )
                    elif candidate.postscript_name != item.name or "+" in item.name:
                        status, reason = (
                            "BLOCKED_AMBIGUOUS_MATCH",
                            "Exact original PostScript face is required; subset identity cannot be inferred.",
                        )
                    else:
                        data = object_value(doc, item.xref)
                        descriptor = object_value(doc, item.descriptor)
                        if int(descriptor.get("Flags", 0)) & 4:
                            raise FontPreflightError("Symbolic font encoding is unsupported.")
                        first, last = data.get("FirstChar"), data.get("LastChar")
                        widths = dereference(doc, data.get("Widths"))
                        if (
                            type(first) is not int
                            or type(last) is not int
                            or not 0 <= first <= last <= 255
                            or not isinstance(widths, list)
                            or len(widths) != last - first + 1
                        ):
                            raise FontPreflightError("Missing or invalid character-width mapping.")
                        with TTFont(candidate.path, lazy=False) as font:
                            cmap = font.getBestCmap() or {}
                            units = font["head"].unitsPerEm
                            for code, width in enumerate(widths, first):
                                check_cancel(is_cancelled)
                                if type(width) not in (int, float):
                                    raise FontPreflightError("Unsupported width entry.")
                                try:
                                    character = bytes([code]).decode("cp1252")
                                except UnicodeDecodeError:
                                    if width != 0:
                                        raise FontPreflightError(
                                            "Non-standard WinAnsi code mapping."
                                        ) from None
                                    continue
                                glyph = cmap.get(ord(character))
                                if not glyph:
                                    raise FontPreflightError(
                                        "The original character mapping cannot be verified."
                                    )
                                advance = font["hmtx"].metrics[glyph][0] * 1000 / units
                                # PDF widths often round to integral 1/1000-em units.
                                # Original /Widths are never altered; reference pixels remain exact.
                                if abs(advance - width) > 0.500001:
                                    raise FontPreflightError(
                                        "Candidate advance widths differ from PDF metrics."
                                    )
                        status, reason = (
                            "CANDIDATE_FOUND",
                            "Name/encoding/widths match; authoritative original-font reference is still required.",
                        )
                except Exception as exc:
                    status, reason = "BLOCKED_ENCODING_OR_GLYPHS", str(exc)
            decisions.append(MatchDecision(item.xref, status, reason, candidate))
    return decisions
