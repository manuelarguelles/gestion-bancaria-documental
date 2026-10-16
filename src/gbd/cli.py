from __future__ import annotations

import argparse
import asyncio
import json

from . import db


def _revisor(args) -> None:
    with db.connect() as cx:
        if args.id is None:
            for r in cx.execute("""SELECT e.id, c.numero, c.codigos, e.prioridad, e.estado, e.accion_recomendada
                                   FROM doc.excepciones e JOIN doc.conciliacion c ON c.id=e.conciliacion_id
                                   ORDER BY e.estado, e.prioridad, e.id""").fetchall():
                print(f"#{r['id']:<3} {r['estado']:<9} {r['prioridad']:<5} {r['numero']} {r['codigos']}")
            return
        cx.execute("""UPDATE doc.excepciones SET estado=%s, revisor=%s, comentario=%s, resuelto_en=now() WHERE id=%s""",
                   (args.decision, args.revisor, args.comentario, args.id))
        cx.commit()
        print(f"excepción #{args.id} -> {args.decision} por {args.revisor}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="gbd")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("migrate", help="aplica el esquema SQL")
    sp.add_parser("indexar-politicas", help="embebe las políticas en pgvector")
    sp.add_parser("deploy-agentes", help="publica agentes y workflow en Foundry")
    r = sp.add_parser("run", help="ejecuta el workflow sobre una bandeja")
    r.add_argument("--bandeja", default="dataplane/samples/bandeja")
    r.add_argument("--registro", default="dataplane/samples/registro_tesoreria.xlsx")
    rv = sp.add_parser("revisar", help="cola del analista: lista o resuelve excepciones")
    rv.add_argument("--id", type=int)
    rv.add_argument("--decision", choices=["APROBADA", "RECHAZADA", "ESCALADA"])
    rv.add_argument("--revisor", default="analista")
    rv.add_argument("--comentario", default="")
    sp.add_parser("api", help="API de consulta (agencias)")
    a = ap.parse_args()

    if a.cmd == "migrate":
        db.migrate()
        print("esquema aplicado")
    elif a.cmd == "indexar-politicas":
        from .rag import politicas
        with db.connect() as cx:
            n = politicas.indexar(cx)
            cx.commit()
        print(f"{n} políticas indexadas")
    elif a.cmd == "deploy-agentes":
        from .agents import deploy
        deploy.main()
    elif a.cmd == "run":
        from .workflow import graph
        print(json.dumps(asyncio.run(graph.ejecutar(a.bandeja, a.registro)), indent=2, ensure_ascii=False))
    elif a.cmd == "revisar":
        _revisor(a)
    elif a.cmd == "api":
        import uvicorn
        uvicorn.run("gbd.api.app:app", host="0.0.0.0", port=8000)
