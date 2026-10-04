"""Streaming, auditable data steps shared by preview and production.

SQLite owns ordering and uniqueness indexes. Values always remain strings;
production ordinals are separate from immutable source record identities.
"""
from __future__ import annotations

import copy
import csv
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from composition.data.source import RecordStore
from composition.engine.rules import CompiledGroup, decimal_value
from composition.production.generator import check_cancel
from composition.template.model import CompositionError, ConditionGroup, RuleCondition
from core.io_atomic import atomic_output

FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def _sample(values):
    # Preview evidence is bounded independently of record and field counts.
    return {key:(value[:256]+"…" if len(value)>256 else value) for key,value in list(values.items())[:12]}


def _field(name):
    if not isinstance(name, str) or not FIELD.fullmatch(name):
        raise CompositionError("Choose a field name of 1–64 letters, digits or underscores.")
    return name


def condition(options):
    try:
        return CompiledGroup(ConditionGroup(mode=options.get("mode", "all"),
            conditions=[RuleCondition(**c) for c in options.get("conditions", [])]))
    except (TypeError, KeyError) as exc:
        raise CompositionError("Invalid filter conditions.") from exc


def validate_options(kind, options):
    if not isinstance(options, dict):
        raise CompositionError("Step settings must be an object.")
    if kind=="media_assignment":
        from composition.media.model import MediaSpec
        MediaSpec.from_dict(options)
        return
    key = {"clean_fields":"operations", "create_fields":"fields", "sort_records":"keys",
           "validate_data":"checks"}.get(kind)
    if key:
        items = options.get(key, [])
        if not isinstance(items, list) or not 1 <= len(items) <= 100 or any(not isinstance(x, dict) for x in items):
            raise CompositionError(f"Configure 1–100 {key}.")
        for item in items:
            _field(item.get("field"))
    if kind == "filter_records":
        condition(options)
    elif kind == "clean_fields":
        for item in items:
            if item.get("operation") not in ("trim", "join_lines", "remove_prefix", "upper", "lower", "replace"):
                raise CompositionError("Unsupported cleaning operation.")
            for name in ("value", "replacement"):
                if not isinstance(item.get(name, ""), str) or len(item.get(name, "")) > 10000:
                    raise CompositionError("Cleaning values must be bounded literal text.")
            if item["operation"] == "replace" and not item.get("value"):
                raise CompositionError("Literal replacement needs nonempty search text.")
    elif kind == "create_fields":
        for item in items:
            if item.get("operation") not in ("constant", "concat", "pad", "first", "last"):
                raise CompositionError("Unsupported field creation operation.")
            if type(item.get("overwrite", False)) is not bool:
                raise CompositionError("Overwrite must be explicitly true or false.")
            if item["operation"] != "constant":
                sources = item.get("sources", [])
                if not isinstance(sources, list) or not 1 <= len(sources) <= 100:
                    raise CompositionError("Choose source fields.")
                for name in sources:
                    _field(name)
            if item["operation"] in ("pad", "first", "last"):
                if type(item.get("length")) is not int or not 1 <= item["length"] <= 10000:
                    raise CompositionError("Field length must be 1–10,000.")
            for name in ("value", "separator"):
                if not isinstance(item.get(name, ""), str) or len(item.get(name, "")) > 10000:
                    raise CompositionError("Field values must be bounded literal text.")
    elif kind == "sort_records":
        for item in items:
            if item.get("type", "text") not in ("text", "number") or type(item.get("descending", False)) is not bool:
                raise CompositionError("Sort keys need a text/number type and an ascending/descending direction.")
    elif kind == "validate_data":
        for item in items:
            if item.get("check") not in ("required", "length", "number", "unique"):
                raise CompositionError("Unsupported data check.")
            if item.get("severity", "error") not in ("error", "warning"):
                raise CompositionError("Validation severity must be error or warning.")
            if item["check"] == "length":
                lo, hi = item.get("min", 0), item.get("max", 10000)
                if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 1000000:
                    raise CompositionError("Invalid validation length range.")
    elif kind == "running_sequence":
        from composition.data.sequences import validate_sequences
        from composition.template.model import SequenceSpec, Template
        try:
            seq = SequenceSpec(**{k:v for k,v in options.items() if k != "scope"},
                               scope="page" if options.get("scope") == "page" else "record")
            if options.get("scope", "record") not in ("record", "mailpiece", "page"):
                raise CompositionError("Choose record, mailpiece or output-page scope.")
            validate_sequences(Template(sequences=[seq]))
        except TypeError as exc:
            raise CompositionError("Invalid running sequence settings.") from exc
    elif kind == "split_output":
        if options.get("method", "count") == "field":
            _field(options.get("field"))
        elif options.get("method", "count") == "count":
            if type(options.get("count")) is not int or not 1 <= options["count"] <= 1000000:
                raise CompositionError("Records/envelopes per file must be 1–1,000,000.")
        else:
            raise CompositionError("Split by field or whole-record/envelope count.")


class DataSet(RecordStore):
    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            for ordinal, value, source_id in db.execute(
                    "SELECT ordinal,value,source_row FROM records ORDER BY ordinal"):
                yield ordinal, json.loads(value), source_id

    def source_id(self, ordinal):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT source_row FROM records WHERE ordinal=?", (ordinal,)).fetchone()[0]


def snapshot(rows, fields, target, *, metadata=None, is_cancelled=None):
    """Rows are (stable source identity, dict of text values)."""
    with atomic_output(target) as temp, closing(sqlite3.connect(temp)) as db:
        _schema(db)
        count = 0
        for source_id, values in rows:
            check_cancel(is_cancelled)
            if type(source_id) is not int or source_id<1:
                raise CompositionError("Source record identities must be positive integers.")
            count += 1
            if any(not isinstance(v, str) for v in values.values()):
                raise CompositionError("Data values must be text.")
            db.execute("INSERT INTO records VALUES(?,?,?)", (count, json.dumps(values, ensure_ascii=False), source_id))
        info = dict(metadata or {})
        info.update(fields=list(fields), record_count=count)
        db.execute("INSERT INTO metadata VALUES('import',?)", (json.dumps(info),))
        db.commit()
    return DataSet(target)


def _schema(db):
    db.executescript("""
        PRAGMA cache_size=-4096;
        PRAGMA temp_store=FILE;
        CREATE TABLE records(ordinal INTEGER PRIMARY KEY,value TEXT NOT NULL,source_row INTEGER NOT NULL);
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE exclusions(source_id INTEGER,node_id TEXT,reason TEXT);
        CREATE TABLE findings(source_id INTEGER,field TEXT,severity TEXT,reason TEXT);
        CREATE TABLE originals(source_id INTEGER PRIMARY KEY,value TEXT NOT NULL);
    """)


def transform(source, target, kind, options, *, node_id="", progress=None, is_cancelled=None):
    validate_options(kind, options)
    source = source if isinstance(source, RecordStore) else DataSet(source)
    fields = list(source.fields)
    requested = [x["field"] for x in options.get({"clean_fields":"operations", "sort_records":"keys",
                                                 "validate_data":"checks"}.get(kind, "unused"), [])]
    if kind == "filter_records":
        requested += [x["field"] for x in options["conditions"]]
    if kind == "create_fields":
        for item in options["fields"]:
            missing_sources=set(item.get("sources",[]))-set(fields)
            if missing_sources:
                raise CompositionError("Missing source fields: "+", ".join(sorted(missing_sources)))
            requested += item.get("sources", [])
            if item["field"] in fields and not item.get("overwrite", False):
                raise CompositionError(f"Field {item['field']} already exists. Enable overwrite explicitly.")
            if item["field"] not in fields:
                fields.append(item["field"])
    missing = set(requested) - set(fields)
    if missing:
        raise CompositionError("Missing fields: " + ", ".join(sorted(missing)))
    if kind == "running_sequence":
        name = options.get("name", "Sequence")
        if name in fields:
            raise CompositionError(f"Sequence field conflicts with supplied data: {name}")
        if options.get("scope")!="page":
            fields.append(name)
    matcher = condition(options) if kind == "filter_records" else None
    summary = {"node_id":node_id, "kind":kind, "input":source.count, "retained":0, "excluded":0,
               "issues":0, "errors":0, "samples":[]}
    with atomic_output(target) as temp, closing(sqlite3.connect(temp)) as db:
        _schema(db)
        db.execute("CREATE TABLE seen(field TEXT,value TEXT,source_id INTEGER,PRIMARY KEY(field,value))")
        # Copy audit trails without materialising them in Python.
        db.execute("ATTACH DATABASE ? AS previous", (str(source.path),))
        old_tables={r[0] for r in db.execute("SELECT name FROM previous.sqlite_master WHERE type='table'")}
        for table in ("exclusions", "findings", "originals"):
            if table in old_tables:
                db.execute(f"INSERT INTO {table} SELECT * FROM previous.{table}")
        prior_findings=db.execute("SELECT COUNT(*),COALESCE(SUM(severity='error'),0) FROM findings").fetchone()
        cursor=db.execute("SELECT ordinal,value,source_row FROM previous.records ORDER BY ordinal")
        for ordinal, raw, source_id in cursor:
            check_cancel(is_cancelled)
            before=json.loads(raw)
            values=dict(before)
            keep=True
            reason=""
            if kind == "clean_fields":
                for item in options["operations"]:
                    name, op=item["field"],item["operation"]
                    text=values[name]
                    literal=item.get("value", "")
                    values[name] = (text.strip() if op=="trim" else " ".join(text.splitlines()) if op=="join_lines"
                        else text.removeprefix(literal) if op=="remove_prefix" else text.upper() if op=="upper"
                        else text.lower() if op=="lower" else text.replace(literal,item.get("replacement", "")))
            elif kind == "create_fields":
                for item in options["fields"]:
                    op=item["operation"]
                    text=item.get("separator", "").join(values[name] for name in item.get("sources", []))
                    values[item["field"]] = (item.get("value", "") if op=="constant" else text if op=="concat"
                        else text.zfill(item["length"]) if op=="pad" else text[:item["length"]] if op=="first"
                        else text[-item["length"]:])
            elif kind == "filter_records":
                try:
                    keep=matcher.matches(values)
                except CompositionError as exc:
                    raise CompositionError(f"Source record {source_id}: {exc}") from exc
                if not keep:
                    reason="Did not match " + options.get("mode", "all") + " filter conditions"
            elif kind == "sort_records":
                for item in options["keys"]:
                    if item.get("type") == "number" and values[item["field"]].strip():
                        try:
                            decimal_value(values[item["field"]], item["field"])
                        except CompositionError as exc:
                            raise CompositionError(f"Source record {source_id}: {exc}") from exc
            elif kind == "validate_data":
                for item in options["checks"]:
                    name, test=item["field"],item["check"]
                    text=values[name]
                    problem=""
                    if test=="required" and not text.strip():
                        problem="Required value is empty"
                    elif test=="length" and not item.get("min",0)<=len(text)<=item.get("max",10000):
                        problem="Value is outside the permitted length"
                    elif test=="number":
                        try:
                            decimal_value(text,name)
                        except CompositionError:
                            problem="Expected a finite decimal number"
                    elif test=="unique":
                        first=db.execute("SELECT source_id FROM seen WHERE field=? AND value=?",(name,text)).fetchone()
                        if first:
                            problem=f"Duplicate identifier; first appears at source record {first[0]}"
                            # Report the first occurrence as well, never delete either record.
                            db.execute("INSERT INTO findings VALUES(?,?,?,?)",(first[0],name,item.get("severity","error"),
                                f"Duplicate identifier; also appears at source record {source_id}"))
                        else:
                            db.execute("INSERT INTO seen VALUES(?,?,?)",(name,text,source_id))
                    if problem:
                        severity=item.get("severity","error")
                        db.execute("INSERT INTO findings VALUES(?,?,?,?)",(source_id,name,severity,problem))
                        summary["issues"]+=1
                        summary["errors"]+=severity=="error"
            elif kind == "running_sequence":
                # Page scope is bound by the renderer, never flattened into record data.
                if options.get("scope", "record") != "page":
                    number=options.get("start",1)+(ordinal-1)*options.get("step",1)
                    values[options.get("name","Sequence")]=options.get("prefix","") + (
                        "-" if number<0 else "") + str(abs(number)).zfill(options.get("padding",0))+options.get("suffix","")
            if not keep:
                db.execute("INSERT INTO exclusions VALUES(?,?,?)",(source_id,node_id,reason))
                summary["excluded"]+=1
            else:
                summary["retained"]+=1
                db.execute("INSERT INTO records VALUES(?,?,?)",(summary["retained"],json.dumps(values,ensure_ascii=False),source_id))
            db.execute("INSERT OR IGNORE INTO originals VALUES(?,?)",(source_id,raw))
            if len(summary["samples"]) < 8:
                summary["samples"].append({"source_id":source_id,"before":_sample(before),"after":_sample(values),"retained":keep,"reason":reason})
            if ordinal%250==0 and progress:
                progress(ordinal,source.count,kind.replace("_"," "))
        if kind=="sort_records":
            db.create_collation("DECIMAL_TEXT", lambda a,b: (decimal_value(a,"sort")>decimal_value(b,"sort")) -
                                (decimal_value(a,"sort")<decimal_value(b,"sort")))
            clauses=[]
            for item in options["keys"]:
                key=f"json_extract(value, '$.{item['field']}')"
                clauses.extend([f"CASE WHEN trim({key})='' THEN 1 ELSE 0 END ASC",
                    f"NULLIF(trim({key}),'') COLLATE " + ("DECIMAL_TEXT" if item.get("type")=="number" else "BINARY") +
                    (" DESC" if item.get("descending",False) else " ASC")])
            clauses.append("ordinal ASC")
            if is_cancelled:
                db.set_progress_handler(lambda:1 if is_cancelled() else 0,1000)
            try:
                db.execute("CREATE TABLE sorted AS SELECT value,source_row FROM records ORDER BY "+",".join(clauses))
            except sqlite3.OperationalError:
                check_cancel(is_cancelled)
                raise
            finally:
                db.set_progress_handler(None,0)
            db.execute("DELETE FROM records")
            db.execute("INSERT INTO records SELECT rowid,value,source_row FROM sorted ORDER BY rowid")
            db.execute("DROP TABLE sorted")
            summary["samples"]=[{"source_id":r[2],"before":_sample(json.loads(r[1])),"after":_sample(json.loads(r[1])),"output_ordinal":r[0],"retained":True}
                for r in db.execute("SELECT ordinal,value,source_row FROM records ORDER BY ordinal LIMIT 8")]
        findings=db.execute("SELECT COUNT(*),COALESCE(SUM(severity='error'),0) FROM findings").fetchone()
        summary["issues"]=findings[0]-prior_findings[0]
        summary["errors"]=findings[1]-prior_findings[1]
        info=copy.deepcopy(source.metadata)
        info.update(fields=fields,record_count=summary["retained"])
        info.setdefault("steps",[]).append(summary)
        if kind=="split_output":
            info["split"]=options
        if kind=="media_assignment":
            info["media"]=options
        db.execute("INSERT INTO metadata VALUES('import',?)",(json.dumps(info,ensure_ascii=False),))
        db.commit()
    return DataSet(target)


def assert_valid(source):
    with closing(sqlite3.connect(source.path)) as db:
        if "findings" not in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            return
        row=db.execute("SELECT source_id,field,reason FROM findings WHERE severity='error' LIMIT 1").fetchone()
        if row:
            raise CompositionError(f"Source record {row[0]}, field {row[1]}: {row[2]}. Review validation findings.")


def export_audit(source, directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(source.path)) as db:
        for table, headers in (("exclusions",("Source record","Node","Reason")),
                               ("findings",("Source record","Field","Severity","Reason")),
                               ("records",("Production record","Values","Source record"))):
            with atomic_output(directory/(table+".csv")) as temp, temp.open("w",encoding="utf-8-sig",newline="") as stream:
                writer=csv.writer(stream)
                writer.writerow(headers)
                for row in db.execute("SELECT * FROM "+table):
                    writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in row])
