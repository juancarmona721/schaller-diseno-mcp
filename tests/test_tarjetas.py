import math

import pytest

import sonda_svg as sv
import fichas
import productos as P
import server


# ---------- geometria -> SVG ----------
class E:
    def __init__(self, tipo, **kw):
        self.ObjectName = "AcDb" + tipo
        self.__dict__.update(kw)


def test_primitivas_y_omitidas():
    ents = [E("Line", StartPoint=(0, 0, 0), EndPoint=(10, 0, 0)), E("Circle", Center=(5, 5, 0), Radius=2.0),
            E("Arc", Center=(0, 0, 0), Radius=3.0, StartAngle=0.0, EndAngle=math.pi / 2),
            E("Polyline", Coordinates=(0, 0, 4, 0, 4, 4), Closed=True),
            E("3dPolyline", Coordinates=(0, 0, 0, 1, 1, 1), Closed=False),
            E("Hatch"), E("MText"), E("Hatch"), E("Region")]
    om = {}
    pr = sv.primitivas(ents, None, 0, om)
    assert [p[0] for p in pr] == ["l", "c", "a", "p", "p"]
    assert om == {"Hatch": 2, "MText": 1, "Region": 1}


def test_bloque_anidado_se_transforma_y_solo_un_nivel():
    hoja = E("Line", StartPoint=(0, 0, 0), EndPoint=(1, 0, 0))
    ref = E("BlockReference", Name="hijo", InsertionPoint=(10, 20, 0), XScaleFactor=2.0, Rotation=math.pi / 2)
    nieto = E("BlockReference", Name="nieto", InsertionPoint=(0, 0, 0), XScaleFactor=1.0, Rotation=0.0)
    om = {}
    pr = sv.primitivas([ref], lambda r: [hoja] if r.Name == "hijo" else [nieto], 0, om)
    p = pr[0]
    assert p[0] == "l" and (round(p[1], 6), round(p[2], 6)) == (10.0, 20.0) and (round(p[3], 6), round(p[4], 6)) == (10.0, 22.0)  # girada 90 y x2
    pr = sv.primitivas([ref], lambda r: [nieto], 0, om)       # el nieto (2do nivel) no se dibuja
    assert pr == [] and om.get("BlockReference") == 1


def test_caja_de_un_arco_es_solo_el_tramo_del_arco():
    cuarto = sv._caja([("a", 0, 0, 100, 0.0, math.pi / 2)])
    assert tuple(round(v, 6) for v in cuarto) == (0.0, 0.0, 100.0, 100.0)            # no 200 x 200 del circulo completo
    medio = sv._caja([("a", 0, 0, 100, 0.0, math.pi)])
    assert (round(medio[0]), round(medio[1]), round(medio[2]), round(medio[3])) == (-100, 0, 100, 100)
    completo = sv._caja([("a", 0, 0, 100, 0.0, 0.0)])                                  # inicio == fin: vuelta entera
    assert tuple(round(v) for v in completo) == (-100, -100, 100, 100)
    cruza = sv._caja([("a", 0, 0, 100, 1.5 * math.pi, 0.5 * math.pi)])                # cruza el angulo 0 (lado derecho)
    assert round(cruza[2]) == 100 and round(cruza[0], 6) >= -1e-6


def test_bloque_anidado_descuenta_su_punto_base_y_baja_varios_niveles():
    punta = E("Line", StartPoint=(100, 100, 0), EndPoint=(101, 100, 0))          # el hijo dibuja lejos de su base (100, 100)
    ref = E("BlockReference", Name="hijo", InsertionPoint=(5, 5, 0), XScaleFactor=1.0, Rotation=0.0)
    pr = sv.primitivas([ref], lambda r: ([punta], (100.0, 100.0)))
    assert (pr[0][1], pr[0][2], pr[0][3], pr[0][4]) == (5.0, 5.0, 6.0, 5.0)         # la base cae en el punto de insercion
    abuelo = E("BlockReference", Name="padre", InsertionPoint=(0, 0, 0), XScaleFactor=1.0, Rotation=0.0)
    padre = E("BlockReference", Name="hijo", InsertionPoint=(0, 0, 0), XScaleFactor=1.0, Rotation=0.0)
    pr = sv.primitivas([abuelo], lambda r: [padre] if r.Name == "padre" else [punta])   # 2 niveles de anidado: se dibuja
    assert len(pr) == 1


def test_a_svg_valido_y_con_y_invertido():
    svg = sv.a_svg([("l", 0, 0, 10, 5), ("c", 5, 2, 1), ("p", [(0, 0), (4, 0), (4, 4)], True), ("a", 0, 0, 3, 0.0, math.pi / 2)])
    assert svg.startswith("<svg") and svg.endswith("</svg>") and "<script" not in svg
    assert 'y2="-5"' in svg and "<circle" in svg and "<polygon" in svg and "<path" in svg and "viewBox" in svg
    assert sv.a_svg([]) is None and sv.a_svg([("c", 0, 0, 1)]) is not None


def test_exportar_con_doc_falso():
    class Bl(list):
        pass

    class ColBloques:
        def __init__(self, d):
            self.d = d

        def Item(self, n):
            if n not in self.d:
                raise KeyError(n)
            return self.d[n]

    class Doc:
        Blocks = ColBloques({"a": Bl([E("Circle", Center=(0, 0, 0), Radius=1.0)]), "solo_texto": Bl([E("MText")])})

    r = sv.exportar(Doc, ["a", "solo_texto", "nope"])["simbolos"]
    assert r["a"]["svg"].startswith("<svg") and r["solo_texto"]["svg"] is None and r["solo_texto"]["omitidas"] == {"MText": 1}
    assert r["nope"]["error"] == "no_existe_en_el_dibujo"


# ---------- cantidades ----------
def prod(fila, ref, corto, sis, bloque, **kw):
    d = {"_fila": fila, P.REF: ref, P.CORTO: corto, P.SISTEMA: sis, P.MARCA: "KEF", P.BLOQUE: bloque, "Instalación": "Muro",
         "Voltaje": "N/A", "W por unidad": "N/A", "Driver": "N/A", "Tipo de conexión": "cable a rack", P.INVENTADOS: "Instalación"}
    d.update(kw)
    return d


TODOS = [prod(2, "A", "Keypad", "Control", "kp"), prod(3, "B", "Parlante", "Audio", "pa"), prod(4, "C", "Parlante 2", "Audio", "pa"),
         prod(5, "D", "Sin bloque", "Audio", None), prod(6, "E", "Bloque ausente", "Audio", "fantasma"), prod(7, "F", "Dos", "Audio", "kp, pa")]


def test_calcular_cantidades():
    cant, comp = fichas.calcular_cantidades(TODOS, TODOS, {"kp": 28, "pa": 4})
    assert cant == {2: 28, 3: 4, 4: 4, 7: 32}              # sin bloque (5) y bloque que no esta en el plano (6) -> sin dato
    assert comp == {3, 4, 7, 2}                            # 'pa' lo comparten B, C y F; 'kp' lo comparten A y F
    cant2, comp2 = fichas.calcular_cantidades(TODOS, [TODOS[0]], {"kp": 28})
    assert cant2 == {2: 28} and comp2 == {2}               # se mira la hoja COMPLETA para saber si se comparte


def test_cantidades_desde_csv(tmp_path):
    csv_ = tmp_path / "p.csv"
    csv_.write_text("handle,bloque\n1,kp\n2,kp\n3,pa\n", encoding="utf-8")
    assert fichas.cantidades_desde_csv(csv_) == {"kp": 2, "pa": 1}
    assert fichas.cantidades_desde_csv(tmp_path / "no.csv") == {} and fichas.cantidades_desde_csv(None) == {}


# ---------- HTML de tarjetas ----------
def test_tarjetas_html():
    lista = [fichas.armar_ficha(p, [], "C") for p in TODOS[:5]]
    svg = '<svg viewBox="0 0 1 1"><circle r="1"/></svg>'
    h = fichas.html_tarjetas(lista, {"kp": svg}, {2: 28, 3: 4}, compartidos={3})
    assert h.count('class="t"') == 5 and svg in h
    assert "sin símbolo" in h and "Convenciones" in h and "RACK" in h and "Punto de datos" in h
    assert "28</span>" in h and "4*</span>" in h and "sin dato" in h
    assert 'class="inv"' in h                                # 'Instalación' esta en Campos inventados
    assert h.index("Control") < h.index("Audio")


def test_tarjetas_escapa_y_no_inserta_svg_peligroso():
    f = fichas.armar_ficha(prod(2, "A<b>", "<img src=x onerror=1>", "Audio", "kp"), [], "C")
    h = fichas.html_tarjetas([f], {"kp": '<svg><script>alert(1)</script></svg>'}, {})
    assert "<img src=x" not in h and "&lt;img" in h and "A&lt;b&gt;" in h
    assert "<script>alert(1)" not in h and "sin símbolo" in h


# ---------- herramientas del servidor ----------
@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_hoja", lambda: ([], TODOS))
    monkeypatch.setitem(server.CFG, "fichas", {"carpeta": str(tmp_path / "fichas"), "extraccion": str(tmp_path / "e.csv")})
    (tmp_path / "e.csv").write_text("handle,bloque\n1,kp\n2,pa\n3,pa\n", encoding="utf-8")
    monkeypatch.setattr(server, "_accesorios", lambda: [])
    return tmp_path


def test_exportar_simbolos_escribe_solo_en_simbolos(entorno, monkeypatch):
    visto = {}

    def falso(nombres, destino_contiene=None, timeout_s=10.0, timeout_lectura_s=60.0):
        visto.update(nombres=list(nombres), destino=destino_contiene)
        return {"ok": True, "simbolos": {"kp": {"svg": "<svg/>", "primitivas": 3, "omitidas": {}}, "../../mal": {"svg": "<svg/>", "primitivas": 1, "omitidas": {}},
                                         "pa": {"svg": None, "primitivas": 0, "omitidas": {"Hatch": 1}}, "fantasma": {"error": "no_existe_en_el_dibujo"}}}

    monkeypatch.setattr(server.acad, "exportar_svg", falso)
    r = server.exportar_simbolos(destino_contiene="dibujo3")
    assert visto["nombres"] == ["kp", "pa", "fantasma"] and visto["destino"] == "dibujo3"
    carpeta = entorno / "fichas" / "simbolos"
    assert sorted(x.name for x in carpeta.iterdir()) == ["..-..-mal.svg", "kp.svg"]          # nada fuera de la carpeta
    assert not list(entorno.glob("*.svg")) and r["con_imagen"] == 2
    assert r["simbolos"]["pa"]["error"] == "sin_geometria_dibujable" and r["simbolos"]["fantasma"]["error"] == "no_existe_en_el_dibujo"


def test_exportar_simbolos_errores(entorno, monkeypatch):
    assert server.exportar_simbolos(referencias=["NOEXISTE"])["error"] == "items_con_problemas"
    assert server.exportar_simbolos(filas_excel=[5])["error"] == "sin_bloques"             # fila sin bloque
    monkeypatch.setattr(server.acad, "exportar_svg", lambda *a, **k: {"ok": False, "error": "autocad_no_responde", "detalle": "x"})
    assert server.exportar_simbolos()["error"] == "autocad_no_responde"


def test_generar_tarjetas(entorno):
    (entorno / "fichas" / "simbolos").mkdir(parents=True)
    (entorno / "fichas" / "simbolos" / "kp.svg").write_text('<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>', encoding="utf-8")
    r = server.generar_tarjetas(sistemas=["control", "AUDIO"])
    assert r["ok"] and r["tarjetas"] == 6 and r["con_simbolo"] == 2 and r["con_cantidad"] == 4     # A, B, C y F tienen cantidad
    assert r["archivo"].endswith("tarjetas_control-audio.html")                          # un filtro tiene su propio archivo
    h = (entorno / "fichas" / "tarjetas_control-audio.html").read_text(encoding="utf-8")
    assert '<rect width="1"' in h and h.count('class="t"') == 6
    assert not (entorno / "fichas" / "tarjetas.html").exists()
    todas = server.generar_tarjetas()
    assert todas["archivo"].endswith("tarjetas.html") and todas["tarjetas"] == 6
    assert server.generar_tarjetas(sistemas=["control"])["tarjetas"] == 1
    assert (entorno / "fichas" / "tarjetas.html").exists() and (entorno / "fichas" / "tarjetas_control.html").exists()
    assert server.generar_tarjetas(sistemas=["nada"])["error"] == "sin_productos"
    assert server.generar_tarjetas(referencias=["A", "NOEXISTE"])["error"] == "items_con_problemas"


def test_generar_tarjetas_sin_extraccion_ni_simbolos(entorno, monkeypatch):
    monkeypatch.setitem(server.CFG, "fichas", {"carpeta": str(entorno / "f2")})
    r = server.generar_tarjetas()
    assert r["ok"] and r["con_simbolo"] == 0 and r["con_cantidad"] == 0


def test_generar_tarjetas_rechaza_nombres_fuera_de_la_carpeta(tmp_path):
    for malo in ("../x.html", "sub/x.html", "x.txt", "..\\x.html"):
        with pytest.raises(ValueError):
            fichas.generar_tarjetas([], {}, {}, tmp_path / "f", nombre=malo)
    assert not list(tmp_path.glob("**/x.*"))


def test_elegir_filtra_por_sistema_sin_tildes():
    sel, prob = server._elegir(TODOS, sistemas=["CONTROL"])
    assert [p["_fila"] for p in sel] == [2] and prob == []
