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
