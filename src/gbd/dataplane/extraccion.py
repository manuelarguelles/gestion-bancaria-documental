"""Extracción de texto de PDF con recuperación máxima, en capas.

    1. NATIVO  — PyMuPDF por bloques, en orden de lectura (y, x). Gratis y exacto cuando hay capa de texto.
    2. OCR     — Tesseract (spa+eng) sobre la página renderizada, con corrección de giro y de inclinación.
                 Se usa si la página casi no tiene texto nativo o si es mayormente una imagen.
    3. VISIÓN  — el modelo del proyecto Foundry transcribe la imagen. Solo si la confianza del OCR es baja.

Cada página registra con qué método se leyó y con qué confianza: la trazabilidad es parte del resultado.
En páginas mixtas (texto nativo + sello o imagen) se conserva el texto nativo y se agregan las líneas
que solo el OCR vio.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf
import pytesseract
from PIL import Image, ImageFilter, ImageOps

from .reglas import norm

log = logging.getLogger("gbd.extraccion")

MIN_CHARS_NATIVO = 80      # menos que esto => la página no tiene capa de texto útil
MAX_RATIO_IMAGEN = 0.40    # más de esta fracción del área cubierta por imágenes => revisar con OCR
MIN_RATIO_IMAGEN_REGION = 0.003  # imágenes incrustadas menores que esto (iconos, rayas) se ignoran
DPI_OCR = 300
CONFIANZA_MIN_OCR = 70.0   # por debajo => se pide visión (si está habilitada)
DPI_MIN_CONFIABLE = 150    # imagen escaneada por debajo de esto => el OCR puede errar con seguridad: se usa visión
PALABRA_FIABLE = 60.0      # una palabra cuenta como leída si Tesseract le da al menos esta confianza


@dataclass
class Pagina:
    numero: int
    metodo: str                      # nativo | ocr | nativo+ocr | vision
    texto: str
    bloques: int = 0
    confianza: float | None = None   # solo OCR (0-100)
    notas: list[str] = field(default_factory=list)


@dataclass
class Extraccion:
    archivo: str
    texto: str
    paginas: list[Pagina]

    @property
    def metodo(self) -> str:
        return "+".join(sorted({p.metodo for p in self.paginas})) or "vacio"

    @property
    def confianza_min(self) -> float | None:
        c = [p.confianza for p in self.paginas if p.confianza is not None]
        return min(c) if c else None


# --------------------------------------------------------------------------- nativo

def _bloques_nativos(page: pymupdf.Page) -> list[str]:
    """Bloques de texto en orden de lectura, sin bloques vacíos ni de imagen."""
    bloques = page.get_text("blocks", sort=True)
    return [b[4].strip() for b in bloques if b[6] == 0 and b[4].strip()]


def _ratio_imagen(page: pymupdf.Page) -> float:
    area = page.rect.width * page.rect.height
    if area <= 0:
        return 0.0
    cubierto = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        cubierto += max(r.width, 0) * max(r.height, 0)
    return min(cubierto / area, 1.0)


# --------------------------------------------------------------------------- OCR

_TESSDATA_LOCAL = Path.home() / ".local" / "share" / "tessdata-gbd"


def _idioma() -> str:
    if "TESSDATA_PREFIX" not in os.environ:
        d = os.getenv("GBD_TESSDATA") or (str(_TESSDATA_LOCAL) if _TESSDATA_LOCAL.is_dir() else "")
        if d:
            os.environ["TESSDATA_PREFIX"] = d
    langs = set(pytesseract.get_languages(config=""))
    if "spa" in langs:
        return "spa+eng" if "eng" in langs else "spa"
    log.warning("Tesseract sin idioma 'spa': se usa 'eng' (acentos y ñ se degradan)")
    return "eng"


def ocr_disponible() -> bool:
    return shutil.which("tesseract") is not None


def _renderizar(page: pymupdf.Page, dpi: int = DPI_OCR) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def _corregir_giro(img: Image.Image) -> tuple[Image.Image, int]:
    """Rotación en múltiplos de 90° detectada por OSD de Tesseract (si no hay señal suficiente, no toca)."""
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=20",
                                       output_type=pytesseract.Output.DICT)
        giro = int(osd.get("rotate", 0))
    except pytesseract.TesseractError:
        return img, 0
    if giro:
        img = img.rotate(-giro, expand=True, fillcolor=255)
    return img, giro


def _angulo_inclinacion(img: Image.Image, rango: float = 4.0, paso: float = 0.5) -> float:
    """Ángulo (grados) que maximiza la nitidez de las líneas de texto (perfil de proyección horizontal)."""
    chico = ImageOps.autocontrast(img).copy()
    chico.thumbnail((900, 900))
    a = (np.asarray(chico) < 128).astype(np.float32)
    if a.sum() < 50:
        return 0.0
    mejor, mejor_s = 0.0, -1.0
    for ang in np.arange(-rango, rango + paso, paso):
        r = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).rotate(ang, resample=Image.BILINEAR, fillcolor=0))
        s = float(np.var(r.sum(axis=1)))
        if s > mejor_s:
            mejor, mejor_s = float(ang), s
    return mejor


def _preprocesar(img: Image.Image) -> tuple[Image.Image, list[str]]:
    notas: list[str] = []
    img, giro = _corregir_giro(img)
    if giro:
        notas.append(f"giro {giro}°")
    ang = _angulo_inclinacion(img)
    if abs(ang) >= 0.5:
        img = img.rotate(ang, resample=Image.BICUBIC, expand=True, fillcolor=255)
        notas.append(f"enderezado {ang:+.1f}°")
    img = ImageOps.autocontrast(img, cutoff=1)
    return img, notas


def _ocr_imagen(img: Image.Image, lang: str) -> tuple[str, float, int]:
    """Mejor segmentación (bloque único o columnas). Devuelve (texto, confianza media, palabras fiables)."""
    mejor: tuple[str, float, int] = ("", 0.0, -1)
    for psm in (6, 4):
        d = pytesseract.image_to_data(img, lang=lang, config=f"--oem 1 --psm {psm}",
                                      output_type=pytesseract.Output.DICT)
        lineas: dict[tuple[int, int, int], list[str]] = {}
        confs: list[float] = []
        for i, palabra in enumerate(d["text"]):
            if not palabra.strip():
                continue
            c = float(d["conf"][i])
            if c < 0:
                continue
            confs.append(c)
            lineas.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(palabra)
        texto = "\n".join(" ".join(p) for _, p in sorted(lineas.items()))
        media = float(np.mean(confs)) if confs else 0.0
        fiables = sum(c >= PALABRA_FIABLE for c in confs)
        if (fiables, media) > (mejor[2], mejor[1]):
            mejor = (texto, media, fiables)
    return mejor


def _umbral_otsu(a: np.ndarray) -> int:
    h, _ = np.histogram(a, bins=256, range=(0, 256))
    total, suma = a.size, float(np.dot(np.arange(256), h))
    acum_w = acum_s = mejor_v = 0.0
    umbral = 127
    for i in range(256):
        acum_w += h[i]
        if acum_w == 0:
            continue
        w_f = total - acum_w
        if w_f == 0:
            break
        acum_s += i * h[i]
        v = acum_w * w_f * (acum_s / acum_w - (suma - acum_s) / w_f) ** 2
        if v > mejor_v:
            mejor_v, umbral = v, i
    return umbral


def _variantes(img: Image.Image) -> dict[str, Image.Image]:
    """Preprocesados alternativos. Un escaneo malo se lee mejor con uno u otro, y no se sabe cuál de antemano."""
    a = np.asarray(img)
    med = np.asarray(img.filter(ImageFilter.MedianFilter(3)))
    return {
        "base": img,
        "mediana+binarizado": Image.fromarray(((med > _umbral_otsu(med)) * 255).astype(np.uint8)),
        "reducido 0.6x": img.resize((int(img.width * 0.6), int(img.height * 0.6)), Image.LANCZOS),
        "binarizado": Image.fromarray(((a > _umbral_otsu(a)) * 255).astype(np.uint8)),
    }


def _mejor_ocr(img: Image.Image, lang: str) -> tuple[str, float, int, str]:
    """Corre todas las variantes y se queda con la que lee más palabras fiables (no la de mayor confianza media:
    una variante que ignora la mitad de la página puede reportar 94 % de confianza)."""
    mejor: tuple[str, float, int, str] = ("", 0.0, -1, "base")
    for nombre, v in _variantes(img).items():
        texto, conf, fiables = _ocr_imagen(v, lang)
        if (fiables, conf) > (mejor[2], mejor[1]):
            mejor = (texto, conf, fiables, nombre)
    return mejor


def _vision(img: Image.Image) -> str:
    """Transcripción con el modelo multimodal del proyecto Foundry (import perezoso: requiere configuración)."""
    from ..config import settings
    from ..foundry import openai_client

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    r = openai_client().responses.create(
        model=settings().model,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": "Transcribe fielmente TODO el texto de este documento bancario, "
                                           "línea por línea, sin resumir ni corregir cifras. Solo el texto."},
            {"type": "input_image", "image_url": url}]}])
    return r.output_text.strip()


def _dpi_efectivo(page: pymupdf.Page) -> float | None:
    """Resolución real de la imagen de mayor tamaño de la página (píxeles de la imagen / pulgadas que ocupa)."""
    mayor, dpi = 0.0, None
    for info in page.get_image_info():
        ancho_pt = pymupdf.Rect(info["bbox"]).width
        if ancho_pt > mayor and info.get("width"):
            mayor, dpi = ancho_pt, info["width"] / (ancho_pt / 72)
    return dpi


def _regiones_imagen(page: pymupdf.Page) -> list[pymupdf.Rect]:
    area = page.rect.width * page.rect.height
    out = []
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if not r.is_empty and (r.width * r.height) / area >= MIN_RATIO_IMAGEN_REGION:
            out.append(r)
    return out


def _ocr_regiones(page: pymupdf.Page, regiones: list[pymupdf.Rect], lang: str) -> tuple[list[str], list[str]]:
    """OCR solo sobre las imágenes incrustadas (sellos, firmas, recortes) de una página que ya tiene texto."""
    lineas: list[str] = []
    notas: list[str] = []
    for r in regiones:
        pix = page.get_pixmap(clip=r, dpi=DPI_OCR, colorspace=pymupdf.csGRAY, alpha=False)
        img = ImageOps.autocontrast(Image.frombytes("L", (pix.width, pix.height), pix.samples), cutoff=1)
        texto, _conf, fiables, variante = _mejor_ocr(img, lang)
        notas.append(f"región {int(r.width)}x{int(r.height)}pt · {fiables} palabras fiables ({variante})")
        lineas += [ln for ln in texto.splitlines() if ln.strip()]
    return lineas, notas


def _lineas_nuevas(nativo: str, ocr: str) -> list[str]:
    base = norm(nativo)
    return [ln for ln in ocr.splitlines() if len(norm(ln)) >= 4 and norm(ln) not in base]


# --------------------------------------------------------------------------- API

def extraer_pagina(page: pymupdf.Page, *, ocr: bool = True, vision: bool | None = None,
                   forzar_vision: bool = False) -> Pagina:
    nativo = _bloques_nativos(page)
    texto_nativo = "\n".join(nativo)
    chars = len(texto_nativo.replace("\n", "").replace(" ", ""))
    ratio = _ratio_imagen(page)
    necesita_ocr = chars < MIN_CHARS_NATIVO or ratio > MAX_RATIO_IMAGEN

    regiones = [] if necesita_ocr else _regiones_imagen(page)
    if not (necesita_ocr or regiones) or not ocr or not ocr_disponible():
        notas = [] if not (necesita_ocr or regiones) else ["OCR deshabilitado"] if not ocr else ["sin OCR disponible"]
        return Pagina(page.number + 1, "nativo", texto_nativo, len(nativo), None, notas)

    lang = _idioma()
    if regiones:  # texto nativo suficiente + imágenes incrustadas: se lee lo nativo y se suma el texto de las imágenes
        extra, notas = _ocr_regiones(page, regiones, lang)
        extra = _lineas_nuevas(texto_nativo, "\n".join(extra))
        if not extra:
            return Pagina(page.number + 1, "nativo", texto_nativo, len(nativo), None, notas + ["imágenes sin texto nuevo"])
        return Pagina(page.number + 1, "nativo+ocr", "\n".join([texto_nativo, *extra]).strip(), len(nativo), None,
                      notas + [f"+{len(extra)} líneas solo de imágenes"])

    img, notas = _preprocesar(_renderizar(page))
    texto_ocr, conf, fiables, variante = _mejor_ocr(img, lang)
    notas.insert(0, f"imagen {ratio:.0%} · nativo {chars} car.")
    notas.append(f"variante '{variante}' · {fiables} palabras fiables")

    usar_vision = (os.getenv("GBD_VISION", "1") == "1") if vision is None else vision
    dpi = _dpi_efectivo(page)
    baja_res = dpi is not None and dpi < DPI_MIN_CONFIABLE
    if dpi is not None:
        notas.append(f"resolución efectiva {dpi:.0f} dpi")
    if (conf < CONFIANZA_MIN_OCR or forzar_vision or baja_res) and usar_vision:
        try:
            texto_v = _vision(img)
            if texto_v:
                return Pagina(page.number + 1, "vision", texto_v, len(nativo), conf,
                              notas + [f"OCR {conf:.0f}% → visión (" + ("datos sin anclar" if forzar_vision else
                                                        f"< {DPI_MIN_CONFIABLE} dpi" if baja_res else "OCR bajo") + ")"])
        except Exception as e:  # noqa: BLE001 - la visión es un respaldo: nunca debe tumbar la lectura
            notas.append(f"visión falló: {type(e).__name__}")

    if chars >= MIN_CHARS_NATIVO:  # página mixta: lo nativo manda; el OCR solo suma lo que faltaba
        extra = _lineas_nuevas(texto_nativo, texto_ocr)
        notas.append(f"+{len(extra)} líneas solo del OCR")
        return Pagina(page.number + 1, "nativo+ocr", "\n".join([texto_nativo, *extra]).strip(),
                      len(nativo), conf, notas)
    return Pagina(page.number + 1, "ocr", texto_ocr, len(nativo), conf, notas)


def extraer_pdf(ruta: Path | str, *, ocr: bool = True, vision: bool | None = None,
                forzar_vision: bool = False) -> Extraccion:
    ruta = Path(ruta)
    with pymupdf.open(ruta) as doc:
        paginas = [extraer_pagina(p, ocr=ocr, vision=vision, forzar_vision=forzar_vision) for p in doc]
    texto = "\n\n".join(p.texto for p in paginas if p.texto).strip()
    return Extraccion(ruta.name, texto, paginas)
