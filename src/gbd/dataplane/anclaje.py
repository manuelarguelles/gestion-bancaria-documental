"""Chequeo de anclaje: cada dato extraído por el modelo debe aparecer en el texto fuente.

Un LLM puede devolver un JSON bien formado con un valor que el documento no dice (o que el OCR leyó mal).
Aquí se comprueba, sin modelo, que número, monto y fecha de vencimiento existan literalmente en el texto
leído, aceptando los formatos habituales (1,234.50 · 1.234,50 · 31/12/2026 · 31 de diciembre de 2026 · ISO).
Un dato sin anclar no se descarta en silencio: pasa a revisión humana.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

MESES = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre",
     "noviembre", "diciembre"])}
MESES["septiembre"] = 9


def _montos(texto: str) -> set[Decimal]:
    """Todos los números del texto, interpretando el separador ambiguo de las dos formas posibles."""
    out: set[Decimal] = set()
    for tok in re.findall(r"\d[\d.,]*\d|\d", texto):
        crudo = tok.rstrip(".,")
        candidatos: list[str] = []
        if "." in crudo and "," in crudo:
            dec = "." if crudo.rfind(".") > crudo.rfind(",") else ","
            mil = "," if dec == "." else "."
            candidatos.append(crudo.replace(mil, "").replace(dec, "."))
        elif "." in crudo or "," in crudo:
            sep = "." if "." in crudo else ","
            candidatos.append(crudo.replace(sep, ""))              # separador de miles
            if crudo.count(sep) == 1:
                candidatos.append(crudo.replace(sep, "."))          # separador decimal
        else:
            candidatos.append(crudo)
        for c in candidatos:
            try:
                out.add(Decimal(c).quantize(Decimal("0.01")))
            except InvalidOperation:
                pass
    return out


def _fechas(texto: str) -> set[date]:
    out: set[date] = set()
    t = texto.lower()
    pares = [(r"(\d{4})-(\d{2})-(\d{2})", (0, 1, 2)), (r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", (2, 1, 0))]
    for rx, (iy, im, idd) in pares:
        for m in re.finditer(rx, t):
            try:
                out.add(date(int(m[iy + 1]), int(m[im + 1]), int(m[idd + 1])))
            except ValueError:
                pass
    for m in re.finditer(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:de|del)\s+(\d{4})", t):
        mes = MESES.get(m[2])
        if mes:
            try:
                out.add(date(int(m[3]), mes, int(m[1])))
            except ValueError:
                pass
    return out


def _compacto(s: str) -> str:
    return re.sub(r"[\s\-_/.]", "", s).upper()


def campos_sin_anclar(campos: dict, texto: str) -> list[str]:
    """Nombres de los campos críticos cuyo valor no se encuentra en el texto fuente."""
    malos: list[str] = []
    if _compacto(str(campos["numero"])) not in _compacto(texto):
        malos.append("numero")
    try:
        if Decimal(str(campos["monto"])).quantize(Decimal("0.01")) not in _montos(texto):
            malos.append("monto")
    except InvalidOperation:
        malos.append("monto")
    try:
        if date.fromisoformat(campos["fecha_vencimiento"]) not in _fechas(texto):
            malos.append("fecha_vencimiento")
    except (ValueError, TypeError):
        malos.append("fecha_vencimiento")
    return malos
