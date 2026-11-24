"""Candado de planos grandes + importar la biblioteca completa + insertar_bloques."""
import math

import _probe_escribir as pe
import _probe_simbolos as ps
import server
from test_fase3 import Doc as DocEsc, MK
from test_simbolos import Bloque, Doc as DocSim, Ent, MKOBJ


class Consola:
    def __init__(self):
        self.mensajes = []

    def Prompt(self, t):
        self.mensajes.append(t)


def grande_esc(n=5000, bloques=("58a",)):
    d = DocEsc(objetos=n, bloques=bloques)
    d.Name, d.Utility = "plano_cliente.dwg", Consola()
    return d


def ins(d, **kw):
    return pe.ejecutar_op(d, {"op": "insertar", "nombre": "58a", "capa": "SCH_BLOQUES", "puntos": [[1, 2]],
                              "max_objetos": 300, **kw}, mk=MK)


def test_ensayo_en_plano_grande_funciona_y_muestra_codigo_solo_en_autocad():
    d = grande_esc()
    r = ins(d, ejecutar=False)
    assert r["ok"] and r["dibujo_grande"] is True and d.ModelSpace.insertados == []
    codigo = pe.codigo_dibujo(d)
    assert any(codigo in m for m in d.Utility.mensajes)
    assert codigo not in str(r) and "plano_cliente" not in str(r)          # nunca en la respuesta (chat)


def test_escribir_con_codigo_correcto_en_plano_grande():
    d = grande_esc()
    r = ins(d, ejecutar=True, confirmacion=pe.codigo_dibujo(d).lower())     # no distingue mayusculas
    assert r["ok"] and r["cantidad"] == 1 and len(d.ModelSpace.insertados) == 1


def test_codigo_incorrecto_o_vacio_no_escribe():
    d = grande_esc()
    for c in (None, "", "ZZZZ"):
        r = ins(d, ejecutar=True, confirmacion=c)
        assert r["error"] == "dibujo_grande_requiere_confirmacion"
    assert d.ModelSpace.insertados == []


def test_el_codigo_cambia_de_un_dibujo_a_otro():
    a, b = grande_esc(), grande_esc()
    b.Name = "otro_plano.dwg"
    assert pe.codigo_dibujo(a) != pe.codigo_dibujo(b)


def test_dibujo_pequeno_no_necesita_codigo():
    d = DocEsc(bloques=["58a"])
    assert ins(d, ejecutar=True)["ok"]


# ---------- biblioteca completa ----------
def biblioteca():
    defs = {"Mira R_Davide Groppi": Bloque([Ent("AcDbLine", 100, 50, x0=500, y0=500)]),
            "Ohm_Davide Groppi": Bloque([Ent("AcDbCircle", 20, 20)]),
            "*U12": Bloque([Ent()]), "A$C1": Bloque([Ent()])}
    for n, b in defs.items():
        b.IsLayout, b.IsXRef, b.Name = False, False, n
    return DocSim("bloques_schaller.dwg", 4, defs)


class BlocksIter:
    """Los Blocks de la sonda real se recorren; el falso solo tiene .defs."""


def con_iter(doc):
    doc.Blocks.__class__ = type("B", (doc.Blocks.__class__,), {"__iter__": lambda self: iter(self.defs.values())})
    return doc


def test_nombres_de_biblioteca_omite_anonimos():
    assert ps.nombres_de_biblioteca(con_iter(biblioteca())) == ["Mira R_Davide Groppi", "Ohm_Davide Groppi"]


def test_importar_biblioteca_copia_tal_cual_sin_centrar_ni_escalar():
    o, d = con_iter(biblioteca()), DocSim("plano.dwg", 4)
    r = ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert set(d.Blocks.creados) == {"Mira R_Davide Groppi", "Ohm_Davide Groppi"}
    e = d.Blocks.defs["Mira R_Davide Groppi"][0]
    assert e.escalas == [] and e.movimientos == [] and (e.x0, e.y0) == (500, 500)   # sin recentrar
    assert r["simbolos"]["Ohm_Davide Groppi"]["estado"] == "importado"


class RefModelo:
    ObjectName = "AcDbBlockReference"

    def __init__(self, nombre):
        self.EffectiveName = nombre


def test_nombres_con_ficha_solo_los_colocados_y_sin_repetir():
    o = con_iter(biblioteca())
    o.ModelSpace.extend([RefModelo("Ohm_Davide Groppi"), Ent("AcDbPolyline"), RefModelo("OHM_davide groppi")])
    assert ps.nombres_con_ficha(o) == ["Ohm_Davide Groppi"]                 # 'Mira R' esta definido pero sin ficha


def test_importar_biblioteca_por_defecto_deja_fuera_los_bloques_sin_ficha():
    o, d = con_iter(biblioteca()), DocSim("plano.dwg", 4)
    o.ModelSpace.append(RefModelo("Ohm_Davide Groppi"))
    ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True)
    assert d.Blocks.creados == ["Ohm_Davide Groppi"]                          # no llega 'Mira R' (resto sin ficha)
    d2 = DocSim("plano2.dwg", 4)
    ps.importar(o, d2, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert set(d2.Blocks.creados) == {"Mira R_Davide Groppi", "Ohm_Davide Groppi"}


def test_tool_importar_biblioteca_pasa_solo_con_ficha(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server.acad, "importar_simbolos", lambda args, **k: llamadas.append(args) or {"ok": True, "ejecutado": False, "avisos": [], "simbolos": {}})
    server.importar_biblioteca()
    server.importar_biblioteca(solo_con_ficha=False)
    assert [a["solo_con_ficha"] for a in llamadas] == [True, False]


def test_importar_biblioteca_convierte_unidades_si_difieren():
    o = con_iter(biblioteca())
    d = DocSim("plano_m.dwg", 6)                                              # plano en metros, biblioteca en mm
    ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert d.Blocks.defs["Ohm_Davide Groppi"][0].escalas == [0.001]


class EntRef(Ent):
    def __init__(self, nombre):
        super().__init__("AcDbBlockReference")
        self.Name = nombre


def biblioteca_con_anidado():
    # 'A geometria' sale ANTES que 'A_x' en orden alfabetico (espacio < guion bajo), como pasaba con FORTYEIGHT
    defs = {"A geometria_T": Bloque([Ent("AcDbEllipse", 46, 30)]), "A_x_T": Bloque([EntRef("A geometria_T"), Ent("AcDbText")]),
            "B_T": Bloque([Ent("AcDbCircle", 20, 20)])}
    for n, b in defs.items():
        b.IsLayout, b.IsXRef, b.Name = False, False, n
    return con_iter(DocSim("bloques_schaller.dwg", 4, defs))


def test_padres_primero_deja_los_anidados_al_final():
    o = biblioteca_con_anidado()
    assert ps.padres_primero(o, ["A geometria_T", "A_x_T", "B_T"]) == ["A_x_T", "B_T", "A geometria_T"]


def test_importar_no_escala_dos_veces_el_sub_bloque():
    """El sub-bloque llega con el padre (CopyObjects de la fake lo trae sin escalar) y luego 'ya existe': no se vuelve a escalar."""
    o, d = biblioteca_con_anidado(), DocSim("plano_m.dwg", 6)
    orig_copy = o.CopyObjects

    def copiar(objs, owner):                      # como AutoCAD: copiar un ref trae tambien su definicion anidada sin escalar
        orig_copy(objs, owner)
        for e in objs:
            if getattr(e, "Name", None) and e.Name not in d.Blocks.defs:
                d.Blocks.defs[e.Name] = Bloque([Ent("AcDbEllipse", 46, 30)])
    o.CopyObjects = copiar
    r = ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert r["simbolos"]["A geometria_T"]["estado"].startswith("ya_existia")
    assert [e.escalas for e in d.Blocks.defs["A geometria_T"]] == [[]]            # sin escalar: llego con el padre
    assert [e.escalas for e in d.Blocks.defs["A_x_T"]][0] == [0.001]              # el padre si, una sola vez


def test_importar_biblioteca_no_pisa_lo_que_ya_existe():
    o = con_iter(biblioteca())
    d = DocSim("plano.dwg", 4, {"Ohm_Davide Groppi": Bloque([Ent()])})
    ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert d.Blocks.creados == ["Mira R_Davide Groppi"]


def test_importar_biblioteca_en_plano_grande_pide_codigo():
    o, d = con_iter(biblioteca()), DocSim("plano.dwg", 4, n=5000)
    r = ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert r["error"] == "dibujo_grande_requiere_confirmacion" and d.Blocks.creados == []
    ok = ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False, confirmacion=ps.codigo_dibujo(d))
    assert ok["ok"] and len(d.Blocks.creados) == 2


# ---------- comparar (solo lectura) ----------
def plano_con(defs, unidades=4):
    for n, b in defs.items():
        b.IsLayout, b.IsXRef, b.Name = False, False, n
    return con_iter(DocSim("plano.dwg", unidades, defs))


def test_comparar_detecta_faltan_iguales_distintos_y_oculta_nombres_ajenos():
    o = con_iter(biblioteca())
    d = plano_con({"Mira R_Davide Groppi": Bloque([Ent("AcDbLine", 100, 50, x0=0, y0=0)]),     # igual (otra posicion no importa)
                   "Ohm_Davide Groppi": Bloque([Ent("AcDbCircle", 40, 40)]),                     # tamano distinto
                   "Apellido Cliente": Bloque([Ent()])})                                        # no esta en la biblioteca
    r = ps.comparar(o, d)
    assert r["ok"] and r["solo_lectura"] and r["en_biblioteca"] == 2 and r["iguales"] == 1
    assert r["posiblemente_desactualizados"] == ["Ohm_Davide Groppi"] and r["faltan_en_plano"] == []
    assert r["solo_en_plano_cantidad"] == 1 and "Apellido" not in str(r)
    assert ps.comparar(o, d, True)["solo_en_plano"] == ["Apellido Cliente"]


def test_comparar_ignora_el_ancho_de_los_textos():
    o = con_iter(biblioteca())
    o.Blocks.defs["Ohm_Davide Groppi"].append(Ent("AcDbText", 5, 1))                  # codigo del bloque en la biblioteca
    d = plano_con({"Ohm_Davide Groppi": Bloque([Ent("AcDbCircle", 20, 20), Ent("AcDbText", 9, 1)]),   # otra fuente: mas ancho
                   "Mira R_Davide Groppi": Bloque([Ent("AcDbLine", 100, 50, x0=0, y0=0)])})
    r = ps.comparar(o, d)
    assert r["iguales"] == 2 and r["posiblemente_desactualizados"] == []


def test_comparar_lista_los_que_faltan_y_no_escribe_nada():
    o, d = con_iter(biblioteca()), plano_con({})
    r = ps.comparar(o, d)
    assert r["faltan_en_plano"] == ["Mira R_Davide Groppi", "Ohm_Davide Groppi"] and d.Blocks.creados == []


def test_comparar_convierte_unidades_antes_de_comparar():
    o = con_iter(biblioteca())                                                    # mm
    d = plano_con({"Ohm_Davide Groppi": Bloque([Ent("AcDbCircle", 0.02, 0.02)]),  # el mismo circulo, en metros
                   "Mira R_Davide Groppi": Bloque([Ent("AcDbLine", 0.1, 0.05)])}, unidades=6)
    assert ps.comparar(o, d)["iguales"] == 2


def test_comparar_tool_pasa_los_argumentos(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server.acad, "importar_simbolos", lambda args, **k: llamadas.append(args) or {"ok": True})
    server.comparar_biblioteca(destino_contiene="plano")
    assert llamadas[0]["comparar"] is True and "ejecutar" not in llamadas[0] and llamadas[0]["mostrar_solo_en_plano"] is False


# ---------- dibujar_espacios ----------
class Obj:
    def __init__(self, h):
        self.Handle, self.Layer = h, None


def doc_dibujo(objetos=0):
    d = DocEsc(objetos=objetos)
    dib = []
    d.dibujados = dib

    def poli(pts):
        o = Obj(f"P{len(dib)}")
        dib.append(("poli", pts, o))
        return o

    def texto(t, p, h):
        o = Obj(f"T{len(dib)}")
        dib.append(("texto", t, o))
        return o

    d.ModelSpace.AddLightWeightPolyline = poli
    d.ModelSpace.AddText = texto
    return d


SP = [{"nombre": "Sala", "x0": 0, "y0": 0, "x1": 5000, "y1": 4000}, {"nombre": "Baño", "x0": 5000, "y0": 0, "x1": 7000, "y1": 2500}]


def esp(d, **kw):
    return pe.ejecutar_op(d, {"op": "espacios", "espacios": SP, "capa_muros": "SCH_MUROS", "capa_espacios": "SCH_ESPACIOS",
                              "max_objetos": 300, **kw}, mk=MK, mkd=lambda v: list(v))


def test_espacios_ensayo_no_dibuja():
    d = doc_dibujo()
    r = esp(d, ejecutar=False)
    assert r["ok"] and r["espacios"] == 2 and d.dibujados == [] and d.Layers.agregados == []


def test_espacios_dibuja_rectangulos_y_nombres_en_sus_capas():
    d = doc_dibujo()
    r = esp(d, ejecutar=True)
    assert r["ok"] and len(r["handles"]) == 4
    polis = [x for x in d.dibujados if x[0] == "poli"]
    assert polis[0][1] == [0, 0, 5000, 0, 5000, 4000, 0, 4000] and {p[2].Layer for p in polis} == {"SCH_MUROS"}
    assert [x[1] for x in d.dibujados if x[0] == "texto"] == ["Sala", "Baño"]
    assert {"SCH_MUROS", "SCH_ESPACIOS"} <= d.Layers.nombres


def test_espacios_en_plano_grande_pide_codigo():
    d = doc_dibujo(objetos=5000)
    d.Name, d.Utility = "plano.dwg", Consola()
    assert esp(d, ejecutar=True)["error"] == "dibujo_grande_requiere_confirmacion" and d.dibujados == []
    assert esp(d, ejecutar=True, confirmacion=pe.codigo_dibujo(d))["ok"]


def test_tool_dibujar_espacios_valida_y_pasa_capas(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server, "_escribir", lambda a: llamadas.append(a) or {"ok": True})
    mal = server.dibujar_espacios([{"nombre": "X", "x0": 5, "y0": 0, "x1": 1, "y1": 3}, {"nombre": "", "x0": 0, "y0": 0, "x1": 1, "y1": 1}])
    assert mal["error"] == "items_con_problemas" and len(mal["problemas"]) == 2 and llamadas == []
    ok = server.dibujar_espacios([{"nombre": "Sala", "x0": 0, "y0": 0, "x1": 5, "y1": 4}], confirmacion="AB12")
    a = llamadas[0]
    assert ok["ok"] and a["capa_muros"] == "SCH_MUROS" and a["capa_espacios"] == "SCH_ESPACIOS" and a["ejecutar"] is False


# ---------- herramientas del servidor ----------
def test_insertar_bloques_agrupa_y_usa_capa_sch(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server, "_escribir", lambda a: llamadas.append(a) or {"ok": True})
    r = server.insertar_bloques([{"bloque": "Ohm_Davide Groppi", "x": 1, "y": 2},
                                 {"bloque": "Ohm_Davide Groppi", "x": 3, "y": 4, "rotacion_grados": 90}], confirmacion="AB12")
    a = llamadas[0]
    assert r["ok"] and r["capa"] == "SCH_BLOQUES" and a["confirmacion"] == "AB12" and a["ejecutar"] is False
    assert a["grupos"] == [{"nombre": "Ohm_Davide Groppi", "capa": "SCH_BLOQUES", "puntos": [[1.0, 2.0, 0.0], [3.0, 4.0, 90.0]],
                            "largo": None, "escala_x": None, "escala_y": None}]


# ---------- adaptar bloques (largo / escala) y flechas ----------
class EntFalsa:
    def __init__(self, tipo, x0, x1):
        self.ObjectName, self._c = tipo, (x0, x1)

    def GetBoundingBox(self):
        return (self._c[0], 0.0, 0.0), (self._c[1], 0.0, 0.0)


def doc_con_tira(ancho=1.816, con_texto=True):
    d = DocEsc(bloques=["Durastrip_Targetti"])
    ents = [EntFalsa("AcDbPolyline", -ancho / 2, ancho / 2)] + ([EntFalsa("AcDbText", 5.0, 9.0)] if con_texto else [])
    d.Blocks.Item = lambda n: ents if n == "Durastrip_Targetti" else (_ for _ in ()).throw(KeyError(n))
    d.ModelSpace.escalas = []
    antes = d.ModelSpace.InsertBlock
    d.ModelSpace.InsertBlock = lambda p, n, ex, ey, ez, rot: d.ModelSpace.escalas.append((p, ex, ey, round(rot, 4))) or antes(p, n, ex, ey, ez, rot)
    return d


def grupo(**kw):
    return {"op": "insertar_varios", "ejecutar": True, "max_objetos": 300,
            "grupos": [{"nombre": "Durastrip_Targetti", "capa": "SCH_BLOQUES", "puntos": [[7.5, 12.6, 0]], **kw}]}


def test_largo_estira_el_bloque_sin_contar_el_texto():
    d = doc_con_tira()
    r = pe.ejecutar_op(d, grupo(largo=3.0), mk=MK)
    (p, ex, ey, rot), = d.ModelSpace.escalas
    assert r["ok"] and abs(ex - 3.0 / 1.816) < 1e-9 and ey == 1.0 and p == (7.5, 12.6, 0)
    assert r["grupos"][0]["escala"] == [round(3.0 / 1.816, 4), 1.0]


def test_ensayo_con_largo_informa_la_escala_y_no_inserta():
    d = doc_con_tira()
    r = pe.ejecutar_op(d, {**grupo(largo=7.0), "ejecutar": False}, mk=MK)
    assert r["grupos"][0]["escala"][0] == round(7.0 / 1.816, 4) and d.ModelSpace.escalas == []


def test_escala_explicita_y_rotacion_vertical():
    d = doc_con_tira()
    g = grupo(escala_x=2.0, escala_y=1.5)
    g["grupos"][0]["puntos"] = [[0.1, 3.5, 90]]
    pe.ejecutar_op(d, g, mk=MK)
    assert d.ModelSpace.escalas == [((0.1, 3.5, 0), 2.0, 1.5, round(math.radians(90), 4))]


def test_si_no_se_puede_medir_no_inserta_nada():
    d = doc_con_tira()
    d.Blocks.Item = lambda n: [EntFalsa("AcDbText", 0, 1)]          # solo texto: sin geometria medible
    r = pe.ejecutar_op(d, grupo(largo=3.0), mk=MK)
    assert r["error"] == "no_se_pudo_adaptar_bloque" and d.ModelSpace.insertados == []


def test_insertar_bloques_valida_largo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server, "_escribir", lambda a: llamadas.append(a) or {"ok": True})
    mal = server.insertar_bloques([{"bloque": "A", "x": 0, "y": 0, "largo": -1}, {"bloque": "A", "x": 0, "y": 0, "largo": 2, "escala_x": 2}])
    assert mal["error"] == "items_con_problemas" and len(mal["problemas"]) == 2 and llamadas == []
    server.insertar_bloques([{"bloque": "A", "x": 1, "y": 2, "largo": 3}, {"bloque": "A", "x": 5, "y": 2, "largo": 4}])
    assert [g["largo"] for g in llamadas[0]["grupos"]] == [3.0, 4.0]          # distinto largo = grupos distintos


def test_lineas_dibuja_en_capa_roja():
    d = doc_dibujo()
    lineas = []
    d.ModelSpace.AddLine = lambda a, b: lineas.append((a, b)) or Obj(f"L{len(lineas)}")
    r = pe.ejecutar_op(d, {"op": "lineas", "segmentos": [[0, 0, 1, 0], [1, 0, 0.8, 0.1]], "capa": "SCH_APUNTADO", "ejecutar": True,
                           "max_objetos": 300}, mk=MK)
    assert r["ok"] and r["lineas"] == 2 and lineas[0] == ((0, 0, 0), (1, 0, 0)) and "SCH_APUNTADO" in d.Layers.nombres


def test_nombre_visible_quita_la_marca_y_los_guiones_bajos():
    assert server.nombre_visible("Durastrip IP20_75W_Targetti") == "Durastrip IP20 75W"
    assert server.nombre_visible("Moon_200_Davide Groppi") == "Moon 200"
    assert server.nombre_visible("CCTEvo Architectural_58_Targetti") == "CCTEvo Architectural 58"
    assert server.nombre_visible("Solo") == "Solo"


def test_textos_op_escribe_centrado_en_su_capa():
    d = doc_dibujo()
    r = pe.ejecutar_op(d, {"op": "textos", "capa": "SCH_ETIQUETAS", "ejecutar": True, "max_objetos": 300,
                           "textos": [{"texto": "Moon 200", "x": 7, "y": 2.2, "altura": 0.15, "rotacion_grados": 90}]}, mk=MK)
    (_, texto, obj), = d.dibujados
    assert r["ok"] and texto == "Moon 200" and obj.Layer == "SCH_ETIQUETAS" and obj.Alignment == 10 and "SCH_ETIQUETAS" in d.Layers.nombres
    assert abs(obj.Rotation - math.radians(90)) < 1e-9


def test_dibujar_textos_usa_el_nombre_del_bloque(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server, "_escribir", lambda a: llamadas.append(a) or {"ok": True})
    r = server.dibujar_textos([{"bloque": "Durastrip IP20_75W_Targetti", "x": 7.5, "y": 12.85}, {"texto": "Hola", "x": 0, "y": 0, "altura": 0.3}])
    a = llamadas[0]
    assert r["rotulos"] == ["Durastrip IP20 75W", "Hola"] and a["capa"] == "SCH_ETIQUETAS" and a["textos"][0]["altura"] == 0.15 and a["textos"][1]["altura"] == 0.3
    assert server.dibujar_textos([{"x": 1, "y": 2}])["error"] == "items_con_problemas"


def test_importar_escala_tambien_el_patron_de_linea():
    o = con_iter(biblioteca())
    d = DocSim("plano_m.dwg", 6)
    ent = o.Blocks.defs["Ohm_Davide Groppi"][0]
    ent.LinetypeScale = 400.0
    original = DocSim.CopyObjects

    def copiar(self, objs, owner):                 # la fake de CopyObjects crea Ent nuevos: les pasamos el patron
        for e in objs:
            c = Ent(e.ObjectName, e.ancho, e.alto, e.x0, e.y0)
            c.LinetypeScale = getattr(e, "LinetypeScale", 1.0)
            owner.append(c)
    o.CopyObjects = lambda objs, owner: copiar(o, objs, owner)
    ps.importar(o, d, None, True, mk=MK, mkobj=MKOBJ, como_esta=True, solo_con_ficha=False)
    assert abs(d.Blocks.defs["Ohm_Davide Groppi"][0].LinetypeScale - 0.4) < 1e-9


def test_flecha_hacia_la_izquierda(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server, "_escribir", lambda a: llamadas.append(a) or {"ok": True})
    server.dibujar_flechas([{"x": 3.0, "y": 11.5, "angulo_grados": 180, "largo": 1.5}])
    seg = llamadas[0]["segmentos"]
    assert seg[0] == [3.0, 11.5, 1.5, 11.5] and len(seg) == 3 and llamadas[0]["capa"] == "SCH_APUNTADO"
    assert all(s[0] == 1.5 and s[2] > 1.5 for s in seg[1:])                    # las puntas salen de la punta hacia atras (derecha)
    mal = server.dibujar_flechas([{"x": 0, "y": 0, "angulo_grados": 0, "largo": 0}])
    assert mal["error"] == "items_con_problemas"


def test_insertar_bloques_rechaza_items_invalidos_sin_escribir(monkeypatch):
    monkeypatch.setattr(server, "_escribir", lambda a: (_ for _ in ()).throw(AssertionError("no debe escribir")))
    r = server.insertar_bloques([{"bloque": "", "x": 1, "y": 2}, {"bloque": "A", "x": "uno", "y": 2}])
    assert r["error"] == "items_con_problemas" and len(r["problemas"]) == 2


def test_importar_biblioteca_tool_resume(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server.acad, "importar_simbolos", lambda args, **k: llamadas.append(args) or {
        "ok": True, "ejecutado": False, "dibujo_grande": True, "avisos": [],
        "simbolos": {"A": {"estado": "se_importaria"}, "B": {"estado": "ya_existia_en_destino (no se toca)"},
                     "C": {"estado": "fallo", "detalle": "x"}}})
    r = server.importar_biblioteca()
    assert llamadas[0]["nombres"] is None and llamadas[0]["como_esta"] is True and llamadas[0]["origen_contiene"] == "bloques_schaller"
    assert r["resumen"] == {"total": 3, "se_importarian_o_importados": 1, "ya_existian": 1, "fallaron": 1}
    assert "ENSAYO" in r["aviso"] and list(r["fallos"]) == ["C"]
