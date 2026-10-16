"""Reglas de conciliación puras (sin I/O): fáciles de probar y de auditar."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

DIAS_ALERTA = 30
CODIGOS_EXCEPCION = {"NO_EN_TESORERIA", "MONTO_DISTINTO", "MONEDA_DISTINTA", "VENCIMIENTO_DISTINTO",
                     "BENEFICIARIO_DISTINTO", "VENCIDA", "DUPLICADA", "SIN_CARTA"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


@dataclass(frozen=True)
class Carta:
    numero: str
    beneficiario: str
    monto: Decimal
    moneda: str
    fecha_vencimiento: date


@dataclass(frozen=True)
class Registro:
    numero: str
    beneficiario: str
    monto: Decimal
    moneda: str
    fecha_vencimiento: date


def evaluar(carta: Carta | None, reg: Registro | None, n_documentos: int, corte: date) -> tuple[str, list[str], dict]:
    """Devuelve (resultado, codigos, detalle). resultado: CONCILIADA | ALERTA | EXCEPCION."""
    codigos: list[str] = []
    detalle: dict = {}
    if carta is None:
        return "EXCEPCION", ["SIN_CARTA"], {"registro_monto": str(reg.monto), "registro_moneda": reg.moneda}
    if n_documentos > 1:
        codigos.append("DUPLICADA")
        detalle["documentos"] = n_documentos
    if reg is None:
        codigos.append("NO_EN_TESORERIA")
    else:
        if carta.monto != reg.monto:
            codigos.append("MONTO_DISTINTO")
            detalle["monto"] = {"carta": str(carta.monto), "tesoreria": str(reg.monto)}
        if carta.moneda != reg.moneda:
            codigos.append("MONEDA_DISTINTA")
            detalle["moneda"] = {"carta": carta.moneda, "tesoreria": reg.moneda}
        if carta.fecha_vencimiento != reg.fecha_vencimiento:
            codigos.append("VENCIMIENTO_DISTINTO")
            detalle["vencimiento"] = {"carta": carta.fecha_vencimiento.isoformat(),
                                      "tesoreria": reg.fecha_vencimiento.isoformat()}
        if norm(carta.beneficiario) != norm(reg.beneficiario):
            codigos.append("BENEFICIARIO_DISTINTO")
            detalle["beneficiario"] = {"carta": carta.beneficiario, "tesoreria": reg.beneficiario}
    dias = (carta.fecha_vencimiento - corte).days
    if dias < 0:
        codigos.append("VENCIDA")
        detalle["dias_vencida"] = -dias
    elif dias <= DIAS_ALERTA:
        codigos.append("POR_VENCER")
        detalle["dias_para_vencer"] = dias
    if any(c in CODIGOS_EXCEPCION for c in codigos):
        return "EXCEPCION", codigos, detalle
    return ("ALERTA" if codigos else "CONCILIADA"), codigos, detalle
