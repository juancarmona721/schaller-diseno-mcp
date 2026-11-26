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
