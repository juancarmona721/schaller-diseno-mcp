"""Vistas (plantas candidatas) de un dibujo: dos plantas lado a lado, ruido, nombres por texto y integracion en el escaner."""
import plantas
import zonas_motor

VOCAB = zonas_motor.cargar_vocabulario()


def rect(x0, y0, x1, y1):
    return (x0, y0, x1, y1)


def planta(x0, y0, n=6):
    """Una planta de ~ 12 x 8 m con `n` recintos contiguos de 4 x 4."""
    return [rect(x0 + 4 * i, y0, x0 + 4 * i + 4, y0 + 4) for i in range(min(n, 3))] + [rect(x0 + 4 * i, y0 + 4, x0 + 4 * i + 4, y0 + 8) for i in range(min(n, 3))]


def test_un_dibujo_con_una_sola_planta_tiene_una_vista():
    v = plantas.detectar(planta(0, 0), [])
    assert len(v) == 1 and v[0]["id"] == "vista_1" and v[0]["tipo_vista"] == "desconocido" and v[0]["nivel"] is None


def test_dos_plantas_lado_a_lado_con_un_hueco_grande_son_dos_vistas_ordenadas_de_izquierda_a_derecha():
    v = plantas.detectar(planta(0, 0) + planta(30, 0), [])
    assert len(v) == 2 and v[0]["bbox"][0] == 0 and v[1]["bbox"][0] == 30 and [x["id"] for x in v] == ["vista_1", "vista_2"]
    assert v[0]["n_elementos"] == 6 and v[1]["n_elementos"] == 6


def test_dos_plantas_apiladas_tambien_se_separan():
    assert len(plantas.detectar(planta(0, 0) + planta(0, 40), [])) == 2


def test_cajas_a_menos_del_hueco_se_consideran_la_misma_vista():
    assert len(plantas.detectar(planta(0, 0) + planta(14, 0), [])) == 1                  # separadas 2 m: una sola vista


def test_el_hueco_depende_de_las_unidades_del_dibujo():
    en_mm = [tuple(c * 1000 for c in caja) for caja in planta(0, 0) + planta(30, 0)]
    assert len(plantas.detectar(en_mm, [], unidad_m=0.001)) == 2


def test_las_cotas_y_detalles_sueltos_no_crean_una_vista_nueva_se_unen_a_la_mas_cercana():
    ruido = [rect(12.5, -3, 12.8, -2.8), rect(40, 4, 40.4, 4.2)]                         # detalles pequenos lejos de todo
    v = plantas.detectar(planta(0, 0) + planta(30, 0) + ruido, [])
    assert len(v) == 2 and sum(x["n_elementos"] for x in v) == 14


def test_un_texto_de_planta_cercano_nombra_la_vista_pero_no_asigna_nivel():
    v = plantas.detectar(planta(0, 0) + planta(30, 0), [{"t": "PLANTA SEGUNDO PISO", "x": 36, "y": -3}, {"t": "Sala", "x": 2, "y": 2}])
    assert v[0]["nombre"] is None and v[1]["nombre"] == "PLANTA SEGUNDO PISO" and v[1]["confianza"] == "media"
    assert all(x["nivel"] is None for x in v)                                              # nunca se asume el nivel arquitectonico


def test_un_texto_de_nivel_lejano_no_nombra_ninguna_vista():
    v = plantas.detectar(planta(0, 0) + planta(30, 0), [{"t": "PLANTA 1", "x": 200, "y": 200}])
    assert all(x["nombre"] is None for x in v)


def test_vista_de_un_punto_y_el_mas_cercano_si_cae_fuera():
    v = plantas.detectar(planta(0, 0) + planta(30, 0), [])
    assert plantas.vista_de(v, 2, 2) == "vista_1" and plantas.vista_de(v, 33, 2) == "vista_2" and plantas.vista_de(v, 28, 2) == "vista_2"
    assert plantas.vista_de([], 0, 0) is None


def test_rendimiento_con_miles_de_cajas():
    import time
    cajas = [rect(i % 200 * 1.0, i // 200 * 1.0, i % 200 * 1.0 + 0.8, i // 200 * 1.0 + 0.8) for i in range(8000)]
    t = time.perf_counter()
    plantas.detectar(cajas, [])
    assert time.perf_counter() - t < 2.0


# ------------------------------------------------------------------------------------------------ integracion en el escaner
def poli(x0, y0, x1, y1):
    return {"capa": "M", "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def test_el_escaner_asigna_cada_zona_a_su_vista_y_las_lista():
    polis = [poli(i * 5, 0, i * 5 + 4.5, 4.5) for i in range(3)] + [poli(40 + i * 5, 0, 40 + i * 5 + 4.5, 4.5) for i in range(3)]
    raw = {"unidad_m": 1.0, "textos": [{"t": "PLANTA ALTA", "x": 50, "y": -2, "capa": "T"}], "poligonos": polis, "bloques": []}
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert len(r["vistas"]) == 2 and r["vistas"][1]["nombre"] == "PLANTA ALTA" and r["total"] == 6
    assert sorted({z["vista"] for z in r["zonas"]}) == ["vista_1", "vista_2"]
    assert sum(1 for z in r["zonas"] if z["vista"] == "vista_1") == 3


def test_con_una_sola_vista_no_se_agrega_ruido_a_cada_zona():
    raw = {"unidad_m": 1.0, "textos": [], "poligonos": [poli(0, 0, 4, 3.5)], "bloques": []}
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert len(r["vistas"]) == 1 and r["zonas"][0].get("vista") == "vista_1"


def test_los_objetos_sueltos_lejanos_no_inflan_la_caja_de_ninguna_vista():
    sueltos = [rect(5000, 5000, 5000.5, 5000.5), rect(-9000, 20, -8999.5, 20.5)]
    v = plantas.detectar(planta(0, 0) + planta(30, 0) + sueltos, [])
    assert len(v) == 2 and max(x["bbox"][2] for x in v) < 50 and min(x["bbox"][0] for x in v) >= 0


def test_una_caja_gigante_no_une_ni_define_vistas():
    gigante = [rect(0, 0, 5000, 5)]                          # un trazo de 5 km
    v = plantas.detectar(planta(0, 0) + planta(30, 0) + gigante, [])
    assert len(v) == 2


def test_el_ruido_cercano_si_se_une_a_su_vista():
    v = plantas.detectar(planta(0, 0) + [rect(13, 2, 13.4, 2.4)], [])
    assert len(v) == 1 and v[0]["n_elementos"] == 7
