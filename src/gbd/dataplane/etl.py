"""ETL de la bandeja: Excel de Tesorería -> Postgres, y extracción de texto de PDFs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader


@dataclass(frozen=True)
class Doc:
    archivo: str
    sha256: str
    texto: str


def leer_bandeja(carpeta: Path) -> list[Doc]:
    docs = []
    for p in sorted(carpeta.glob("*.pdf")):
        raw = p.read_bytes()
        texto = "\n".join((pg.extract_text() or "") for pg in PdfReader(p).pages).strip()
        docs.append(Doc(p.name, hashlib.sha256(raw).hexdigest(), texto))
    return docs


def _fecha(v) -> date:
    return v.date() if isinstance(v, datetime) else v if isinstance(v, date) else date.fromisoformat(str(v))


def cargar_registro_tesoreria(cx, xlsx: Path) -> int:
    ws = load_workbook(xlsx, data_only=True)["Garantias"]
    n = 0
    for numero, ordenante, benef, monto, moneda, vence, estado in list(ws.iter_rows(values_only=True))[1:]:
        if not numero:
            continue
        cx.execute(
            """INSERT INTO doc.registro_tesoreria(numero, ordenante, beneficiario, monto, moneda, fecha_vencimiento, estado_registro)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (numero) DO UPDATE SET ordenante=EXCLUDED.ordenante, beneficiario=EXCLUDED.beneficiario,
                 monto=EXCLUDED.monto, moneda=EXCLUDED.moneda, fecha_vencimiento=EXCLUDED.fecha_vencimiento,
                 estado_registro=EXCLUDED.estado_registro""",
            (str(numero).strip(), ordenante, benef, Decimal(str(monto)), str(moneda).strip(), _fecha(vence), estado))
        n += 1
    return n
