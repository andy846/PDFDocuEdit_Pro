"""Support logs retain safe failure stages and process identity, not PDF values."""
import logging
import os

from core import diagnostics


def test_lifecycle_file_is_bounded_idempotent_and_redacts_exception_values(tmp_path):
    logger = logging.getLogger("pdfdocuedit.lifecycle")
    previous_level = logger.level
    before = set(logger.handlers)
    try:
        diagnostics.configure_lifecycle_logging(tmp_path)
        diagnostics.configure_lifecycle_logging(tmp_path)
        handlers = [h for h in logger.handlers if h not in before]
        assert len(handlers) == 1
        assert handlers[0].maxBytes == 1024 * 1024 and handlers[0].backupCount == 2
        diagnostics.log_lifecycle("open.first_page", request=2, generation=4)
        try:
            raise ValueError("CUSTOMER_TEXT_OR_PASSWORD_MUST_NOT_APPEAR")
        except ValueError:
            diagnostics.log_failure("Watermark preview failed")
        handlers[0].flush()
        text = (tmp_path / "lifecycle.log").read_text(encoding="utf-8")
        assert str(os.getpid()) in text
        assert "open.first_page" in text and "request=2" in text
        assert "Watermark preview failed" in text and "ValueError" in text
        assert "CUSTOMER_TEXT_OR_PASSWORD" not in text
    finally:
        for handler in set(logger.handlers) - before:
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(previous_level)
