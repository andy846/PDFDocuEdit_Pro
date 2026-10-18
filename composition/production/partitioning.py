"""Read only the logical partition plan already bound into production review."""

import sqlite3
from pathlib import Path

from composition.template.model import CompositionError


def reviewed_groups(context, record_store):
    outputs = context.get("outputs", [])
    if not outputs:
        return None, {}, lambda: None
    db = sqlite3.connect(Path(record_store).resolve().as_uri() + "?mode=ro", uri=True)
    names = {str(item["key"]): item["name"] for item in outputs}

    def group_for(ordinal):
        row = db.execute("SELECT partition_key FROM partitions WHERE ordinal=?", (ordinal,)).fetchone()
        if row is None or str(row[0]) not in names:
            raise CompositionError("Output partition does not match the reviewed record membership.")
        return str(row[0])

    return group_for, names, db.close
