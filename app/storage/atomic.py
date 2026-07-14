from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        json.dump(data, tmp_file, ensure_ascii=False, indent=2)
        tmp_file.write("\n")
        tmp_file.flush()
        os.fsync(tmp_file.fileno())

    os.replace(tmp_path, path)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(content)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())

    os.replace(tmp_path, path)
