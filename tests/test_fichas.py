from pathlib import Path

import openpyxl
import pytest

import fichas
import productos as P
import server

ENC = ["#", "Sistema", "Referencia (Odoo)", "Nombre corto (ficha)", "Marca (sigla)", "Instalación", "Voltaje", "W por unidad",
       "Tipo de conexión", "Driver", "Bloque en CAD (sugerido, por confirmar)", "Fuente de los datos", "Notas / por confirmar",
       "Nombre en Odoo", "Campos inventados (PRUEBA)"]
ACC_ENC = ["#", "Referencia (Odoo)", "Nombre corto", "Marca", "Tipo", "Aparece junto a (según cotización S00297 / PDF)", "Fuente", "Nombre en Odoo"]


def prod(fila, ref, corto, sis, **kw):
    d = {"_fila": fila, P.REF: ref, P.CORTO: corto, P.SISTEMA: sis, P.MARCA: "DG", "Voltaje": "N/A", "W por unidad": "N/A", "Driver": "N/A",
         "Instalación": "Cielo raso", "Tipo de conexión": None, P.BLOQUE: "58a", P.ODOO: "NOMBRE ODOO", P.INVENTADOS: "Voltaje, Driver",
         "Fuente de los datos": "Ficha L1", "Notas / por confirmar": None}
    d.update(kw)
    return d


ACCS = [
    {"referencia": "D1", "nombre_corto": "Driver 24 V", "marca": "DG", "tipo": "Driver", "junto_a": "NULLA", "fuente": None, "nombre_odoo": None},
    {"referencia": "D2", "nombre_corto": "Driver 500 mA", "marca": "DG", "tipo": "Driver", "junto_a": "MIRA R, ASINTOTO", "fuente": None, "nombre_odoo": None},
    {"referencia": "D3", "nombre_corto": "Perfil", "marca": "—", "tipo": "Perfil", "junto_a": "CINTA LED", "fuente": None, "nombre_odoo": None},
    {"referencia": "D4", "nombre_corto": "Driver 100W", "marca": "Dur", "tipo": "Driver", "junto_a": "CINTA LED; ECLIPSE (ficha L4)", "fuente": None, "nombre_odoo": None},
    {"referencia": "D5", "nombre_corto": "Controlador", "marca": "DG", "tipo": "Controlador", "junto_a": "INFINITO, MAGIA", "fuente": None, "nombre_odoo": None},
]


# ---------- accesorios ----------
def test_accesorios_se_enlazan_por_nombre_sin_tildes_ni_parentesis():
    refs = lambda nombre: sorted(a["referencia"] for a in P.accesorios_de({P.CORTO: nombre}, ACCS))  # noqa: E731
    assert refs("NULLA") == ["D1"]
    assert refs("MIRA R (negro)") == ["D2"]
    assert refs("Asintoto".upper()) == ["D2"]
    assert refs("CINTA LED 45W 24V IP20") == ["D3", "D4"]
    assert refs("ECLIPSE") == ["D4"]                        # "(ficha L4)" se ignora
    assert refs("INFINITO 12") == ["D5"] and refs("MAGIA SIDE") == ["D5"]
    assert refs("DOT PL 51") == [] and refs(None) == []


def test_cargar_accesorios_desde_excel(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Productos"
    ws = wb.create_sheet("Drivers y accesorios")
    ws.append(ACC_ENC)
    ws.append([1, "1Z0241270.24", "Driver 24 V", "DG", "Driver", "NULLA", "Ficha L3", "Driver - X"])
    ws.append([None] * 8)
    ruta = tmp_path / "h.xlsx"
    wb.save(ruta)
    a = P.cargar_accesorios(ruta)
    assert len(a) == 1 and a[0]["referencia"] == "1Z0241270.24" and a[0]["junto_a"] == "NULLA" and a[0]["tipo"] == "Driver"
    assert P.cargar_accesorios(ruta, hoja="No existe") == []   # opcional


# ---------- contenido de la ficha ----------
def test_extras_son_estables_y_siempre_inventados():
    p = prod(2, "AAA1", "NULLA", "Iluminación")
    assert fichas.extras_inventados(p) == fichas.extras_inventados(dict(p))
    for sis in ("Iluminación", "Cinta LED", "Audio", "Control", "Redes", "Otro"):
        f = fichas.armar_ficha(prod(2, "X", "Algo", sis), [], "DL-TEST-X")
        assert f["adicionales"] and all(c["inventado"] for c in f["adicionales"])


def test_ficha_marca_lo_inventado_y_el_dato_vacio():
    f = fichas.armar_ficha(prod(2, "AAA1", "NULLA", "Iluminación"), ACCS, "DL-TEST-ILUMINACION")
    tec = {c["nombre"]: c for c in f["tecnicos"]}
    assert tec["Voltaje"]["inventado"] and tec["Driver"]["inventado"]            # estan en 'Campos inventados'
    assert tec["Voltaje"]["valor"] == "N/A"                                      # N/A es un valor valido
    assert not tec["Instalación"]["inventado"]
    assert tec["Tipo de conexión"]["valor"] == fichas.SIN_DATO and tec["Tipo de conexión"]["vacio"] and not tec["Tipo de conexión"]["inventado"]
    assert f["es_prueba"] and f["total_campos_inventados"] == 2 + len(f["adicionales"])
    assert [a["referencia"] for a in f["accesorios"]] == ["D1"]


def test_nunca_inventa_referencia_ni_bloque():
    f = fichas.armar_ficha(prod(3, "SIN REFERENCIA", "ECLIPSE", "Iluminación", **{P.BLOQUE: None}), [], "DL-TEST-ILUMINACION")
    assert f["cad"]["bloques"] == [] and f["referencia"] == "SIN REFERENCIA"
    assert f["identificacion"][0]["valor"] == "SIN REFERENCIA" and not f["identificacion"][0]["inventado"]


# ---------- HTML ----------
def test_html_marca_prueba_escapa_y_muestra_sin_dato():
    f = fichas.armar_ficha(prod(2, "A<1>", "<script>alert(1)</script>", "Iluminación", **{P.BLOQUE: None}), ACCS, "DL-TEST-ILUMINACION")
    h = fichas.html_ficha(f)
    assert "<script>" not in h and "&lt;script&gt;" in h and "A&lt;1&gt;" in h
    assert "FICHA DE PRUEBA" in h and 'class="inv"' in h and "sin bloque asignado" in h and "sin dato" in h
    assert 'href="indice.html"' in h


def test_nombre_de_archivo_no_permite_escapar_de_la_carpeta():
    f = {"fila_excel": 7, "referencia": "../../..\\evil/x"}
    n = fichas.nombre_archivo(f)
    assert n == "fila07_..-..-..-evil-x.html"            # separadores de ruta reemplazados
    assert Path(n).name == n and "/" not in n and "\\" not in n


def test_generar_escribe_solo_en_la_carpeta(tmp_path):
    lista = [fichas.armar_ficha(prod(2, "AAA1", "NULLA", "Iluminación"), ACCS, "C"),
             fichas.armar_ficha(prod(3, "../../evil", "Otro", "Audio"), [], "C")]
    r = fichas.generar(lista, tmp_path / "salida")
    archivos = sorted(x.name for x in (tmp_path / "salida").iterdir())
    assert "indice.html" in archivos and len(archivos) == 3
    assert not (tmp_path / "evil.html").exists() and not list(tmp_path.glob("*.html"))
    assert (tmp_path / "salida" / "indice.html").read_text(encoding="utf-8").count("<a href=") == 2
    assert [x["fila_excel"] for x in r["fichas"]] == [2, 3]


# ---------- herramientas del servidor ----------
@pytest.fixture
def hoja(tmp_path, monkeypatch):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Productos"
    ws.append(ENC)
    base = {"#": 1, "Sistema": "Iluminación", "Marca (sigla)": "DG", "Instalación": "Cielo", "Voltaje": "N/A", "W por unidad": "N/A",
            "Tipo de conexión": "DALI", "Driver": "N/A", "Bloque en CAD (sugerido, por confirmar)": "58a", "Fuente de los datos": "Ficha",
            "Notas / por confirmar": None, "Nombre en Odoo": "X", "Campos inventados (PRUEBA)": "Ninguno (datos de la hoja original)"}
    for ref, corto in [("AAA1", "NULLA"), ("SIN REFERENCIA", "ECLIPSE"), ("SIN REFERENCIA", "SHADOW LAMP"), ("CCC1", "MIRA R")]:
        ws.append([{**base, "Referencia (Odoo)": ref, "Nombre corto (ficha)": corto}[h] for h in ENC])
    wa = wb.create_sheet("Drivers y accesorios")
    wa.append(ACC_ENC)
    wa.append([1, "D1", "Driver 24 V", "DG", "Driver", "NULLA", "F", "X"])
    ruta = tmp_path / "h.xlsx"
    wb.save(ruta)
    monkeypatch.setitem(server.CFG, "productos", {"ruta_hoja": str(ruta), "hoja": "Productos", "hoja_accesorios": "Drivers y accesorios"})
    monkeypatch.setitem(server.CFG, "fichas", {"carpeta": str(tmp_path / "fichas")})
    return tmp_path


def test_ver_ficha(hoja):
    r = server.ver_ficha("aaa1")
    assert r["ok"] and r["ficha"]["nombre_corto"] == "NULLA" and [a["referencia"] for a in r["ficha"]["accesorios"]] == ["D1"]
    assert r["ficha"]["cad"]["capa_sugerida"] == "DL-TEST-ILUMINACION"
    assert server.ver_ficha("NOEXISTE")["error"] == "no_encontrado"
    assert server.ver_ficha("SIN REFERENCIA")["error"] == "referencia_ambigua"
    assert server.ver_ficha("SIN REFERENCIA", fila_excel=3)["ficha"]["nombre_corto"] == "ECLIPSE"


def test_generar_todas(hoja):
    r = server.generar_fichas()
    assert r["ok"] and r["total"] == 4 and r["con_accesorios"] == 1 and r["con_datos_inventados"] == 4
    assert len(list((hoja / "fichas").glob("fila*.html"))) == 4 and (hoja / "fichas" / "indice.html").exists()


def test_generar_algunas_todo_o_nada(hoja):
    r = server.generar_fichas(referencias=["AAA1"], filas_excel=[3, 3])
    assert r["ok"] and r["total"] == 2                       # AAA1 + fila 3, sin repetir
    malo = server.generar_fichas(referencias=["AAA1", "NOEXISTE", "SIN REFERENCIA"], filas_excel=[99])
    assert malo["error"] == "items_con_problemas" and len(malo["problemas"]) == 3


def test_generar_sin_carpeta_o_hoja_mala(hoja, monkeypatch):
    monkeypatch.setitem(server.CFG, "fichas", {})
    assert server.generar_fichas()["error"] == "sin_carpeta"
    monkeypatch.setitem(server.CFG, "productos", {"ruta_hoja": "C:/no/existe.xlsx"})
    assert server.generar_fichas()["error"] == "hoja_no_disponible"
