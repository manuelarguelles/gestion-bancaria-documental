from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field
from datetime import date


def _load_dotenv() -> None:
    """Carga .env si existe (sin dependencias). Las variables ya definidas ganan."""
    for candidate in (".env", os.path.join(os.path.dirname(__file__), "..", "..", ".env")):
        if os.path.isfile(candidate):
            for line in pathlib.Path(candidate).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    pg_host: str = field(default_factory=lambda: os.getenv("PGHOST", "127.0.0.1"))
    pg_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "55440")))
    pg_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "gbd"))
    pg_password: str = field(default_factory=lambda: os.environ["POSTGRES_PASSWORD"])
    pg_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "gbd"))
    project_endpoint: str = field(default_factory=lambda: os.environ["FOUNDRY_PROJECT_ENDPOINT"])
    model: str = field(default_factory=lambda: os.getenv("FOUNDRY_MODEL", "gpt-5-mini"))
    embedding_model: str = field(default_factory=lambda: os.getenv("FOUNDRY_EMBEDDING_MODEL", "text-embedding-3-small"))
    fecha_corte: date = field(
        default_factory=lambda: date.fromisoformat(os.getenv("GBD_FECHA_CORTE") or date.today().isoformat())
    )

    @property
    def dsn(self) -> str:
        return (f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
                f"user={self.pg_user} password={self.pg_password}")


def settings() -> Settings:
    return Settings()
