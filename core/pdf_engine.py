"""Headless PDF document engine built on PyMuPDF."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

import fitz

# Serializes every operation on the shared live document between the GUI
# thread and background render workers. PyMuPDF document and page objects must
# not be used concurrently across threads, even when both callers only read.
DOCUMENT_LOCK = threading.RLock()


def _locked(function):
    @wraps(function)
    def wrapper(self, *args, **kwargs):
        with DOCUMENT_LOCK:
            return function(self, *args, **kwargs)

    return wrapper


class PdfEngineError(RuntimeError):
    pass


class PdfPasswordRequired(PdfEngineError):
    pass


class PdfInvalidPassword(PdfEngineError):
    pass


@dataclass(frozen=True)
class SearchHit:
    """One search result page with matching rectangles and a text excerpt."""

    page: int
    rects: list[fitz.Rect]
    context: str


@dataclass(frozen=True)
class PagePlanEntry:
    """One stable page reference used by the visual organizer transaction."""

    entry_id: str
    source_kind: str
    source_page: int
    source_path: str = ""
    final_rotation: int = 0
    password: str = ""


class PdfEngine:
    def __init__(self):
        self._doc: fitz.Document | None = None
        self._original_path: Path | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._temp_path: Path | None = None
        self._is_modified = False
        self._password: str | None = None
        self._reencrypt_on_save = False
        self._saved_permissions: int | None = None
        self._document_id = uuid.uuid4().hex
        self._revision = 0

    @_locked
    def open(self, path: str | os.PathLike[str], password: str | None = None) -> None:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise PdfEngineError(f"File not found: {source}")
        # Authenticate the new file BEFORE touching the currently open
        # document: a cancelled or wrong password must never destroy the
        # document that is already on screen.
        temp_dir = tempfile.TemporaryDirectory(prefix="pdfdocuedit-")
        temp_path = Path(temp_dir.name) / source.name
        password_used: str | None = None
        reencrypt = False
        saved_permissions: int | None = None
        try:
            shutil.copy2(source, temp_path)
            doc = fitz.open(temp_path)
            if doc.needs_pass:
                if not password:
                    doc.close()
                    raise PdfPasswordRequired("This document requires a password.")
                if not doc.authenticate(password):
                    doc.close()
                    raise PdfInvalidPassword("The password is not valid.")
                password_used = password
                reencrypt = True
                # Remember the document's effective permissions so re-saving
                # does not silently upgrade or downgrade them.
                try:
                    saved_permissions = int(doc.permissions)
                except Exception:
                    saved_permissions = None
                # MuPDF's in-memory decryption state on encrypted documents
                # corrupts unpredictably across the app's many readers, so
                # rebuild an unencrypted working copy up front. Saving will
                # re-encrypt with the user password.
                doc = self._decrypted_working_copy(doc, temp_dir.name)
        except Exception:
            temp_dir.cleanup()
            raise
        self.close()
        self._temp_dir = temp_dir
        self._temp_path = temp_path
        self._doc = doc
        self._original_path = source
        self._is_modified = False
        self._password = password_used
        self._reencrypt_on_save = reencrypt
        self._saved_permissions = saved_permissions
        self._document_id = uuid.uuid4().hex
        self._revision = 0

    def _decrypted_working_copy(
        self, source_doc: fitz.Document, directory: str
    ) -> fitz.Document:
        """Rebuild an encrypted document into a plain working copy."""
        handle, temp_name = tempfile.mkstemp(
            prefix="decrypted-", suffix=".pdf", dir=directory
        )
        os.close(handle)
        try:
            try:
                # Fast path: strip encryption directly. Preserves forms,
                # attachments and signatures when MuPDF has enough rights.
                source_doc.save(
                    temp_name,
                    garbage=4,
                    deflate=True,
                    encryption=fitz.PDF_ENCRYPT_NONE,
                )
            except Exception:
                # Direct stripping can fail when only the *user* password is
                # known, so rebuild instead.
                Path(temp_name).unlink(missing_ok=True)
                with fitz.open() as working:
                    if source_doc.page_count:
                        working.insert_pdf(
                            source_doc, from_page=0, to_page=source_doc.page_count - 1
                        )
                    working.set_metadata(source_doc.metadata or {})
                    working.set_toc(source_doc.get_toc() or [])
                    working.save(
                        temp_name,
                        garbage=4,
                        deflate=True,
                        encryption=fitz.PDF_ENCRYPT_NONE,
                    )
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise
        source_doc.close()
        return fitz.open(temp_name)

    @_locked
    def close(self) -> None:
        if self._doc:
            self._doc.close()
        if self._temp_dir:
            self._temp_dir.cleanup()
        self._doc = None
        self._original_path = None
        self._temp_dir = None
        self._temp_path = None
        self._is_modified = False
        self._password = None
        self._reencrypt_on_save = False
        self._saved_permissions = None

    @_locked
    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        if not self._doc:
            raise PdfEngineError("No PDF is open.")
        target = Path(path).expanduser().resolve() if path else self._original_path
        if target is None:
            raise PdfEngineError("No save location is available.")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
        )
        os.close(handle)
        try:
            if self._reencrypt_on_save:
                # MuPDF cannot preserve the original owner password when only
                # the user password is known (a full re-save must generate
                # fresh encryption keys), but the user password, encryption
                # strength, and the document's original permissions are kept.
                self._doc.save(
                    temp_name,
                    garbage=0,
                    deflate=False,
                    clean=False,
                    encryption=fitz.PDF_ENCRYPT_AES_256,
                    owner_pw=secrets.token_hex(20),
                    user_pw=self._password or "",
                    permissions=(
                        int(self._saved_permissions)
                        if self._saved_permissions is not None
                        else int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT)
                    ),
                )
            elif self._doc.can_save_incrementally():
                # The working document is an isolated copy of the source.
                # Append annotation changes there, then atomically copy it to
                # the destination. Existing page, font, image and barcode
                # streams remain byte-for-byte untouched.
                self._doc.saveIncr()
                shutil.copy2(self._doc.name, temp_name)
            else:
                # Repaired PDFs and a few unusual inputs cannot be saved
                # incrementally. Preserve all live objects and content streams
                # instead of sanitizing or deduplicating them.
                self._doc.save(
                    temp_name,
                    garbage=0,
                    deflate=False,
                    clean=False,
                    encryption=fitz.PDF_ENCRYPT_KEEP,
                )
            os.replace(temp_name, target)
        except Exception:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
        self._original_path = target
        self._is_modified = False
        return target

    @_locked
    def save_as(self, path: str | os.PathLike[str]) -> Path:
        return self.save(path)

    def mark_modified(self) -> None:
        """Flag the open document as modified (used by canvas editing)."""
        if self._doc:
            self._touch()

    def _touch(self) -> None:
        """Record one logical mutation for stale-analysis detection."""
        self._is_modified = True
        self._revision += 1

    def detach_save_target(self) -> None:
        """Require the next save to choose a PDF path (used for converted input)."""
        self._original_path = None

    def inherit_save_context(
        self, source: PdfEngine, *, modified: bool = True
    ) -> None:
        """Keep the user's save destination when loading an undo snapshot.

        Undo snapshots are ordinary temporary PDFs. Opening one normally
        makes that temporary file the engine's ``original_path``, so a later
        Ctrl+S would save to the snapshot instead of the user's document.
        Preserve the destination and encryption policy from the live engine,
        along with whether the restored state still has unsaved edits.
        """
        self._original_path = source._original_path
        self._password = source._password
        self._reencrypt_on_save = source._reencrypt_on_save
        self._saved_permissions = source._saved_permissions
        self._document_id = source._document_id
        self._revision = source._revision + 1
        self._is_modified = modified

    @property
    def document(self) -> fitz.Document | None:
        return self._doc

    @property
    def original_path(self) -> Path | None:
        return self._original_path

    @property
    def temp_path(self) -> Path | None:
        return self._temp_path

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    @property
    def document_id(self) -> str:
        return self._document_id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    @_locked
    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def is_loaded(self) -> bool:
        return self._doc is not None

    @_locked
    def has_digital_signatures(self) -> bool:
        """Return True only for signature fields that contain a signature value."""
        if self._doc is None:
            return False
        for page_number in range(self._doc.page_count):
            try:
                widgets = list(self._doc.load_page(page_number).widgets() or [])
            except Exception:
                continue
            for widget in widgets:
                if widget.field_type != fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    continue
                if widget.field_value:
                    return True
                try:
                    if re.search(
                        r"/V\s+\d+\s+\d+\s+R", self._doc.xref_object(widget.xref)
                    ):
                        return True
                except Exception:
                    continue
        return False

    @property
    def password(self) -> str | None:
        return self._password

    # Compatibility accessors used by older modular callers.
    def get_document(self) -> fitz.Document | None:
        return self._doc

    def get_original_path(self) -> str | None:
        return str(self._original_path) if self._original_path else None

    def get_temp_path(self) -> str | None:
        return str(self._temp_path) if self._temp_path else None

    def get_page_count(self) -> int:
        return self.page_count

    def is_encrypted(self) -> bool:
        # The working copy is decrypted in memory; the *original* file's
        # encryption state is what tools and panels need to know about.
        return self._password is not None

    @_locked
    def insert_pages(self, source_path: str, pages: list[int], position: int) -> None:
        doc = self._require_document()
        with fitz.open(source_path) as source:
            insert_at = min(max(0, position), doc.page_count)
            invalid = sorted(
                {page + 1 for page in pages if not 0 <= page < source.page_count}
            )
            if invalid:
                raise PdfEngineError(
                    "Source pages are out of range: " + ", ".join(map(str, invalid))
                )
            valid = [page for page in pages if 0 <= page < source.page_count]
            if not valid:
                raise PdfEngineError("No valid source pages were selected.")
            for offset, page_num in enumerate(valid):
                doc.insert_pdf(
                    source,
                    from_page=page_num,
                    to_page=page_num,
                    start_at=insert_at + offset,
                )
        self._touch()

    @_locked
    def insert_blank_pages(
        self, count: int, position: int, width: float, height: float
    ) -> None:
        doc = self._require_document()
        insert_at = min(max(0, position), doc.page_count)
        for offset in range(max(0, count)):
            doc.new_page(pno=insert_at + offset, width=width, height=height)
        self._touch()

    @_locked
    def repeat_insert_pages(
        self, source_path: str, pages: list[int], interval: int
    ) -> None:
        """Insert source pages after every N pages of the original document."""
        doc = self._require_document()
        if interval < 1 or not pages:
            raise PdfEngineError(
                "A repeat interval and at least one source page are required."
            )
        original_count = doc.page_count
        inserted = 0
        with fitz.open(source_path) as source:
            invalid = sorted(
                {page + 1 for page in pages if not 0 <= page < source.page_count}
            )
            if invalid:
                raise PdfEngineError(
                    "Source pages are out of range: " + ", ".join(map(str, invalid))
                )
            valid = [page for page in pages if 0 <= page < source.page_count]
            if not valid:
                raise PdfEngineError("No valid source pages were selected.")
            for boundary in range(interval, original_count + 1, interval):
                position = boundary + inserted
                for offset, page_num in enumerate(valid):
                    doc.insert_pdf(
                        source,
                        from_page=page_num,
                        to_page=page_num,
                        start_at=position + offset,
                    )
                inserted += len(valid)
        if not inserted:
            raise PdfEngineError(
                "The repeat interval does not create any insertion points."
            )
        self._touch()

    @_locked
    def delete_page(self, page_num: int) -> None:
        self.delete_pages([page_num])

    @_locked
    def delete_pages(self, pages: Iterable[int]) -> None:
        doc = self._require_document()
        valid = sorted(
            {page for page in pages if 0 <= page < doc.page_count}, reverse=True
        )
        if len(valid) >= doc.page_count:
            raise PdfEngineError("A PDF must contain at least one page.")
        for page_num in valid:
            doc.delete_page(page_num)
        if valid:
            self._touch()

    @_locked
    def extract_pages(
        self, pages: Iterable[int], output_path: str | os.PathLike[str]
    ) -> Path:
        doc = self._require_document()
        valid = list(
            dict.fromkeys(page for page in pages if 0 <= page < doc.page_count)
        )
        if not valid:
            raise PdfEngineError("No valid pages were selected.")
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
        )
        os.close(handle)
        try:
            with fitz.open() as output:
                for page in valid:
                    output.insert_pdf(doc, from_page=page, to_page=page)
                output.set_metadata(doc.metadata or {})
                output.set_toc(doc.get_toc() or [])
                output.save(temp_name, garbage=4, deflate=True)
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    @_locked
    def rotate_page(self, page_num: int, angle: int) -> None:
        self.rotate_pages([page_num], angle)

    @_locked
    def rotate_pages(self, pages: Iterable[int], angle: int) -> None:
        doc = self._require_document()
        changed = False
        for page_num in pages:
            if 0 <= page_num < doc.page_count:
                page = doc.load_page(page_num)
                page.set_rotation((page.rotation + angle) % 360)
                changed = True
        if changed:
            self._touch()

    @_locked
    def reorder_pages(self, new_order: list[int]) -> None:
        doc = self._require_document()
        if sorted(new_order) != list(range(doc.page_count)):
            raise PdfEngineError("The page order is incomplete or contains duplicates.")
        doc.select(new_order)
        self._touch()

    @_locked
    def organize_pages(self, new_order: list[int], rotations: dict[int, int]) -> None:
        """Apply one visual-organizer transaction using original page indexes."""
        doc = self._require_document()
        if not new_order:
            raise PdfEngineError("A PDF must contain at least one page.")
        if len(set(new_order)) != len(new_order) or any(
            page < 0 or page >= doc.page_count for page in new_order
        ):
            raise PdfEngineError(
                "The page arrangement contains invalid or duplicate pages."
            )
        doc.select(new_order)
        for current_index, original_index in enumerate(new_order):
            amount = int(rotations.get(original_index, 0)) % 360
            if amount:
                page = doc.load_page(current_index)
                page.set_rotation((page.rotation + amount) % 360)
        self._touch()

    @_locked
    def apply_page_plan(self, entries: Iterable[PagePlanEntry]) -> None:
        """Apply insert / replace / duplicate / reorder as one atomic edit."""

        doc = self._require_document()
        plan = list(entries)
        if not plan:
            raise PdfEngineError("A PDF must contain at least one page.")
        original_count = doc.page_count
        external_keys: list[tuple[str, int, str]] = []
        for entry in plan:
            if entry.source_kind == "current":
                if not 0 <= entry.source_page < original_count:
                    raise PdfEngineError(
                        "The page plan references an invalid current page."
                    )
                continue
            if entry.source_kind != "external":
                raise PdfEngineError(f"Unknown page source: {entry.source_kind}")
            source = Path(entry.source_path).expanduser().resolve()
            if not source.is_file():
                raise PdfEngineError(f"Source PDF no longer exists: {source}")
            key = (str(source), int(entry.source_page), entry.password)
            if key not in external_keys:
                external_keys.append(key)

        # Validate every external document before touching the live document.
        validated: dict[str, tuple[int, str]] = {}
        for path, page_number, password in external_keys:
            if path not in validated:
                with fitz.open(path) as source:
                    if source.needs_pass and (
                        not password or not source.authenticate(password)
                    ):
                        raise PdfEngineError(
                            f"A password is required for {Path(path).name}."
                        )
                    validated[path] = (source.page_count, password)
            if not 0 <= page_number < validated[path][0]:
                raise PdfEngineError(
                    f"Source page {page_number + 1} is outside {Path(path).name}."
                )

        backup = doc.tobytes(garbage=3, deflate=True)
        appended: dict[str, int] = {}
        try:
            # Document.select reuses the same page object when an index is
            # repeated. Append an independent copy for every duplicate entry
            # so rotations and later annotations never leak between copies.
            with fitz.open(stream=backup, filetype="pdf") as original:
                seen_current: set[int] = set()
                for entry in plan:
                    if entry.source_kind == "current":
                        if entry.source_page not in seen_current:
                            seen_current.add(entry.source_page)
                            continue
                        destination = doc.page_count
                        doc.insert_pdf(
                            original,
                            from_page=entry.source_page,
                            to_page=entry.source_page,
                            start_at=destination,
                        )
                        appended[entry.entry_id] = destination
                        continue
                    path = str(Path(entry.source_path).expanduser().resolve())
                    with fitz.open(path) as source:
                        if source.needs_pass and not source.authenticate(
                            entry.password
                        ):
                            raise PdfEngineError(f"Cannot unlock {Path(path).name}.")
                        destination = doc.page_count
                        doc.insert_pdf(
                            source,
                            from_page=entry.source_page,
                            to_page=entry.source_page,
                            start_at=destination,
                        )
                        appended[entry.entry_id] = destination

            desired: list[int] = []
            used_current: set[int] = set()
            for entry in plan:
                if (
                    entry.source_kind == "current"
                    and entry.source_page not in used_current
                ):
                    used_current.add(entry.source_page)
                    desired.append(entry.source_page)
                else:
                    desired.append(appended[entry.entry_id])
            doc.select(desired)
            for index, entry in enumerate(plan):
                doc.load_page(index).set_rotation(int(entry.final_rotation) % 360)
        except Exception:
            try:
                doc.close()
            finally:
                self._doc = fitz.open(stream=backup, filetype="pdf")
            raise
        self._touch()

    @_locked
    def split_pdf(
        self,
        ranges: list[tuple[int, int]],
        output_dir: str | os.PathLike[str],
        prefix: str | None = None,
        overwrite: bool = False,
    ) -> list[Path]:
        doc = self._require_document()
        folder = Path(output_dir).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        stem = prefix or (
            self._original_path.stem if self._original_path else "document"
        )
        jobs: list[tuple[int, int, Path]] = []
        for start, end in ranges:
            first = max(0, start)
            last = min(end, doc.page_count - 1)
            if first > last:
                continue
            page_label = (
                f"page_{first + 1}"
                if first == last
                else f"pages_{first + 1}-{last + 1}"
            )
            target = folder / f"{stem}_{page_label}.pdf"
            jobs.append((first, last, target))
        if not jobs:
            raise PdfEngineError("The selected ranges do not create any output files.")
        targets = [target for _first, _last, target in jobs]
        if len(set(targets)) != len(targets):
            raise PdfEngineError(
                "The selected ranges create duplicate output filenames."
            )
        existing = next((target for target in targets if target.exists()), None)
        if existing and not overwrite:
            raise PdfEngineError(f"Output already exists: {existing.name}")

        outputs: list[Path] = []
        for first, last, target in jobs:
            handle, temp_name = tempfile.mkstemp(
                prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
            )
            os.close(handle)
            try:
                with fitz.open() as split:
                    split.insert_pdf(doc, from_page=first, to_page=last)
                    split.set_metadata(doc.metadata or {})
                    split.save(temp_name, garbage=4, deflate=True)
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            outputs.append(target)
        return outputs

    @_locked
    def get_page_size(self, page_num: int) -> tuple[float, float]:
        doc = self._require_document()
        if not 0 <= page_num < doc.page_count:
            return 0.0, 0.0
        rect = doc.load_page(page_num).rect
        return rect.width, rect.height

    @_locked
    def get_metadata(self) -> dict:
        return dict(self._require_document().metadata or {})

    @_locked
    def set_metadata(self, metadata: dict) -> None:
        self._require_document().set_metadata(metadata)
        self._touch()

    @_locked
    def encrypt(
        self,
        password: str,
        output_path: str | os.PathLike[str],
        *,
        owner_password: str = "",
        encryption: int = fitz.PDF_ENCRYPT_AES_256,
        permissions: int = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT),
    ) -> Path:
        doc = self._require_document()
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
        )
        os.close(handle)
        try:
            doc.save(
                temp_name,
                garbage=4,
                deflate=True,
                encryption=encryption,
                owner_pw=owner_password or secrets.token_hex(20),
                user_pw=password,
                permissions=permissions,
            )
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    @_locked
    def decrypt(self, output_path: str | os.PathLike[str]) -> Path:
        doc = self._require_document()
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
        )
        os.close(handle)
        try:
            try:
                # Fast path: strip the encryption directly. This preserves
                # forms, attachments and signatures when MuPDF has enough
                # rights to do so.
                doc.save(
                    temp_name,
                    garbage=4,
                    deflate=True,
                    encryption=fitz.PDF_ENCRYPT_NONE,
                )
            except Exception:
                # Direct stripping can fail when only the *user* password is
                # known, so rebuild instead: insert_pdf re-encodes every page
                # through the authenticated session and yields a clean file.
                Path(temp_name).unlink(missing_ok=True)
                with fitz.open() as output:
                    if doc.page_count:
                        output.insert_pdf(doc, from_page=0, to_page=doc.page_count - 1)
                    output.set_metadata(doc.metadata or {})
                    output.set_toc(doc.get_toc() or [])
                    output.save(
                        temp_name,
                        garbage=4,
                        deflate=True,
                        encryption=fitz.PDF_ENCRYPT_NONE,
                    )
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    @_locked
    def snapshot(self, output_path: str | os.PathLike[str]) -> Path:
        """Save the current in-memory state as an unencrypted working copy."""
        doc = self._require_document()
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}-", suffix=".pdf", dir=target.parent
        )
        os.close(handle)
        try:
            doc.save(
                temp_name,
                garbage=0,
                deflate=False,
                clean=False,
                encryption=fitz.PDF_ENCRYPT_NONE,
            )
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    @_locked
    def search_text(
        self, text: str, page_num: int | None = None
    ) -> list[tuple[int, list[fitz.Rect]]]:
        doc = self._require_document()
        pages = [page_num] if page_num is not None else range(doc.page_count)
        results: list[tuple[int, list[fitz.Rect]]] = []
        for number in pages:
            if number is not None and 0 <= number < doc.page_count:
                hits = list(doc.load_page(number).search_for(text))
                if hits:
                    results.append((number, hits))
        return results

    @_locked
    def search_text_detailed(
        self,
        text: str,
        *,
        case_sensitive: bool = False,
        whole_word: bool = False,
        pages: Iterable[int] | None = None,
    ) -> list[SearchHit]:
        """Search the open document and return structured hits with rects and context."""
        doc = self._require_document()
        return _search_in_document(
            doc, text, case_sensitive=case_sensitive, whole_word=whole_word, pages=pages
        )

    @_locked
    def extract_text(self, page_num: int | None = None) -> str:
        doc = self._require_document()
        if page_num is not None:
            return (
                doc.load_page(page_num).get_text()
                if 0 <= page_num < doc.page_count
                else ""
            )
        return "\n\n".join(
            doc.load_page(index).get_text() for index in range(doc.page_count)
        )

    @_locked
    def get_toc(self) -> list:
        return self._require_document().get_toc()

    @_locked
    def get_page_labels(self) -> list[str]:
        doc = self._require_document()
        return [
            doc.load_page(index).get_label() or str(index + 1)
            for index in range(doc.page_count)
        ]

    def _require_document(self) -> fitz.Document:
        if not self._doc:
            raise PdfEngineError("No PDF is open.")
        return self._doc


def search_pdf_file(
    path: str | os.PathLike[str],
    text: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    password: str | None = None,
    pages: Iterable[int] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[SearchHit]:
    """Search a PDF file without keeping it open (safe for background threads)."""
    with fitz.open(path) as doc:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise PdfEngineError(
                    "The document is password protected; provide the correct password."
                )
        return _search_in_document(
            doc,
            text,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            pages=pages,
            progress=progress,
            is_cancelled=is_cancelled,
        )


def _search_in_document(
    doc: fitz.Document,
    text: str,
    *,
    case_sensitive: bool,
    whole_word: bool,
    pages: Iterable[int] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[SearchHit]:
    """Shared search implementation.

    Substring search uses ``page.search_for`` (case-insensitive by itself, so
    case constraints are enforced by re-reading the matched rectangle). Whole
    word search works on the extracted word boxes so word boundaries are
    honoured exactly.
    """
    needle = text.strip()
    if not needle:
        return []
    needle_check = needle if case_sensitive else needle.casefold()
    page_numbers = list(
        [number for number in pages if 0 <= number < doc.page_count]
        if pages is not None
        else range(doc.page_count)
    )
    hits: list[SearchHit] = []
    for position, number in enumerate(page_numbers, start=1):
        if is_cancelled and is_cancelled():
            break
        if progress:
            progress(position - 1, len(page_numbers), f"Searching page {number + 1}…")
        page = doc.load_page(number)
        if whole_word:
            kept = _search_words(page, needle, case_sensitive)
        else:
            kept = []
            for rect in page.search_for(needle):
                box_text = page.get_textbox(rect).strip()
                check = box_text if case_sensitive else box_text.casefold()
                if needle_check not in check:
                    continue
                kept.append(rect)
        if progress:
            progress(position, len(page_numbers), f"Searched page {number + 1}")
        if not kept:
            continue
        context = _context_for(page, kept[0])
        hits.append(SearchHit(page=number, rects=kept, context=context))
    return hits


def _search_words(page: fitz.Page, query: str, case_sensitive: bool) -> list[fitz.Rect]:
    """Find whole-word matches (single word or same-line phrase) on a page."""
    tokens = query.split()
    if not tokens:
        return []
    strip_chars = ".,;:!?()[]{}\"'“”‘’"
    words = [list(word) for word in page.get_text("words")]
    for word in words:
        word[4] = str(word[4]).strip(strip_chars)
        if not case_sensitive:
            word[4] = word[4].casefold()
    targets = [
        (
            token.strip(strip_chars)
            if case_sensitive
            else token.strip(strip_chars).casefold()
        )
        for token in tokens
    ]
    if any(not target for target in targets):
        return []

    rects: list[fitz.Rect] = []
    for index, word in enumerate(words):
        if word[4] != targets[0]:
            continue
        if len(targets) == 1:
            rects.append(_word_rect(word))
            continue
        matched = [word]
        for offset in range(1, len(targets)):
            if index + offset >= len(words):
                break
            next_word = words[index + offset]
            if next_word[6] != word[6] or next_word[4] != targets[offset]:
                break
            matched.append(next_word)
        else:
            x0 = min(item[0] for item in matched)
            y0 = min(item[1] for item in matched)
            x1 = max(item[2] for item in matched)
            y1 = max(item[3] for item in matched)
            rects.append(fitz.Rect(x0, y0, x1, y1))
    return rects


def _word_rect(word: list) -> fitz.Rect:
    return fitz.Rect(float(word[0]), float(word[1]), float(word[2]), float(word[3]))


def _context_for(page: fitz.Page, rect: fitz.Rect, width: float = 320.0) -> str:
    """Return a single-line text excerpt surrounding a search rectangle."""
    expanded = fitz.Rect(
        max(page.rect.x0, rect.x0 - width / 2),
        rect.y0 - 6,
        min(page.rect.x1, rect.x1 + width / 2),
        rect.y1 + 6,
    )
    try:
        text = page.get_textbox(expanded) or page.get_text()
    except Exception:
        text = ""
    return " ".join(text.split())


def parse_page_range(value: str, page_count: int | None = None) -> list[int]:
    """Parse a one-based range such as 1,3,5-8 into zero-based pages.

    Also accepts the keywords "all", "odd" and "even" (case-insensitive);
    they require a known page count to expand.
    """
    if not value.strip():
        return []
    pages: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        keyword = part.casefold()
        if keyword in {"all", "odd", "even"}:
            if page_count is None:
                raise ValueError(f"'{part}' requires a known page count")
            if keyword == "all":
                pages.update(range(page_count))
            elif keyword == "even":
                pages.update(range(page_count)[1::2])
            else:
                pages.update(range(page_count)[0::2])
            continue
        try:
            if "-" in part:
                raw_start, raw_end = part.split("-", 1)
                start, end = int(raw_start), int(raw_end)
                if start > end:
                    start, end = end, start
                if page_count is not None:
                    start = max(1, start)
                    end = min(page_count, end)
                elif end - start > 1_000_000:
                    raise ValueError(f"Page range is too large: {part}")
                if start <= end:
                    pages.update(range(start - 1, end))
            else:
                pages.add(int(part) - 1)
        except ValueError as exc:
            if str(exc).startswith("Page range is too large"):
                raise
            raise ValueError(f"Invalid page range: {part}") from exc
    pages = {
        page
        for page in pages
        if page >= 0 and (page_count is None or page < page_count)
    }
    return sorted(pages)
