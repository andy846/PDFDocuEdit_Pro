"""Execute typed data steps with disk snapshots, shared by all workflow clients."""
from pathlib import Path

from composition.template.model import CompositionError, SequenceSpec

from .registry import EXTRA_KINDS
from .transforms import assert_valid, snapshot, transform


def prepare_records(spec, records, directory, *, template=None, progress=None, is_cancelled=None):
    root=Path(directory)
    root.mkdir(parents=True,exist_ok=True)
    source=getattr(records,"store",None)
    if source:
        import sqlite3
        from contextlib import closing
        def rows():
            import json
            with closing(sqlite3.connect(source.path)) as db:
                for value, source_id in db.execute("SELECT value,source_row FROM records ORDER BY ordinal"):
                    yield source_id,json.loads(value)
        fields=source.fields
    else:
        def rows():
            yield from records.records()
        fields=[]
    current=snapshot(rows(),fields,root/"data-input.sqlite",metadata={**records.metadata,"source_records":records.count},is_cancelled=is_cancelled)
    for node in spec.chain():
        if node.kind not in EXTRA_KINDS:
            continue
        if node.kind=="media_assignment" and template:
            import copy
            template.media=copy.deepcopy(node.params)
        if node.kind=="running_sequence" and template:
            name=node.params.get("name","Sequence")
            if name in {seq.name for seq in template.sequences}:
                raise CompositionError(f"Sequence field {name} already exists in the template. Preserve or rename it.")
            if node.params.get("scope")=="page":
                if name in current.fields:
                    raise CompositionError(f"Sequence field conflicts with data: {name}")
                template.sequences.append(SequenceSpec(**node.params))
        current=transform(current,root/(node.id+".sqlite"),node.kind,node.params,node_id=node.id,
                          progress=progress,is_cancelled=is_cancelled)
    return current


def summary(source, original_count):
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(source.path)) as db:
        excluded=db.execute("SELECT COUNT(DISTINCT source_id) FROM exclusions").fetchone()[0]
        errors=db.execute("SELECT COUNT(*) FROM findings WHERE severity='error'").fetchone()[0]
        warnings=db.execute("SELECT COUNT(*) FROM findings WHERE severity='warning'").fetchone()[0]
    if original_count!=source.count+excluded:
        raise CompositionError("Data reconciliation failed: input does not equal kept plus excluded.")
    return {"input":original_count,"retained":source.count,"excluded":excluded,"errors":errors,"warnings":warnings,
            "fields":source.fields,"steps":source.metadata.get("steps",[])}


def split_names(source, output_name):
    """Bounded partition index; no complete record set in Python memory."""
    import re
    import sqlite3
    from contextlib import closing

    from composition.production.model import validate_output_name
    options=source.metadata.get("split")
    if not options:
        return []
    with closing(sqlite3.connect(source.path)) as db:
        if options["method"]=="field":
            if options["field"] not in source.fields:
                raise CompositionError("Split field is absent: "+options["field"])
            expression=f"json_extract(value,'$.{options['field']}')"
        else:
            expression=f"CAST((ordinal-1)/{options['count']} AS INTEGER)"
        db.execute("CREATE TABLE IF NOT EXISTS partitions(ordinal INTEGER PRIMARY KEY,partition_key TEXT)")
        db.execute("DELETE FROM partitions")
        db.execute(f"INSERT INTO partitions SELECT ordinal,CAST({expression} AS TEXT) FROM records")
        result=[]
        names=set()
        for key,count in db.execute("SELECT partition_key,COUNT(*) FROM partitions GROUP BY partition_key ORDER BY MIN(ordinal)"):
            if len(result)>=10000:
                raise CompositionError("Split output supports at most 10,000 files per job.")
            label=str(int(key)+1).zfill(4) if options["method"]=="count" else (
                re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",key or "empty").strip(" .") or "empty")
            name=Path(output_name).stem+"-"+label+".pdf"
            validate_output_name(name)
            if name.casefold() in names:
                raise CompositionError("Split filename collision after sanitization: "+name)
            names.add(name.casefold())
            result.append({"key":key,"name":name,"records":count})
        db.commit()
    return result


def validate_result(source):
    assert_valid(source)
