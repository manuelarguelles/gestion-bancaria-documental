import importlib.util
import json
from pathlib import Path

from gbd.dataplane import etl
from gbd.rag.politicas import parsear
from gbd.workflow.graph import _parse_mensajes

RAIZ = Path(__file__).resolve().parents[1]


def _gen():
    spec = importlib.util.spec_from_file_location("gen", RAIZ / "dataplane" / "generar_muestras.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_generador_y_lectura_de_bandeja(tmp_path):
    _gen().main(tmp_path)
    docs = etl.leer_bandeja(tmp_path / "bandeja")
    assert len(docs) == 13
    assert len({d.sha256 for d in docs}) == 13  # el reenvío duplicado tiene bytes distintos
    d = next(x for x in docs if x.archivo == "CF-2026-0003.pdf")
    assert "45.000,50 soles" in d.texto
    esperado = json.loads((tmp_path / "esperado.json").read_text())
    assert esperado["conciliacion"]["CF-2026-0011"] == ["SIN_CARTA"]


def test_politicas_parseables():
    pols = parsear((RAIZ / "dataplane" / "policies.md").read_text(encoding="utf-8"))
    assert [p[0] for p in pols] == [f"POL-GAR-0{i}" for i in range(1, 9)]


def test_parse_mensajes_workflow():
    c, f = _parse_mensajes(['{"tipo":"carta_fianza","confianza":0.9,"motivo":"x"}', '{"numero":"CF-1"}'])
    assert c["tipo"] == "carta_fianza" and f == {"numero": "CF-1"}
    c, f = _parse_mensajes(['{"tipo":"otro","confianza":0.9,"motivo":"x"}', "FUERA_DE_ALCANCE"])
    assert f is None


def test_sql_es_idempotente_en_texto():
    sql = (RAIZ / "dataplane" / "sql" / "001_schema.sql").read_text()
    assert "CREATE TABLE doc." not in sql and "CREATE EXTENSION IF NOT EXISTS vector" in sql
