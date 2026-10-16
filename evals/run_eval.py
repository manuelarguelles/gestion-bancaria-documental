"""Evalúa la última corrida contra la verdad plantada en dataplane/samples/esperado.json.

Mide: (1) clasificación de documentos, (2) extracción de campos vs. el generador,
(3) conciliación (códigos exactos por garantía), (4) política correcta citada en cada excepción.
Sale con código 1 si algo no coincide. Requiere Postgres + Foundry (corrida previa con `gbd run`).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from gbd import db

RAIZ = Path(__file__).resolve().parents[1]
POLITICA_ESPERADA = {"MONTO_DISTINTO": "POL-GAR-02", "MONEDA_DISTINTA": "POL-GAR-02", "NO_EN_TESORERIA": "POL-GAR-01",
                     "VENCIDA": "POL-GAR-03", "VENCIMIENTO_DISTINTO": "POL-GAR-04", "DUPLICADA": "POL-GAR-05",
                     "SIN_CARTA": "POL-GAR-06"}


def _generador():
    spec = importlib.util.spec_from_file_location("gen", RAIZ / "dataplane" / "generar_muestras.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    esperado = json.loads((RAIZ / "dataplane/samples/esperado.json").read_text())
    gen = _generador()
    fallos: list[str] = []
    with db.connect() as cx:
        corrida = cx.execute("SELECT id FROM doc.corridas ORDER BY creado_en DESC LIMIT 1").fetchone()["id"]
        # (1) clasificación
        tipos = {r["archivo"]: r["tipo"] for r in cx.execute("SELECT archivo, tipo FROM doc.documentos").fetchall()}
        ok_cls = sum(tipos.get(a) == t for a, t in esperado["documentos"].items())
        fallos += [f"clasif {a}: {tipos.get(a)} != {t}" for a, t in esperado["documentos"].items() if tipos.get(a) != t]
        # (2) extracción
        cartas = {r["numero"]: r for r in cx.execute("SELECT * FROM doc.cartas_fianza").fetchall()}
        campos = ok_campos = 0
        for numero, ordenante, benef, monto, mon, emi, vence, *_ in gen.CARTAS:
            r = cartas.get(numero)
            for campo, val in (("ordenante", ordenante), ("beneficiario", benef), ("monto", monto), ("moneda", mon),
                               ("fecha_emision", emi), ("fecha_vencimiento", vence)):
                campos += 1
                got = r[campo] if r else None
                same = (float(got) == val) if campo == "monto" and got is not None else got == val
                ok_campos += same
                if not same:
                    fallos.append(f"extracción {numero}.{campo}: {got!r} != {val!r}")
        # (3) conciliación
        conc = cx.execute("SELECT numero, codigos FROM doc.conciliacion WHERE corrida_id=%s", (corrida,)).fetchall()
        ok_conc = 0
        for r in conc:
            exp = sorted(esperado["conciliacion"].get(r["numero"], []))
            if sorted(r["codigos"]) == exp:
                ok_conc += 1
            else:
                fallos.append(f"conciliación {r['numero']}: {sorted(r['codigos'])} != {exp}")
        # (4) política citada
        exc = cx.execute("""SELECT c.numero, c.codigos, e.politicas_citadas, e.prioridad FROM doc.excepciones e
                            JOIN doc.conciliacion c ON c.id=e.conciliacion_id WHERE c.corrida_id=%s""", (corrida,)).fetchall()
        ok_pol = 0
        for r in exc:
            need = {POLITICA_ESPERADA[c] for c in r["codigos"] if c in POLITICA_ESPERADA}
            if need <= set(r["politicas_citadas"]):
                ok_pol += 1
            else:
                fallos.append(f"política {r['numero']}: citó {r['politicas_citadas']}, esperaba ⊇ {sorted(need)}")
    print(f"clasificación : {ok_cls}/{len(esperado['documentos'])}")
    print(f"extracción    : {ok_campos}/{campos} campos")
    print(f"conciliación  : {ok_conc}/{len(conc)} garantías con los códigos exactos")
    print(f"política citada: {ok_pol}/{len(exc)} excepciones")
    for f in fallos:
        print(" ✗", f)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
