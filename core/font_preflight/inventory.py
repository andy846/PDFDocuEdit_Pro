"""Discover reachable font programs and resource contexts without changing PDFs."""

from collections import defaultdict

import fitz

from core.pdf_operations.analysis import check_cancel, file_hash, open_pdf

from .model import FontInventory, FontPreflightError, FontResource
from .syntax import Name, Ref, parse, refs

BASE14 = frozenset(
    "Helvetica Helvetica-Bold Helvetica-Oblique Helvetica-BoldOblique Times-Roman Times-Bold Times-Italic Times-BoldItalic Courier Courier-Bold Courier-Oblique Courier-BoldOblique Symbol ZapfDingbats".split()
)


def object_value(doc, xref):
    if not 0 < xref < doc.xref_length():
        raise FontPreflightError("Invalid resource reference.")
    return parse(doc.xref_object(xref, compressed=False))


def name(value):
    return value.value if isinstance(value, Name) else ""


def dereference(doc, value):
    return object_value(doc, value.xref) if isinstance(value, Ref) else value


def analyze(source, *, password="", policy="print", progress=None, is_cancelled=None):
    if policy not in {"print", "strict"}:
        raise FontPreflightError("Unknown font policy.")
    initial_hash = file_hash(source, is_cancelled)
    with open_pdf(source, password) as doc:
        if doc.xref_length() > 250000:
            raise FontPreflightError("PDF exceeds 250,000-object analysis limit.")
        cached, found = {}, {}
        issues, uses, locations = set(), defaultdict(set), defaultdict(set)
        resource_keys, cache_bytes = defaultdict(set), 0
        protected = bool(doc._pdf_operation_encrypted) or not bool(doc.permissions & fitz.PDF_PERM_MODIFY)

        def read(xref):
            nonlocal cache_bytes
            if not 0 < xref < doc.xref_length():
                raise FontPreflightError("Invalid resource reference.")
            if xref not in cached:
                raw = doc.xref_object(xref, compressed=False)
                cache_bytes += len(raw)
                if cache_bytes > 64 * 1024 * 1024:
                    raise FontPreflightError("Resource metadata exceeds 64 MB cache limit.")
                cached[xref] = parse(raw)
            return cached[xref]

        # Inspect all objects for signature markers, including certification signatures.
        for xref in range(1, doc.xref_length()):
            check_cancel(is_cancelled)
            try:
                value = read(xref)
                if isinstance(value, dict) and (
                    name(value.get("Type")) == "Sig" or "ByteRange" in value or "DocMDP" in value
                ):
                    protected = True
            except Exception:
                issues.add(f"Object {xref}: cannot inspect object structure.")

        def walk(roots, page, label):
            pending, visited = list(roots), set()
            while pending:
                check_cancel(is_cancelled)
                xref = pending.pop()
                if xref in visited:
                    continue
                visited.add(xref)
                if len(visited) > 20000:
                    issues.add(f"{label}: resource traversal limit reached.")
                    return
                try:
                    value = read(xref)
                    if isinstance(value, dict) and name(value.get("Type")) == "Font":
                        found[xref] = value
                        if page is not None:
                            uses[xref].add(page)
                        locations[xref].add(label)

                    def collect_keys(node):
                        if isinstance(node, dict):
                            fonts = node.get("Font")
                            fonts = read(fonts.xref) if isinstance(fonts, Ref) else fonts
                            if isinstance(fonts, dict):
                                for key, font in fonts.items():
                                    if isinstance(font, Ref):
                                        resource_keys[font.xref].add(key)
                                    else:
                                        issues.add(f"{label}: inline font resource is not supported.")
                            for child in node.values():
                                collect_keys(child)
                        elif isinstance(node, list):
                            for child in node:
                                collect_keys(child)

                    collect_keys(value)
                    pending.extend(refs(value))
                except Exception:
                    issues.add(f"{label}: resource {xref} could not be traversed.")

        for index in range(doc.page_count):
            page = doc[index]
            roots = [page.xref]
            # Page resources may be inherited from the page tree.
            node, parents = page.xref, set()
            while node not in parents:
                parents.add(node)
                value = read(node)
                if isinstance(value, dict):
                    roots.extend(refs(value.get("Resources")))
                    parent = value.get("Parent")
                    if isinstance(parent, Ref):
                        node = parent.xref
                        continue
                break
            walk(roots, index + 1, "Page resources / appearances")
            if progress:
                progress(index + 1, doc.page_count, f"Inspecting fonts on page {index + 1}")
        catalog = read(doc.pdf_catalog())
        if isinstance(catalog, dict):
            for key in ("AcroForm", "OCProperties"):
                walk(refs(catalog.get(key)), None, key)
        resources = []
        for xref, value in sorted(found.items()):
            descriptor = value.get("FontDescriptor")
            descriptor_xref = descriptor.xref if isinstance(descriptor, Ref) else 0
            descendants = [
                ref.xref
                for ref in (dereference(doc, value.get("DescendantFonts")) or [])
                if isinstance(ref, Ref)
            ]
            streams = []
            descriptors = [(descriptor_xref, dereference(doc, descriptor))]
            for child in descendants:
                data = read(child)
                child_descriptor = data.get("FontDescriptor") if isinstance(data, dict) else None
                if isinstance(child_descriptor, Ref):
                    descriptors.append((child_descriptor.xref, read(child_descriptor.xref)))
            for _fd, data in descriptors:
                if not isinstance(data, dict):
                    continue
                for key in ("FontFile", "FontFile2", "FontFile3"):
                    ref = data.get(key) if isinstance(data, dict) else None
                    if isinstance(ref, Ref) and doc.xref_is_stream(ref.xref):
                        # Verify a non-empty program, bound decompression before reading.
                        raw_length = len(doc.xref_stream_raw(ref.xref) or b"")
                        if raw_length > 64 * 1024 * 1024:
                            issues.add(f"Font {xref}: font program exceeds analysis limit.")
                        elif raw_length:
                            streams.append(ref.xref)
                        else:
                            issues.add(f"Font {xref}: declared program stream is empty.")
                    elif ref is not None:
                        issues.add(f"Font {xref}: declared program is not a reachable stream.")
            subtype, base = name(value.get("Subtype")), name(value.get("BaseFont"))
            status = "EMBEDDED" if streams else "NON_EMBEDDED"
            reason = (
                "Program stream present; binary correctness not certified."
                if streams
                else "No reachable font program."
            )
            if subtype == "Type3":
                status, reason = "UNSUPPORTED", "Type3 uses glyph procedures; no automatic embedding."
            elif base in BASE14 and not streams and policy == "print":
                status, reason = (
                    "BASE14_POLICY_EXEMPT",
                    "Base-14 allowed by print policy; this is not PDF/A certification.",
                )
            elif subtype not in {"TrueType", "Type1", "Type0", "CIDFontType0", "CIDFontType2"}:
                status, reason = "UNSUPPORTED", "Font subtype is not supported for native repair."
            resource = FontResource(
                xref,
                base,
                subtype,
                descriptor_xref,
                name(value.get("Encoding")) or ("Custom" if value.get("Encoding") else "Unspecified"),
                bool(value.get("ToUnicode")),
                sorted(set(streams)),
                descendants,
                sorted(uses[xref]),
                sorted(locations[xref]),
                status,
                reason,
            )
            resource.resource_keys = sorted(resource_keys[xref])
            resource.details = {
                "first_char": value.get("FirstChar"),
                "last_char": value.get("LastChar"),
                "widths_declared": value.get("Widths") is not None,
                "to_unicode_status": "Declared; mapping correctness unverified"
                if value.get("ToUnicode")
                else "Absent; risk indicator",
                "program_validation": "Presence only; binary compatibility unverified",
            }
            resources.append(resource)
        if doc.is_repaired:
            issues.add("PDF opened using structural recovery; safe embedding is blocked.")
        if file_hash(source, is_cancelled) != initial_hash:
            raise FontPreflightError("Source changed during analysis. Analyze again.")
        return FontInventory(
            initial_hash, doc.page_count, resources, not issues, sorted(issues), protected, policy
        )
