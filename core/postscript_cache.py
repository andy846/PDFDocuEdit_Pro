"""Optional content-bound PS previews. No Qt, production rules or source writes."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.cancellation import TaskCancelled
from core.pdf_backend import fitz
from core.pdf_io import validate_pdf_file

_LOG = logging.getLogger("pdfdocuedit")
_HEX = re.compile(r"[0-9a-f]{64}")
_SCHEMA = 1
_SINK = ContextVar("postscript_preview_sink", default=None)


def check_cancel(is_cancelled=None):
    if is_cancelled and is_cancelled():
        raise TaskCancelled


def file_digest(path, is_cancelled=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancel(is_cancelled)
            digest.update(chunk)
    check_cancel(is_cancelled)
    return digest.hexdigest()


@contextmanager
def source_snapshot(source, directory=None, *, is_cancelled=None, progress=None):
    """Hash and spool one stable version, never execute a changing source path."""
    source = Path(source)
    if directory is not None:
        Path(directory).mkdir(parents=True, exist_ok=True)
    check_cancel(is_cancelled)
    before = source.stat()
    with tempfile.TemporaryDirectory(prefix="ps-source-", dir=directory) as scratch:
        target = Path(scratch) / ("source" + source.suffix.lower())
        digest = hashlib.sha256()
        copied = 0
        reported = 0.0
        with source.open("rb") as src, target.open("wb") as dst:
            opened = os.fstat(src.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                raise ValueError("The PostScript source changed. Open it again.")
            while chunk := src.read(1024 * 1024):
                check_cancel(is_cancelled)
                dst.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                now = time.monotonic()
                if progress and now - reported >= 1:
                    progress(copied, before.st_size, "Preparing stable PostScript source")
                    reported = now
            after = os.fstat(src.fileno())
        current = source.stat()
        def fields(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns
        if (fields(before) != fields(after) or fields(before) != fields(current)
                or before.st_ctime_ns != current.st_ctime_ns or opened.st_ctime_ns != after.st_ctime_ns
                or copied != before.st_size):
            raise ValueError("The PostScript source changed. Open it again.")
        check_cancel(is_cancelled)
        yield target, digest.hexdigest()


def _profile_ok(value):
    if value == {"kind": "editor-v1"}:
        return True
    return (isinstance(value, dict) and set(value) == {"kind", "resolution_dpi"}
            and value["kind"] == "production-v1" and type(value["resolution_dpi"]) is int
            and 1 <= value["resolution_dpi"] <= 9600)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=8)
def _converter_identity(path, stamp, dll_stamp):
    del stamp, dll_stamp
    executable = Path(path)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run([str(executable), "--version"], capture_output=True, timeout=10, check=True, **options)
    value = {"sha256": file_digest(executable), "version": result.stdout.decode("ascii", errors="replace").strip()[:100]}
    dll = executable.with_name("gsdll64.dll" if "64" in executable.name else "gsdll32.dll")
    if dll.is_file():
        value["dll_sha256"] = file_digest(dll)
    return value


def converter_identity(executable):
    path = Path(executable).resolve()
    stat = path.stat()
    dll = path.with_name("gsdll64.dll" if "64" in path.name else "gsdll32.dll")
    ds = dll.stat() if dll.is_file() else None
    return dict(_converter_identity(str(path), (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
                                    (ds.st_size, ds.st_mtime_ns, ds.st_ctime_ns) if ds else None))


def _is_link(path):
    return path.is_symlink() or (getattr(path, "is_junction", lambda: False)())


def _pending_lease(path):
    """Reuse the project's nonblocking OS-lock pattern; crashes release leases."""
    lock_path = path.with_suffix(".lease")
    if _is_link(lock_path):
        return None
    stream = lock_path.open("a+b")
    try:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except OSError:
        stream.close()
        return None


def _release_pending(path, stream):
    if stream is not None:
        stream.close()  # closing the handle releases the OS lock
        try:
            path.with_suffix(".lease").unlink(missing_ok=True)
        except OSError:
            _LOG.warning("Optional PS preview lease cleanup deferred")



@dataclass(frozen=True)
class PreviewEntry:
    path: Path
    pages: int
    profile: dict


class PreviewCache:
    def __init__(self, root, *, enabled=True, max_bytes=2 * 1024**3, max_entry=512 * 1024**2, ttl=7 * 86400, pdf_lock=None):
        self.root = Path(root)
        self.database = self.root / "index.sqlite"
        self.enabled = enabled
        self.max_bytes = max_bytes
        self.max_entry = max_entry
        self.ttl = ttl
        self.pdf_lock = pdf_lock or nullcontext()
        self.last_status = "disabled" if not enabled else "not_checked"

    @property
    def active(self):
        return self.enabled and not (self.root / "disabled").exists()

    def set_enabled(self, enabled):
        db = None
        applied = False
        try:
            if _is_link(self.root):
                return False
            self.root.mkdir(parents=True, exist_ok=True)
            flag = self.root / "disabled"
            if _is_link(flag):
                return False
            if enabled:
                flag.unlink(missing_ok=True)
            else:
                flag.touch()
            applied = True
            db = self._connect()
            if not enabled:
                db.execute("UPDATE control SET epoch=epoch+1 WHERE id=1")
            return True
        except (OSError, sqlite3.Error):
            return applied
        finally:
            self._finish(db)

    def _delete_pending(self, path):
        lease = _pending_lease(path)
        if lease is None:
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        finally:
            _release_pending(path, lease)

    def _connect(self):
        if _is_link(self.root):
            raise OSError("Preview cache is a link")
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("entries", "pending"):
            path = self.root / name
            if _is_link(path):
                raise OSError("Preview cache child is a link")
            path.mkdir(exist_ok=True)
        if _is_link(self.database):
            raise OSError("Preview index is a link")
        db = sqlite3.connect(self.database, timeout=0)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, source TEXT, converter TEXT, profile TEXT, digest TEXT, pages INTEGER, size INTEGER, used REAL, version INTEGER)")
            db.execute("CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY, epoch INTEGER)")
            db.execute("INSERT OR IGNORE INTO control VALUES (1,0)")
            return db
        except Exception:
            db.close()
            raise

    def _path(self, key):
        if not isinstance(key, str) or not _HEX.fullmatch(key):
            raise ValueError("Invalid preview key")
        path = self.root / "entries" / (key + ".pdf")
        if _is_link(path) or path.resolve().parent != (self.root / "entries").resolve():
            raise OSError("Invalid preview location")
        return path

    def _remove(self, db, key):
        try:
            self._path(key).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass  # never follow a link or remove an unowned path
        db.execute("DELETE FROM entries WHERE key=?", (key,))

    def _pending_bytes(self):
        return sum(p.stat().st_size for p in (self.root / "pending").iterdir()
                   if re.fullmatch(r"[0-9a-f]{32}\.pdf", p.name) and not _is_link(p))

    def _prune(self, db, reserve=0):
        now = time.time()
        for path in (self.root / "pending").iterdir():
            if re.fullmatch(r"[0-9a-f]{32}\.pdf", path.name) and not _is_link(path):
                if path.stat().st_mtime < now - self.ttl:
                    self._delete_pending(path)
        pending = self._pending_bytes()
        rows = list(db.execute("SELECT key,size,used FROM entries ORDER BY used"))
        size = sum(row[1] for row in rows)
        for key, amount, used in rows:
            if used < now - self.ttl or size + pending + reserve > self.max_bytes:
                self._remove(db, key)
                size -= amount
        registered = {row[0] for row in db.execute("SELECT key FROM entries")}
        # Only a crashed writer can leave an unindexed final cache filename;
        # the database transaction excludes other active writers/readers.
        for path in (self.root / "entries").iterdir():
            if _HEX.fullmatch(path.stem) and path.suffix == ".pdf" and path.stem not in registered and not _is_link(path):
                path.unlink(missing_ok=True)
        return size + pending

    @staticmethod
    def _finish(db):
        if db is not None:
            try:
                db.commit()
            except sqlite3.Error:
                _LOG.warning("Optional PS cache index commit unavailable")
            finally:
                db.close()


    @contextmanager
    def acquire(self, source, converter, *, is_cancelled=None):
        db = None
        hit = None
        self.last_status = "disabled"
        try:
            if self.active:
                try:
                    db = self._connect()
                    previous = db.execute("SELECT converter,used FROM entries WHERE source=?", (source,)).fetchall()
                    self._prune(db)
                    self.last_status = ("expired_or_evicted" if any(c == _canonical(converter) for c, _ in previous)
                                        else "converter_changed" if previous else "not_found")
                    rows = db.execute("SELECT key,profile,digest,pages,size,version FROM entries WHERE source=? AND converter=? ORDER BY CASE WHEN profile=? THEN 0 ELSE 1 END,used DESC",
                                      (source, _canonical(converter), _canonical({"kind": "editor-v1"}))).fetchall()
                    for key, raw_profile, digest, pages, size, version in rows:
                        check_cancel(is_cancelled)
                        try:
                            profile = json.loads(raw_profile)
                            path = self._path(key)
                            valid = (version == _SCHEMA and _profile_ok(profile) and path.stat().st_size == size
                                     and file_digest(path, is_cancelled) == digest)
                            if valid:
                                with self.pdf_lock:
                                    validate_pdf_file(path, expected_page_count=pages, is_cancelled=is_cancelled)
                                hit = PreviewEntry(path, pages, profile)
                                self.last_status = "hit"
                                db.execute("UPDATE entries SET used=? WHERE key=?", (time.time(), key))
                                break
                        except TaskCancelled:
                            raise
                        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
                            pass
                        self.last_status = "invalid_entry"
                        self._remove(db, key)
                except (OSError, sqlite3.Error, ValueError):
                    self.last_status = "unavailable"
                    _LOG.info("PERF ps_cache: unavailable")
            yield hit
        finally:
            self._finish(db)

    def epoch(self):
        if not self.enabled:
            return None
        db = None
        try:
            db = self._connect()
            return db.execute("SELECT epoch FROM control WHERE id=1").fetchone()[0]
        except (OSError, sqlite3.Error):
            return None
        finally:
            self._finish(db)

    def store(self, pdf, source, converter, profile, *, expected_epoch=None, is_cancelled=None, consume_pending=False):
        if not self.active or not _HEX.fullmatch(source) or not _profile_ok(profile):
            return False
        db = None
        temporary = None
        try:
            size = Path(pdf).stat().st_size
            if size > min(self.max_entry, self.max_bytes):
                return False
            check_cancel(is_cancelled)
            with self.pdf_lock:
                validate_pdf_file(pdf, is_cancelled=is_cancelled)
                with fitz.open(pdf) as doc:
                    pages = doc.page_count
            digest = file_digest(pdf, is_cancelled)
            key = hashlib.sha256(_canonical([_SCHEMA, source, converter, profile]).encode()).hexdigest()
            db = self._connect()
            if not self.active:
                return False
            if expected_epoch is not None and db.execute("SELECT epoch FROM control WHERE id=1").fetchone()[0] != expected_epoch:
                return False
            self._remove(db, key)
            owned_pending = (consume_pending and Path(pdf).parent.resolve() == (self.root/"pending").resolve()
                             and re.fullmatch(r"[0-9a-f]{32}\.pdf", Path(pdf).name) and not _is_link(Path(pdf)))
            used = self._prune(db, 0 if owned_pending else size)
            if used + (0 if owned_pending else size) > self.max_bytes:
                return False
            if owned_pending:
                temporary = Path(pdf)
            else:
                temporary = self.root / "pending" / (uuid.uuid4().hex + ".pdf")
                with Path(pdf).open("rb") as src, temporary.open("xb") as dst:
                    while chunk := src.read(1024 * 1024):
                        check_cancel(is_cancelled)
                        dst.write(chunk)
            if file_digest(temporary, is_cancelled) != digest:
                return False
            check_cancel(is_cancelled)
            if not self.active:
                return False
            os.replace(temporary, self._path(key))
            db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?)", (key, source, _canonical(converter), _canonical(profile), digest, pages, size, time.time(), _SCHEMA))
            return True
        except TaskCancelled:
            raise
        except (OSError, sqlite3.Error, ValueError, RuntimeError):
            _LOG.info("PERF ps_cache: store unavailable")
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    _LOG.warning("Optional PS cache temporary cleanup deferred")
            self._finish(db)

    def clear(self):
        db = None
        try:
            db = self._connect()
            keys = [row[0] for row in db.execute("SELECT key FROM entries")]
            for key in keys:
                self._remove(db, key)
            db.execute("UPDATE control SET epoch=epoch+1 WHERE id=1")
            removed = len(keys)
            deferred = 0
            for path in (self.root / "entries").iterdir():
                if _HEX.fullmatch(path.stem) and path.suffix == ".pdf" and not _is_link(path):
                    path.unlink(missing_ok=True)
                    removed += 1
            for path in (self.root / "pending").iterdir():
                if re.fullmatch(r"[0-9a-f]{32}\.pdf", path.name) and not _is_link(path):
                    if self._delete_pending(path):
                        removed += 1
                    else:
                        deferred += 1
            return {"removed": removed, "busy": False, "deferred": deferred}
        except (OSError, sqlite3.Error):
            return {"removed": 0, "busy": True}
        finally:
            self._finish(db)


class ProductionPreviewSink:
    def __init__(self, cache):
        self.cache = cache
        self.epoch = cache.epoch()
        self.pending = []
        self.leases = {}

    def stage(self, pdf, digest, converter, profile):
        size = Path(pdf).stat().st_size
        if not self.cache.active or self.epoch is None or size > min(self.cache.max_entry, self.cache.max_bytes):
            return
        db = self.cache._connect()
        target = self.cache.root / "pending" / (uuid.uuid4().hex + ".pdf")
        try:
            if self.cache._prune(db, size) + size > self.cache.max_bytes:
                return
            lease = _pending_lease(target)
            if lease is None:
                return
            self.leases[target] = lease
            shutil.copyfile(pdf, target)
            self.pending.append((target, digest, converter, profile))
        except OSError:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                _LOG.warning("Optional PS preview partial cleanup deferred")
            finally:
                _release_pending(target, self.leases.pop(target, None))
            raise
        finally:
            self.cache._finish(db)

    def commit(self, result):
        rows = result.get("output_files") or [result]
        hashes = {file_digest(row["output_ps"]) for row in rows if row.get("output_ps") and Path(row["output_ps"]).is_file()}
        for pdf, digest, converter, profile in self.pending:
            if digest in hashes:
                self.cache.store(pdf, digest, converter, profile, expected_epoch=self.epoch, consume_pending=True)

    def close(self):
        while self.leases:
            path, lease = self.leases.popitem()
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _LOG.warning("Optional PS preview cleanup deferred")
            finally:
                _release_pending(path, lease)
        self.pending.clear()


@contextmanager
def production_previews(cache):
    sink = ProductionPreviewSink(cache) if cache is not None and cache.enabled else None
    token = _SINK.set(sink)
    try:
        yield sink
    finally:
        _SINK.reset(token)
        if sink:
            try:
                sink.close()
            except OSError:
                _LOG.warning("Optional PS preview cleanup deferred")


def stage_production_preview(pdf, digest, converter, profile):
    sink = _SINK.get()
    if sink:
        try:
            sink.stage(pdf, digest, converter, profile)
        except Exception as exc:
            _LOG.warning("Optional PS preview staging failed [%s]", type(exc).__name__)


def commit_production_previews(result):
    sink = _SINK.get()
    if sink:
        try:
            sink.commit(result)
        except Exception as exc:
            _LOG.warning("Optional PS preview cache commit failed [%s]", type(exc).__name__)


def application_cache_config(settings=None):
    """GUI-side resolution only; headless workers receive the resolved path."""
    from core.resources import cache_dir
    if settings is None:
        from core.settings import SettingsManager
        settings = SettingsManager()
    try:
        return {"root": str(cache_dir()/"postscript-previews-v1"),
                "enabled": bool(settings.get("ps_preview_cache_enabled", True))}
    except OSError:
        _LOG.warning("Optional PS preview cache location unavailable")
        return {"enabled": False}


def cache_from_config(config):
    if not isinstance(config, dict) or not config.get("root"):
        return None
    root = Path(config["root"])
    if not root.is_absolute():
        return None
    return PreviewCache(root, enabled=bool(config.get("enabled", False)))


def capture_production_preview(pdf, digest, executable, resolution_dpi):
    if _SINK.get() is not None:
        try:
            stage_production_preview(pdf, digest, converter_identity(executable),
                                     {"kind": "production-v1", "resolution_dpi": int(resolution_dpi)})
        except Exception as exc:
            _LOG.warning("Optional PS preview capture failed [%s]", type(exc).__name__)
