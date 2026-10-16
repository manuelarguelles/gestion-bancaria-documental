from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from .config import settings
from .paths import root

SQL_DIR = root() / "dataplane" / "sql"


def connect() -> psycopg.Connection:
    return psycopg.connect(settings().dsn, row_factory=dict_row, autocommit=False)


def migrate() -> None:
    with connect() as cx:
        for f in sorted(SQL_DIR.glob("*.sql")):
            cx.execute(f.read_text(encoding="utf-8"))
        cx.commit()
