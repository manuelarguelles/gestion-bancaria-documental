"""Integración con Postgres + pgvector reales (CI: service container; local: `make up`)."""
import os

import psycopg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cx():
    from gbd import db
    try:
        db.migrate()
        c = db.connect()
    except psycopg.OperationalError as e:  # sin Postgres disponible -> se omite
        pytest.skip(f"Postgres no disponible: {e}")
    yield c
    c.close()


def test_pgvector_hnsw_y_distancia_coseno(cx):
    cx.execute("DELETE FROM doc.politicas WHERE codigo LIKE 'T-%'")
    v1 = "[" + ",".join(["1"] + ["0"] * 1535) + "]"
    v2 = "[" + ",".join(["0", "1"] + ["0"] * 1534) + "]"
    cx.execute("INSERT INTO doc.politicas VALUES ('T-1','a','a',%s::vector),('T-2','b','b',%s::vector)", (v1, v2))
    r = cx.execute("SELECT codigo FROM doc.politicas WHERE codigo LIKE 'T-%%' ORDER BY embedding <=> %s::vector LIMIT 1",
                   (v1,)).fetchone()
    assert r["codigo"] == "T-1"
    cx.rollback()


def test_rol_lector_no_ve_texto_de_documentos(cx):
    cx.execute("SET LOCAL ROLE gbd_lector")
    with pytest.raises(Exception, match="permission denied"):
        cx.execute("SELECT texto FROM doc.documentos LIMIT 1")
    cx.rollback()
    assert os.getenv("POSTGRES_PASSWORD")
