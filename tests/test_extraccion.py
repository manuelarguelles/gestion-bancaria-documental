import importlib.util
import shutil
from pathlib import Path

import pytest

from gbd.dataplane.extraccion import extraer_pdf

RAIZ = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="requiere tesseract")


@pytest.fixture(scope="module")
def bandeja(tmp_path_factory):
    d = tmp_path_factory.mktemp("muestras")
    spec = importlib.util.spec_from_file_location("gen", RAIZ / "dataplane" / "generar_muestras.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.main(d)
    return d / "bandeja"


def test_nativo_no_usa_ocr_y_conserva_orden(bandeja):
    e = extraer_pdf(bandeja / "CF-2026-0001.pdf", vision=False)
    assert e.metodo == "nativo" and e.confianza_min is None
    assert e.texto.index("CARTA FIANZA") < e.texto.index("Ordenante") < e.texto.index("Vigencia")


def test_escaneo_limpio_se_lee_con_ocr(bandeja):
    e = extraer_pdf(bandeja / "CF-2026-0012.pdf", vision=False)
    assert e.metodo == "ocr" and e.confianza_min > 85
    assert "CF-2026-0012" in e.texto and "130,000.00" in e.texto


def test_escaneo_degradado_recupera_todas_las_lineas(bandeja):
    e = extraer_pdf(bandeja / "CF-2026-0013.pdf", vision=False)
    assert e.metodo == "ocr"
    for clave in ("Applicant", "Amount", "87,500.25", "2027-06-01", "Cajamarca"):
        assert clave in e.texto, clave


def test_mixto_recupera_el_texto_del_sello(bandeja):
    e = extraer_pdf(bandeja / "CF-2026-0014.pdf", vision=False)
    assert e.metodo == "nativo+ocr" and "RECIBIDO" in e.texto and "Fecha de vencimiento: 09/03/2027" in e.texto


def test_ocr_deshabilitado_deja_el_escaneo_vacio(bandeja):
    e = extraer_pdf(bandeja / "CF-2026-0012.pdf", ocr=False)
    assert e.texto == "" and "OCR deshabilitado" in e.paginas[0].notas
