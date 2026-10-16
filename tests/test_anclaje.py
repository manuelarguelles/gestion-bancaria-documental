from gbd.dataplane.anclaje import campos_sin_anclar

BASE = {"numero": "CF-2026-0003", "monto": 45000.5, "fecha_vencimiento": "2026-12-31"}


def test_formatos_de_monto_y_fecha():
    for texto in ("Nro CF-2026-0003 por la suma de 45.000,50 soles. Vence 31/12/2026",
                  "ref CF-2026-0003 Amount: USD 45,000.50 Expiry date: 2026-12-31",
                  "garantía CF 2026 0003 S/ 45000.50 hasta el 31 de diciembre de 2026"):
        assert campos_sin_anclar(BASE, texto) == [], texto


def test_detecta_cifra_mal_leida():
    mal = "Ref CF-2026-0003 Amount: USD 45,000.50 Expiry date: 2026-12-81"
    assert campos_sin_anclar(BASE, mal) == ["fecha_vencimiento"]
    assert "monto" in campos_sin_anclar({**BASE, "monto": 78500.25}, "Ref CF-2026-0003 USD 87,500.25 2026-12-31")


def test_detecta_dato_inventado():
    assert set(campos_sin_anclar(BASE, "documento ilegible sin cifras")) == {"numero", "monto", "fecha_vencimiento"}
