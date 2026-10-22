"""Exact structural and all-page visual gates, independent of general Compare."""

import hashlib

from core.pdf_backend import fitz
from core.pdf_operations.analysis import check_cancel

from .inventory import object_value
from .model import FontPreflightError
from .syntax import Name, Ref


def digest(data):
    return hashlib.sha256(data).hexdigest()


def descriptor_without_program(value):
    return {key: child for key, child in value.items() if key not in {"FontFile", "FontFile2", "FontFile3"}}


def compare_objects(original, other, descriptors, *, ignored_streams=(), is_cancelled=None):
    ignored = set(ignored_streams)
    if other.xref_length() < original.xref_length():
        raise FontPreflightError("Object identities changed; safe validation cannot establish equivalence.")
    for xref in range(1, original.xref_length()):
        check_cancel(is_cancelled)
        if xref in ignored:
            continue
        a, b = object_value(original, xref), object_value(other, xref)
        if xref in descriptors:
            a, b = descriptor_without_program(a), descriptor_without_program(b)
        if original.xref_is_stream(xref):
            if not other.xref_is_stream(xref):
                raise FontPreflightError(f"Stream {xref} was removed.")
            a = {k: v for k, v in a.items() if k != "Length"}
            b = {k: v for k, v in b.items() if k != "Length"}
            for doc in (original, other):
                if len(doc.xref_stream_raw(xref) or b"") > 64 * 1024 * 1024:
                    raise FontPreflightError("Stream exceeds verification limit.")
            if digest(original.xref_stream_raw(xref)) != digest(other.xref_stream_raw(xref)):
                raise FontPreflightError(f"Original stream {xref} changed.")
        if a != b:
            raise FontPreflightError(f"Original object {xref} changed.")


def compare_pages(reference, output, *, progress=None, is_cancelled=None):
    if reference.page_count != output.page_count:
        raise FontPreflightError("Page count changed.")
    evidence = []
    for index in range(reference.page_count):
        check_cancel(is_cancelled)
        left, right = reference[index], output[index]
        if (
            left.mediabox != right.mediabox
            or left.cropbox != right.cropbox
            or left.rotation != right.rotation
        ):
            raise FontPreflightError(f"Page {index + 1}: page geometry changed.")
        # Tile at 300 dpi to bound image buffers; all pages, not a sample.
        tiles = 0
        rect = left.rect
        y = rect.y0
        while y < rect.y1:
            x = rect.x0
            while x < rect.x1:
                check_cancel(is_cancelled)
                clip = fitz.Rect(x, y, min(x + 144, rect.x1), min(y + 144, rect.y1))
                a = left.get_pixmap(dpi=300, clip=clip, colorspace=fitz.csRGB, alpha=False, annots=True)
                b = right.get_pixmap(dpi=300, clip=clip, colorspace=fitz.csRGB, alpha=False, annots=True)
                if (a.width, a.height, a.samples) != (b.width, b.height, b.samples):
                    raise FontPreflightError(
                        f"Page {index + 1}: output differs from trusted reference at 300 dpi."
                    )
                tiles += 1
                x += 144
            y += 144
        evidence.append({"page": index + 1, "dpi": 300, "tiles": tiles, "pixels_equal": True})
        if progress:
            progress(index + 1, reference.page_count, f"Validating page {index + 1}")
    return evidence


def verify_reference(source_doc, reference_doc, resources, matches, *, is_cancelled=None):
    descriptors = {item.descriptor for item in resources if item.xref in {m.font_xref for m in matches}}
    allowed_streams = set()
    for match in matches:
        resource = next(item for item in resources if item.xref == match.font_xref)
        descriptor = object_value(reference_doc, resource.descriptor)
        ref = descriptor.get("FontFile2")
        if not isinstance(ref, Ref) or not reference_doc.xref_is_stream(ref.xref):
            raise FontPreflightError("Reference must contain the verified original TrueType font program.")
        if len(reference_doc.xref_stream_raw(ref.xref) or b"") > 64 * 1024 * 1024:
            raise FontPreflightError("Reference font exceeds verification limit.")
        if digest(font_program(reference_doc, ref.xref)) != match.source.sha256:
            raise FontPreflightError("Reference font binary differs from the selected original font.")
        allowed_streams.add(ref.xref)
    compare_objects(
        source_doc, reference_doc, descriptors, ignored_streams=allowed_streams, is_cancelled=is_cancelled
    )
    if source_doc.page_count != reference_doc.page_count:
        raise FontPreflightError("Reference belongs to a different document.")
    return descriptors


def font_program(doc, xref):
    """Bound Flate expansion rather than trusting native unlimited decompression."""
    import zlib

    limit = 64 * 1024 * 1024
    data = doc.xref_stream_raw(xref) or b""
    if not data or len(data) > limit:
        raise FontPreflightError("Font program is empty or exceeds verification limit.")
    metadata = object_value(doc, xref)
    encoding = metadata.get("Filter")
    if encoding is None:
        return data
    if isinstance(encoding, list) and len(encoding) == 1:
        encoding = encoding[0]
    if encoding != Name("FlateDecode") or metadata.get("DecodeParms") is not None:
        raise FontPreflightError("Reference font compression requires unsupported decoding.")
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, limit + 1)
    except zlib.error as exc:
        raise FontPreflightError("Reference font program is corrupt.") from exc
    if len(result) > limit or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise FontPreflightError("Reference font exceeds expansion limit or has invalid trailing data.")
    return result
