"""RAG sobre políticas internas con pgvector (recuperación por similitud coseno)."""
from __future__ import annotations

import re

from ..foundry import embed
from ..paths import root

POLITICAS_MD = root() / "dataplane" / "policies.md"


def parsear(md: str) -> list[tuple[str, str, str]]:
    out = []
    for bloque in re.split(r"^## ", md, flags=re.MULTILINE)[1:]:
        cab, _, cuerpo = bloque.partition("\n")
        codigo, _, titulo = cab.partition(" · ")
        out.append((codigo.strip(), titulo.strip(), cuerpo.strip()))
    return out


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def indexar(cx) -> int:
    pols = parsear(POLITICAS_MD.read_text(encoding="utf-8"))
    vecs = embed([f"{c} {t}. {b}" for c, t, b in pols])
    for (c, t, b), v in zip(pols, vecs, strict=True):
        cx.execute(
            """INSERT INTO doc.politicas(codigo, titulo, contenido, embedding) VALUES (%s,%s,%s,%s::vector)
               ON CONFLICT (codigo) DO UPDATE SET titulo=EXCLUDED.titulo, contenido=EXCLUDED.contenido,
                 embedding=EXCLUDED.embedding""", (c, t, b, _vec(v)))
    return len(pols)


def recuperar(cx, consulta: str, k: int = 3) -> list[dict]:
    v = embed([consulta])[0]
    return cx.execute(
        """SELECT codigo, titulo, contenido, 1 - (embedding <=> %s::vector) AS similitud
           FROM doc.politicas ORDER BY embedding <=> %s::vector LIMIT %s""", (_vec(v), _vec(v), k)).fetchall()
