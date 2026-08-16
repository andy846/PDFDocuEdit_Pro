from __future__ import annotations

from pathlib import Path

from core.tasks import FunctionTask
from core.tools import text_files_to_pdf


def test_function_task_reports_result_and_finish() -> None:
    task = FunctionTask(lambda: "done")
    results: list[object] = []
    finished: list[bool] = []
    task.signals.result.connect(results.append)
    task.signals.finished.connect(lambda: finished.append(True))
    task.run()
    assert results == ["done"]
    assert finished == [True]


def test_function_task_reports_cooperative_cancellation_without_result() -> None:
    task = FunctionTask(lambda: "should not run")
    results: list[object] = []
    cancelled: list[bool] = []
    finished: list[bool] = []
    task.signals.result.connect(results.append)
    task.signals.cancelled.connect(lambda: cancelled.append(True))
    task.signals.finished.connect(lambda: finished.append(True))
    task.cancel()
    task.run()
    assert results == []
    assert cancelled == [True]
    assert finished == [True]


def test_mid_operation_cancellation_leaves_no_partial_text_pdf(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("word " * 5000, encoding="utf-8")
    output = tmp_path / "cancelled.pdf"
    task = FunctionTask(
        text_files_to_pdf,
        [source],
        output,
        progress_argument="progress",
        cancel_argument="is_cancelled",
    )
    cancelled: list[bool] = []
    errors: list[str] = []
    task.signals.progress.connect(lambda *_args: task.cancel())
    task.signals.cancelled.connect(lambda: cancelled.append(True))
    task.signals.error.connect(errors.append)
    task.run()
    assert cancelled == [True]
    assert errors == []
    assert not output.exists()
