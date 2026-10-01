"""Streaming CSV/TXT import into a bounded-memory, random-access SQLite snapshot."""

from __future__ import annotations

import codecs
import csv
import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path

from composition.template.model import CompositionError, DataConfig

MAX_FIELDS = 1000
MAX_RECORD_CHARS = 1_000_000


def normalize_field(name: str, position: int) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    if not value:
        value = f"Field_{position}"
    if value[0].isdigit():
        value = "Field_" + value
    return value


def suggest_import(path: str | Path) -> DataConfig:
    source = Path(path)
    if source.suffix.lower() in (".xlsm", ".xlsb"):
        raise CompositionError("Use .xlsx or .xls; macro-enabled/binary workbooks are not supported.")
    from .excel_source import is_excel, workbook_info
    if is_excel(source):
        info = workbook_info(source)
        return DataConfig(path=str(source.resolve()), sheet=info["default_sheet"],
                          excel_formulas="cached" if source.suffix.lower() == ".xls" else "reject")
    with source.open("rb") as stream:
        sample = stream.read(64 * 1024)
    if sample.startswith(codecs.BOM_UTF16_LE) or sample.startswith(codecs.BOM_UTF16_BE):
        encoding = "utf-16"
    elif sample.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
        # Legacy encodings are ambiguous: suggestions remain user-confirmable.
        for candidate in ("utf-8", "big5", "gb18030", "cp1252"):
            try:
                codecs.getincrementaldecoder(candidate)(errors="strict").decode(sample, final=False)
                encoding = candidate
                break
            except UnicodeDecodeError:
                continue
    text = codecs.getincrementaldecoder(encoding)(errors="replace").decode(sample, final=False)
    try:
        delimiter = csv.Sniffer().sniff(text, delimiters=",\t;|").delimiter
    except csv.Error:
        delimiter = "\t" if source.suffix.lower() == ".txt" and "\t" in text else ","
    return DataConfig(str(source.resolve()), encoding, delimiter)


def _fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class RecordStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='import'").fetchone()
        if row is None:
            raise CompositionError("The record snapshot is incomplete.")
        self.metadata = json.loads(row[0])
        self.fields: list[str] = self.metadata["fields"]
        self.count: int = self.metadata["record_count"]

    def record(self, index: int) -> dict[str, str]:
        if not 1 <= index <= self.count:
            raise CompositionError(f"Record {index} is out of range.")
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT value FROM records WHERE ordinal=?", (index,)).fetchone()
        return json.loads(row[0])

    def records(self):
        with closing(sqlite3.connect(self.path)) as connection:
            cursor = connection.execute("SELECT ordinal,value FROM records ORDER BY ordinal")
            for ordinal, value in cursor:
                yield ordinal, json.loads(value)


@contextmanager
def source_rows(config, diagnostics):
    from .excel_source import excel_rows, is_excel
    if type(config.header) is not bool:
        raise CompositionError("Header setting must be true or false.")
    if type(config.header_row) is not int or not 1 <= config.header_row <= 100_000:
        raise CompositionError("Header/start row is out of range.")
    diagnostics.setdefault("warnings", [])
    if Path(config.path).suffix.lower() in (".xlsm", ".xlsb"):
        raise CompositionError("Use .xlsx or .xls; macro-enabled/binary workbooks are not supported.")
    if is_excel(config.path):
        with excel_rows(config, diagnostics) as rows:
            yield rows
    else:
        if len(config.delimiter) != 1 or config.delimiter in "\r\n\0":
            raise CompositionError("Choose a single-character delimiter.")
        codecs.lookup(config.encoding)
        csv.field_size_limit(MAX_RECORD_CHARS)
        with Path(config.path).open("r", encoding=config.encoding, newline="", errors="strict") as stream:
            reader = csv.reader(stream, delimiter=config.delimiter, strict=True)
            for _ in range(config.header_row - 1):
                next(reader, None)
            yield enumerate(reader, config.header_row)


def field_names(first, config):
    if not 1 <= len(first) <= MAX_FIELDS:
        raise CompositionError("Selected header/start row is empty or has too many fields.")
    original = first if config.header else [f"Field_{i+1}" for i in range(len(first))]
    if len(set(original)) != len(original) or any(not name.strip() for name in original):
        raise CompositionError("Header fields must be non-empty and unique.")
    fields = [config.mapping.get(name, normalize_field(name, i+1)) for i, name in enumerate(original)]
    if len(set(fields)) != len(fields) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in fields):
        raise CompositionError("Mapped field names must be unique valid variable names.")
    return original, fields


def sample_records(config):
    diagnostics = {}
    with source_rows(config, diagnostics) as reader:
        first = next(reader, None)
        if first is None:
            raise CompositionError("The source contains no records.")
        # Permit normalization collisions in the sample so aliases can be fixed in the dialog.
        names = first[1] if config.header else [f"Field_{i+1}" for i in range(len(first[1]))]
        if not 1 <= len(names) <= MAX_FIELDS or len(set(names)) != len(names) or any(not v.strip() for v in names):
            raise CompositionError("Selected header/start row needs non-empty, unique field names.")
        from .excel_source import is_excel
        excel = is_excel(config.path)
        sample = [] if config.header else [first[1]]
        for _row, values in reader:
            if not values:
                continue
            if excel:
                if len(values) > len(names):
                    raise CompositionError(f"Worksheet {diagnostics.get('sheet', '')}, row {_row}: values exist outside the selected field columns.")
                values += [""] * (len(names)-len(values))
            sample.append(values)
            if len(sample) == 5:
                break
    if not sample:
        raise CompositionError("The selected worksheet/source contains no data records.")
    return {"originals": names, "fields": [normalize_field(name, i+1) for i, name in enumerate(names)],
            "sample": [[cell[:500] for cell in row] for row in sample],
            "warnings": diagnostics["warnings"]}


def import_records(config: DataConfig, target: str | Path, *, progress: Callable | None = None,
                   is_cancelled: Callable[[], bool] | None = None) -> RecordStore:
    from .excel_source import is_excel
    source = Path(config.path).expanduser().resolve()
    before = _fingerprint(source)
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise CompositionError("The import snapshot already exists.")
    diagnostics = {}
    excel = is_excel(source)
    skipped = 0
    try:
        with closing(sqlite3.connect(destination)) as connection, connection, source_rows(config, diagnostics) as reader:
            connection.execute("CREATE TABLE records(ordinal INTEGER PRIMARY KEY,value TEXT NOT NULL,source_row INTEGER)")
            connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            first = next(reader, None)
            if first is None:
                raise CompositionError("The source contains no records.")
            original, fields = field_names(first[1], config)
            count = 0

            def append(row, values):
                nonlocal count
                if is_cancelled and is_cancelled():
                    raise CompositionError("Data import cancelled.")
                if excel:
                    if len(values) > len(fields):
                        raise CompositionError(f"Worksheet {diagnostics.get('sheet', '')}, row {row}: values exist outside the selected field columns.")
                    values += [""] * (len(fields)-len(values))
                if len(values) != len(fields):
                    raise CompositionError(f"Record {count+1}: expected {len(fields)} fields, got {len(values)}.")
                if sum(map(len, values)) > MAX_RECORD_CHARS:
                    raise CompositionError(f"Record {count+1} is too large.")
                if any("\0" in value for value in values):
                    raise CompositionError(f"Record {count+1} contains a NUL character.")
                count += 1
                connection.execute("INSERT INTO records VALUES(?,?,?)",
                    (count, json.dumps(dict(zip(fields, values, strict=True)), ensure_ascii=False), row))
                if count % 500 == 0:
                    connection.commit()
                    if progress:
                        progress(count, 0, f"Imported {count:,} records")

            if not config.header:
                append(*first)
            for row, values in reader:
                if is_cancelled and is_cancelled():
                    raise CompositionError("Data import cancelled.")
                if not values:
                    skipped += 1
                    continue
                append(row, values)
            if count == 0:
                raise CompositionError("The source contains no data records.")
            after = _fingerprint(source)
            if before != after:
                raise CompositionError("The data source changed during import. Import it again.")
            digest = hashlib.sha256()
            with source.open("rb") as raw:
                for chunk in iter(lambda: raw.read(1024 * 1024), b""):
                    if is_cancelled and is_cancelled():
                        raise CompositionError("Data import cancelled.")
                    digest.update(chunk)
            if _fingerprint(source) != after:
                raise CompositionError("The data source changed during import. Import it again.")
            metadata = {"fields": fields, "original_fields": original, "record_count": count,
                "source": {**after, "sha256": digest.hexdigest(), **({"worksheet":diagnostics["sheet"]} if excel else {})},
                "config": asdict(config), "warnings": diagnostics["warnings"],
                "skipped_blank_rows": skipped, "source_row_mapping": "records.source_row",
                "source_row_kind": "Excel worksheet row" if excel else "delimited logical row"}
            connection.execute("INSERT INTO metadata VALUES('import',?)", (json.dumps(metadata),))
            connection.commit()
    except Exception as exc:
        destination.unlink(missing_ok=True)
        if isinstance(exc, UnicodeDecodeError):
            raise CompositionError(f"Unable to decode source using {config.encoding}; choose another encoding.") from exc
        if isinstance(exc, csv.Error):
            raise CompositionError(f"Invalid delimited record: {exc}") from exc
        raise
    return RecordStore(destination)
