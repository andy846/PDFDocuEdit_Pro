"""Read-only comparison of private PDF snapshots. No live engine objects cross threads."""
from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from dataclasses import dataclass

import cv2
import fitz
import numpy as np

from core.tasks import TaskCancelled


@dataclass(frozen=True)
class TextChange:
    kind: str
    before: str
    after: str
    a_rects: tuple = ()
    b_rects: tuple = ()


@dataclass(frozen=True)
class PageDifference:
    a: int | None
    b: int | None
    status: str
    text: tuple[TextChange, ...] = ()
    a_regions: tuple = ()
    b_regions: tuple = ()
    has_text: bool = True


@dataclass(frozen=True)
class Feature:
    text: str
    digest: str
    image: bytes
    size: tuple


def check_cancel(cancelled):
    if cancelled():
        raise TaskCancelled()


def snapshot_file(path, password=""):
    with fitz.open(path) as doc:
        if doc.needs_pass and not doc.authenticate(password):
            raise ValueError("A valid PDF password is required.")
        if not doc.is_pdf or not doc.page_count:
            raise ValueError("Select a PDF containing at least one page.")
        return doc.tobytes(garbage=0, clean=False, no_new_id=True)


def features(doc, cancelled, progress, offset=0, total=None):
    result = []
    for number, page in enumerate(doc):
        check_cancel(cancelled)
        text = unicodedata.normalize("NFC", " ".join(page.get_text().split()))
        pix = page.get_pixmap(matrix=fitz.Matrix(64 / max(page.rect.width, page.rect.height),
                                                64 / max(page.rect.width, page.rect.height)), colorspace=fitz.csGRAY)
        matrix = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        image = cv2.resize(matrix, (32, 32), interpolation=cv2.INTER_AREA).tobytes()
        size = (round(page.rect.width, 2), round(page.rect.height, 2))
        digest = hashlib.sha256(text.encode("utf-8") + pix.samples + repr(size).encode()).hexdigest()
        result.append(Feature(text, digest, image, size))
        progress(offset + number + 1, total or doc.page_count)
    return result


def similarity(left, right):
    # Image comparison helps scanned pages; size remains a separate difference.
    a = np.frombuffer(left.image, np.uint8).astype(np.int16)
    b = np.frombuffer(right.image, np.uint8).astype(np.int16)
    visual = 1 - float(np.abs(a - b).mean()) / 255
    if left.text or right.text:
        textual = difflib.SequenceMatcher(None, left.text[:8000], right.text[:8000], autojunk=False).ratio()
        return .85 * textual + .15 * visual
    return visual


def align_pages(a, b, cancelled=lambda: False):
    """Exact anchors plus bounded monotonic alignment of changed runs."""
    matcher = difflib.SequenceMatcher(None, [f.digest for f in a], [f.digest for f in b], autojunk=False)
    pairs = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        check_cancel(cancelled)
        if tag == "equal":
            pairs.extend(zip(range(a0, a1), range(b0, b1), strict=True))
        elif tag == "delete":
            pairs.extend((i, None) for i in range(a0, a1))
        elif tag == "insert":
            pairs.extend((None, j) for j in range(b0, b1))
        else:
            n, m = a1 - a0, b1 - b0
            # Keep memory bounded for entirely unrelated, very large documents.
            if n * m > 250_000:
                pairs.extend((a0 + i if i < n else None, b0 + i if i < m else None)
                             for i in range(max(n, m)))
                continue
            costs = np.empty((n + 1, m + 1), dtype=np.float32)
            moves = np.zeros((n + 1, m + 1), dtype=np.uint8)
            costs[:, 0] = np.arange(n + 1) * .65
            costs[0, :] = np.arange(m + 1) * .65
            moves[1:, 0] = 1
            moves[0, 1:] = 2
            for i in range(1, n + 1):
                check_cancel(cancelled)
                for j in range(1, m + 1):
                    if j % 32 == 0:
                        check_cancel(cancelled)
                    score = similarity(a[a0 + i - 1], b[b0 + j - 1])
                    options = (costs[i-1, j-1] + (1 - score) * 1.5,
                               costs[i-1, j] + .65, costs[i, j-1] + .65)
                    move = min(range(3), key=options.__getitem__)
                    costs[i, j], moves[i, j] = options[move], move
            chunk, i, j = [], n, m
            while i or j:
                move = moves[i, j]
                chunk.append((a0 + i - 1 if move != 2 else None,
                              b0 + j - 1 if move != 1 else None))
                i -= move != 2
                j -= move != 1
            pairs.extend(reversed(chunk))
    return list(pairs)


def manual_pair(pairs, a, b):
    """Pair chosen pages, preserving all pages and non-crossing existing pairs."""
    left = sorted(x for x, _ in pairs if x is not None)
    right = sorted(y for _, y in pairs if y is not None)
    if a not in left or b not in right:
        raise ValueError("Page is outside this comparison.")
    anchors = sorted([(x, y) for x, y in pairs
                      if x is not None and y is not None and x != a and y != b] + [(a, b)])
    if [y for _, y in anchors] != sorted(y for _, y in anchors):
        raise ValueError("This pairing would cross another pair. Unpair intervening pages first.")
    rebuilt, i, j = [], 0, 0
    for x, y in anchors:
        while i < len(left) and left[i] < x:
            rebuilt.append((left[i], None))
            i += 1
        while j < len(right) and right[j] < y:
            rebuilt.append((None, right[j]))
            j += 1
        rebuilt.append((x, y))
        i += 1
        j += 1
    rebuilt.extend((x, None) for x in left[i:])
    rebuilt.extend((None, y) for y in right[j:])
    return rebuilt


def unpair(pairs, index):
    a, b = pairs[index]
    replacement = [(a, None), (None, b)] if a is not None and b is not None else [(a, b)]
    return pairs[:index] + replacement + pairs[index + 1:]


def tokens(page):
    """Latin words and individual CJK characters with actual character boxes."""
    result = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            chars = [c for span in line["spans"] for c in span["chars"]]
            text = "".join(c["c"] for c in chars)
            for match in re.finditer(r"[\u3400-\u9fff\uf900-\ufaff]|[^\s\u3400-\u9fff\uf900-\ufaff]+", text):
                rect = fitz.Rect(chars[match.start()]["bbox"])
                for char in chars[match.start()+1:match.end()]:
                    rect |= fitz.Rect(char["bbox"])
                result.append((unicodedata.normalize("NFC", match[0]), tuple(rect)))
    return result


def text_differences(left, right):
    a, b = tokens(left), tokens(right)
    matcher = difflib.SequenceMatcher(None, [t[0] for t in a], [t[0] for t in b], autojunk=False)
    changes = []
    for kind, i, j, k, end in matcher.get_opcodes():
        if kind != "equal":
            changes.append(TextChange(kind, " ".join(t[0] for t in a[i:j]), " ".join(t[0] for t in b[k:end]),
                                      tuple(t[1] for t in a[i:j]), tuple(t[1] for t in b[k:end])))
    return tuple(changes), bool(a or b)


def visual_differences(left, right, dpi=96):
    # Render at the same physical scale, preserving paper sizes and rotation.
    # Cap pathological page dimensions without stretching either page.
    scale = min(dpi / 72, 2400 / max(*left.rect[2:], *right.rect[2:]))
    images = []
    for page in (left, right):
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
        images.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3))
    height, width = max(i.shape[0] for i in images), max(i.shape[1] for i in images)
    canvases = []
    for image in images:
        canvas = np.full((height, width, 3), 255, np.uint8)
        canvas[:image.shape[0], :image.shape[1]] = image
        canvases.append(canvas)
    mask = (np.max(cv2.absdiff(*canvases), axis=2) > 28).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    regions = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area >= 5:
            regions.append(fitz.Rect(float(x)/scale, float(y)/scale,
                                     float(x+w)/scale, float(y+h)/scale))
    if (left.rect.width, left.rect.height) != (right.rect.width, right.rect.height):
        regions.append(left.rect | right.rect)
    if len(regions) > 500:
        union = fitz.Rect(regions[0])
        for rect in regions[1:]:
            union |= rect
        regions = [union]
    def mapped(page):
        return tuple(tuple((rect & page.rect) * page.derotation_matrix)
                     for rect in regions if not (rect & page.rect).is_empty)
    return mapped(left), mapped(right)


def compare_snapshots(a_bytes, b_bytes, *, pairs=None, cancelled=lambda: False, progress=lambda n, total: None):
    with fitz.open(stream=a_bytes, filetype="pdf") as a, fitz.open(stream=b_bytes, filetype="pdf") as b:
        if pairs is None:
            total = a.page_count + b.page_count
            fa = features(a, cancelled, progress, total=total)
            fb = features(b, cancelled, progress, offset=a.page_count, total=total)
            pairs = align_pages(fa, fb, cancelled)
        results = []
        for index, (i, j) in enumerate(pairs):
            check_cancel(cancelled)
            if i is None or j is None:
                results.append(PageDifference(i, j, "Added" if i is None else "Deleted"))
            else:
                text, has_text = text_differences(a[i], b[j])
                check_cancel(cancelled)
                ar, br = visual_differences(a[i], b[j])
                results.append(PageDifference(i, j, "Modified" if text or ar or br else "Same", text, ar, br, has_text))
            progress(index + 1, len(pairs))
        return results
