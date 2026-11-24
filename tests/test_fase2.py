import math

import pytest

import _probe_bloques as probe
import acad
import productos
import server


# ---------- AutoCAD de mentira (misma forma que COM) ----------
class Bloque:
    ObjectName = "AcDbBlockReference"

    def __init__(self, nombre, capa, x, y, rot=0.0, esc=1.0):
        self.EffectiveName, self.Layer, self.InsertionPoint = nombre, capa, (x, y, 0.0)
        self.Rotation, self.XScaleFactor = rot, esc


class Linea:
    ObjectName, Layer = "AcDbLine", "0"


class Modelo(list):
    @property
    def Count(self):
        return len(self)


class Doc:
    def __init__(self, objs):
        self.ModelSpace = Modelo(objs)

    def GetVariable(self, n):
        return 4  # milimetros


DOC = Doc([Bloque("58a", "L1", 1, 2), Bloque("58A", "L2", 3, 4, math.pi / 2), Bloque("ohm", "L1", 9, 9), Linea(),
           Bloque("58a", "L1", 5, 6)])


def test_analizar_cuenta_por_nombre_y_capa():
    r = probe.analizar(DOC)
    cant = {b["nombre"]: b["cantidad"] for b in r["bloques"]}
    assert cant == {"58a": 2, "58A": 1, "ohm": 1}   # el nombre se respeta tal cual en el dibujo
    assert r["unidades"] == "milimetros" and r["objetos_en_modelo"] == 5 and r["truncado"] is False
    assert r["posiciones"] == {}                    # sin nombres buscados no hay posiciones


def test_analizar_posiciones_sin_distinguir_mayusculas():
    r = probe.analizar(DOC, nombres=["58a"])
    assert sum(len(v) for v in r["posiciones"].values()) == 3
    giro = [p for v in r["posiciones"].values() for p in v if p["capa"] == "L2"][0]
    assert giro["rotacion_grados"] == 90.0 and (giro["x"], giro["y"]) == (3, 4)


def test_analizar_limite_y_max_posiciones():
    r = probe.analizar(DOC, limite=2)
    assert r["objetos_revisados"] == 2 and r["truncado"] is True
    r = probe.analizar(DOC, nombres=["58a"], max_posiciones=1)
    assert all(len(v) == 1 for v in r["posiciones"].values())


def test_dibujo_vacio():
    r = probe.analizar(Doc([]))
    assert r["bloques"] == [] and r["truncado"] is False


# ---------- acad.leer_bloques ----------
def test_leer_bloques_no_lee_si_autocad_no_responde(monkeypatch):
    llamado = []
    monkeypatch.setattr(acad, "estado", lambda t=10: {"ok": False, "error": "autocad_no_responde", "detalle": "x"})
    monkeypatch.setattr(acad, "_correr", lambda *a, **k: llamado.append(1))
    assert acad.leer_bloques()["error"] == "autocad_no_responde" and not llamado


def test_leer_bloques_usa_limite_largo_y_mensaje_propio(monkeypatch):
    visto = {}
    monkeypatch.setattr(acad, "estado", lambda t=10: {"ok": True, "dibujo_activo": "x"})

    def falso(script, timeout, argumentos=None, mensaje_timeout=None):
        visto.update(timeout=timeout, args=argumentos, msg=mensaje_timeout)
        return {"ok": True}

    monkeypatch.setattr(acad, "_correr", falso)
    acad.leer_bloques(nombres=["a"], timeout_lectura_s=60)
    assert visto["timeout"] == 60 and "limite_objetos" in visto["msg"] and '"a"' in visto["args"][0]


def test_leer_bloques_sin_dibujo(monkeypatch):
    monkeypatch.setattr(acad, "estado", lambda t=10: {"ok": True, "dibujo_activo": None})
    assert acad.leer_bloques()["error"] == "sin_dibujo"


# ---------- hoja: nombres de bloque ----------
def test_bloques_cad_separadores_y_vacios():
    assert productos.bloques_cad({productos.BLOQUE: "58a"}) == ["58a"]
    assert productos.bloques_cad({productos.BLOQUE: "ohm, ohm3 ; infi|x"}) == ["ohm", "ohm3", "infi", "x"]
    assert productos.bloques_cad({productos.BLOQUE: "   "}) == []
    assert productos.bloques_cad({productos.BLOQUE: None}) == []


# ---------- herramientas del servidor ----------
@pytest.fixture
def hoja_falsa(monkeypatch):
    prods = [
        {"_fila": 2, productos.REF: "AAA1", productos.CORTO: "Downlight", productos.BLOQUE: "58a"},
        {"_fila": 3, productos.REF: "BBB1", productos.CORTO: "Sin bloque", productos.BLOQUE: None},
        {"_fila": 4, productos.REF: "SIN REFERENCIA", productos.CORTO: "Uno", productos.BLOQUE: "ohm"},
        {"_fila": 5, productos.REF: "SIN REFERENCIA", productos.CORTO: "Dos", productos.BLOQUE: "zzz"},
    ]
    monkeypatch.setattr(server, "_hoja", lambda: ([], prods))


def _fake_leer(monkeypatch, **extra):
    r = {"ok": True, "unidades": "milimetros", "truncado": False,
         "bloques": [{"nombre": "58a", "cantidad": 2, "capas": {"L1": 2}}],
         "posiciones": {"58a": [{"x": 1, "y": 2, "rotacion_grados": 0, "capa": "L1", "escala_x": 1}] * 2}, **extra}
    monkeypatch.setattr(server.acad, "leer_bloques", lambda **k: r)


def test_ubicar_producto_ok(hoja_falsa, monkeypatch):
    _fake_leer(monkeypatch)
    r = server.ubicar_producto("aaa1")
    assert r["ok"] and r["cantidad_en_dibujo"] == {"58a": 2} and len(r["posiciones"]["58a"]) == 2
    assert "por confirmar" in r["aviso"] and r["unidades"] == "milimetros"


def test_ubicar_producto_no_esta_en_el_dibujo(hoja_falsa, monkeypatch):
    _fake_leer(monkeypatch, posiciones={}, bloques=[])
    r = server.ubicar_producto("AAA1")
    assert r["ok"] and r["cantidad_en_dibujo"] == {"58a": 0} and "Ninguno" in r["aviso"]


def test_ubicar_producto_errores_claros(hoja_falsa, monkeypatch):
    _fake_leer(monkeypatch)
    assert server.ubicar_producto("NOEXISTE")["error"] == "no_encontrado"
    assert server.ubicar_producto("BBB1")["error"] == "sin_bloque_asignado"
    amb = server.ubicar_producto("SIN REFERENCIA")
    assert amb["error"] == "referencia_ambigua" and len(amb["filas"]) == 2
    assert server.ubicar_producto("SIN REFERENCIA", fila_excel=4)["ok"] is True


def test_ubicar_producto_propaga_error_de_autocad(hoja_falsa, monkeypatch):
    monkeypatch.setattr(server.acad, "leer_bloques",
                        lambda **k: {"ok": False, "error": "autocad_no_responde", "detalle": "x"})
    r = server.ubicar_producto("AAA1")
    assert r["error"] == "autocad_no_responde" and r["referencia"] == "AAA1"


def test_ubicar_truncado_avisa(hoja_falsa, monkeypatch):
    _fake_leer(monkeypatch, truncado=True)
    assert "incompleta" in server.ubicar_producto("AAA1")["aviso"]


@pytest.mark.autocad
def test_bloques_en_dibujo_con_autocad_abierto():
    r = server.bloques_en_dibujo()
    assert r["ok"] is True and "bloques" in r
