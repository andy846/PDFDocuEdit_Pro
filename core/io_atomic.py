"""Same-directory staged writes; commit only after caller validation succeeds."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_output(
    output_path: str | os.PathLike[str], *, suffix: str | None = None, overwrite: bool = True
) -> Iterator[Path]:
    """Yield a temporary path, then atomically replace the destination.

    Write and validate inside the scope. Exceptions retain the old destination.
    This is replacement atomicity, not a power-loss durability guarantee.
    """
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=target.suffix if suffix is None else suffix,
        dir=target.parent,
    )
    os.close(handle)
    staged = Path(temp_name)
    try:
        yield staged
        if overwrite:
            os.replace(staged, target)
        elif os.name == "nt":
            # Windows rename fails atomically if another writer created target.
            os.rename(staged, target)
        else:
            # Same-filesystem link publishes the complete file without replacing
            # an existing name. The staging link is removed in finally.
            os.link(staged, target)
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).warning("Cannot remove staged output %s", staged, exc_info=True)
