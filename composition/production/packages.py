"""Bounded, whole-envelope packages assembled directly from rendered chunks.

The disk index is private to a single authorized production attempt. Only the
completed set is published by the caller's existing journal transaction.
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.pdf_backend import fitz
from core.pdf_io import validate_pdf_file
from core.variables import VariableContext

from .output_naming import NamingSpec, part_filename
from .output_policy import MAX_PART_PAGES, MAX_PARTS, OutputPartTooLarge


def discard_packages(staging):
    """Remove only owned unpublished package directories; never follow links."""
    root = Path(staging).resolve()
    for path in root.glob(".piece-*"):
        if path.is_symlink() or path.resolve().parent != root:
            raise CompositionError("Unsafe package cleanup path.")
        shutil.rmtree(path)
    for path in root.glob("part[0-9][0-9][0-9][0-9][0-9][0-9]"):
        if path.is_symlink() or path.resolve().parent != root:
            raise CompositionError("Unsafe package cleanup path.")
        shutil.rmtree(path)


def build_packages(
    staging,
    final,
    chunks,
    plan,
    policy,
    original,
    context,
    *,
    executable,
    marks_path=None,
    media=None,
    progress=None,
    is_cancelled=None,
    group_for=None,
    group_names=None,
    checker=None,
):
    from composition.engine.inserter_production import audit_pdf
    from composition.media.postscript import export_postscript
    from composition.media.ticket import export_rows

    from .generator import _assemble, _csv_value, check_cancel

    staging, final = Path(staging), Path(final)
    naming = NamingSpec.from_dict(policy.naming)
    context = context if isinstance(context, VariableContext) else VariableContext(**context)
    accepted, peak, decoded = [], 0, 0
    index_path = staging / "package-index.sqlite"
    with closing(sqlite3.connect(index_path)) as db:
        db.executescript("""CREATE TABLE pages(global_page INTEGER PRIMARY KEY, envelope INTEGER, data TEXT);
            CREATE INDEX page_envelope ON pages(envelope,global_page);
            CREATE TABLE envelopes(ordinal INTEGER PRIMARY KEY, group_key TEXT, pages INTEGER, sheets INTEGER);
            CREATE INDEX envelope_group ON envelopes(group_key,ordinal);
            CREATE TABLE marks(global_page INTEGER,data TEXT);
            CREATE INDEX mark_page ON marks(global_page);""")
        for ordinal in range(1, plan.envelopes + 1):
            check_cancel(is_cancelled)
            settings = plan.settings_for(ordinal)
            db.execute(
                "INSERT INTO envelopes VALUES(?,?,?,?)",
                (
                    ordinal,
                    str(group_for(ordinal) if group_for else ""),
                    settings.output_pages_per_envelope,
                    settings.sheets_per_envelope,
                ),
            )
        for page in plan.pages():
            check_cancel(is_cancelled)
            fields = page.fields()
            row = [
                page.output_page,
                page.output_page,
                page.envelope,
                page.source_page or "",
                fields["LetterPage"],
                fields["PageRole"],
                fields["SheetNo"],
                fields["Side"],
                getattr(page, "stock", ""),
                getattr(page, "reason", ""),
            ]
            db.execute("INSERT INTO pages VALUES(?,?,?)", (page.output_page, page.envelope, json.dumps(row)))
        if marks_path and Path(marks_path).exists():
            with Path(marks_path).open(encoding="utf-8") as stream:
                for line in stream:
                    check_cancel(is_cancelled)
                    mark = json.loads(line)
                    db.execute("INSERT INTO marks VALUES(?,?)", (mark["output_page"], line))
        db.commit()
        chunk_ranges, start = [], 1
        for path in chunks:
            with fitz.open(path) as document:
                count = document.page_count
            chunk_ranges.append((path, start, start + count - 1))
            start += count
        if start - 1 != plan.output_pages:
            raise CompositionError("Package reconciliation: rendered chunk page count differs.")

        def attempt(envelopes, key):
            nonlocal peak, decoded
            check_cancel(is_cancelled)
            if len(accepted) >= MAX_PARTS:
                raise CompositionError("Output exceeds the system maximum number of parts.")
            directory = staging / f".piece-{len(accepted):06}"
            directory.mkdir()
            rows, sheets = [], 0
            for ordinal in envelopes:
                sheets += plan.settings_for(ordinal).sheets_per_envelope
                rows.extend(
                    json.loads(raw)
                    for (raw,) in db.execute(
                        "SELECT data FROM pages WHERE envelope=? ORDER BY global_page", (ordinal,)
                    )
                )
            mapping = {row[1]: i for i, row in enumerate(rows, 1)}
            selections = []
            for path, first, last in chunk_ranges:
                numbers = [page - first + 1 for page in mapping if first <= page <= last]
                if numbers:
                    # Compress adjacent pages, keeping the chunk argument file bounded.
                    ranges = []
                    a = b = numbers[0]
                    for number in numbers[1:]:
                        if number == b + 1:
                            b = number
                        else:
                            ranges.append(str(a) if a == b else f"{a}-{b}")
                            a = b = number
                    ranges.append(str(a) if a == b else f"{a}-{b}")
                    selections.append((path, ",".join(ranges)))
            pdf = directory / "production.pdf"
            try:
                from .output_policy import check_scratch_space

                estimated = sum(
                    int(
                        Path(path).stat().st_size
                        * sum(first <= page <= last for page in mapping)
                        / (last - first + 1)
                    )
                    for path, first, last in chunk_ranges
                )
                check_scratch_space(
                    directory,
                    estimated,
                    postscript=bool(
                        media
                        and media.get("enabled")
                        and media.get("printer_profile", {}).get("backend") == "postscript"
                    ),
                    ps_limit=policy.ps_bytes,
                )
                if progress:
                    progress(0, 0, f"Assembling part {len(accepted) + 1:,}: {len(envelopes):,} envelopes")
                peak = max(
                    peak,
                    _assemble(
                        chunks,
                        pdf,
                        executable,
                        is_cancelled,
                        selections=selections,
                        size_limit=policy.pdf_bytes,
                    ),
                )
                policy.check_size(pdf, "PDF")
                validate_pdf_file(pdf, expected_page_count=len(rows))
                media_summary = {}
                if media and media.get("enabled"):

                    def local_rows():
                        for i, row in enumerate(rows, 1):
                            yield [i, *row[1:]]

                    media_summary = export_rows(
                        directory, media, local_rows(), len(rows), pdf.name, is_cancelled=is_cancelled
                    )
                    media_summary.update(
                        export_postscript(
                            directory,
                            media,
                            pdf.name,
                            is_cancelled=is_cancelled,
                            progress=progress,
                            output_policy=policy,
                        )
                    )
                    if media_summary.get("postscript"):
                        policy.check_size(directory / media_summary["postscript"], "PS")
                local_marks = directory / "part-marks.jsonl"
                expected = 0
                with local_marks.open("w", encoding="utf-8") as stream:
                    for global_page, local_page in mapping.items():
                        for (raw,) in db.execute(
                            "SELECT data FROM marks WHERE global_page=?", (global_page,)
                        ):
                            mark = json.loads(raw)
                            mark.update(global_output_page=global_page, output_page=local_page)
                            mark.setdefault("sheet", "")
                            mark.setdefault("profile", "")
                            stream.write(json.dumps(mark, ensure_ascii=False) + "\n")
                            expected += 1

                def qc_progress(done, total, message):
                    if progress:
                        progress(done, total, "Barcode QC: " + message if checker else message)

                checked = audit_pdf(
                    pdf,
                    local_marks,
                    directory / "barcodes.csv",
                    is_cancelled=is_cancelled,
                    progress=qc_progress,
                    expected=expected,
                    checker=checker,
                )
                decoded += checked
                with (directory / "source-map.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(
                        [
                            "File page",
                            "Global output page",
                            "Envelope",
                            "Source page",
                            "Logical page",
                            "Sheet in envelope",
                            "Side",
                            "Stock",
                        ]
                    )
                    writer.writerows(
                        (i, row[1], row[2], row[3], row[4], row[6], row[7], row[8])
                        for i, row in enumerate(rows, 1)
                    )
                source_runs = []
                for local, row in enumerate(rows, 1):
                    source = row[3] if isinstance(row[3], int) else None
                    if source_runs and (
                        (source is None and source_runs[-1][2] is None)
                        or (
                            source is not None
                            and source_runs[-1][2] is not None
                            and source == source_runs[-1][2] + local - source_runs[-1][0]
                        )
                    ):
                        source_runs[-1][1] = local
                    else:
                        source_runs.append([local, local, source])
                global_ranges = []
                for number in mapping:
                    if global_ranges and number == global_ranges[-1][1] + 1:
                        global_ranges[-1][1] = number
                    else:
                        global_ranges.append([number, number])
                with (staging / "parts-progress.jsonl").open("a", encoding="utf-8") as checkpoint:
                    checkpoint.write(
                        json.dumps(
                            dict(
                                candidate=directory.name,
                                first=envelopes[0],
                                last=envelopes[-1],
                                envelopes=len(envelopes),
                                pages=len(rows),
                                sheets=sheets,
                                pdf_sha256=file_hash(pdf),
                                status="validated_unpublished",
                            )
                        )
                        + "\n"
                    )
                accepted.append(
                    dict(
                        source_page_runs=source_runs,
                        global_page_ranges=global_ranges,
                        directory=directory,
                        records=len(envelopes),
                        pages=len(rows),
                        sheets=sheets,
                        first=envelopes[0],
                        last=envelopes[-1],
                        key=key,
                        media_summary=media_summary,
                        membership=envelopes.copy(),
                    )
                )
            except (OutputPartTooLarge, CompositionError) as exc:
                retriable = isinstance(exc, OutputPartTooLarge) or "ticket exceeds" in str(exc)
                if not retriable:
                    raise
                shutil.rmtree(directory)
                if len(envelopes) == 1:
                    raise CompositionError(f"Envelope {envelopes[0]} exceeds a package limit: {exc}") from exc
                middle = len(envelopes) // 2
                attempt(envelopes[:middle], key)
                attempt(envelopes[middle:], key)

        for (key,) in db.execute(
            "SELECT group_key FROM envelopes GROUP BY group_key ORDER BY MIN(ordinal)"
        ).fetchall():
            pending = []
            pages = 0
            for ordinal, count in db.execute(
                "SELECT ordinal,pages FROM envelopes WHERE group_key=? ORDER BY ordinal", (key,)
            ):
                if count > MAX_PART_PAGES:
                    raise CompositionError(f"Envelope {ordinal} exceeds the system page limit.")
                if pending and (
                    (policy.envelopes and len(pending) >= policy.envelopes) or pages + count > MAX_PART_PAGES
                ):
                    attempt(pending, key)
                    pending = []
                    pages = 0
                pending.append(ordinal)
                pages += count
            if pending:
                attempt(pending, key)
        if (
            sum(p["records"] for p in accepted) != plan.envelopes
            or sum(p["pages"] for p in accepted) != plan.output_pages
            or sum(p["sheets"] for p in accepted) != plan.sheets
        ):
            raise CompositionError("Package reconciliation: envelope/page/sheet totals differ.")
        names = []
        for i, item in enumerate(accepted, 1):
            fallback = (group_names or {}).get(item["key"], original)
            naming_total = (
                1
                if group_names
                and naming.mode == "original"
                and sum(p["key"] == item["key"] for p in accepted) == 1
                else len(accepted)
            )
            name = part_filename(
                naming,
                context,
                fallback,
                index=1 if naming_total == 1 else i,
                total=naming_total,
                sheets=item["sheets"],
                envelopes=item["records"],
                pages=item["pages"],
                duplex=plan.settings.duplex,
                first=item["first"],
                last=item["last"],
                group=item["key"] or None,
            )
            destination = final / name if len(accepted) == 1 else final / f"part{i:06}" / name
            if len(str(destination).encode("utf-16-le")) // 2 > 240:
                raise CompositionError("Output path is too long; choose a shorter output folder or filename.")
            names.append(name)
        # Validate names together on Windows rules, including case-folded collisions.
        if len(set(name.casefold() for name in names)) != len(names):
            raise CompositionError("Duplicate package filenames.")
        output = []
        with (
            (staging / "package-barcodes.csv").open("w", encoding="utf-8-sig", newline="") as audit,
            (staging / "barcodes.jsonl").open("w", encoding="utf-8") as raw_audit,
        ):
            writer = csv.writer(audit)
            header = False
            for i, (item, name) in enumerate(zip(accepted, names, strict=True), 1):
                check_cancel(is_cancelled)
                directory = item.pop("directory")
                target = staging if len(accepted) == 1 else staging / f"part{i:06}"
                if target != staging:
                    directory.rename(target)
                else:
                    for path in directory.iterdir():
                        path.replace(staging / path.name)
                    directory.rmdir()
                (target / "production.pdf").rename(target / name)
                old_ps = target / "production.ps"
                if old_ps.exists():
                    old_ps.rename(target / Path(name).with_suffix(".ps"))
                for file in ("media-summary.json", "postscript-report.json", "SUBMISSION.txt"):
                    path = target / file
                    if path.exists():
                        path.write_text(
                            path.read_text(encoding="utf-8")
                            .replace("production.pdf", name)
                            .replace("production.ps", Path(name).with_suffix(".ps").name),
                            encoding="utf-8",
                        )
                local_marks = target / "part-marks.jsonl"
                marks = {}
                with local_marks.open(encoding="utf-8") as stream:
                    for line in stream:
                        mark = json.loads(line)
                        marks[mark["output_page"]] = mark["global_output_page"]
                        raw_audit.write(
                            json.dumps(
                                {
                                    **mark,
                                    "file_page": mark["output_page"],
                                    "output_page": mark["global_output_page"],
                                    "qc": "decoded_exact",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                # Read before replacing root audit in the single-part legacy layout.
                with (target / "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.reader(stream)
                    columns = next(reader)
                    if not header:
                        writer.writerow(columns)
                        header = True
                    for row in reader:
                        row[2] = marks[int(row[2])]
                        writer.writerow(row)
                local_marks.unlink()
                relative = (target / name).relative_to(staging)
                ps = relative.with_suffix(".ps")
                entry = {
                    **item,
                    "part": i,
                    "output_pdf": str(final / relative),
                    "output_sha256": file_hash(target / name),
                    "output_size": policy.check_size(target / name, "PDF"),
                    "output_ps": str(final / ps) if (staging / ps).exists() else "",
                }
                if entry["output_ps"]:
                    entry.update(
                        postscript_sha256=file_hash(staging / ps),
                        postscript_size=policy.check_size(staging / ps, "PS"),
                    )
                entry["printing"] = "D" if plan.settings.duplex else "S"
                if entry["media_summary"]:
                    entry["media_summary"]["pdf"] = name
                if entry["output_ps"]:
                    entry["media_summary"]["postscript"] = Path(entry["output_ps"]).name
                (target / "job.json").write_text(
                    json.dumps(
                        {
                            "job_id": context.namespaces.get("job", {}).get("id", ""),
                            "status": "validated_unpublished",
                            "policy": policy.to_dict(),
                            **entry,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                with (target / "control.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                    control = csv.writer(stream)
                    control.writerow(
                        [
                            "Part",
                            "PDF",
                            "PS",
                            "Envelopes",
                            "Physical sheets",
                            "Pages",
                            "Printing",
                            "PDF bytes",
                            "PS bytes",
                        ]
                    )
                    control.writerow(
                        [
                            _csv_value(value)
                            for value in [
                                i,
                                name,
                                Path(entry["output_ps"]).name if entry["output_ps"] else "",
                                entry["records"],
                                entry["sheets"],
                                entry["pages"],
                                entry["printing"],
                                entry["output_size"],
                                entry.get("postscript_size", ""),
                            ]
                        ]
                    )
                output.append(entry)
        if len(output) > 1 and media and media.get("enabled"):
            summary_path = staging / "media-summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary.update(pdf="", ticket="", parts=len(output), manifest="outputs-manifest.json")
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            (staging / "SUBMISSION.txt").write_text(
                "MULTI-PART PRINT PACKAGE\nSubmit the matched PDF / JDF or PS inside each numbered part folder, in numeric order. Consult outputs.csv for sheets, envelopes and D/S. Each part has its own checked paper programming. No combined production file is provided. Device validation remains pending.\n",
                encoding="utf-8",
            )
        (staging / "package-barcodes.csv").replace(staging / "barcodes.csv")
        for path in chunks:
            path.unlink()
        manifest = {
            "version": 1,
            "policy": policy.to_dict(),
            "parts": output,
            "envelopes": plan.envelopes,
            "pages": plan.output_pages,
            "sheets": plan.sheets,
        }
        (staging / "outputs-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (staging / "outputs.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Part", "PDF", "PS", "Envelopes", "Physical sheets", "Pages", "Printing"])
            writer.writerows(
                [
                    _csv_value(value)
                    for value in [
                        p["part"],
                        Path(p["output_pdf"]).name,
                        Path(p["output_ps"]).name if p["output_ps"] else "",
                        p["records"],
                        p["sheets"],
                        p["pages"],
                        "D" if plan.settings.duplex else "S",
                    ]
                ]
                for p in output
            )
    index_path.unlink()
    return output, decoded, peak
