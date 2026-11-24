from pathlib import Path

import openpyxl
import pytest

import productos
import server

ENC = ["#", "Sistema", "Referencia (Odoo)", "Nombre corto (ficha)", "Marca (sigla)", "Voltaje",
       "Bloque en CAD (sugerido, por confirmar)", "Nombre en Odoo", "Campos inventados (PRUEBA)"]
FILAS = [
    [1, "Iluminación", "AAA1", "Downlight uno", "TG", "220 Vac", "58a", "DL UNO 9W", "Ninguno (datos de la hoja original)"],
    [2, "Iluminación", "AAA2", "Downlight dos", "TG", "N/A", None, "DL DOS 12W", "Voltaje, Driver"],
    [3, "Audio", "SIN REFERENCIA", "Parlante sin ref", "SN", "N/A", "ohm", "PARLANTE X", "Ninguno (datos de la hoja original)"],
    [4, "Audio", "SIN REFERENCIA", "Otro sin ref", "SN", "12 V", "  ", "PARLANTE Y", "Voltaje"],
    [5, "Control", "CCC1", "Keypad", "LU", "24 V", "kp", "KEYPAD 1", "Ninguno (datos de la hoja original)"],
    [6, "Control", "CCC1", "Keypad repetido", "LU", "24 V", "kp", "KEYPAD 2", "Ninguno (datos de la hoja original)"],
]


@pytest.fixture
def hoja(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Leeme"
    ws = wb.create_sheet("Productos")
    ws.append(ENC)
    for f in FILAS:
        ws.append(f)
    ruta = tmp_path / "hoja.xlsx"
    wb.save(ruta)
    return ruta


@pytest.fixture
def prods(hoja):
    return productos.cargar(hoja)


def test_carga_filas_y_numero_de_fila(prods):
    enc, p = prods
    assert len(p) == 6 and p[0]["_fila"] == 2 and p[-1]["_fila"] == 7


def test_na_es_valor_valido_no_vacio(prods):
    enc, p = prods
    assert p[1]["Voltaje"] == "N/A"
    r = productos.validar(p, enc)
    fila2 = next(d for d in r["detalle"] if d["fila_excel"] == 3)
    assert "Voltaje" not in fila2["campos_vacios"]


def test_vacios_reales_incluye_solo_espacios(prods):
    enc, p = prods
    r = productos.validar(p, enc)
    vacio = {d["fila_excel"]: d["campos_vacios"] for d in r["detalle"]}
    assert "Bloque en CAD (sugerido, por confirmar)" in vacio[3]   # None
    assert "Bloque en CAD (sugerido, por confirmar)" in vacio[5]   # solo espacios


def test_validar_sin_referencia_y_repetidas(prods):
    enc, p = prods
    r = productos.validar(p, enc)
    assert r["sin_referencia"] == 2
    assert r["referencias_repetidas"] == {"CCC1": [6, 7]}
    assert r["total_productos"] == 6


def test_listar_filtra_sin_tildes_ni_mayusculas(prods):
    _, p = prods
    assert len(productos.listar(p, "ILUMINACION")) == 2
    assert len(productos.listar(p)) == 6
    assert productos.listar(p, "audio")[0].keys() == {"referencia", "nombre_corto", "marca", "sistema"}


def test_buscar_en_referencia_corto_y_odoo(prods):
    _, p = prods
    assert len(productos.buscar(p, "aaa1")) == 1          # referencia
    assert len(productos.buscar(p, "KEYPAD")) == 2        # nombre corto / odoo
    assert len(productos.buscar(p, "parlante y")) == 1    # odoo
    assert productos.buscar(p, "") == []


def test_ficha_avisa_datos_de_prueba(prods):
    _, p = prods
    f = productos.ficha(productos.ver(p, "AAA2")[0])
    assert f["aviso"] == "DATOS DE PRUEBA: Voltaje, Driver"
    assert "aviso" not in productos.ficha(productos.ver(p, "AAA1")[0])


def test_errores_claros(tmp_path):
    with pytest.raises(productos.HojaError, match="ruta_hoja"):
        productos.cargar("")
    with pytest.raises(productos.HojaError, match="No encuentro"):
        productos.cargar(tmp_path / "no_existe.xlsx")


def test_hoja_inexistente_y_columnas_faltantes(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Productos"
    wb.active.append(["#", "Sistema"])
    ruta = tmp_path / "mala.xlsx"
    wb.save(ruta)
    with pytest.raises(productos.HojaError, match="Faltan columnas"):
        productos.cargar(ruta)
    with pytest.raises(productos.HojaError, match="no existe"):
        productos.cargar(ruta, hoja="Otra")


def test_herramientas_del_servidor(hoja, monkeypatch):
    monkeypatch.setitem(server.CFG, "productos", {"ruta_hoja": str(hoja), "hoja": "Productos"})
    assert server.listar_productos("audio")["total"] == 2
    uno = server.ver_producto("AAA2")
    assert uno["ok"] and uno["producto"]["aviso"].startswith("DATOS DE PRUEBA")
    dup = server.ver_producto("SIN REFERENCIA")
    assert len(dup["productos"]) == 2 and "aviso" in dup
    assert server.ver_producto("NOEXISTE")["error"] == "no_encontrado"
    assert server.buscar_producto("keypad")["total"] == 2
    assert server.validar_hoja()["productos_con_hallazgos"] >= 4


def test_servidor_con_ruta_mala_devuelve_error_no_excepcion(monkeypatch):
    monkeypatch.setitem(server.CFG, "productos", {"ruta_hoja": "C:/no/existe.xlsx"})
    r = server.listar_productos()
    assert r["ok"] is False and r["error"] == "hoja_no_disponible"


REAL = Path(server.CFG["productos"].get("ruta_hoja") or "x")


@pytest.mark.skipif(not REAL.is_file(), reason="hoja de PRUEBA real no disponible")
def test_hoja_real_de_prueba():
    enc, p = productos.cargar(REAL, server.CFG["productos"]["hoja"])
    assert len(p) == 30
    r = productos.validar(p, enc)
    assert r["sin_referencia"] == 2
