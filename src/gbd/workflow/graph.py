"""Workflow local (Microsoft Agent Framework) del proceso de Gestión Bancaria Documental.

    Ingestar ─▶ Cognitivo (workflow de Foundry) ─▶ Cargar ─▶ Conciliar ─▶ Excepciones (RAG + agente) ─▶ Resumen

Los nodos deterministas (ETL, SQL, reglas) corren en el contenedor sobre Postgres/pgvector; los nodos
cognitivos son agentes/workflows de Microsoft Foundry, visibles y versionados en el portal.
Las excepciones quedan PENDIENTES para decisión humana (HITL): el agente propone, el analista decide.
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Never

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from .. import db, foundry
from ..config import settings
from ..dataplane import etl
from ..dataplane.reglas import Carta, Registro, evaluar
from ..rag import politicas

WORKFLOW_FOUNDRY = "gbd-workflow-documental"
AGENTE_ANALISTA = "gbd-analista-excepciones"


@dataclass
class Entrada:
    bandeja: str
    registro_xlsx: str
    fecha_corte: date


@dataclass
class Lote:
    corrida_id: str
    fecha_corte: date
    docs: list[etl.Doc]


@dataclass
class Leido:
    doc: etl.Doc
    clasificacion: dict
    campos: dict | None


@dataclass
class Procesado:
    corrida_id: str
    fecha_corte: date
    leidos: list[Leido]
    omitidos: list[str] = field(default_factory=list)


@dataclass
class Conciliado:
    corrida_id: str
    fecha_corte: date
    cargados: int
    fuera_alcance: list[str]
    omitidos: list[str]
    excepciones: list[int]  # ids de doc.conciliacion con resultado EXCEPCION


def _parse_mensajes(msgs: list[str]) -> tuple[dict, dict | None]:
    """El workflow de Foundry emite 1) la clasificación y 2) la extracción (o FUERA_DE_ALCANCE)."""
    clasif = json.loads(msgs[0])
    campos = None
    if clasif.get("tipo") == "carta_fianza" and len(msgs) > 1 and msgs[1].strip() != "FUERA_DE_ALCANCE":
        campos = json.loads(msgs[1])
    return clasif, campos


class Ingestar(Executor):
    @handler
    async def run(self, e: Entrada, ctx: WorkflowContext[Lote]) -> None:
        with db.connect() as cx:
            n = etl.cargar_registro_tesoreria(cx, Path(e.registro_xlsx))
            conocidos = {r["sha256"] for r in cx.execute("SELECT sha256 FROM doc.documentos").fetchall()}
            corrida = str(uuid.uuid4())
            cx.execute("INSERT INTO doc.corridas(id, fecha_corte) VALUES (%s,%s)", (corrida, e.fecha_corte))
            cx.commit()
        todos = etl.leer_bandeja(Path(e.bandeja))
        nuevos = [d for d in todos if d.sha256 not in conocidos]
        print(f"[ingestar] registro tesorería: {n} filas · bandeja: {len(todos)} PDF ({len(nuevos)} nuevos)")
        await ctx.send_message(Lote(corrida, e.fecha_corte, nuevos))


class Cognitivo(Executor):
    @handler
    async def run(self, lote: Lote, ctx: WorkflowContext[Procesado]) -> None:
        def leer(d: etl.Doc) -> Leido:
            clasif, campos = _parse_mensajes(foundry.run_workflow(WORKFLOW_FOUNDRY, d.texto))
            print(f"[cognitivo] {d.archivo}: {clasif['tipo']} ({clasif['confianza']:.2f})")
            return Leido(d, clasif, campos)

        with ThreadPoolExecutor(max_workers=4) as pool:
            leidos = list(pool.map(leer, lote.docs))
        await ctx.send_message(Procesado(lote.corrida_id, lote.fecha_corte, leidos))


class Cargar(Executor):
    @handler
    async def run(self, p: Procesado, ctx: WorkflowContext[Conciliado]) -> None:
        cargados, fuera = 0, []
        with db.connect() as cx:
            for lei in p.leidos:
                tipo = lei.clasificacion["tipo"]
                row = cx.execute(
                    """INSERT INTO doc.documentos(archivo, sha256, tipo, clasificacion, texto)
                       VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                    (lei.doc.archivo, lei.doc.sha256, tipo, json.dumps(lei.clasificacion), lei.doc.texto)).fetchone()
                if lei.campos is None:
                    fuera.append(lei.doc.archivo)
                    continue
                c = lei.campos
                cx.execute(
                    """INSERT INTO doc.cartas_fianza(documento_id, numero, ordenante, beneficiario, monto, moneda,
                         fecha_emision, fecha_vencimiento, tipo_garantia) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row["id"], c["numero"].strip(), c["ordenante"], c["beneficiario"], Decimal(str(c["monto"])),
                     c["moneda"], c["fecha_emision"], c["fecha_vencimiento"], c["tipo_garantia"]))
                cargados += 1
            cx.commit()
        await ctx.send_message(Conciliado(p.corrida_id, p.fecha_corte, cargados, fuera, p.omitidos, []))


class Conciliar(Executor):
    @handler
    async def run(self, c: Conciliado, ctx: WorkflowContext[Conciliado]) -> None:
        excepciones: list[int] = []
        resumen = {"CONCILIADA": 0, "ALERTA": 0, "EXCEPCION": 0}
        with db.connect() as cx:
            cartas = cx.execute("SELECT * FROM doc.cartas_fianza ORDER BY id").fetchall()
            regs = {r["numero"]: r for r in cx.execute("SELECT * FROM doc.registro_tesoreria").fetchall()}
            por_numero: dict[str, list[dict]] = {}
            for ca in cartas:
                por_numero.setdefault(ca["numero"], []).append(ca)

            def guardar(numero, carta_id, res, cods, det):
                resumen[res] += 1
                cid = cx.execute(
                    """INSERT INTO doc.conciliacion(corrida_id, numero, carta_id, resultado, codigos, detalle)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (c.corrida_id, numero, carta_id, res, cods, json.dumps(det))).fetchone()["id"]
                if res == "EXCEPCION":
                    excepciones.append(cid)

            for numero, grupo in por_numero.items():
                for ca in grupo:
                    r = regs.get(numero)
                    res, cods, det = evaluar(
                        Carta(numero, ca["beneficiario"], ca["monto"], ca["moneda"], ca["fecha_vencimiento"]),
                        Registro(numero, r["beneficiario"], r["monto"], r["moneda"], r["fecha_vencimiento"]) if r else None,
                        len(grupo), c.fecha_corte)
                    guardar(numero, ca["id"], res, cods, det)
            for numero, r in regs.items():
                if numero not in por_numero:
                    res, cods, det = evaluar(None, Registro(numero, r["beneficiario"], r["monto"], r["moneda"],
                                                           r["fecha_vencimiento"]), 0, c.fecha_corte)
                    guardar(numero, None, res, cods, det)
            cx.execute("UPDATE doc.corridas SET resumen=%s WHERE id=%s",
                       (json.dumps({**resumen, "fuera_de_alcance": c.fuera_alcance}), c.corrida_id))
            cx.commit()
        print(f"[conciliar] {resumen}")
        c.excepciones = excepciones
        await ctx.send_message(c)


class Excepciones(Executor):
    @handler
    async def run(self, c: Conciliado, ctx: WorkflowContext[Conciliado]) -> None:
        with db.connect() as cx:
            filas = [cx.execute("SELECT * FROM doc.conciliacion WHERE id=%s", (i,)).fetchone() for i in c.excepciones]
            # Idempotencia HITL: no reabrir una excepción que ya está en la cola (o resuelta) para el mismo caso.
            vistas = {(r["numero"], tuple(sorted(r["codigos"]))) for r in cx.execute(
                """SELECT c.numero, c.codigos FROM doc.excepciones e JOIN doc.conciliacion c ON c.id=e.conciliacion_id
                   WHERE c.corrida_id <> %s""", (c.corrida_id,)).fetchall()}
            filas = [f for f in filas if (f["numero"], tuple(sorted(f["codigos"]))) not in vistas]
            carta_por_id = {r["id"]: r for r in cx.execute("SELECT * FROM doc.cartas_fianza").fetchall()}
            contextos = []
            for f in filas:
                consulta = f"{' '.join(f['codigos'])}: " + json.dumps(f["detalle"], ensure_ascii=False)
                pols = politicas.recuperar(cx, consulta, k=3)
                contextos.append((f, pols))

        def analizar(item):
            f, pols = item
            carta = carta_por_id.get(f["carta_id"])
            prompt = json.dumps({
                "numero": f["numero"], "codigos": f["codigos"], "detalle": f["detalle"],
                "fecha_corte": c.fecha_corte.isoformat(),
                "carta": {k: str(v) for k, v in carta.items() if k in ("ordenante", "beneficiario", "monto", "moneda",
                                                                         "fecha_vencimiento")} if carta else None,
                "politicas_recuperadas": [{"codigo": p["codigo"], "titulo": p["titulo"], "texto": p["contenido"]}
                                          for p in pols],
            }, ensure_ascii=False)
            out = foundry.invoke_json(AGENTE_ANALISTA, prompt)
            validos = {p["codigo"] for p in pols}
            out["politicas_citadas"] = [x for x in out["politicas_citadas"] if x in validos]
            print(f"[excepciones] {f['numero']} {f['codigos']} -> {out['prioridad']}")
            return f["id"], out

        with ThreadPoolExecutor(max_workers=4) as pool:
            resultados = list(pool.map(analizar, contextos))
        with db.connect() as cx:
            for cid, o in resultados:
                cx.execute(
                    """INSERT INTO doc.excepciones(conciliacion_id, explicacion, accion_recomendada, prioridad, politicas_citadas)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (conciliacion_id) DO NOTHING""",
                    (cid, o["explicacion"], o["accion_recomendada"], o["prioridad"], o["politicas_citadas"]))
            cx.commit()
        await ctx.send_message(c)


class Resumen(Executor):
    @handler
    async def run(self, c: Conciliado, ctx: WorkflowContext[Never, dict]) -> None:
        with db.connect() as cx:
            r = cx.execute("SELECT resumen FROM doc.corridas WHERE id=%s", (c.corrida_id,)).fetchone()["resumen"]
            pend = cx.execute("SELECT count(*) n FROM doc.excepciones WHERE estado='PENDIENTE'").fetchone()["n"]
        await ctx.yield_output({"corrida_id": c.corrida_id, "fecha_corte": c.fecha_corte.isoformat(),
                                "cargadas": c.cargados, "resumen": r, "excepciones_pendientes_analista": pend})


def build():
    ing, cog, car, con, exc, res = Ingestar(id="ingestar"), Cognitivo(id="cognitivo"), Cargar(id="cargar"), \
        Conciliar(id="conciliar"), Excepciones(id="excepciones"), Resumen(id="resumen")
    return (WorkflowBuilder(start_executor=ing, name="gbd-workflow-local")
            .add_chain([ing, cog, car, con, exc, res]).build())


async def ejecutar(bandeja: str, registro_xlsx: str) -> dict:
    wf = build()
    result = await wf.run(Entrada(bandeja, registro_xlsx, settings().fecha_corte))
    return result.get_outputs()[0]
