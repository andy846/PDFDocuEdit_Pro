"""Exact payload decoding on cropped mark areas in the final assembled PDF."""
from __future__ import annotations

import fitz
from PIL import Image

from composition.template.model import CompositionError


def check_mark(page, mark):
    from pyzbar.pyzbar import ZBarSymbol, decode
    rect=fitz.Rect(mark["rect"])
    pix=page.get_pixmap(matrix=fitz.Matrix(300/72,300/72),clip=rect,alpha=False)
    image=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
    symbols = {"code128": ZBarSymbol.CODE128, "i25": ZBarSymbol.I25, "qr": ZBarSymbol.QRCODE}
    try:
        symbol = symbols[mark["symbology"]]
    except KeyError as exc:
        raise CompositionError("Unsupported barcode symbology in QC.") from exc
    values=[result.data.decode("utf-8") for result in decode(image,symbols=[symbol])]
    if values != [mark["payload"]]:
        raise CompositionError(f"Barcode QC failed: expected exactly one {mark['symbology']} payload "
                               f"for object {mark['object']}, found {len(values)} matching/different symbols.")
    return True
