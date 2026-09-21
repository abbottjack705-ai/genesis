from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def scratch_directory():
    root = Path(__file__).resolve().parents[1] / "work" / "test_runtime" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)

