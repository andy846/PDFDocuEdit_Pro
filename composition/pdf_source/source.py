"""Background-safe PDF inspection and streamed immutable job snapshots."""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from composition.production.generator import check_cancel
from composition.template.model import CompositionError

from .model import SourceInfo
from .planner import EnvelopePlan


def geometry(page):
    return {"width_pt": page.rect.width, "height_pt": page.rect.height,
            "mediabox": list(page.mediabox), "cropbox": list(page.cropbox), "rotation": page.rotation}


def _stat(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _hash(path, is_cancelled=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            check_cancel(is_cancelled)
            digest.update(block)
    return digest.hexdigest()


def inspect_source(path, settings, *, is_cancelled=None, progress=None, uniform=False):
    settings.validate()
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() != ".pdf":
        raise CompositionError("Choose an existing PDF source.")
    before = _stat(source)
    digest = _hash(source, is_cancelled)
    geometries = []
    with fitz.open(source) as doc:
        if not doc.is_pdf or doc.is_encrypted or doc.needs_pass:
            raise CompositionError("Unlock the source PDF in the editor before creating an overlay job.")
        if doc.get_sigflags() > 0:
            raise CompositionError("Signed/signature-field PDF sources need review; overlay cannot preserve signature validity.")
        plan = EnvelopePlan(doc.page_count, settings)
        for index in range(doc.page_count):
            check_cancel(is_cancelled)
            page = doc[index]
            if next(page.widgets(), None) is not None:
                raise CompositionError(f"Source page {index+1}: interactive forms are not supported by PDF Overlay.")
            current = geometry(page)
            variable = uniform or bool(settings.groups)
            role = 0 if variable else index % settings.pages_per_envelope
            if index == 0 or (not variable and index < settings.pages_per_envelope):
                geometries.append(current)
            elif any(abs(a-b) > .02 for key in ("mediabox", "cropbox")
                     for a, b in zip(current[key], geometries[role][key], strict=True)) or current["rotation"] != geometries[role]["rotation"]:
                raise CompositionError(f"Source page {index+1}: geometry differs from letter page {role+1}; review the source.")
            if progress and (index % 100 == 0 or index == doc.page_count-1):
                progress(index+1, doc.page_count, f"Checking source page {index+1:,} / {doc.page_count:,}")
        pages = plan.source_pages
    if _stat(source) != before:
        raise CompositionError("Source PDF changed during inspection. Review and inspect it again.")
    return SourceInfo(str(source), digest, before[0], before[1], pages, geometries,
                      ["Print overlay copies page content/annotations; document navigation and interactive links are not transferred."],
                      "uniform" if uniform or settings.groups else "roles")


def snapshot_source(path, target, expected_sha256, *, is_cancelled=None):
    source, destination = Path(path).resolve(), Path(target).resolve()
    if source == destination:
        raise CompositionError("The source PDF must never be overwritten.")
    before = _stat(source)
    digest = hashlib.sha256()
    created = False
    try:
        with source.open("rb") as incoming, destination.open("xb") as outgoing:
            created = True
            for block in iter(lambda: incoming.read(1024*1024), b""):
                check_cancel(is_cancelled)
                outgoing.write(block)
                digest.update(block)
        if _stat(source) != before or digest.hexdigest() != expected_sha256:
            raise CompositionError("Source PDF changed since preview. Inspect and review it again.")
        return destination
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
