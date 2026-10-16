from datetime import date
from decimal import Decimal

from gbd.dataplane.reglas import Carta, Registro, evaluar, norm

CORTE = date(2026, 10, 16)


def carta(**kw):
    base = {"numero": "CF-1", "beneficiario": "Municipalidad de Trujillo", "monto": Decimal("100.00"), "moneda": "PEN",
                "fecha_vencimiento": date(2027, 3, 1)}
    return Carta(**{**base, **kw})


def reg(**kw):
    base = {"numero": "CF-1", "beneficiario": "Municipalidad de Trujillo", "monto": Decimal("100.00"), "moneda": "PEN",
                "fecha_vencimiento": date(2027, 3, 1)}
    return Registro(**{**base, **kw})


def test_conciliada():
    assert evaluar(carta(), reg(), 1, CORTE)[:2] == ("CONCILIADA", [])


def test_monto_distinto():
    r, c, d = evaluar(carta(), reg(monto=Decimal("90.00")), 1, CORTE)
    assert (r, c) == ("EXCEPCION", ["MONTO_DISTINTO"]) and d["monto"]["tesoreria"] == "90.00"


def test_moneda_y_vencimiento():
    _, c, _ = evaluar(carta(), reg(moneda="USD", fecha_vencimiento=date(2027, 2, 1)), 1, CORTE)
    assert set(c) == {"MONEDA_DISTINTA", "VENCIMIENTO_DISTINTO"}


def test_sin_registro():
    assert evaluar(carta(), None, 1, CORTE)[:2] == ("EXCEPCION", ["NO_EN_TESORERIA"])


def test_sin_carta():
    assert evaluar(None, reg(), 0, CORTE)[:2] == ("EXCEPCION", ["SIN_CARTA"])


def test_duplicada():
    assert "DUPLICADA" in evaluar(carta(), reg(), 2, CORTE)[1]


def test_vencida_y_por_vencer():
    v = carta(fecha_vencimiento=date(2026, 10, 15))
    assert evaluar(v, reg(fecha_vencimiento=v.fecha_vencimiento), 1, CORTE)[:2] == ("EXCEPCION", ["VENCIDA"])
    p = carta(fecha_vencimiento=date(2026, 11, 15))
    assert evaluar(p, reg(fecha_vencimiento=p.fecha_vencimiento), 1, CORTE)[:2] == ("ALERTA", ["POR_VENCER"])


def test_borde_vence_hoy_no_esta_vencida():
    h = carta(fecha_vencimiento=CORTE)
    assert evaluar(h, reg(fecha_vencimiento=CORTE), 1, CORTE)[:2] == ("ALERTA", ["POR_VENCER"])


def test_beneficiario_normalizado():
    assert norm("  Ingeniería   Y Obras ") == "ingenieria y obras"
    assert evaluar(carta(beneficiario="MUNICIPALIDAD DE  TRUJILLO"), reg(), 1, CORTE)[0] == "CONCILIADA"
