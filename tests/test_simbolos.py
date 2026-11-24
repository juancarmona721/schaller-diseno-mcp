import pytest

import sonda_simbolos as ps
import productos
import server

MK = lambda x, y, z=0.0: (x, y, z)  # noqa: E731
MKOBJ = lambda objs: list(objs)  # noqa: E731


class Ent:
    def __init__(self, tipo="AcDbLine", ancho=2.0, alto=1.0, x0=0.0, y0=0.0):
        self.ObjectName, self.ancho, self.alto, self.x0, self.y0 = tipo, ancho, alto, x0, y0
        self.escalas, self.movimientos = [], []

    def GetBoundingBox(self):
        return (self.x0, self.y0, 0.0), (self.x0 + self.ancho, self.y0 + self.alto, 0.0)

    def ScaleEntity(self, base, f):
        self.escalas.append(f)
        self.x0, self.y0 = base[0] + (self.x0 - base[0]) * f, base[1] + (self.y0 - base[1]) * f
        self.ancho, self.alto = self.ancho * f, self.alto * f

    def Move(self, desde, hasta):
        self.movimientos.append((desde, hasta))
        self.x0 += hasta[0] - desde[0]
        self.y0 += hasta[1] - desde[1]


class Bloque(list):
    def __init__(self, ents=(), origen=(0.0, 0.0, 0.0)):
        super().__init__(ents)
        self.Origin, self.borrado = origen, False

    def Delete(self):
        self.borrado = True


class Blocks:
    def __init__(self, defs=None):
        self.defs = dict(defs or {})
        self.creados = []

    def Item(self, n):
        if n not in self.defs:
            raise KeyError(n)
        return self.defs[n]

    def Add(self, origen, nombre):
        b = Bloque(origen=tuple(origen))
        self.defs[nombre] = b
        self.creados.append(nombre)
        return b


class Ref:
    ObjectName = "AcDbBlockReference"

    def __init__(self, nombre, esc):
        self.EffectiveName, self.XScaleFactor = nombre, esc


class Modelo(list):
    forzado = None  # para simular un dibujo grande sin llenar la lista

    @property
    def Count(self):
        return len(self) if self.forzado is None else self.forzado


class Doc:
    def __init__(self, nombre, unidades, defs=None, objetos=(), n=None):
        self.Name, self._u, self.Blocks = nombre, unidades, Blocks(defs)
        self.ModelSpace = Modelo(objetos)
        self.ModelSpace.forzado = n

    def GetVariable(self, v):
        return self._u

    def CopyObjects(self, objs, owner):
        for e in objs:
            c = Ent(e.ObjectName, e.ancho, e.alto, e.x0, e.y0)
            owner.append(c)


def origen_metros():
    defs = {"58a": Bloque([Ent("AcDbCircle", 0.1, 0.1), Ent("AcDbText", 0.05, 0.02)]),
            "dg": Bloque([Ent("AcDbLine", 100, 50)]),               # dibujado en mm
            "eclipse": Bloque([Ent("AcDbArc", 1, 1)])}
    refs = [Ref("58a", 1.0)] * 3 + [Ref("dg", 0.001)] * 2 + [Ref("eclipse", 0.03), Ref("eclipse", 0.012), Ref("eclipse", 0.03)]
    return Doc("origen.dwg", 6, defs, refs)


def run(origen, destino, nombres, ejecutar, **kw):
    return ps.importar(origen, destino, nombres, ejecutar, mk=MK, mkobj=MKOBJ, **kw)


def test_ensayo_no_escribe_y_calcula_factores():
    o, d = origen_metros(), Doc("dest.dwg", 4)
    r = run(o, d, ["58a", "dg", "eclipse", "nada"], ejecutar=False)
    s = r["simbolos"]
    assert d.Blocks.creados == [] and r["ejecutado"] is False
    assert s["58a"]["factor_aplicado"] == 1000.0 and s["58a"]["tamano_en_unidades_destino"] == [100.0, 100.0]
    assert s["dg"]["factor_aplicado"] == 1.0 and s["dg"]["tamano_en_unidades_destino"] == [100.0, 50.0]   # 0.001 x 1000
    assert s["eclipse"]["escala_tipica_en_origen"] == 0.03 and "variables" in s["eclipse"]["aviso"]
    assert s["nada"]["estado"] == "no_existe_en_origen" and s["58a"]["estado"] == "se_importaria"


def test_ejecutar_crea_copia_y_escala_solo_la_copia():
    o, d = origen_metros(), Doc("dest.dwg", 4)
    r = run(o, d, ["58a", "dg"], ejecutar=True)
    assert r["simbolos"]["58a"]["estado"] == "importado" and r["simbolos"]["58a"]["entidades_copiadas"] == 2
    assert [e.escalas for e in d.Blocks.defs["58a"]] == [[1000.0], [1000.0]]
    assert [e.escalas for e in d.Blocks.defs["dg"]] == [[]]                 # factor 1: no se escala
    assert all(e.escalas == [] for e in o.Blocks.defs["58a"])                # el origen no se toca


def test_no_pisa_bloque_existente_en_destino():
    o = origen_metros()
    d = Doc("dest.dwg", 4, {"58a": Bloque([Ent()])})
    r = run(o, d, ["58a"], ejecutar=True)
    assert r["simbolos"]["58a"]["estado"].startswith("ya_existia") and d.Blocks.creados == []


def test_se_niega_si_el_destino_es_grande():
    o, d = origen_metros(), Doc("dest.dwg", 4, n=5000)
    r = run(o, d, ["58a"], ejecutar=True)
    assert r["error"] == "dibujo_grande_requiere_confirmacion" and d.Blocks.creados == []
    assert run(o, d, ["58a"], ejecutar=False)["ok"] is True                    # el ensayo si se permite


def test_origen_igual_destino():
    o = origen_metros()
    assert run(o, o, ["58a"], ejecutar=True)["error"] == "origen_igual_destino"


def test_si_falla_la_copia_borra_solo_la_definicion_vacia_recien_creada():
    o, d = origen_metros(), Doc("dest.dwg", 4)
    o.CopyObjects = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    r = run(o, d, ["58a"], ejecutar=True)["simbolos"]["58a"]
    assert r["estado"] == "fallo" and "elimino" in r["limpieza"] and d.Blocks.defs["58a"].borrado is True


def test_unidades_distintas_y_sin_unidades():
    o, d = origen_metros(), Doc("dest.dwg", 5)                                  # m -> cm
    assert run(o, d, ["58a"], False)["simbolos"]["58a"]["factor_aplicado"] == 100.0
    r = run(o, Doc("d.dwg", 0), ["58a"], False)                                 # destino sin unidades
    assert r["simbolos"]["58a"]["factor_aplicado"] == 1.0 and r["avisos"]


def _centro(bloque):
    xs = [v for e in bloque for v in (e.GetBoundingBox()[0][0], e.GetBoundingBox()[1][0])]
    ys = [v for e in bloque for v in (e.GetBoundingBox()[0][1], e.GetBoundingBox()[1][1])]
    return (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2


def origen_con_bloque_lejano():
    """Como MIRA R / CATHODE: el dibujo esta a ~2.4 km (en metros) de su punto base (0, 0)."""
    o = origen_metros()
    o.Blocks.defs["lejos"] = Bloque([Ent("AcDbLine", 0.4, 0.3, x0=1502.0, y0=1853.0), Ent("AcDbCircle", 0.1, 0.1, x0=1502.1, y0=1853.1)])
    o.ModelSpace.append(Ref("lejos", 1.0))
    return o


def test_ensayo_avisa_cuando_la_geometria_esta_lejos_del_punto_base():
    r = run(origen_con_bloque_lejano(), Doc("dest.dwg", 4), ["lejos", "58a"], ejecutar=False)["simbolos"]
    assert "MUY lejos" in r["lejos"]["aviso_base"] and r["lejos"]["centrado_desde"][0] > 1_000_000   # mm
    assert "aviso_base" not in r["58a"]


def test_importar_centra_cada_simbolo_en_su_punto_base():
    o, d = origen_con_bloque_lejano(), Doc("dest.dwg", 4)
    r = run(o, d, ["lejos", "58a", "dg"], ejecutar=True)
    assert all(v["estado"] == "importado" for v in r["simbolos"].values())
    for n in ("lejos", "58a", "dg"):
        cx, cy = _centro(d.Blocks.defs[n])
        assert abs(cx) < 1e-6 and abs(cy) < 1e-6, n          # centro del dibujo en (0, 0)
    assert d.Blocks.defs["lejos"][0].ancho == pytest.approx(400.0)   # y el tamano sigue siendo el esperado
    assert d.Blocks.creados.count("lejos") == 1
    assert _centro(o.Blocks.defs["lejos"]) != (0, 0) and all(e.movimientos == [] for e in o.Blocks.defs["lejos"])  # origen intacto


def test_elegir_doc_no_revela_nombres():
    a, b = Doc("Plano CASA X.dwg", 6), Doc("Dibujo1.dwg", 4)
    assert ps.elegir_doc([a, b], "dibujo") == (b, None)
    doc, err = ps.elegir_doc([a, b], "zzz")
    assert doc is None and "0 documentos" in err and "Plano" not in err
    assert ps.elegir_doc([a, b], "dibujo", excluir=b)[0] is None


# ---------- servidor ----------
@pytest.fixture
def hoja_falsa(monkeypatch):
    prods = [
        {"_fila": 2, productos.REF: "AAA1", productos.CORTO: "Downlight", productos.BLOQUE: "58a"},
        {"_fila": 3, productos.REF: "BBB1", productos.CORTO: "Dos nombres", productos.BLOQUE: "dg, 58a"},
        {"_fila": 4, productos.REF: "NOBLK", productos.CORTO: "Sin bloque", productos.BLOQUE: None},
    ]
    monkeypatch.setattr(server, "_hoja", lambda: ([], prods))
    llamadas = []
    monkeypatch.setattr(server.acad, "importar_simbolos",
                        lambda args, timeout_s=10.0, timeout_importar_s=300.0: llamadas.append(args) or {"ok": True, "ejecutado": args["ejecutar"]})
    return llamadas


def test_servidor_sin_referencias_usa_todos_los_bloques_sin_repetir(hoja_falsa):
    r = server.importar_simbolos("plano")
    a = hoja_falsa[0]
    assert a["nombres"] == ["58a", "dg"] and a["ejecutar"] is False and a["max_objetos"] == 300 and "ENSAYO" in r["aviso"]


def test_servidor_con_referencias_y_destino(hoja_falsa):
    server.importar_simbolos("plano", destino_contiene="dibujo", referencias=["bbb1"], ejecutar=True)
    assert hoja_falsa[0]["nombres"] == ["dg", "58a"] and hoja_falsa[0]["destino_contiene"] == "dibujo" and hoja_falsa[0]["ejecutar"] is True


def test_servidor_todo_o_nada_en_referencias(hoja_falsa):
    r = server.importar_simbolos("plano", referencias=["AAA1", "NOEXISTE", "NOBLK"], ejecutar=True)
    assert r["error"] == "items_con_problemas" and {p["referencia"] for p in r["problemas"]} == {"NOEXISTE", "NOBLK"}
    assert hoja_falsa == []


def test_servidor_desactivado_y_error_propagado(hoja_falsa, monkeypatch):
    monkeypatch.setitem(server.CFG, "escritura", {"habilitada": False})
    assert server.importar_simbolos("plano", ejecutar=True)["error"] == "escritura_desactivada" and hoja_falsa == []
    monkeypatch.setitem(server.CFG, "escritura", {"habilitada": True})
    monkeypatch.setattr(server.acad, "importar_simbolos", lambda *a, **k: {"ok": False, "error": "origen_no_valido", "detalle": "x"})
    assert server.importar_simbolos("plano")["error"] == "origen_no_valido"
