"""El escaneo mide el plano: recintos desde muros, medidas reales de cada recinto y resumen cuantitativo. Sin reglas de diseno."""
import pytest

import zonas_motor

VOCAB = zonas_motor.cargar_vocabulario()
shapely = pytest.importorskip("shapely")


def caja(x0, y0, x1, y1, espesor=0.2, huecos=()):
    from tests.test_recintos import caja_doble
    return caja_doble(x0, y0, x1, y1, espesor, huecos)


def raw_muros(segs, u=1.0, textos=None, poligonos=None, bloques=None, capa_muros=True):
    return {"unidad_m": u, "textos": textos or [], "poligonos": poligonos or [], "bloques": bloques or [],
            "muros": {"segmentos": [list(s) for s in segs], "capas": {"A-MURO": len(segs)} if capa_muros else {}, "entidades": len(segs), "truncado": False}}


def test_un_plano_solo_de_muros_sin_rotulos_ni_mobiliario_da_recintos_con_medidas():
    segs = caja(0, 0, 4, 3) + caja(4.2, 0, 9.2, 3, huecos=[("O", 1.0, 1.9)]) + caja(0, 3.2, 9.2, 6) [:0]
    r = zonas_motor.construir_zonas(raw_muros(segs), VOCAB)
    assert r["total"] == 2 and all(z["origen"] == "muros" and z["confianza"] == "baja" and z["candidato"] for z in r["zonas"])
    m = sorted((z["medidas"]["largo_m"], z["medidas"]["ancho_m"]) for z in r["zonas"])
    assert m[0] == pytest.approx((4.0, 3.0), abs=0.3) and m[1] == pytest.approx((5.0, 3.0), abs=0.3)


def test_cada_recinto_trae_area_perimetro_orientacion_y_forma():
    r = zonas_motor.construir_zonas(raw_muros(caja(0, 0, 4, 3)), VOCAB)
    md = r["zonas"][0]["medidas"]
    assert md["area_m2"] == pytest.approx(12.0, abs=0.8) and md["perimetro_m"] == pytest.approx(14.0, abs=0.8)
    assert md["relacion_aspecto"] == pytest.approx(1.33, abs=0.1) and md["rectangularidad"] > 0.95 and md["compacidad"] > 0.7
    assert md["angulo_grados"] in (pytest.approx(0, abs=1), pytest.approx(180, abs=1))


def test_un_texto_con_nombre_dentro_de_un_recinto_de_muros_lo_nombra_con_confianza_media():
    r = zonas_motor.construir_zonas(raw_muros(caja(0, 0, 4, 3), textos=[{"t": "Sala de juntas", "x": 2, "y": 1.5, "capa": "T"}]), VOCAB)
    z = r["zonas"][0]
    assert z["tipo_espacio"] == "sala_juntas" and z["origen"] == "texto+muros" and z["confianza"] == "media" and z["medidas"]["area_m2"] > 10


def test_el_mobiliario_dentro_de_un_recinto_de_muros_le_da_tipo_y_se_declara():
    bloque = {"n": "cama king", "capa": "0", "x0": 1.0, "y0": 0.5, "x1": 3.0, "y1": 2.5}
    z = zonas_motor.construir_zonas(raw_muros(caja(0, 0, 4, 3), bloques=[bloque]), VOCAB)["zonas"][0]
    assert z["tipo_espacio"] == "alcoba" and z["origen"] == "muros" and z["muebles"] == ["cama king"]


def test_los_muros_en_un_dibujo_declarado_en_mm_se_miden_en_metros():
    segs = [(a * 1000, b * 1000, c * 1000, d * 1000) for a, b, c, d in caja(0, 0, 4, 3)]
    r = zonas_motor.construir_zonas(raw_muros(segs, u=0.001), VOCAB)
    assert r["unidad_m"] == 0.001 and r["zonas"][0]["medidas"]["area_m2"] == pytest.approx(12.0, abs=0.8)


def test_si_el_dibujo_dice_mm_pero_esta_en_metros_los_muros_ayudan_a_corregir_la_unidad():
    r = zonas_motor.construir_zonas(raw_muros(caja(0, 0, 4, 3) + caja(4.2, 0, 8, 3), u=0.001), VOCAB)
    assert r["unidad_m"] == 1.0 and r["aviso_unidades"] and r["total"] == 2


def test_el_resumen_del_plano_son_solo_medidas():
    r = zonas_motor.construir_zonas(raw_muros(caja(0, 0, 4, 3) + caja(4.2, 0, 8, 3)), VOCAB)
    mp = r["medidas_plano"]
    assert mp["unidad_m"] == 1.0 and mp["muros"]["segmentos"] == 16 and mp["muros"]["longitud_total_m"] > 40
    assert mp["recintos"]["total"] == 2 and mp["recintos"]["por_origen"] == {"muros": 2} and mp["recintos"]["area_total_m2"] > 20
    assert mp["vistas"][0]["ancho_m"] >= 7.9 and mp["reconstruccion_por_muros"]["recintos"] == 2
    texto = str(mp).lower()
    for sesgo in ("downlight", "luminaria", "producto", "rejilla", "espaciado"):
        assert sesgo not in texto                               # el escaneo mide, no aplica reglas de diseno


def test_sin_shapely_el_resto_del_escaneo_funciona_y_lo_dice(monkeypatch):
    import recintos
    monkeypatch.setattr(recintos, "disponible", lambda: False)
    polis = [{"capa": "M", "pts": [[0, 0], [4, 0], [4, 3.5], [0, 3.5]]}]
    r = zonas_motor.construir_zonas({**raw_muros(caja(0, 0, 4, 3)), "poligonos": polis}, VOCAB)
    assert r["total"] == 1 and r["zonas"][0]["origen"] == "poligono"                      # el poligono dibujado sigue funcionando
    assert r["medidas_plano"]["reconstruccion_por_muros"]["error"] == "geometria_avanzada_no_disponible"


def test_un_recinto_dibujado_como_poligono_tambien_trae_medidas():
    r = zonas_motor.construir_zonas({"unidad_m": 1.0, "textos": [], "poligonos": [{"capa": "M", "pts": [[0, 0], [5, 0], [5, 4], [0, 4]]}], "bloques": []}, VOCAB)
    assert r["zonas"][0]["medidas"]["largo_m"] == 5.0 and r["zonas"][0]["medidas"]["ancho_m"] == 4.0 and r["zonas"][0]["medidas"]["area_m2"] == 20.0


def test_los_trazos_cerrados_finos_en_capas_de_muros_son_muros_macizos():
    solidos = [{"capa": "A-MURO", "pts": [[0, 0], [5, 0], [5, 0.2], [0, 0.2]]}, {"capa": "A-MURO", "pts": [[0, 3.8], [5, 3.8], [5, 4], [0, 4]]},
               {"capa": "A-MURO", "pts": [[0, 0], [0.2, 0], [0.2, 4], [0, 4]]}, {"capa": "A-MURO", "pts": [[4.8, 0], [5, 0], [5, 4], [4.8, 4]]}]
    r = zonas_motor.construir_zonas({"unidad_m": 1.0, "textos": [], "poligonos": solidos, "bloques": []}, VOCAB)
    assert r["total"] == 1 and r["zonas"][0]["origen"] == "muros" and r["zonas"][0]["medidas"]["area_m2"] == pytest.approx(16.5, abs=1.5)
