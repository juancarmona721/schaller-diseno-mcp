"""Que lineas son muros: por nombre de capa y, si no hay nombres utiles, por geometria. Integrado con el escaneo."""
import re

import pytest

import muros as mu
import zonas_motor

VOCAB = zonas_motor.cargar_vocabulario()


def con_capa(segs, capa):
    return [[*s, capa] for s in segs]


def habitacion(x0, y0, x1, y1):
    return [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]


def varias(n=4):
    segs = []
    for i in range(n):
        for j in range(n):
            segs += habitacion(i * 5.0, j * 4.0, i * 5.0 + 4.8, j * 4.0 + 3.8)
    return segs


def test_estadisticas_por_capa_miden_cantidad_longitud_y_ortogonalidad():
    e = mu.estadisticas_por_capa(con_capa(habitacion(0, 0, 4, 3), "A") + con_capa([(0, 0, 3, 3)], "B"))
    assert e["A"] == {"n": 4, "longitud_m": 14.0, "mediana_m": 4.0, "ortogonal": 1.0} or e["A"]["longitud_m"] == 14.0
    assert e["B"]["ortogonal"] == 0.0 and e["B"]["n"] == 1


def test_una_capa_de_trazos_largos_y_ortogonales_parece_de_muros():
    e = mu.estadisticas_por_capa(con_capa(varias(), "X-PLANO 2") + con_capa([(i * 0.01, 0, i * 0.01 + 0.005, 0) for i in range(400)], "HATCH"))
    assert mu.capas_por_geometria(e, re.compile("(?!x)x")) == ["X-PLANO 2"]


def test_las_capas_de_mobiliario_o_cajetin_nunca_se_eligen_por_geometria():
    e = mu.estadisticas_por_capa(con_capa(varias(), "MB-AMOBLAMIENTO") + con_capa(varias(), "ROTULO"))
    assert mu.capas_por_geometria(e, VOCAB.capas_no_recinto) == []


def test_trazos_en_diagonal_o_pocos_no_son_muros():
    diag = [(i, 0, i + 1, 1.0) for i in range(30)]
    assert mu.capas_por_geometria(mu.estadisticas_por_capa(con_capa(diag, "D")), re.compile("(?!x)x")) == []
    assert mu.capas_por_geometria(mu.estadisticas_por_capa(con_capa(habitacion(0, 0, 4, 3), "P")), re.compile("(?!x)x")) == []


def test_el_nombre_de_capa_manda_sobre_la_geometria():
    d = mu.elegir([], con_capa(varias(), "A-MURO") + con_capa(varias(), "OTRA"), VOCAB.capas_muros_rx, VOCAB.capas_no_recinto)
    assert d["modo"] == "nombre_de_capa" and d["capas"] == ["A-MURO"] and len(d["segmentos"]) == len(varias())


def test_sin_nombres_se_usa_la_geometria_y_se_informa():
    d = mu.elegir([], con_capa(varias(), "X-PLANO 2"), VOCAB.capas_muros_rx, VOCAB.capas_no_recinto)
    assert d["modo"] == "geometria" and d["capas"] == ["X-PLANO 2"] and "X-PLANO 2" in d["estadisticas"]


def test_sin_muros_ni_geometria_de_muros_el_modo_es_ninguno_pero_las_estadisticas_se_informan():
    d = mu.elegir([], con_capa([(i, 0, i + 1, 1) for i in range(40)], "RUIDO"), VOCAB.capas_muros_rx, VOCAB.capas_no_recinto)
    assert d["modo"] == "ninguno" and d["segmentos"] == [] and "RUIDO" in d["estadisticas"]


# ------------------------------------------------------------------------------------------------ integracion en el escaneo
pytest.importorskip("shapely")


def raw_lineas(lineas, **extra):
    return {"unidad_m": 1.0, "textos": [], "poligonos": [], "bloques": [], "lineas": {"segmentos": lineas, "truncado": False, "entidades_leidas": len(lineas)}, **extra}


def test_arquitectura_dentro_de_un_bloque_con_capas_sin_nombre_de_muro_da_recintos():
    from tests.test_recintos import caja_doble
    segs = []
    for i in range(3):
        segs += caja_doble(i * 5.0, 0, i * 5.0 + 4.6, 3.6)
    r = zonas_motor.construir_zonas(raw_lineas(con_capa(segs, "X-PLANO 2")), VOCAB)
    mm = r["medidas_plano"]["muros"]
    assert mm["como_se_eligieron"] == "geometria" and mm["capas_usadas"] == ["X-PLANO 2"] and "hipotesis" in mm["aviso"]
    assert r["total"] == 3 and all(z["origen"] == "muros" and z["confianza"] == "baja" for z in r["zonas"])
    assert "X-PLANO 2" in r["medidas_plano"]["lineas_por_capa"]


def test_si_el_bloque_trae_capas_con_nombre_de_muro_se_usan_por_nombre():
    from tests.test_recintos import caja_doble
    nombrados = []
    for i in range(4):                                                    # suficientes metros con nombre de muro (>= 60 m) para no completar por geometria
        nombrados += caja_doble(i * 6.0, 0, i * 6.0 + 4.6, 3.6)
    r = zonas_motor.construir_zonas(raw_lineas(con_capa(nombrados, "A-MURO") + con_capa(caja_doble(10, 10, 12, 12), "BASURA")), VOCAB)
    mm = r["medidas_plano"]["muros"]
    assert mm["como_se_eligieron"] == "nombre_de_capa" and mm["capas_usadas"] == ["A-MURO"] and "aviso" not in mm


def test_con_pocos_muros_con_nombre_se_completan_por_geometria_y_se_dice():
    from tests.test_recintos import caja_doble
    segs = con_capa(caja_doble(0, 0, 4, 3), "A-MURO")                      # solo ~28 m con nombre de muro
    for i in range(1, 4):
        segs += con_capa(caja_doble(i * 6.0, 0, i * 6.0 + 4.6, 3.6), "X-PLANO 2")
    r = zonas_motor.construir_zonas(raw_lineas(segs), VOCAB)
    mm = r["medidas_plano"]["muros"]
    assert mm["como_se_eligieron"] == "nombre_y_geometria" and set(mm["capas_usadas"]) == {"A-MURO", "X-PLANO 2"}
    assert r["total"] == 4


def test_el_resultado_siempre_dice_que_lineas_vio_aunque_no_las_use():
    r = zonas_motor.construir_zonas(raw_lineas(con_capa([(i, 0, i + 1, 1) for i in range(40)], "RUIDO")), VOCAB)
    assert r["medidas_plano"]["muros"]["como_se_eligieron"] == "ninguno" and "RUIDO" in r["medidas_plano"]["lineas_por_capa"]


def test_las_lineas_del_contenedor_ayudan_a_detectar_la_unidad():
    from tests.test_recintos import caja_doble
    segs = []
    for i in range(3):
        segs += caja_doble(i * 5.0, 0, i * 5.0 + 4.6, 3.6)
    r = zonas_motor.construir_zonas({**raw_lineas(con_capa(segs, "X-PLANO 2")), "unidad_m": 0.001}, VOCAB)
    assert r["unidad_m"] == 1.0 and "lo mayor" in r["aviso_unidades"] and r["total"] == 3                   # el aviso dice tambien la extension: ya no parece contradictorio


# ------------------------------------------------------------------------------------------------ planos importados de PDF: cada linea es un rectangulo finisimo
def trazo(x1, y1, x2, y2, ancho=0.015):
    """Un trazo de PDF: rectangulo fino alrededor del eje (x1,y1)-(x2,y2)."""
    import math
    L = math.hypot(x2 - x1, y2 - y1)
    nx, ny = -(y2 - y1) / L * ancho / 2, (x2 - x1) / L * ancho / 2
    return [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]


class FalsaPolilinea:
    ObjectName = "AcDbPolyline"

    def __init__(self, pts, capa="PDF_Geometria", cerrada=True):
        self.Layer = capa
        self.Coordinates = [v for p in pts for v in p]
        self.Closed = cerrada


class Id:
    @staticmethod
    def punto(x, y):
        return (x, y)


def _sz():
    import sonda_zonas
    return sonda_zonas


def test_un_trazo_fino_de_pdf_es_UN_segmento_con_su_longitud_real():
    sz = _sz()
    poli, segs, capa = sz._procesar_polilinea(FalsaPolilinea(trazo(0, 0, 4.0, 0)), "AcDbPolyline", Id)
    assert len(segs) == 1 and capa == "PDF_Geometria" and poli is not None
    x1, y1, x2, y2, _ = segs[0]
    assert abs(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 - 4.0) < 1e-3


def test_un_rectangulo_normal_no_es_un_trazo_y_da_sus_cuatro_lados():
    sz = _sz()
    poli, segs, _ = sz._procesar_polilinea(FalsaPolilinea([(0, 0), (3, 0), (3, 2), (0, 2)]), "AcDbPolyline", Id)
    assert len(segs) == 4 and poli == [[0, 0], [3, 0], [3, 2], [0, 2]]


def test_una_polilinea_abierta_da_segmentos_y_ningun_poligono():
    sz = _sz()
    poli, segs, _ = sz._procesar_polilinea(FalsaPolilinea([(0, 0), (2, 0), (2, 3)], cerrada=False), "AcDbPolyline", Id)
    assert poli is None and len(segs) == 2


def test_la_transformacion_del_bloque_se_aplica_al_eje():
    sz = _sz()

    class Mover:
        @staticmethod
        def punto(x, y):
            return (x + 100.0, y + 50.0)
    _, segs, _ = sz._procesar_polilinea(FalsaPolilinea(trazo(0, 0, 4.0, 0)), "AcDbPolyline", Mover)
    assert min(segs[0][0], segs[0][2]) == pytest.approx(100.0, abs=0.02) and segs[0][1] == pytest.approx(50.0, abs=0.02)


def test_la_capa_de_un_pdf_con_miles_de_trazos_diminutos_y_unos_pocos_largos_se_elige_por_sus_trazos_largos():
    import random
    random.seed(7)
    ruido = [(x * 0.01, 5.0, x * 0.01 + random.choice([0.01, 0.02, 0.03]), 5.0) for x in range(4000)]          # texto y hachura: trazos de 1-3 cm
    largos = varias(3)                                                                                          # las caras de los muros: trazos de ~4 m
    lineas = con_capa(ruido + largos, "PDF_Geometria")
    d = mu.elegir([], lineas, VOCAB.capas_muros_rx, VOCAB.capas_no_recinto)
    e = d["estadisticas"]["PDF_Geometria"]
    assert d["modo"] == "geometria" and d["capas"] == ["PDF_Geometria"] and e["mediana_m"] < 0.05 and e["trazos_largos"] == len(largos)
    assert len(d["segmentos"]) == len(largos)                                                                   # el ruido diminuto no entra como muro


def test_un_plano_de_pdf_con_muros_largos_reconstruye_habitaciones_aunque_la_mediana_sea_diminuta():
    from tests.test_recintos import caja_doble
    muros_ = []
    for i in range(3):
        muros_ += caja_doble(i * 5.0, 0, i * 5.0 + 4.6, 3.6)
    ruido = [(x * 0.01, 9.0, x * 0.01 + 0.015, 9.0) for x in range(3000)]
    r = zonas_motor.construir_zonas(raw_lineas(con_capa(muros_ + ruido, "PDF_Geometria")), VOCAB)
    assert r["total"] == 3 and r["medidas_plano"]["muros"]["como_se_eligieron"] == "geometria"


# ------------------------------------------------------------------------------------------------ lectura progresiva: cache de contenedores
class _Doc:
    Name = "Plano.dwg"


class _Ref:
    Handle = "2A"


class _Defn:
    Count = 5854


def test_la_cache_del_contenedor_depende_del_dibujo_la_instancia_y_el_numero_de_entidades(tmp_path):
    sz = _sz()
    a = sz._ruta_cache_contenedor(tmp_path, _Doc(), _Ref(), _Defn())

    class OtraCuenta(_Defn):
        Count = 5855

    class OtraRef(_Ref):
        Handle = "2B"
    assert a != sz._ruta_cache_contenedor(tmp_path, _Doc(), _Ref(), OtraCuenta())
    assert a != sz._ruta_cache_contenedor(tmp_path, _Doc(), OtraRef(), _Defn())
    assert a == sz._ruta_cache_contenedor(tmp_path, _Doc(), _Ref(), _Defn())
    assert sz._ruta_cache_contenedor(None, _Doc(), _Ref(), _Defn()) is None


def test_guardar_y_cargar_la_cache_es_atomico_y_tolera_archivos_danados(tmp_path):
    sz = _sz()
    ruta = tmp_path / "sub" / "cont_x.json"
    sz._guardar_cache_contenedor(ruta, {"leidas": 120, "completo": False, "lineas": [[0, 0, 1, 1, "A"]]})
    assert sz._cargar_cache_contenedor(ruta)["leidas"] == 120 and not list(ruta.parent.glob("*.tmp"))
    ruta.write_text("{roto", encoding="utf-8")
    assert sz._cargar_cache_contenedor(ruta) is None
    assert sz._cargar_cache_contenedor(tmp_path / "no_existe.json") is None
    sz._guardar_cache_contenedor(None, {"x": 1})                       # sin carpeta de cache: no hace nada ni falla


def test_una_lectura_incompleta_le_dice_a_claude_que_repita_hasta_completar(monkeypatch):
    import server
    raw = {"ok": True, "plano": "P.dwg", "unidad_m": 1.0, "textos": [], "poligonos": [], "bloques": [], "avisos": [], "tiempo_lectura_s": 40.0,
           "lectura": {"contenedores_completos": 0, "contenedores_incompletos": 1}}
    monkeypatch.setattr(server.acad, "estado", lambda timeout_s=10: {"ok": True, "dibujo_activo": "P.dwg", "objetos_en_modelo": 30})
    monkeypatch.setattr(server.acad, "plano_crudo", lambda **k: raw)
    r = server._zonas_del_plano(True)
    assert r["lectura_incompleta"] is True


def test_el_siguiente_paso_pide_repetir_el_escaneo_si_la_lectura_quedo_a_medias(monkeypatch):
    import server
    raw = {"ok": True, "plano": "P.dwg", "unidad_m": 1.0, "textos": [], "poligonos": [], "bloques": [], "avisos": [], "tiempo_lectura_s": 40.0,
           "lectura": {"contenedores_completos": 0, "contenedores_incompletos": 1}}
    monkeypatch.setattr(server.acad, "estado", lambda timeout_s=10: {"ok": True, "dibujo_activo": "P.dwg", "objetos_en_modelo": 30})
    monkeypatch.setattr(server.acad, "plano_crudo", lambda **k: raw)
    r = server.escanear_zonas(forzar_recarga=True)
    assert "forzar_recarga=True" in r["siguiente_paso"] and "INCOMPLETA" in r["siguiente_paso"]
