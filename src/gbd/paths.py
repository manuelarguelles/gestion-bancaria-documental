"""Raíz del proyecto: funciona en el repo (editable) y en la imagen (/app, WORKDIR)."""
from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    candidates = [os.getenv("GBD_HOME"), Path(__file__).resolve().parents[2], Path.cwd()]
    for c in candidates:
        if c and (Path(c) / "dataplane" / "sql").is_dir():
            return Path(c)
    raise RuntimeError("no encuentro la raíz del proyecto (define GBD_HOME)")
