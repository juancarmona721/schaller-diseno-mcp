import muros
import zonas_motor as zm


def _poli(pts, capa="muros"):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    a = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2
    return {"pts": pts, "area_m2": a, "bbox": (min(xs), min(ys), max(xs), max(ys)), "capa": capa, "origen_poli": "muros"}


def test_ejes_une_las_dos_caras_de_un_muro():
    segs = [[0, 0, 10, 0], [0, 0.12, 10, 0.12], [0, 5, 0, 8], [0.15, 5, 0.15, 8]]
    e = muros.ejes_de_muro(segs, 1.0)
    assert e["pares"] == 2 and abs(e["longitud_eje_m"] - 13.0) < 0.01
    assert abs(e["espesor_mediano_m"] - 0.12) < 0.02 and e["longitud_sin_pareja_m"] < 0.01


def test_ejes_segmentos_sin_pareja_se_informan_aparte():
    e = muros.ejes_de_muro([[0, 0, 10, 0], [0, 3, 10, 3]], 1.0)           # 3 m separados: no son caras del mismo muro
    assert e["pares"] == 0 and e["longitud_sin_pareja_m"] == 20.0


def test_recinto_en_L_no_es_un_contorno_que_contiene_a_su_vecino():
    L = _poli([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])        # caja 10x10, area 76
    vecino = _poli([(6, 6), (9, 6), (9, 9), (6, 9)])                       # dentro de la caja de la L pero FUERA de la L
    otro = _poli([(7, 7), (9, 7), (9, 9), (7, 9)])
    d, det = {}, {}
    salida = zm._poligonos_candidatos([L, vecino, otro], 1.0, d, det)
    assert L in salida and "contorno_que_contiene_varios" not in d


def test_contorno_que_si_contiene_varios_reporta_espacio_abierto():
    casco = _poli([(0, 0), (20, 0), (20, 10), (0, 10)])
    a = _poli([(1, 1), (5, 1), (5, 5), (1, 5)])
    b = _poli([(8, 1), (12, 1), (12, 5), (8, 5)])
    d, det = {}, {}
    salida = zm._poligonos_candidatos([casco, a, b], 1.0, d, det)
    assert casco not in salida and d["contorno_que_contiene_varios"] == 1
    ab = det["espacios_abiertos"][0]
    assert ab["recintos_contenidos"] == 2 and abs(ab["area_libre_m2"] - 168.0) < 0.1


def test_zonas_traen_contorno_y_centroide_dentro_del_recinto():
    """Un plano sintetico con un recinto cerrado a doble linea: la zona trae su contorno (para dibujarlo en AutoCAD) y el centroide cae dentro."""
    import pytest
    import recintos
    import server
    if not recintos.disponible():
        pytest.skip("sin shapely")
    muros_, _ = _bano_con_baldosas()
    raw = {"ok": True, "plano": "p.dwg", "unidad_m": 1.0, "insunits": 6, "n_objetos": 8, "textos": [], "poligonos": [], "bloques": [], "definiciones": {}, "muros": {},
           "lineas": {"segmentos": [list(s) + ["PDF_Geometria"] for s in muros_ * 3], "truncado": False, "entidades_leidas": 24}, "lectura": {}, "contenedores_leidos": 1,
           "elementos_en_contenedores": 24, "avisos": [], "tiempo_lectura_s": 0.1}
    zonas = zm.construir_zonas(raw, zm.cargar_vocabulario())["zonas"]
    con = [z for z in zonas if z.get("contorno")]
    assert con and all(len(z["contorno"]) >= 3 for z in con)
    cx, cy = server._centroide([[0, 0], [4, 0], [4, 2], [0, 2]])
    assert (cx, cy) == (2.0, 1.0)



def test_poligono_dibujado_en_U_conserva_el_dibujado_y_descarta_el_reconstruido_del_hueco():
    U = {"pts": [(0, 0), (1, 0), (1, 3), (2, 3), (2, 0), (3, 0), (3, 4), (0, 4)], "area_m2": 8.0, "bbox": (0, 0, 3, 4), "capa": "x"}
    hueco = _poli([(1, 0.1), (2, 0.1), (2, 3), (1, 3)])
    hueco["area_m2"] = 3.0
    d = {}
    salida = zm._poligonos_candidatos([U, hueco], 1.0, d, {})
    assert U in salida and hueco not in salida and d["reconstruccion_dentro_de_poligono"] == 1


def test_recintos_ignoran_hojas_de_puerta_inclinadas_en_planos_ortogonales():
    import pytest
    import recintos
    if not recintos.disponible():
        pytest.skip("sin shapely")
    caja = [(0, 0, 4, 0), (4, 0, 4, 3), (4, 3, 0, 3), (0, 3, 0, 0)]
    hoja = [(0.2, 0.2, 1.1, 0.9)]                                   # hoja de puerta abierta: un segmento inclinado dentro del cuarto
    r = recintos.reconstruir(caja + hoja, 1.0, None, {"area_min_m2": 1.0})
    assert r["diagnostico"]["inclinados_descartados"] == 1
    assert len(r["recintos"]) == 1 and abs(r["recintos"][0]["area_m2"] - 12.0) < 0.6


def test_prolongacion_cierra_una_puerta_en_linea_recta():
    import pytest
    import recintos
    if not recintos.disponible():
        pytest.skip("sin shapely")
    # cuarto de 4x3 con una puerta de 0.9 m en el muro de abajo (tramos 0-1.5 y 2.4-4)
    segs = [(0, 0, 1.5, 0), (2.4, 0, 4, 0), (4, 0, 4, 3), (4, 3, 0, 3), (0, 3, 0, 0)]
    r = recintos.reconstruir(segs, 1.0, None, {"cierre_por_prolongacion": True, "area_min_m2": 1.0})
    assert len(r["recintos"]) == 1 and r["diagnostico"]["aberturas_cerradas"] >= 1


def _bano_con_baldosas():
    """Cuarto de 3.6 x 3.0 m a DOBLE linea (caras a 12 cm) con juntas de baldosa SUELTAS (a >45 cm de las caras y entre si) que lo parten en celdas pequenas."""
    exterior = [(0, 0, 3.6, 0), (3.6, 0, 3.6, 3.0), (3.6, 3.0, 0, 3.0), (0, 3.0, 0, 0)]
    interior = [(0.12, 0.12, 3.48, 0.12), (3.48, 0.12, 3.48, 2.88), (3.48, 2.88, 0.12, 2.88), (0.12, 2.88, 0.12, 0.12)]
    juntas = [(0.12, 1.0, 3.48, 1.0), (0.12, 2.0, 3.48, 2.0), (1.0, 0.12, 1.0, 2.88), (1.8, 0.12, 1.8, 2.88), (2.6, 0.12, 2.6, 2.88)]
    return exterior + interior, juntas


def test_segmentos_con_pareja_descarta_las_juntas_y_conserva_los_muros():
    muros_, juntas = _bano_con_baldosas()
    sal, info = muros.segmentos_con_pareja(muros_ + juntas, 1.0)
    assert info["descartados"] == 5 and len(sal) == 8


def test_un_bano_partido_por_juntas_de_baldosa_se_recupera_en_la_segunda_pasada():
    import pytest
    import recintos
    if not recintos.disponible():
        pytest.skip("sin shapely")
    muros_, juntas = _bano_con_baldosas()
    sin = recintos.reconstruir(muros_ + juntas, 1.0, None, {"completar_sin_lineas_sueltas": False})
    con = recintos.reconstruir(muros_ + juntas, 1.0, None, {})
    assert len(sin["recintos"]) == 0                                  # celdas diminutas: todo descartado
    assert len(con["recintos"]) == 1 and con["recintos"][0]["sin_lineas_sueltas"] and con["diagnostico"]["completados_sin_lineas_sueltas"] == 1
    assert 9.0 < con["recintos"][0]["area_m2"] < 11.0


def test_lo_que_queda_fuera_de_los_muros_de_la_casa_no_se_convierte_en_recinto():
    """Una casa a doble linea con un marco de lineas SUELTAS alrededor (cerca, cotas, marco de hoja): el anillo entre ambos NO es un recinto."""
    import pytest
    import recintos
    if not recintos.disponible():
        pytest.skip("sin shapely")
    casa = [(0, 0, 8, 0), (8, 0, 8, 6), (8, 6, 0, 6), (0, 6, 0, 0), (0.12, 0.12, 7.88, 0.12), (7.88, 0.12, 7.88, 5.88), (7.88, 5.88, 0.12, 5.88), (0.12, 5.88, 0.12, 0.12)]
    marco = [(-4, -4, 12, -4), (12, -4, 12, 10), (12, 10, -4, 10), (-4, 10, -4, -4)]
    con = recintos.reconstruir(casa + marco, 1.0, None, {"completar_sin_lineas_sueltas": False})
    sin = recintos.reconstruir(casa + marco, 1.0, None, {"completar_sin_lineas_sueltas": False, "envolvente_de_la_casa": False})
    assert len(sin["recintos"]) == 2                                  # antes: la casa Y el anillo exterior
    assert len(con["recintos"]) == 1 and abs(con["recintos"][0]["area_m2"] - 7.76 * 5.76) < 1.0
    assert con["diagnostico"]["envolvente"]["tipo"] == "muros_de_doble_linea"


def test_una_zona_abierta_grande_con_muebles_de_dos_tipos_se_divide_en_subzonas():
    """Un salon de 12 x 6 m (72 m2) sin muros interiores, con una cama a la izquierda y un sofa a la derecha: dos subzonas que suman el salon."""
    import pytest
    import recintos
    if not recintos.disponible():
        pytest.skip("sin shapely")
    sala = [[0, 0], [12, 0], [12, 6], [0, 6]]
    raw = {"ok": True, "plano": "p.dwg", "unidad_m": 1.0, "insunits": 6, "n_objetos": 3, "textos": [], "poligonos": [{"capa": "0", "pts": sala}],
           "bloques": [{"n": "Cama doble", "capa": "0", "x0": 1, "y0": 2, "x1": 3, "y1": 4}, {"n": "Sofa grande", "capa": "0", "x0": 9, "y0": 2, "x1": 11, "y1": 4}],
           "definiciones": {}, "muros": {}, "lineas": {"segmentos": [], "truncado": False, "entidades_leidas": 0}, "lectura": {}, "contenedores_leidos": 0,
           "elementos_en_contenedores": 0, "avisos": [], "tiempo_lectura_s": 0.1}
    zonas = zm.construir_zonas(raw, zm.cargar_vocabulario())["zonas"]
    subs = [z for z in zonas if z.get("subdividida_de")]
    assert len(subs) == 2 and abs(sum(z["area_m2"] for z in subs) - 72.0) < 0.5
    izq = min(subs, key=lambda z: z["x"])
    assert izq["x"] < 6 < max(z["x"] for z in subs) and all(z["origen"] in ("muros", "poligono") and z["confianza"] == "baja" for z in subs)
    assert all(z.get("contorno") for z in subs)                       # cada subzona se puede dibujar
