"""Genera documentos sintéticos (PDF + Excel) con anomalías plantadas y la verdad esperada.

Todo es ficticio. Fecha de corte de referencia: 2026-10-16.
Uso: python dataplane/generar_muestras.py [directorio_salida]
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

CORTE = date(2026, 10, 16)
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre",
         "octubre", "noviembre", "diciembre"]

# numero, ordenante, beneficiario, monto, moneda, emision, vence, plantilla, (override registro), esperado
CARTAS = [
    ("CF-2026-0001", "Constructora Inca SAC", "Municipalidad Provincial de Trujillo", 150000.00, "PEN", date(2026, 3, 15), date(2027, 3, 15), "A", {}, []),
    ("CF-2026-0002", "Agroexport del Norte SA", "Ministerio de Desarrollo Agrario", 80000.00, "USD", date(2026, 1, 20), date(2027, 1, 20), "B", {}, []),
    ("CF-2026-0003", "Transportes Chimú SRL", "Gobierno Regional La Libertad", 45000.50, "PEN", date(2026, 6, 30), date(2026, 12, 31), "C", {}, ["DUPLICADA"]),
    ("CF-2026-0004", "Metalmecánica Andina SAC", "Empresa Regional de Agua Potable", 250000.00, "PEN", date(2026, 5, 2), date(2027, 5, 2), "A", {"monto": 205000.00}, ["MONTO_DISTINTO"]),
    ("CF-2026-0005", "Inversiones Pacífico SA", "Universidad Nacional de Trujillo", 30000.00, "PEN", date(2026, 7, 10), date(2027, 1, 10), "B", None, ["NO_EN_TESORERIA"]),
    ("CF-2026-0006", "Servicios Logísticos del Sur SAC", "Municipalidad Distrital de Víctor Larco", 72000.00, "PEN", date(2025, 9, 30), date(2026, 9, 30), "C", {}, ["VENCIDA"]),
    ("CF-2026-0007", "Textiles Moche SA", "Hospital Regional Docente", 18500.00, "PEN", date(2026, 5, 5), date(2026, 11, 5), "A", {}, ["POR_VENCER"]),
    ("CF-2026-0008", "Pesquera Salaverry SAC", "Ministerio de la Producción", 60000.00, "USD", date(2026, 4, 12), date(2027, 4, 12), "B", {"moneda": "PEN"}, ["MONEDA_DISTINTA"]),
    ("CF-2026-0009", "Ingeniería y Obras Norte SRL", "Proyecto Especial Chavimochic", 410000.00, "PEN", date(2026, 8, 1), date(2027, 6, 30), "C", {"fecha_vencimiento": date(2027, 5, 30)}, ["VENCIMIENTO_DISTINTO"]),
    ("CF-2026-0010", "Distribuidora Libertad SAC", "Seguro Social de Salud", 95000.00, "PEN", date(2026, 2, 14), date(2027, 2, 14), "A", {}, []),
]
SIN_CARTA = ("CF-2026-0011", "Agrícola Virú SA", "Gobierno Regional La Libertad", 120000.00, "PEN", date(2027, 2, 28))


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def monto_txt(plantilla: str, monto: float, moneda: str) -> str:
    if plantilla == "A":
        return f"{'S/' if moneda == 'PEN' else 'US$'} {monto:,.2f}"
    if plantilla == "B":
        return f"{moneda} {monto:,.2f}"
    s = f"{monto:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {'soles' if moneda == 'PEN' else 'dólares americanos'}"


def pdf_carta(path: Path, c: tuple) -> None:
    numero, orden, benef, monto, mon, emi, vence, pl, _, _ = c
    cv = canvas.Canvas(str(path), pagesize=A4)
    y = 800

    def linea(t, size=11, dy=18):
        nonlocal y
        cv.setFont("Helvetica", size)
        cv.drawString(60, y, t)
        y -= dy

    linea("BANCO ANDINO DEMO S.A. (entidad ficticia)", 13, 28)
    if pl == "A":
        linea(f"CARTA FIANZA N° {numero}", 14, 26)
        linea(f"Lugar y fecha: Trujillo, {fecha_larga(emi)}")
        linea(f"Ordenante: {orden}")
        linea(f"Beneficiario: {benef}")
        linea(f"Importe afianzado: {monto_txt(pl, monto, mon)}")
        linea(f"Vigencia: desde el {fecha_larga(emi)} hasta el {fecha_larga(vence)}")
        linea("Tipo de garantia: Fiel cumplimiento", dy=26)
        linea("El Banco se constituye en fiador solidario, irrevocable, incondicional y de realización")
        linea("automática a primer requerimiento del beneficiario.")
    elif pl == "B":
        linea("STANDBY / LETTER OF GUARANTEE (Carta Fianza)", 13, 24)
        linea(f"Ref: {numero}")
        linea(f"Issue date: {emi.isoformat()}")
        linea(f"Applicant: {orden}")
        linea(f"Beneficiary: {benef}")
        linea(f"Amount: {monto_txt(pl, monto, mon)}")
        linea(f"Expiry date: {vence.isoformat()}", dy=26)
        linea("Garantia de adelanto directo / Advance payment guarantee")
        linea("Esta garantía es irrevocable y pagadera a primera demanda.")
    else:
        linea("GARANTÍA BANCARIA — CARTA FIANZA", 13, 24)
        linea(f"Nro. de garantía: {numero}")
        linea(f"Emitida en Trujillo el {emi.strftime('%d/%m/%Y')} a solicitud de {orden}")
        linea(f"a favor de {benef}")
        linea(f"por la suma de {monto_txt(pl, monto, mon)}", dy=22)
        linea(f"Fecha de vencimiento: {vence.strftime('%d/%m/%Y')}")
        linea("Modalidad: Fiel cumplimiento de contrato", dy=26)
        linea("Fianza solidaria, irrevocable, incondicional y de ejecución inmediata.")
    y -= 40
    linea("p. Banco Andino Demo S.A. — firma autorizada (documento sintético de ejemplo)", 9)
    cv.save()


def pdf_texto(path: Path, titulo: str, lineas: list[str]) -> None:
    cv = canvas.Canvas(str(path), pagesize=A4)
    cv.setFont("Helvetica-Bold", 13)
    cv.drawString(60, 800, titulo)
    cv.setFont("Helvetica", 11)
    y = 770
    for t in lineas:
        cv.drawString(60, y, t)
        y -= 18
    cv.save()


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    bandeja = out / "bandeja"
    bandeja.mkdir(exist_ok=True)
    esperado: dict = {"fecha_corte": CORTE.isoformat(), "documentos": {}, "conciliacion": {}}

    for c in CARTAS:
        pdf_carta(bandeja / f"{c[0]}.pdf", c)
        esperado["documentos"][f"{c[0]}.pdf"] = "carta_fianza"
        esperado["conciliacion"][c[0]] = c[9]
    # Duplicado de la 0003 (mismo número, archivo distinto -> distinto sha256)
    dup = list(CARTAS[2])
    dup[5] = date(2026, 6, 30)
    pdf_carta(bandeja / "CF-2026-0003_reenvio.pdf", tuple(dup))
    esperado["documentos"]["CF-2026-0003_reenvio.pdf"] = "carta_fianza"

    pdf_texto(bandeja / "oficio_liberacion_0099.pdf", "OFICIO DE LIBERACIÓN DE GARANTÍA", [
        "Trujillo, 3 de octubre de 2026",
        "Se comunica la liberación de la carta fianza N° CF-2025-0099 a favor de Obras Civiles del Norte SAC.",
        "Atentamente, Área de Garantías del beneficiario."])
    esperado["documentos"]["oficio_liberacion_0099.pdf"] = "liberacion_garantia"
    pdf_texto(bandeja / "factura_proveedor_F001-4521.pdf", "FACTURA ELECTRÓNICA F001-4521", [
        "Proveedor: Papelera Trujillo SAC", "Concepto: útiles de oficina", "Total: S/ 1,180.00 (incluye IGV)"])
    esperado["documentos"]["factura_proveedor_F001-4521.pdf"] = "otro"

    wb = Workbook()
    ws = wb.active
    ws.title = "Garantias"
    ws.append(["N° Garantía", "Ordenante", "Beneficiario", "Monto", "Moneda", "Vencimiento", "Estado"])
    for c in CARTAS:
        if c[8] is None:
            continue
        ov = c[8]
        ws.append([c[0], c[1], c[2], ov.get("monto", c[3]), ov.get("moneda", c[4]),
                   ov.get("fecha_vencimiento", c[6]), "VIGENTE"])
    s = SIN_CARTA
    ws.append([s[0], s[1], s[2], s[3], s[4], s[5], "VIGENTE"])
    esperado["conciliacion"][s[0]] = ["SIN_CARTA"]
    wb.save(out / "registro_tesoreria.xlsx")

    (out / "esperado.json").write_text(json.dumps(esperado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"muestras en {out}: {len(list(bandeja.glob('*.pdf')))} PDF + registro_tesoreria.xlsx")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "samples")
