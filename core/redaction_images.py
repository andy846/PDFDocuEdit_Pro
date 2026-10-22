"""Page-local process-colour copies for genuine pixel redaction of spot images."""

from __future__ import annotations

from core.pdf_backend import fitz


def _copy_dictionary(doc, value):
    kind, data = value
    if kind == "xref":
        data = doc.xref_object(int(data.split()[0]))
    elif kind != "dict":
        raise ValueError("Image redaction requires a readable PDF resource dictionary.")
    xref = doc.get_new_xref()
    doc.update_object(xref, data)
    return xref


def _page_resources(page):
    doc = page.parent
    owner = page.xref
    seen = set()
    while owner not in seen:
        seen.add(owner)
        value = doc.xref_get_key(owner, "Resources")
        if value[0] in {"dict", "xref"}:
            return value
        parent = doc.xref_get_key(owner, "Parent")
        if parent[0] != "xref":
            break
        owner = int(parent[1].split()[0])
    raise ValueError("Image redaction cannot locate the page's PDF resources.")


def _private_resources(doc, value, forms, bindings):
    """Copy resources and Form XObjects; shared pages keep original objects."""
    resources = _copy_dictionary(doc, value)
    objects = doc.xref_get_key(resources, "XObject")
    if objects[0] == "null":
        return resources
    objects = _copy_dictionary(doc, objects)
    doc.xref_set_key(resources, "XObject", f"{objects} 0 R")
    for name in doc.xref_get_keys(objects):
        kind, reference = doc.xref_get_key(objects, name)
        if kind != "xref":
            continue
        source = int(reference.split()[0])
        subtype = doc.xref_get_key(source, "Subtype")[1]
        if subtype == "/Image":
            bindings.append((objects, name, source))
        elif subtype == "/Form":
            if source not in forms:
                target = doc.get_new_xref()
                forms[source] = target
                doc.update_object(target, "<<>>")
                doc.xref_copy(source, target)
                nested = doc.xref_get_key(source, "Resources")
                if nested[0] != "null":
                    copied = _private_resources(doc, nested, forms, bindings)
                    doc.xref_set_key(target, "Resources", f"{copied} 0 R")
            doc.xref_set_key(objects, name, f"{forms[source]} 0 R")
    return resources


def _affected_spot_images(page, rects):
    affected = {}
    for image in page.get_images(full=True):
        xref, mask = image[:2]
        if image[5] not in {"Separation", "DeviceN", "Indexed"} or xref in affected:
            continue
        if not any(bounds.intersects(rect) for bounds in page.get_image_rects(xref) for rect in rects):
            continue
        source_space, alternate = image[5:7]
        if source_space == "Indexed":
            # Indexed palettes decode into their base colourspace. Ordinary
            # RGB/Gray palettes already work; only spot-colour bases need a copy.
            colorspace = fitz.Pixmap(page.parent, xref).colorspace
            if colorspace is None or not colorspace.name.startswith(("Separation(", "DeviceN(")):
                continue
            source_space += "/" + colorspace.name.split("(")[0]
            alternate = "DeviceCMYK" if "CMYK" in colorspace.name else "DeviceRGB"
        affected[xref] = (mask, source_space, alternate)
    return affected


def redaction_spot_image_count(doc):
    """Read-only count for the explicit pre-apply process-colour warning."""
    count = 0
    for page in doc:
        rects = [annot.rect for annot in page.annots(types=[fitz.PDF_ANNOT_REDACT]) or []]
        if rects:
            count += len(_affected_spot_images(page, rects))
    return count


def prepare_spot_images(page, rects):
    """Convert only intersecting Separation/DeviceN images, at native resolution.

    The replacement retains each placement's transform and soft mask. Originals
    used by another page stay intact. A temporary image placement embeds the new
    pixels; its stream and resource alias are removed before actual redaction.
    """
    doc = page.parent
    affected = _affected_spot_images(page, rects)
    if not affected:
        return []
    bindings = []
    resources = _private_resources(doc, _page_resources(page), {}, bindings)
    doc.xref_set_key(page.xref, "Resources", f"{resources} 0 R")
    root_objects = int(doc.xref_get_key(resources, "XObject")[1].split()[0])
    conversions = []
    for source, (mask, source_space, alternate) in affected.items():
        pixmap = fitz.Pixmap(doc, source)
        if mask and not pixmap.alpha:
            pixmap = fitz.Pixmap(pixmap, fitz.Pixmap(doc, mask))
        target_space = fitz.csCMYK if alternate == "DeviceCMYK" else fitz.csRGB
        converted = fitz.Pixmap(target_space, pixmap)
        contents = doc.xref_get_key(page.xref, "Contents")[1]
        aliases = set(doc.xref_get_keys(root_objects))
        try:
            target = page.insert_image(page.rect, pixmap=converted)
        finally:
            doc.xref_set_key(page.xref, "Contents", contents)
            for alias in set(doc.xref_get_keys(root_objects)) - aliases:
                doc.xref_set_key(root_objects, alias, "null")
        for owner, name, old in bindings:
            if old == source:
                doc.xref_set_key(owner, name, f"{target} 0 R")
        conversions.append((page.number, source, source_space, target_space.name))
    return conversions
