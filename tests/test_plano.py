"""ver_plano: lectura estructurada (espacios, bloques por espacio, unidades). Todo con un AutoCAD de mentira."""
import math

import pytest

import _probe_plano as pp
import server


class E:
    def __init__(self, on, **kw):
        self.ObjectName = on
        self.Layer = kw.pop("Layer", "0")
        self.__dict__.update(kw)


def rect(x0, y0, x1, y1, capa="SCH_MUROS"):
    return E("AcDbPolyline", Closed=True, Layer=capa, Coordinates=(x0, y0, x1, y0, x1, y1, x0, y1))


def texto(t, x, y, h=0.4, mt=False):
    return E("AcDbMText" if mt else "AcDbText", TextString=t, InsertionPoint=(x, y, 0), Height=h)


def bloque(n, cx, cy, w=0.3, h=0.3, rot=0.0, esc=1.0):
    return E("AcDbBlockReference", EffectiveName=n, InsertionPoint=(cx, cy, 0), Rotation=math.radians(rot), XScaleFactor=esc,
             YScaleFactor=esc, Layer="SCH_BLOQUES", GetBoundingBox=lambda: ((cx - w / 2, cy - h / 2, 0), (cx + w / 2, cy + h / 2, 0)))


class Modelo(list):
    @property
    def Count(self):
        return len(self)

    def Item(self, i):
        return self[i]


class Doc:
    def __init__(self, ents, unidades=6, nombre="plano.dwg"):
        self.ModelSpace, self._u, self.Name = Modelo(ents), unidades, nombre

    def GetVariable(self, v):
        return self._u


def casa():
    return Doc([rect(0, 0, 9, 7), texto("Sala", 4.5, 3.5), rect(9, 0, 15, 7), texto("Comedor", 12, 3.5),
                bloque("Moon_200_Davide Groppi", 7, 3.5, 2, 2), bloque("Ci200QR_KEF", 2.25, 0.2), bloque("Ci200QR_KEF", 6.75, 0.2),
                bloque("Tao_Davide Groppi", 12, 3.5, 0.3, 6), bloque("Suelto_X", 30, 30)])


def test_detecta_espacios_con_medidas_y_limites():
    r = pp.analizar(casa())
    assert r["ok"] and r["solo_lectura"] and r["espacios_total"] == 2
    sala = next(s for s in r["espacios"] if s["nombre"] == "Sala")
    assert (sala["x0"], sala["y0"], sala["x1"], sala["y1"]) == (0, 0, 9, 7) and sala["ancho"] == 9 and sala["alto"] == 7
    assert sala["area"] == 63 and sala["forma"] == "rectangulo" and sala["capa"] == "SCH_MUROS"


def test_asigna_bloques_a_su_espacio_y_los_sueltos_quedan_fuera():
    r = pp.analizar(casa())
    por = {s["nombre"]: s["productos"] for s in r["espacios"]}
    assert por["Sala"] == {"Moon_200_Davide Groppi": 1, "Ci200QR_KEF": 2} and por["Comedor"] == {"Tao_Davide Groppi": 1}
    assert r["bloques_fuera_de_espacios"] == {"Suelto_X": 1} and r["bloques_total"] == 5 and r["bloques_por_nombre"]["Ci200QR_KEF"] == 2


def test_poligono_anidado_gana_el_mas_pequeno():
    d = Doc([rect(0, 0, 20, 16), texto("Casa", 15, 14, 0.8), rect(0, 0, 9, 7), texto("Sala", 4, 3), bloque("A", 4, 3)])
    r = pp.analizar(d)
    sala = next(s for s in r["espacios"] if s["nombre"] == "Sala")
    casa_ = next(s for s in r["espacios"] if s["nombre"] == "Casa")
    assert sala["productos"] == {"A": 1} and casa_["productos"] == {}          # el bloque pertenece al espacio mas pequeno


def test_nombre_es_el_texto_de_mayor_altura_y_se_limpia_el_formato_mtext():
    d = Doc([rect(0, 0, 5, 5), texto("{\\fArial|b0;pequeno}", 1, 1, 0.1, mt=True), texto("\\A1;Ba\\U+00F1o\\Pprincipal", 2, 2, 0.5, mt=True)])
    assert pp.analizar(d)["espacios"][0]["nombre"] == "Baño principal"


def test_aviso_de_unidades_que_no_cuadran():
    mm_pero_metros = Doc([bloque("A", 1, 1, 0.4, 0.4), bloque("B", 2, 2, 0.6, 0.3), bloque("C", 3, 3, 1.5, 0.2)], unidades=4)
    assert "METROS" in pp.analizar(mm_pero_metros)["unidades"]["aviso"]
    m_pero_mm = Doc([bloque("A", 1, 1, 300, 300), bloque("B", 2, 2, 450, 200)], unidades=6)
    assert "MILIMETROS" in pp.analizar(m_pero_mm)["unidades"]["aviso"]
    assert pp.analizar(casa())["unidades"]["aviso"] is None and pp.analizar(casa())["unidades"]["nombre"] == "metros"


def test_poligonos_sin_texto_se_cuentan_y_se_trunca_en_el_limite():
    d = Doc([rect(0, 0, 1, 1), rect(2, 2, 3, 3), texto("X", 2.5, 2.5)] + [bloque("A", i, 0) for i in range(50)])
    r = pp.analizar(d)
    assert r["poligonos_cerrados_sin_texto"] == 1 and r["espacios_total"] == 1
    r2 = pp.analizar(d, limite=10)
    assert r2["truncado"] is True and r2["leidos"] == 10 and r2["objetos"] == 53


def test_texto_centrado_usa_el_punto_de_alineacion_no_el_extremo_izquierdo():
    t = E("AcDbText", TextString="Baño principal", InsertionPoint=(5.9, 14.25, 0), Height=0.4, Alignment=10,
          TextAlignmentPoint=(7.5, 14.25, 0))                       # el extremo izquierdo (5.9) cae FUERA del cuarto 6..9
    r = pp.analizar(Doc([rect(6, 12.5, 9, 16), t, bloque("Durastrip_X", 7.5, 12.6, 3, 0.04)]))
    assert r["espacios_total"] == 1 and r["espacios"][0]["productos"] == {"Durastrip_X": 1} and r["bloques_fuera_de_espacios"] == {}


def test_poligono_en_L_no_es_rectangulo():
    l_ = E("AcDbPolyline", Closed=True, Layer="0", Coordinates=(0, 0, 4, 0, 4, 2, 2, 2, 2, 4, 0, 4))
    r = pp.analizar(Doc([l_, texto("Sala L", 1, 1)]))
    assert r["espacios"][0]["forma"] == "poligono" and r["espacios"][0]["area"] == 12


def test_no_devuelve_el_nombre_del_archivo():
    assert "cliente_secreto" not in str(pp.analizar(Doc([rect(0, 0, 1, 1), texto("A", .5, .5)], nombre="cliente_secreto.dwg")))


def test_elegir_doc_por_fragmento_sin_revelar_nombres():
    a, b = Doc([], nombre="Drawing4.dwg"), Doc([], nombre="otro.dwg")
    assert pp.elegir_doc([a, b], "drawing4", a) == (a, None)
    assert pp.elegir_doc([a, b], None, b) == (b, None)
    doc, err = pp.elegir_doc([a, b], ".dwg", a)
    assert doc is None and "2 documentos" in err and "otro" not in err


def test_reintenta_cuando_autocad_esta_ocupado(monkeypatch):
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    n = {"i": 0}

    class Ocupado(Exception):
        hresult = -2147418111

    def f():
        n["i"] += 1
        if n["i"] < 3:
            raise Ocupado("La llamada fue rechazada")
        return "ok"
    assert pp.reintentar(f) == "ok" and n["i"] == 3
    with pytest.raises(ValueError):                       # otros errores NO se reintentan
        pp.reintentar(lambda: (_ for _ in ()).throw(ValueError("x")))


def test_tool_pasa_los_argumentos_y_los_tiempos(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server.acad, "ver_plano", lambda *a, **k: llamadas.append((a, k)) or {"ok": True})
    server.ver_plano("drawing4", 500, 10)
    (a, k), = llamadas
    assert a == ("drawing4", 500, 10) and "timeout_s" in k and "timeout_lectura_s" in k
