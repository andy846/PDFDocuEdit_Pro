"""Disk-backed storage for a single Deep Search run."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from core.deep_search import SearchBatch, SearchFile, SearchHit, SearchIssue


class SearchResultsStore:
    """Keep all occurrences exportable while the dialog only loads visible rows."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="pdfdocuedit-search-")
        self.path = Path(self._temporary.name) / "results.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE hits (
                id INTEGER PRIMARY KEY, path TEXT NOT NULL, filename TEXT NOT NULL,
                page INTEGER NOT NULL, keyword TEXT NOT NULL, source TEXT NOT NULL,
                context TEXT NOT NULL, position INTEGER NOT NULL
            );
            CREATE TABLE files (
                path TEXT PRIMARY KEY, filename TEXT NOT NULL, pages INTEGER NOT NULL,
                matching_pages INTEGER NOT NULL, matches INTEGER NOT NULL,
                no_text INTEGER NOT NULL
            );
            CREATE TABLE issues (
                path TEXT NOT NULL, filename TEXT NOT NULL, message TEXT NOT NULL
            );
            CREATE INDEX hits_path ON hits(path);
            CREATE INDEX hits_keyword ON hits(keyword);
        """)

    @classmethod
    def open_reader(cls, path: str | Path) -> SearchResultsStore:
        reader = object.__new__(cls)
        reader.path = Path(path)
        reader._temporary = None
        reader.db = sqlite3.connect(reader.path.as_uri() + "?mode=ro", uri=True)
        reader.db.execute("BEGIN")
        return reader

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
            if self._temporary is not None:
                self._temporary.cleanup()

    def remove_incomplete_files(self) -> None:
        """Drop streamed hits from a file interrupted before its summary arrived."""
        with self.db:
            self.db.execute("DELETE FROM hits WHERE path NOT IN (SELECT path FROM files)")

    def hit_count(self, paths: Sequence[str] | None = None,
                  keyword: str = "", source: str = "") -> int:
        where, args = self._where(paths, keyword, source)
        return int(self.db.execute(f"SELECT COUNT(*) FROM hits{where}", args).fetchone()[0])

    def add(self, batch: SearchBatch) -> None:
        with self.db:
            if batch.hits:
                self.db.executemany(
                    "INSERT INTO hits(path, filename, page, keyword, source, context, position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ((h.path, h.filename, h.page, h.keyword, h.source, h.context, h.position)
                     for h in batch.hits),
                )
            if batch.file:
                f = batch.file
                self.db.execute(
                    "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?)",
                    (f.path, f.filename, f.pages, f.matching_pages, f.matches, int(f.no_text)),
                )
            if batch.issue:
                i = batch.issue
                self.db.execute("INSERT INTO issues VALUES (?, ?, ?)", (i.path, i.filename, i.message))

    def files(self) -> list[SearchFile]:
        return [SearchFile(*row[:5], bool(row[5])) for row in self.db.execute(
            "SELECT path, filename, pages, matching_pages, matches, no_text "
            "FROM files WHERE matches > 0 ORDER BY filename COLLATE NOCASE, path"
        )]

    def issues(self) -> list[SearchIssue]:
        return [SearchIssue(*row) for row in self.db.execute(
            "SELECT path, filename, message FROM issues ORDER BY filename COLLATE NOCASE, path"
        )]

    def counts(self, paths: Sequence[str] | None = None,
               keyword: str = "", source: str = "") -> tuple[int, int, int]:
        where, args = self._where(paths, keyword, source)
        hits, files = self.db.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT path) FROM hits{where}", args
        ).fetchone()
        pages = self.db.execute(
            f"SELECT COUNT(*) FROM (SELECT path, page FROM hits{where} GROUP BY path, page)",
            args,
        ).fetchone()[0]
        return int(hits), int(files), int(pages)

    def _where(self, paths: Sequence[str] | None, keyword: str,
               source: str) -> tuple[str, list[str]]:
        clauses: list[str] = []
        args: list[str] = []
        if paths is not None:
            if not paths:
                return " WHERE 0", args
            clauses.append("path IN (" + ",".join("?" for _ in paths) + ")")
            args.extend(paths)
        if keyword:
            clauses.append("keyword = ?")
            args.append(keyword)
        if source:
            clauses.append("source = ?")
            args.append(source)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), args

    def iter_hits(self, paths: Sequence[str] | None = None,
                  keyword: str = "", source: str = "",
                  order: str = "path COLLATE NOCASE, page, position, id") -> Iterator[SearchHit]:
        where, args = self._where(paths, keyword, source)
        cursor = self.db.execute(
            "SELECT path, filename, page, keyword, source, context, position "
            f"FROM hits{where} ORDER BY {order}", args
        )
        for row in cursor:
            yield SearchHit(*row)

    def hit_page(self, offset: int, limit: int, paths: Sequence[str] | None = None,
                 keyword: str = "", source: str = "",
                 order: str = "path COLLATE NOCASE, page, position, id") -> list[SearchHit]:
        where, args = self._where(paths, keyword, source)
        rows = self.db.execute(
            "SELECT path, filename, page, keyword, source, context, position "
            f"FROM hits{where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*args, limit, offset),
        )
        return [SearchHit(*row) for row in rows]
