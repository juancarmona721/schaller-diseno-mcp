import pytest

import sonda_tarjetas as pt
import fichas
import productos as P
import server

MK = lambda x, y, z=0.0: (x, y, z)  # noqa: E731
MKP = lambda vals: list(vals)  # noqa: E731


class Ent:
    def __init__(self, tipo, **kw):
        self.tipo, self.Layer, self.color, self.Closed, self.Height, self.StyleName = tipo, None, None, None, None, None
        self.__dict__.update(kw)


class Coleccion:
    def __init__(self, nombres=()):
        self.nombres, self.agregados = set(nombres), []

    def Item(self, n):
        if n not in self.nombres:
            raise KeyError(n)
        return n

    def Add(self, n):
        self.nombres.add(n)
        self.agregados.append(n)
        return Estilo()


class Estilo:
    def SetFont(self, *a):
        pass


class Modelo:
    def __init__(self, n=0):
        self.n, self.cosas = n, []

    @property
    def Count(self):
        return self.n + len(self.cosas)

    def _add(self, e):
        self.cosas.append(e)
        return e

    def AddLine(self, a, b):
        return self._add(Ent("linea", a=a, b=b))

    def AddLightWeightPolyline(self, pts):
        return self._add(Ent("poli", pts=pts))

    def AddMText(self, p, w, t):
        return self._add(Ent("mtext", p=p, w=w, t=t))

    def AddCircle(self, c, r):
        return self._add(Ent("circulo", c=c, r=r))

    def InsertBlock(self, p, nombre, sx, sy, sz, rot):
        return self._add(Ent("insert", p=p, nombre=nombre, s=sx))


class Bloque(list):
    pass


class BE:  # entidad de bloque con caja
    def __init__(self, w, h):
        self.w, self.h = w, h

    def GetBoundingBox(self):
        return (-self.w / 2, -self.h / 2, 0), (self.w / 2, self.h / 2, 0)


class Blocks(Coleccion):
    def __init__(self, defs):
        super().__init__(defs)
        self.defs = defs

    def Item(self, n):
        if n not in self.defs:
            raise KeyError(n)
        return self.defs[n]


class Doc:
    def __init__(self, objetos=0, defs=None, capas=(), estilos=()):
        self.ModelSpace = Modelo(objetos)
        self.Blocks = Blocks(defs if defs is not None else {"kp": Bloque([BE(100, 50)]), "pa": Bloque([BE(400, 400)])})
        self.Layers, self.TextStyles = Coleccion(capas), Coleccion(estilos)


def tarjeta(ref, bloques, **kw):
    d = {"referencia": ref, "marca": "KEF", "descripcion": "Parlante", "instalacion": {"v": "Muro", "inv": False},
         "conexion": {"v": "cable a rack", "inv": True}, "cantidad": "6", "bloques": bloques}
    d.update(kw)
    return d


def run(doc, tarjetas, ejecutar=True, **kw):
    return pt.crear(doc, {"tarjetas": tarjetas, "ejecutar": ejecutar, "max_objetos": 300, **kw}, mk=MK, mkplano=MKP)


def cuenta(doc):
    c = {}
    for e in doc.ModelSpace.cosas:
        c[e.tipo] = c.get(e.tipo, 0) + 1
    return c


# ---------- disenio ----------
def test_disenar_posiciones_en_cuadricula():
    pos, alto, gap, k = pt.disenar([0] * 7, 1800.0, 0.0, 0.0, 3)
    assert k == 1.0 and alto == 3000.0 and gap == 120.0          # 3000 = 2760 de antes + 240 de la fila NOMBRE
    assert pos[0] == (0.0, 0.0) and pos[1] == (1920.0, 0.0) and pos[3] == (0.0, -3120.0) and pos[6] == (0.0, -6240.0)
    pos2, alto2, _, k2 = pt.disenar([0, 0], 900.0, 100.0, 50.0, 8)                # mitad de ancho: todo proporcional
    assert k2 == 0.5 and alto2 == 1500.0 and pos2[1][0] == 100.0 + 900.0 + 60.0


# ---------- ensayo y escritura ----------
def test_ensayo_no_dibuja_nada():
    d = Doc()
    r = run(d, [tarjeta("A", ["kp"]), tarjeta("B", ["nada"])], ejecutar=False)
    assert r["ok"] and r["ejecutado"] is False and r["tarjetas"] == 1
    assert r["omitidas_sin_simbolo"] == [{"referencia": "B", "motivo": "sin simbolo en el dibujo"}]
    assert d.ModelSpace.cosas == [] and d.Layers.agregados == [] and d.TextStyles.agregados == []


def test_ejecutar_dibuja_cada_tarjeta_completa():
    d = Doc()
    r = run(d, [tarjeta("A", ["kp"]), tarjeta("B", ["pa"])], leyenda=False)
    assert r["dibujado"] and r["tarjetas"] == 2
    assert cuenta(d) == {"poli": 2, "linea": 12, "mtext": 12, "insert": 2}                 # 1+6+6+1 por tarjeta (con la fila NOMBRE)
    assert set(d.Layers.agregados) == {"DL-TEST-FICHAS", "DL-TEST-FICHAS-TEXTO", "DL-TEST-FICHAS-SIMBOLO"} and d.TextStyles.agregados == ["DL-TEST-FICHA"]
    assert all(e.Layer == "DL-TEST-FICHAS-SIMBOLO" for e in d.ModelSpace.cosas if e.tipo == "insert")
    assert all(e.StyleName == "DL-TEST-FICHA" for e in d.ModelSpace.cosas if e.tipo == "mtext")


def test_el_simbolo_se_escala_para_caber_en_su_recuadro():
    d = Doc()
    r = run(d, [tarjeta("A", ["kp"]), tarjeta("B", ["pa"])], leyenda=False)
    # kp 100x50: min(20, 0.8*1700/100=13.6, 0.8*1000/50=16) = 13.6 ; pa 400x400: min(20, 3.4, 2.0) = 2.0
    assert r["escalas_simbolo"] == {"kp": 13.6, "pa": 2.0}
    ins = [e for e in d.ModelSpace.cosas if e.tipo == "insert"]
    assert ins[0].s == pytest.approx(13.6) and ins[0].p[0] == pytest.approx(900.0)       # centrado horizontalmente en la tarjeta


def test_texto_con_colores_escapes_y_recorte():
    d = Doc()
    t = tarjeta("A{1}\\x", ["kp"], descripcion="D" * 500, conexion={"v": "cable", "inv": True}, instalacion={"v": None, "inv": False})
    run(d, [t], leyenda=False)
    textos = [e.t for e in d.ModelSpace.cosas if e.tipo == "mtext"]
    nombre, inst, ref, desc, cant, con = textos
    assert "NOMBRE:" in nombre and "\\C8;sin dato" in nombre                           # fila nueva arriba: vacia (gris), no se rellena sola
    assert "INSTALACIÓN:" in inst and "\\C8;sin dato" in inst                          # vacio: gris
    assert "A(1)\\\\x" in ref and "(KEF)" in ref and "\\C5;" in ref                  # llaves fuera, barra escapada, valor azul
    assert desc.endswith("…") and len(desc) < 160                                      # recortado
    assert "\\C30;\\Q15;cable" in con and "TIPO DE CONEXIÓN:" in con                    # inventado: naranja inclinado
    assert "\\C5;6" in cant


def test_leyenda():
    d = Doc()
    run(d, [tarjeta("A", ["kp"])], leyenda=True)
    todo = " ".join(e.t for e in d.ModelSpace.cosas if e.tipo == "mtext")
    assert "RACK" in todo and "Punto de datos" in todo and 'Tubería Ø1/2"' in todo
    assert cuenta(d)["circulo"] == 1
    sin = Doc()
    run(sin, [tarjeta("A", ["kp"])], leyenda=False)
    assert "RACK" not in " ".join(e.t for e in sin.ModelSpace.cosas if e.tipo == "mtext")


def test_sin_simbolo_opcional():
    d = Doc()
    r = run(d, [tarjeta("B", ["nada"]), tarjeta("C", [])], incluir_sin_simbolo=True, leyenda=False)
    assert r["tarjetas"] == 2 and cuenta(d).get("insert", 0) == 0
    assert any("sin símbolo" in e.t for e in d.ModelSpace.cosas if e.tipo == "mtext")


def test_usa_el_primer_bloque_que_existe():
    d = Doc()
    run(d, [tarjeta("A", ["no_esta", "pa", "kp"])], leyenda=False)
    assert [e.nombre for e in d.ModelSpace.cosas if e.tipo == "insert"] == ["pa"]


def test_no_recrea_capas_ni_estilo_existentes():
    d = Doc(capas=["DL-TEST-FICHAS", "DL-TEST-FICHAS-TEXTO", "DL-TEST-FICHAS-SIMBOLO"], estilos=["DL-TEST-FICHA"])
    run(d, [tarjeta("A", ["kp"])], leyenda=False)
    assert d.Layers.agregados == [] and d.TextStyles.agregados == []


# ---------- proteccion ----------
def test_se_niega_en_dibujo_grande_sin_dibujar():
    d = Doc(objetos=12046)
    r = run(d, [tarjeta("A", ["kp"])])
    assert r["error"] == "dibujo_demasiado_grande_para_escribir" and d.ModelSpace.cosas == [] and d.Layers.agregados == []


def test_se_niega_si_superaria_el_maximo():
    d = Doc(objetos=250)
    r = run(d, [tarjeta(str(i), ["kp"]) for i in range(10)])
    assert r["error"] == "superaria_el_maximo" and r["ejecutado"] is False
    assert d.ModelSpace.cosas == [] and d.Layers.agregados == []


def test_sin_ninguna_tarjeta_con_simbolo():
    d = Doc()
    r = run(d, [tarjeta("A", ["nada"])])
    assert r["error"] == "sin_tarjetas" and d.ModelSpace.cosas == []


# ---------- herramienta del servidor ----------
PRODS = [
    {"_fila": 2, P.REF: "KEYPAD1", P.CORTO: "Keypad", P.SISTEMA: "Control", P.MARCA: "CT", P.BLOQUE: "kp", "Instalación": "Muro",
     "Tipo de conexión": "cresnet", P.INVENTADOS: "Tipo de conexión"},
    {"_fila": 3, P.REF: "PARL1", P.CORTO: "Parlante", P.SISTEMA: "Audio", P.MARCA: "KEF", P.BLOQUE: "pa", "Instalación": None,
     "Tipo de conexión": "audio", P.INVENTADOS: "Ninguno (datos de la hoja original)"},
    {"_fila": 4, P.REF: "PARL2", P.CORTO: "Parlante 2", P.SISTEMA: "Audio", P.MARCA: "KEF", P.BLOQUE: "pa", "Instalación": "Techo",
     "Tipo de conexión": "audio", P.INVENTADOS: ""},
]


@pytest.fixture
def espia(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_hoja", lambda: ([], PRODS))
    monkeypatch.setattr(server, "_accesorios", lambda: [])
    (tmp_path / "e.csv").write_text("handle,bloque\n1,kp\n2,pa\n3,pa\n4,pa\n", encoding="utf-8")
    monkeypatch.setitem(server.CFG, "fichas", {"carpeta": str(tmp_path), "extraccion": str(tmp_path / "e.csv")})
    llamadas = []
    monkeypatch.setattr(server.acad, "dibujar_tarjetas",
                        lambda args, timeout_s=10.0, timeout_escritura_s=30.0: llamadas.append(args) or {"ok": True, "ejecutado": args["ejecutar"]})
    return llamadas


def test_servidor_arma_las_tarjetas_en_orden_de_hoja(espia):
    r = server.crear_tarjetas_cad(destino_contiene="dibujo3")
    a = espia[0]
    assert a["op"] == "tarjetas" and a["ejecutar"] is False and a["destino_contiene"] == "dibujo3" and a["max_objetos"] == 300
    assert [t["referencia"] for t in a["tarjetas"]] == ["KEYPAD1", "PARL1", "PARL2"]       # Control, luego Audio (orden de la hoja)
    k, p1, p2 = a["tarjetas"]
    assert k["conexion"] == {"v": "cresnet", "inv": True} and k["instalacion"] == {"v": "Muro", "inv": False}
    assert p1["instalacion"] == {"v": None, "inv": False} and p1["bloques"] == ["pa"]       # vacio -> None
    assert k["cantidad"] == "1" and p1["cantidad"] == "3*" and p2["cantidad"] == "3*"        # 'pa' lo comparten dos productos
    assert "ENSAYO" in r["aviso"]


def test_servidor_pasa_la_geometria_y_el_ejecutar(espia):
    server.crear_tarjetas_cad(sistemas=["audio"], columnas=4, x0=100, y0=-50, ancho_tarjeta=900, incluir_leyenda=False,
                              incluir_sin_simbolo=True, ejecutar=True)
    a = espia[0]
    assert (a["columnas"], a["x0"], a["y0"], a["ancho"], a["leyenda"], a["incluir_sin_simbolo"], a["ejecutar"]) == (4, 100.0, -50.0, 900.0, False, True, True)
    assert [t["referencia"] for t in a["tarjetas"]] == ["PARL1", "PARL2"]


@pytest.mark.parametrize("kw", [{"columnas": 0}, {"columnas": 21}, {"ancho_tarjeta": 10}, {"ancho_tarjeta": 1e6},
                                {"x0": float("nan")}, {"y0": 1e12}])
def test_servidor_valida_parametros(espia, kw):
    assert server.crear_tarjetas_cad(**kw)["error"] == "parametros_invalidos" and espia == []


def test_servidor_errores_y_desactivado(espia, monkeypatch):
    assert server.crear_tarjetas_cad(referencias=["NOEXISTE"])["error"] == "items_con_problemas"
    assert server.crear_tarjetas_cad(sistemas=["nada"])["error"] == "sin_productos"
    monkeypatch.setitem(server.CFG, "escritura", {"habilitada": False})
    assert server.crear_tarjetas_cad(ejecutar=True)["error"] == "escritura_desactivada"
    assert espia == []
    monkeypatch.setitem(server.CFG, "escritura", {"habilitada": True})
    monkeypatch.setattr(server.acad, "dibujar_tarjetas", lambda *a, **k: {"ok": False, "error": "autocad_no_responde", "detalle": "x"})
    assert server.crear_tarjetas_cad()["error"] == "autocad_no_responde"
