"""Payload checks shared by preview editors and the headless PDF renderer."""
from __future__ import annotations

from composition.template.model import CompositionError

BARCODE_TYPES = frozenset({"code128", "i25", "qr"})


def validate_payload(symbology: str, value: str) -> None:
    if symbology not in BARCODE_TYPES:
        raise CompositionError("Unsupported barcode format.")
    if not value:
        raise CompositionError("Barcode content is empty.")
    if symbology == "i25":
        if not value.isascii() or not value.isdigit():
            raise CompositionError("I25 accepts digits 0-9 only; remove letters, spaces or separators from the payload.")
        if len(value) % 2:
            raise CompositionError("I25 requires an even number of digits; adjust the field or profile width. No zero is added automatically.")
    elif symbology == "code128" and any(not 32 <= ord(c) <= 126 for c in value):
        raise CompositionError("Code 128 currently accepts printable ASCII; use QR for Unicode.")


def validate_size(element, value):
    """Apply the renderer's module/label limits without producing any PDF."""
    validate_payload(element.type, value)
    from composition.template.model import MM_TO_PT
    if element.type in {"code128", "i25"}:
        from barcode import ITF, Code128
        pattern = (ITF(value, narrow=1, wide=3) if element.type == "i25" else Code128(value)).build()[0]
        module = element.width_mm / (len(pattern) + 20)
        if element.show_barcode_text and element.height_mm - element.font.size_pt * 1.6 / MM_TO_PT < 5:
            raise CompositionError("Barcode is too short for the bars and readable text.")
    else:
        import segno
        qr = segno.make_qr(value, error=element.qr_error, boost_error=False, encoding="utf-8", eci=not value.isascii())
        module = min(element.width_mm, element.height_mm) / (len(qr.matrix) + 8)
    if module + .001 / MM_TO_PT < element.barcode_module_mm:
        raise CompositionError("Barcode box is too small for its minimum module size.")
