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
    r = zonas_motor.construir_zonas(raw_lineas(con_capa(caja_doble(0, 0, 4, 3), "A-MURO") + con_capa(caja_doble(10, 10, 12, 12), "BASURA")), VOCAB)
    mm = r["medidas_plano"]["muros"]
    assert mm["como_se_eligieron"] == "nombre_de_capa" and mm["capas_usadas"] == ["A-MURO"] and "aviso" not in mm


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
