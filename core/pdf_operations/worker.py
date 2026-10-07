"""Isolated worker using the established JSON event / cancellation protocol."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import PdfCancelled, analyse
from .model import PdfOperationPlan, PdfOptions
from .service import execute


def main(argv=None):
    parser = argparse.ArgumentParser(description="Headless PDF production operation")
    parser.add_argument("request")
    args = parser.parse_args(argv)
    request_path = Path(args.request)
    if request_path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("PDF worker request exceeds 10 MB.")
    request = json.loads(request_path.read_text(encoding="utf-8"))

    def emit(event, **values):
        line = json.dumps({"event": event, **values}, ensure_ascii=True) + "\n"
        with Path(request["events_file"]).open("a", encoding="utf-8") as stream:
            stream.write(line)

    def progress(done, total, message):
        emit("progress", done=done, total=total, message=message)

    def cancelled():
        return Path(request["cancel_file"]).exists()

    try:
        secrets = json.loads(sys.stdin.readline(65536)) if request.get("stdin_secrets") else {}
        if request["task"] in ("analyse_batch", "execute_batch"):
            from .batch import analyse_batch, execute_batch
            passwords = {source: secrets.get("password", "") for source in request.get("sources", [])}
            if request["task"] == "analyse_batch":
                result = {"analyses": analyse_batch(request["sources"], PdfOptions.from_dict(request["options"]),
                            passwords=passwords, progress=progress, is_cancelled=cancelled)}
            else:
                passwords = {row["source"]: secrets.get("password", "") for row in request["analyses"]}
                result = execute_batch(request["analyses"], request["output_dir"], request["output_name"],
                                       passwords=passwords, progress=progress, is_cancelled=cancelled)
        elif request["task"] == "analyse":
            plan = analyse(request["source"], PdfOptions.from_dict(request["options"]),
                           password=secrets.get("password", ""), progress=progress, is_cancelled=cancelled)
            result = {"plan": plan.to_dict()}
        elif request["task"] == "execute":
            result = execute(PdfOperationPlan.from_dict(request["plan"]), request["output_dir"],
                             password=secrets.get("password", ""),
                             output_password=secrets.get("output_password", ""),
                             output_permissions=secrets.get("output_permissions"),
                             output_name=request.get("output_name"), progress=progress, is_cancelled=cancelled)
        else:
            raise ValueError("Unknown PDF operation worker task.")
        emit("result", result=result)
        return 0
    except PdfCancelled as exc:
        emit("result", result={"status": "cancelled", "error": str(exc), "report_dir": getattr(exc, "report_dir", "")})
        return 0
    except Exception as exc:
        if getattr(exc, "report_dir", ""):
            emit("result", result={"status": "failed", "error": str(exc), "report_dir": exc.report_dir})
            return 0
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
