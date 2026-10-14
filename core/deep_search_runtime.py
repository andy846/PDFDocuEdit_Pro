"""Headless live search: owned SQLite writer and cooperative pause checkpoints."""
from __future__ import annotations

from collections import deque
from threading import Condition

from core.deep_search import search_folder_detailed
from core.search_results_store import SearchResultsStore


class SearchRuntime:
    def __init__(self, path):
        self.path = path
        self.condition = Condition()
        self.pause_requested = self.paused = self.cancelled = False
        self.finished = False
        self.updates = deque()
        self.progress = (0, 0, "")
        self.revision = 0
        self.counts = (0, 0, 0)

    def pause(self):
        with self.condition:
            self.pause_requested = True

    def resume(self):
        with self.condition:
            self.pause_requested = False
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.cancelled = True
            self.pause_requested = False
            self.condition.notify_all()

    def checkpoint(self):
        with self.condition:
            while self.pause_requested and not self.cancelled:
                self.paused = True
                self.condition.notify_all()
                self.condition.wait()
            self.paused = False
            return self.cancelled

    def take_updates(self, limit=30):
        with self.condition:
            updates = [self.updates.popleft() for _ in range(min(limit, len(self.updates)))]
            return updates, self.progress, self.revision, self.paused, self.pause_requested

    def pending(self):
        with self.condition:
            return bool(self.updates)

    def run(self, folder, query, subfolders, barcodes):
        store = SearchResultsStore.open_writer(self.path)
        first_context = ""

        def batch(value):
            nonlocal first_context
            store.add(value)
            if value.hits and not first_context:
                first_context = value.hits[0].context
            with self.condition:
                self.revision += 1
                if value.file or value.issue:
                    self.updates.append((value, first_context))
                    first_context = ""

        def progress(current, total, message):
            with self.condition:
                self.progress = (current, total, message)

        try:
            return search_folder_detailed(folder, query, subfolders, barcodes,
                                          on_batch=batch, progress=progress,
                                          is_cancelled=self.checkpoint)
        finally:
            try:
                store.remove_incomplete_files()
                self.counts = store.counts()
            finally:
                store.close()
                with self.condition:
                    self.finished = True


def read_search_query(path, request):
    """Each query gets its own read snapshot; SQL never runs in a Qt model."""
    store = SearchResultsStore.open_reader(path)
    try:
        kind = request["kind"]
        paths, keyword, source = request["paths"], request["keyword"], request["source"]
        if kind == "preview":
            return {**request, "rows": store.hit_page(0, 20, paths), "counts": store.counts(paths)}
        cutoff = request.get("cutoff")
        if kind == "header":
            cutoff = int(store.db.execute("SELECT COALESCE(MAX(id),0) FROM hits").fetchone()[0])
        rows = store.hit_page(request.get("offset", 0), 200, paths, keyword, source,
                              request["order"], cutoff=cutoff)
        result = {**request, "rows": rows, "cutoff": cutoff}
        if kind == "header":
            result["total"] = store.hit_count(paths, keyword, source, cutoff=cutoff)
            selected = request.get("selected")
            reference = request.get("selected_ref")
            if selected is None and reference is not None:
                old = store.hit_page(reference["offset"], 1, reference["paths"], reference["keyword"],
                                     reference["source"], reference["order"], cutoff=reference["cutoff"])
                selected = old[0] if old else None
            result["selected"] = selected
            result["selected_row"] = None
            if selected is not None:
                where, args = store._where(paths, keyword, source, cutoff)
                row = store.db.execute(
                    "SELECT n FROM (SELECT path,page,keyword,source,position,"
                    f"ROW_NUMBER() OVER (ORDER BY {request['order']})-1 AS n FROM hits{where}) "
                    "WHERE path=? AND page=? AND keyword=? AND source=? AND position=? LIMIT 1",
                    (*args, selected.path, selected.page, selected.keyword, selected.source, selected.position),
                ).fetchone()
                result["selected_row"] = row[0] if row else None
        return result
    finally:
        store.close()
