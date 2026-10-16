"""Reglas de conciliación puras (sin I/O): fáciles de probar y de auditar."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

DIAS_ALERTA = 30
CODIGOS_EXCEPCION = {"NO_EN_TESORERIA", "MONTO_DISTINTO", "MONEDA_DISTINTA", "VENCIMIENTO_DISTINTO",
                     "BENEFICIARIO_DISTINTO", "VENCIDA", "DUPLICADA", "SIN_CARTA", "LECTURA_DUDOSA"}


DESCRIPCION_CODIGO = {
    "NO_EN_TESORERIA": "carta fianza recibida que no figura en el Registro de Garantías de Tesorería",
    "MONTO_DISTINTO": "el monto de la carta no coincide con el del Registro de Tesorería",
    "MONEDA_DISTINTA": "la moneda de la carta no coincide con la del Registro de Tesorería",
    "VENCIMIENTO_DISTINTO": "la fecha de vencimiento de la carta difiere de la del Registro de Tesorería",
    "BENEFICIARIO_DISTINTO": "el beneficiario de la carta difiere del del Registro de Tesorería",
    "VENCIDA": "carta fianza con fecha de vencimiento anterior a la fecha de corte",
    "DUPLICADA": "mismo número de carta recibido en más de un documento",
    "SIN_CARTA": "registro de Tesorería sin carta fianza recibida",
    "LECTURA_DUDOSA": "campos de la carta que no se pudieron verificar en el texto original del documento",
    "POR_VENCER": "carta fianza que vence dentro de los próximos 30 días",
}


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


def evaluar(carta: Carta | None, reg: Registro | None, n_documentos: int, corte: date,
            lectura_dudosa: tuple[str, ...] = ()) -> tuple[str, list[str], dict]:
    """Devuelve (resultado, codigos, detalle). resultado: CONCILIADA | ALERTA | EXCEPCION."""
    codigos: list[str] = []
    detalle: dict = {}
    if carta is None:
        return "EXCEPCION", ["SIN_CARTA"], {"registro_monto": str(reg.monto), "registro_moneda": reg.moneda}
    if lectura_dudosa:
        codigos.append("LECTURA_DUDOSA")
        detalle["campos_sin_anclar"] = list(lectura_dudosa)
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
