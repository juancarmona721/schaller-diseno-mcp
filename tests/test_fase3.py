import math

import pytest

import sonda_escribir as pe
import productos
import server

MK = lambda x, y, z=0.0: (x, y, z)  # noqa: E731  (punto simple en vez de VARIANT COM)


# ---------- AutoCAD de mentira que registra todo lo que se le escribe ----------
class Coleccion:
    def __init__(self, nombres=()):
        self.nombres = set(nombres)
        self.agregados = []

    def Item(self, n):
        if n not in self.nombres:
            raise KeyError(n)
        return n

    def Add(self, *a):
        self.agregados.append(a)
        nombre = a[-1]
        self.nombres.add(nombre)
        return Bloque()


class Bloque:
    def __init__(self):
        self.hecho = []

    def AddCircle(self, c, r):
        self.hecho.append(("circulo", r))

    def AddText(self, t, p, h):
        self.hecho.append(("texto", t, h))


class Ref:
    Handle = "ABC"
    Layer = None


class Modelo:
    def __init__(self, n):
        self.n, self.insertados = n, []

    @property
    def Count(self):
        return self.n

    def InsertBlock(self, p, nombre, ex, ey, ez, rot):
        r = Ref()
        self.insertados.append((p, nombre, rot, r))
        return r


class Doc:
    def __init__(self, objetos=0, bloques=(), capas=()):
        self.ModelSpace, self.Blocks, self.Layers = Modelo(objetos), Coleccion(bloques), Coleccion(capas)


def op(doc, **kw):
    return pe.ejecutar_op(doc, {"max_objetos": 300, **kw}, mk=MK)


# ---------- proteccion: ensayo, dibujo grande, no pisar ----------
def test_ensayo_crear_bloque_no_escribe_nada():
    d = Doc()
    r = op(d, op="crear_bloque", nombres=["58a"], tamano=100, ejecutar=False)
    assert r["ok"] and r["ejecutado"] is False and r["bloques"] == {"58a": "se_crearia"}
    assert d.Blocks.agregados == []


def test_crear_bloque_ejecutar_crea_circulo_y_texto():
    d = Doc()
    r = op(d, op="crear_bloque", nombres=["58a"], tamano=100, ejecutar=True)
    assert r["bloques"] == {"58a": "creado"} and "58a" in d.Blocks.nombres


def test_crear_bloque_existente_no_se_toca():
    d = Doc(bloques=["58a"])
    r = op(d, op="crear_bloque", nombres=["58a", "ohm"], tamano=50, ejecutar=True)
    assert r["bloques"]["58a"].startswith("ya_existia") and r["bloques"]["ohm"] == "creado"
    assert len(d.Blocks.agregados) == 1  # solo se agrego 'ohm'


def test_se_niega_en_dibujo_grande_sin_confirmacion():
    d = Doc(objetos=12046)
    for o in ({"op": "crear_bloque", "nombres": ["x"], "tamano": 1}, {"op": "insertar", "nombre": "x", "capa": "C", "puntos": [[0, 0]]}):
        r = op(d, ejecutar=True, **o)
        assert r["ok"] is False and r["error"] == "dibujo_grande_requiere_confirmacion"
    assert d.Blocks.agregados == [] and d.ModelSpace.insertados == [] and d.Layers.agregados == []


def test_insertar_requiere_que_el_bloque_exista():
    r = op(Doc(), op="insertar", nombre="58a", capa="DL-TEST-X", puntos=[[0, 0]], ejecutar=True)
    assert r["error"] == "bloque_no_existe"


def test_ensayo_insertar_no_escribe():
    d = Doc(bloques=["58a"])
    r = op(d, op="insertar", nombre="58a", capa="DL-TEST-X", puntos=[[1, 2]], ejecutar=False)
    assert r["ok"] and r["ejecutado"] is False and r["capa_existia"] is False
    assert d.ModelSpace.insertados == [] and d.Layers.agregados == []


def test_insertar_ejecutar_crea_capa_pone_rotacion_y_capa():
    d = Doc(bloques=["58a"])
    r = op(d, op="insertar", nombre="58a", capa="DL-TEST-ILUMINACION", puntos=[[1, 2], [3.5, 4]], rotacion_grados=90, ejecutar=True)
    assert r["cantidad"] == 2 and r["handles"] == ["ABC", "ABC"]
    assert d.Layers.agregados and "DL-TEST-ILUMINACION" in d.Layers.nombres
    (p, nombre, rot, ref) = d.ModelSpace.insertados[0]
    assert p == (1.0, 2.0, 0) and nombre == "58a" and math.isclose(rot, math.pi / 2) and ref.Layer == "DL-TEST-ILUMINACION"


def test_insertar_no_recrea_capa_existente():
    d = Doc(bloques=["58a"], capas=["DL-TEST-ILUMINACION"])
    op(d, op="insertar", nombre="58a", capa="DL-TEST-ILUMINACION", puntos=[[0, 0]], ejecutar=True)
    assert d.Layers.agregados == []


def test_operacion_desconocida():
    assert op(Doc(), op="borrar_todo")["error"] == "operacion_desconocida"


# ---------- servidor ----------
@pytest.fixture
def hoja_falsa(monkeypatch):
    prods = [
        {"_fila": 2, productos.REF: "AAA1", productos.CORTO: "Downlight", productos.SISTEMA: "Iluminación", productos.BLOQUE: "58a"},
        {"_fila": 3, productos.REF: "BBB1", productos.CORTO: "Sin bloque", productos.SISTEMA: "Audio", productos.BLOQUE: None},
        {"_fila": 4, productos.REF: "CCC1", productos.CORTO: "Cinta", productos.SISTEMA: "Cinta LED", productos.BLOQUE: "cinta1, cinta2"},
    ]
    monkeypatch.setattr(server, "_hoja", lambda: ([], prods))


@pytest.fixture
def espia(monkeypatch):
    llamadas = []

    def falso(args, timeout_s=10.0, timeout_escritura_s=30.0):
        llamadas.append(args)
        return {"ok": True, "ejecutado": args["ejecutar"]}

    monkeypatch.setattr(server.acad, "escribir", falso)
    return llamadas


def test_nombre_capa():
    assert server.nombre_capa("DL-TEST-", "Iluminación") == "DL-TEST-ILUMINACION"
    assert server.nombre_capa("DL-TEST-", "Cinta LED") == "DL-TEST-CINTA-LED"
    assert server.nombre_capa("DL-TEST-", None) == "DL-TEST-PRODUCTOS"


def test_por_defecto_es_ensayo(hoja_falsa, espia):
    r = server.crear_bloque_producto("AAA1")
    assert espia[0]["ejecutar"] is False and "ENSAYO" in r["aviso"]
    r = server.insertar_producto("AAA1", [[0, 0]])
    assert espia[1]["ejecutar"] is False and "ENSAYO" in r["aviso"]


def test_ejecutar_true_se_pasa_y_manda_limite_de_objetos(hoja_falsa, espia):
    server.insertar_producto("AAA1", [[1, 2]], rotacion_grados=45, ejecutar=True)
    a = espia[0]
    assert a["ejecutar"] is True and a["nombre"] == "58a" and a["capa"] == "DL-TEST-ILUMINACION"
    assert a["max_objetos"] == 300 and a["rotacion_grados"] == 45.0


def test_crear_usa_todos_los_nombres_de_bloque(hoja_falsa, espia):
    server.crear_bloque_producto("CCC1", tamano=80, ejecutar=True)
    assert espia[0]["nombres"] == ["cinta1", "cinta2"] and espia[0]["tamano"] == 80.0


def test_escritura_desactivada_no_llama_a_autocad(hoja_falsa, espia, monkeypatch):
    monkeypatch.setitem(server.CFG, "escritura", {"habilitada": False})
    assert server.crear_bloque_producto("AAA1", ejecutar=True)["error"] == "escritura_desactivada"
    assert server.insertar_producto("AAA1", [[0, 0]], ejecutar=True)["error"] == "escritura_desactivada"
    assert espia == []


@pytest.mark.parametrize("pts", [[], [[1]], [["a", 2]], [[1e12, 0]], [[float("nan"), 0]], [[0, 0]] * 101])
def test_puntos_invalidos_no_llegan_a_autocad(hoja_falsa, espia, pts):
    assert server.insertar_producto("AAA1", pts, ejecutar=True)["error"] == "puntos_invalidos"
    assert espia == []


def test_errores_de_producto_no_llegan_a_autocad(hoja_falsa, espia):
    assert server.insertar_producto("NOEXISTE", [[0, 0]], ejecutar=True)["error"] == "no_encontrado"
    assert server.insertar_producto("BBB1", [[0, 0]], ejecutar=True)["error"] == "sin_bloque_asignado"
    assert server.crear_bloque_producto("BBB1", ejecutar=True)["error"] == "sin_bloque_asignado"
    assert server.crear_bloque_producto("AAA1", tamano=0, ejecutar=True)["error"] == "tamano_invalido"
    assert espia == []


def test_error_de_autocad_se_propaga(hoja_falsa, monkeypatch):
    monkeypatch.setattr(server.acad, "escribir", lambda *a, **k: {"ok": False, "error": "autocad_no_responde", "detalle": "x"})
    r = server.crear_bloque_producto("AAA1", ejecutar=True)
    assert r["error"] == "autocad_no_responde" and r["referencia"] == "AAA1"
