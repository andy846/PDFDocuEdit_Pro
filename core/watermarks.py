"""Owned, editable watermarks stored as ordinary printable PDF content.

The small placement stream owns its metadata and indirect resource references.
Only that stream is replaced on move/resize; duplicated pages use copy on write.
Unrecognised or externally merged streams are never edited or removed.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
from math import cos, isfinite, radians, sin
from pathlib import Path
from uuid import uuid4

import fitz

from .page_images import _placement_delta, _replace_content
from .pdf_engine import DOCUMENT_LOCK

KIND = "Watermark"
_META = "PDFdocuEditWatermark"
_ASSET = "PDFdocuEditWatermarkAsset"
_FORM = "PDFdocuEditWatermarkForm"
_REF = re.compile(r"\b(\d+)\s+\d+\s+R\b")
_NUMBER = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_CALL = re.compile(rb"\s*q\s+(?:(" + rb"\s+".join([_NUMBER] * 6)
                   + rb")\s+cm\s+)?/([A-Za-z0-9]+)\s+Do\s+Q\s*")
ANCHORS = ("top-left", "top", "top-right", "left", "centre", "right",
           "bottom-left", "bottom", "bottom-right")
PT_MM = 72 / 25.4


class WatermarkError(ValueError):
    """User-readable rejection; caller's mutation transaction handles rollback."""


@dataclass(frozen=True)
class WatermarkSpec:
    mode: str = "text"
    text: str = "CONFIDENTIAL"
    fontsize: float = 64
    scale: float = 1
    rotation: float = 45
    opacity: float = .25
    anchor: str = "centre"
    x_mm: float = 0
    y_mm: float = 0
    color: tuple[float, float, float] = (.5, .5, .5)
    image_width_pt: float | None = None

    def validate(self):
        values = (self.fontsize, self.scale, self.rotation, self.opacity,
                  self.x_mm, self.y_mm, *self.color)
        if (not all(isfinite(float(v)) for v in values) or self.mode not in {"text", "image"}
                or self.anchor not in ANCHORS or not 1 <= self.fontsize <= 1000
                or not 0 < self.scale <= 20 or not 0 <= self.opacity <= 1
                or len(self.color) != 3 or not all(0 <= v <= 1 for v in self.color)
                or not isinstance(self.text, str) or len(self.text) > 4000
                or (self.mode == "text" and not self.text.strip())
                or (self.image_width_pt is not None and
                    (not isfinite(self.image_width_pt) or self.image_width_pt <= 0))):
            raise WatermarkError("Choose valid watermark text, size, angle, opacity and position.")


def _metadata(page, xref):
    if xref not in page.get_contents():
        return None
    kind, value = page.parent.xref_get_key(xref, _META)
    if kind != "string" or len(value) > 32768:
        return None
    try:
        data = json.loads(value)
        if (not isinstance(data, dict) or type(data.get("version")) is not int
                or data["version"] != 1 or not isinstance(data.get("id"), str)):
            return None
        spec = WatermarkSpec(**data["spec"])
        spec.validate()
        data["spec"] = asdict(spec)
        if (not isinstance(data["page_rotation"], int) or data["page_rotation"] % 90
                or len(data["id"]) > 64):
            return None
        origin = data["origin"]
        values, size = data["rect"], data["content_size"]
        if (not isinstance(values, list) or len(values) != 4
                or not isinstance(origin, list) or len(origin) != 2
                or not isinstance(size, list) or len(size) != 2
                or not all(isinstance(v, (float, int)) and not isinstance(v, bool)
                           and isfinite(v) for v in (*values, *origin, *size))
                or min(size) <= 0):
            return None
        rect = fitz.Rect(values)
        if rect.is_empty or rect.is_infinite:
            return None
        dx, dy = origin[0] - page.cropbox.x0, origin[1] - page.cropbox.y0
        data["rect"] = rect + (dx, dy, dx, dy)
        return data
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _resource_digest(doc, xref, memo=None, visiting=None):
    """Fingerprint decoded owned resources, independent of xref renumbering.

    Compression transport fields may change on an ordinary deflate save;
    decoded streams and every other dictionary field/reference remain covered.
    Batch creation shares the memo, avoiding repeated embedded-font hashing.
    """
    memo = {} if memo is None else memo
    visiting = set() if visiting is None else visiting
    if xref in memo:
        return memo[xref]
    if xref in visiting:
        return "cycle"
    visiting.add(xref)
    raw = doc.xref_object(xref, compressed=True)
    if raw.startswith("<<"):
        fields = [(key, *doc.xref_get_key(xref, key)) for key in sorted(doc.xref_get_keys(xref))
                  if key not in {"Length", "Filter", "DecodeParms"}]
        raw = json.dumps(fields, separators=(",", ":"))
    references = [int(match[1]) for match in _REF.finditer(raw)]
    canonical = _REF.sub("REFERENCE", raw).encode("utf-8")
    digest = hashlib.sha256(canonical)
    if doc.xref_is_stream(xref):
        digest.update(doc.xref_stream(xref))
    for ref in references:
        digest.update(_resource_digest(doc, ref, memo, visiting).encode("ascii"))
    visiting.remove(xref)
    memo[xref] = digest.hexdigest()
    return memo[xref]


def _owned(page, xref):
    data = _metadata(page, xref)
    if data is None:
        raise WatermarkError("The selected watermark is no longer available.")
    stream = page.parent.xref_stream(xref)
    match = _CALL.fullmatch(stream)
    if match is None:
        raise WatermarkError("Another PDF tool changed this watermark's content. Editing is blocked to protect the page.")
    name = match[2].decode("ascii")
    matrices = tuple(map(float, match[1].split())) if match[1] else (1, 0, 0, 1, 0, 0)
    a, b, c, d, _e, _f = matrices
    if not all(isfinite(v) for v in matrices) or b or c or a <= 0 or d <= 0:
        raise WatermarkError("The watermark transform was changed. Editing is blocked.")
    if hashlib.sha256(stream).hexdigest() != data.get("wrapper_hash"):
        raise WatermarkError("The watermark placement was changed by another PDF tool. Editing is blocked.")
    kind, value = page.parent.xref_get_key(xref, _FORM)
    resource = int(value.split()[0]) if kind == "xref" else None
    if not any(item[1] == name and item[0] == resource and item[2] == 0 for item in page.get_xobjects()):
        raise WatermarkError("The watermark resource is missing. Editing is blocked.")
    if _resource_digest(page.parent, resource) != data.get("resource_hash"):
        raise WatermarkError("The watermark resource was changed by another PDF tool. Editing is blocked.")
    if data["spec"]["mode"] == "image":
        kind, value = page.parent.xref_get_key(xref, _ASSET)
        if kind != "xref" or hashlib.sha256(page.parent.xref_stream(int(value.split()[0]))).hexdigest() != data.get("asset_hash"):
            raise WatermarkError("The embedded watermark image was changed. Editing is blocked.")
    return data, stream


def _write_metadata(page, xref, data):
    data = dict(data, rect=list(data["rect"]), origin=[page.cropbox.x0, page.cropbox.y0],
                wrapper_hash=hashlib.sha256(page.parent.xref_stream(xref)).hexdigest())
    value = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    page.parent.xref_set_key(xref, _META, fitz.get_pdf_str(value))


def list_watermarks(page: fitz.Page) -> list[dict]:
    with DOCUMENT_LOCK:
        entries = []
        for xref in page.get_contents():
            data = _metadata(page, xref)
            if data is not None:
                entries.append(dict(kind=KIND, xref=xref, id=data["id"], rect=data["rect"],
                                    text=data["spec"]["text"] if data["spec"]["mode"] == "text" else "",
                                    subject="Editable watermark", opacity=data["spec"]["opacity"],
                                    width=0., keep_aspect=True))
        return entries


def watermark_spec(page, xref) -> WatermarkSpec:
    with DOCUMENT_LOCK:
        data, _ = _owned(page, xref)
        spec = WatermarkSpec(**data["spec"])
        # Moving/cropping/rotating a page must not reset its placement when
        # properties are opened. Express the actual centre in today's view.
        visible = data["rect"] * page.rotation_matrix
        centre = (visible.tl + visible.br) / 2
        return replace(spec, anchor="centre", x_mm=(centre.x - page.rect.width / 2) / PT_MM,
                       y_mm=(centre.y - page.rect.height / 2) / PT_MM,
                       image_width_pt=data["content_size"][0] / spec.scale if spec.mode == "image" else None,
                       rotation=(spec.rotation + data["page_rotation"] - page.rotation) % 360)


def watermark_image(page, xref) -> bytes | None:
    with DOCUMENT_LOCK:
        _owned(page, xref)
        kind, value = page.parent.xref_get_key(xref, _ASSET)
        return page.parent.xref_stream(int(value.split()[0])) if kind == "xref" else None


def _local_content(spec, image):
    """Return one small vector/text or embedded image source page, no PDF rasterization."""
    source = fitz.open()
    try:
        if spec.mode == "text":
            # Built-in CJK font for non-Latin text, as elsewhere in MuPDF;
            # preserve Unicode and vectors rather than replacing characters.
            fontname = "helv" if all(ord(c) < 256 for c in spec.text) else "china-s"
            font = fitz.Font(fontname)
            size = spec.fontsize * spec.scale
            width = max(1., font.text_length(spec.text, fontsize=size))
            height = max(1., (font.ascender - font.descender) * size)
            local = source.new_page(width=width, height=height)
            if fontname != "helv":
                local.insert_font(fontname="WatermarkFont", fontbuffer=font.buffer)
                fontname = "WatermarkFont"
            local.insert_text((0, font.ascender * size), spec.text, fontname=fontname,
                              fontsize=size, color=tuple(spec.color), fill_opacity=spec.opacity)
        else:
            if not image:
                raise WatermarkError("Choose a watermark image.")
            from PIL import Image
            with Image.open(io.BytesIO(image)) as original:
                rgba = original.convert("RGBA")
                rgba.putalpha(rgba.getchannel("A").point(lambda v: round(v * spec.opacity)))
                output = io.BytesIO()
                rgba.save(output, format="PNG")
                width, height = rgba.size
            local = source.new_page(width=width, height=height)
            local.insert_image(local.rect, stream=output.getvalue())
        return source
    except BaseException:
        source.close()
        raise


def add_watermark(page: fitz.Page, spec: WatermarkSpec, *, image: bytes | None = None,
                  identifier: str | None = None, _source=None, _asset=None, _resource_cache=None) -> int:
    spec.validate()
    with DOCUMENT_LOCK, (nullcontext(_source) if _source is not None else _local_content(spec, image)) as source:
        angle = radians(spec.rotation)
        width, height = source[0].rect.width, source[0].rect.height
        if spec.mode == "image":
            factor = ((spec.image_width_pt / width) if spec.image_width_pt is not None else
                      min(page.rect.width * .4 / width, page.rect.height * .4 / height)) * spec.scale
            width, height = width * factor, height * factor
        w = abs(cos(angle)) * width + abs(sin(angle)) * height
        h = abs(sin(angle)) * width + abs(cos(angle)) * height
        fit = min(1., page.rect.width * .9 / w, page.rect.height * .9 / h)
        w, h = w * fit, h * fit
        row, col = divmod(ANCHORS.index(spec.anchor), 3)
        # Anchors are left/top, centre, right/bottom, inset by 5%.
        xs = (page.rect.width * .05 + w / 2, page.rect.width / 2, page.rect.width * .95 - w / 2)
        ys = (page.rect.height * .05 + h / 2, page.rect.height / 2, page.rect.height * .95 - h / 2)
        cx, cy = xs[col] + spec.x_mm * PT_MM, ys[row] + spec.y_mm * PT_MM
        target = fitz.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        if not page.rect.contains(target):
            raise WatermarkError("Keep the watermark inside the visible page; reduce its size or offsets.")
        target = target * page.derotation_matrix
        page.wrap_contents()
        before = set(page.get_contents())
        page_rotation = page.rotation
        try:
            page.set_rotation(0)
            page.show_pdf_page(target, source, 0, rotate=(spec.rotation + page_rotation) % 360)
        finally:
            page.set_rotation(page_rotation)
        created = [xref for xref in page.get_contents() if xref not in before]
        if len(created) != 1 or not _CALL.fullmatch(page.parent.xref_stream(created[0])):
            raise WatermarkError("Unable to identify the new watermark placement.")
        xref = created[0]
        name = _CALL.fullmatch(page.parent.xref_stream(xref))[2].decode("ascii")
        resource = next(item[0] for item in page.get_xobjects() if item[1] == name and item[2] == 0)
        page.parent.xref_set_key(xref, _FORM, f"{resource} 0 R")
        _write_metadata(page, xref, dict(version=1, id=identifier or str(uuid4()),
                                       spec=asdict(replace(spec, scale=spec.scale * fit)),
                                       rect=target, page_rotation=page_rotation,
                                       content_size=[width * fit, height * fit],
                                       asset_hash=hashlib.sha256(image).hexdigest() if image is not None else None,
                                       resource_hash=_resource_digest(page.parent, resource, _resource_cache)))
        if image is not None:
            asset = _asset or page.parent.get_new_xref()
            if _asset is None:
                page.parent.update_object(asset, "<<>>")
                page.parent.update_stream(asset, image, compress=True)
            page.parent.xref_set_key(xref, _ASSET, f"{asset} 0 R")
        return xref


def add_watermarks(doc, pages, spec, *, image=None):
    """Reuse one source/graft map and embedded asset for the whole operation."""
    spec.validate()
    with DOCUMENT_LOCK, _local_content(spec, image) as source:
        asset = None
        resource_cache = {}
        if image is not None:
            asset = doc.get_new_xref()
            doc.update_object(asset, "<<>>")
            doc.update_stream(asset, image, compress=True)
        return [add_watermark(doc[page], spec, image=image, _source=source, _asset=asset,
                              _resource_cache=resource_cache)
                for page in pages if 0 <= page < doc.page_count]


def update_watermark_geometry(page, xref, rect) -> int | None:
    with DOCUMENT_LOCK:
        if _metadata(page, xref) is None:
            return None
        data, stream = _owned(page, xref)
        rect = fitz.Rect(rect)
        bounds = page.rect * page.derotation_matrix
        if not all(isfinite(v) for v in rect) or rect.width < 1 or rect.height < 1 or not bounds.contains(rect):
            raise WatermarkError("Keep the watermark inside the page.")
        old = data["rect"]
        sx, sy = rect.width / old.width, rect.height / old.height
        # Uniform scaling preserves text/image proportions and arbitrary angle.
        if abs(sx - sy) > .01:
            raise WatermarkError("Resize the watermark with its proportions preserved.")
        matrix = _placement_delta(page, old, rect)
        match = _CALL.fullmatch(stream)
        name = match[2].decode("ascii")
        # Flatten an earlier wrapper rather than growing nested content on each drag.
        previous = fitz.Matrix(*map(float, match[1].split())) if match[1] else fitz.Identity
        combined = previous * matrix
        new = page.parent.get_new_xref()
        page.parent.update_object(new, page.parent.xref_object(xref))
        page.parent.update_stream(new, ("q " + " ".join(f"{v:.9g}" for v in combined)
                                        + f" cm /{name} Do Q").encode("ascii"))
        data["rect"] = rect
        data["spec"]["scale"] *= sx
        data["content_size"] = [size * sx for size in data["content_size"]]
        _write_metadata(page, new, data)
        _replace_content(page, xref, new)
        return new


def remove_watermark(page, xref) -> bool:
    with DOCUMENT_LOCK:
        if _metadata(page, xref) is None:
            return False
        _owned(page, xref)
        _replace_content(page, xref, None)
        return True


def image_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()
