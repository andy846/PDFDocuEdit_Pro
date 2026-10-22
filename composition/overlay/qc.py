"""Exact payload decoding on cropped mark areas in the final assembled PDF."""
from __future__ import annotations

import fitz
from PIL import Image

from composition.template.model import CompositionError


def _decode_short_i25(image):
    """ZBar defaults to a six-digit minimum; fixed layouts also permit 2/4.

    Own a scanner per check, so adjusting its minimum cannot affect another
    job/thread. Exact payload and symbol-count checks still happen below.
    """
    from ctypes import c_void_p, cast, create_string_buffer, string_at

    from pyzbar import wrapper as w
    scanner, native = w.zbar_image_scanner_create(), None
    if not scanner:
        raise CompositionError("Unable to allocate barcode decoder.")
    try:
        if w.zbar_image_scanner_set_config(scanner, w.ZBarSymbol.NONE, w.ZBarConfig.CFG_ENABLE, 0):
            raise CompositionError("Unable to configure barcode decoder.")
        for config, value in ((w.ZBarConfig.CFG_ENABLE, 1), (w.ZBarConfig.CFG_MIN_LEN, 2)):
            if w.zbar_image_scanner_set_config(scanner, w.ZBarSymbol.I25, config, value):
                raise CompositionError("Unable to configure short I25 decoding.")
        grey = image.convert("L")
        pixels = create_string_buffer(grey.tobytes())
        native = w.zbar_image_create()
        if not native:
            raise CompositionError("Unable to allocate barcode image.")
        w.zbar_image_set_format(native, int.from_bytes(b"Y800", "little"))
        w.zbar_image_set_size(native, *grey.size)
        w.zbar_image_set_data(native, cast(pixels, c_void_p), len(pixels)-1, None)
        if w.zbar_scan_image(scanner, native) < 0:
            raise CompositionError("Barcode decoder rejected the image.")
        results = []
        symbol = w.zbar_image_first_symbol(native)
        while symbol:
            results.append(string_at(w.zbar_symbol_get_data(symbol), w.zbar_symbol_get_data_length(symbol)).decode("utf-8"))
            symbol = w.zbar_symbol_next(symbol)
        return results
    finally:
        if native:
            w.zbar_image_destroy(native)
        w.zbar_image_scanner_destroy(scanner)


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
    values=(_decode_short_i25(image) if mark["symbology"] == "i25" and len(mark["payload"]) < 6 else
            [result.data.decode("utf-8") for result in decode(image,symbols=[symbol])])
    if values != [mark["payload"]]:
        raise CompositionError(f"Barcode QC failed: expected exactly one {mark['symbology']} payload "
                               f"for object {mark['object']}, found {len(values)} matching/different symbols.")
    return True
