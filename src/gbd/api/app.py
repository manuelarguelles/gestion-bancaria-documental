"""Canal de consulta (agencias): solo estado y vigencia, con el rol de solo lectura gbd_lector."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .. import db

app = FastAPI(title="GBD · consulta de garantías", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/garantias/{numero}")
def estado(numero: str) -> dict:
    with db.connect() as cx:
        cx.execute("SET LOCAL ROLE gbd_lector")
        r = cx.execute(
            """SELECT c.numero, c.resultado, c.codigos, cf.beneficiario, cf.moneda, cf.monto, cf.fecha_vencimiento
               FROM doc.conciliacion c LEFT JOIN doc.cartas_fianza cf ON cf.id=c.carta_id
               WHERE c.numero=%s ORDER BY c.id DESC LIMIT 1""", (numero,)).fetchone()
    if not r:
        raise HTTPException(404, "garantía no encontrada")
    return {k: (str(v) if k in ("monto", "fecha_vencimiento") else v) for k, v in r.items()}
