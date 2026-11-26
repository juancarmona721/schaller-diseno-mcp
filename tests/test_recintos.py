"""Recintos a partir de muros: habitaciones simples, aberturas de puerta, columnas, ruido y unidades. Requiere Shapely."""
import pytest

pytest.importorskip("shapely")
import recintos as rc


def caja_doble(x0, y0, x1, y1, espesor=0.2, huecos=()):
    """Cuatro muros de DOS caras (lineas paralelas a `espesor`). huecos [(lado, desde, hasta)]: vanos en metros medidos desde la esquina (S/N a lo largo de X,
    O/E a lo largo de Y)."""
    segs = []
    for off in (0.0, espesor):
        X0, Y0, X1, Y1 = x0 - off, y0 - off, x1 + off, y1 + off
        for lado, (a, b, c, d) in {"S": (X0, Y0, X1, Y0), "N": (X0, Y1, X1, Y1), "O": (X0, Y0, X0, Y1), "E": (X1, Y0, X1, Y1)}.items():
            horiz = lado in ("S", "N")
            base = x0 if horiz else y0
            trozos, ini, fin = [], (a if horiz else b), (c if horiz else d)
            cursor = ini
            for h0, h1 in sorted((h0, h1) for l, h0, h1 in huecos if l == lado):
                trozos.append((cursor, base + h0))
                cursor = base + h1
            trozos.append((cursor, fin))
            for p0, p1 in trozos:
                if p1 > p0 + 1e-9:
                    segs.append((p0, b, p1, d) if horiz else (a, p0, c, p1))
    return segs


def test_una_habitacion_de_cuatro_muros_es_un_recinto_con_su_area():
    r = rc.reconstruir(caja_doble(0, 0, 4, 3))
    assert r["ok"] and len(r["recintos"]) == 1
    assert r["recintos"][0]["area_m2"] == pytest.approx(12.0, abs=0.8)                  # entre caras de muro (tolerancia del engrosado)


def test_dos_habitaciones_con_pared_compartida_son_dos_recintos():
    segs = caja_doble(0, 0, 4, 3) + caja_doble(4.2, 0, 8, 3)
    r = rc.reconstruir(segs)
    assert len(r["recintos"]) == 2 and all(8 < x["area_m2"] < 13 for x in r["recintos"])


def test_una_puerta_interior_no_fusiona_las_dos_habitaciones():
    # pared central con vano de 0.9 m: sin el cierre virtual serian un solo espacio
    izq = caja_doble(0, 0, 4, 3, huecos=[("E", 1.0, 1.9)])
    der = caja_doble(4.2, 0, 8, 3, huecos=[("O", 1.0, 1.9)])
    con = rc.reconstruir(izq + der)
    sin = rc.reconstruir(izq + der, parametros={"abertura_max_m": 0.01})
    assert len(con["recintos"]) == 2 and con["diagnostico"]["aberturas_cerradas"] >= 1
    assert len(sin["recintos"]) <= 1                                                   # sin cerrar la abertura, el espacio se funde


def test_una_puerta_exterior_no_hace_que_la_habitacion_se_pierda_en_el_exterior():
    r = rc.reconstruir(caja_doble(0, 0, 4, 3, huecos=[("S", 1.5, 2.4)]))
    assert len(r["recintos"]) == 1 and r["diagnostico"]["aberturas_cerradas"] >= 1


def test_una_abertura_mayor_que_el_maximo_no_se_cierra_y_el_espacio_es_exterior():
    r = rc.reconstruir(caja_doble(0, 0, 4, 3, huecos=[("S", 0.5, 3.5)]))              # un vano de 3 m: una fachada abierta
    assert r["recintos"] == []


def test_una_columna_dentro_deja_un_hueco_y_area_neta_menor():
    segs = caja_doble(0, 0, 6, 5) + [(2.9, 2.4, 3.1, 2.4), (3.1, 2.4, 3.1, 2.6), (3.1, 2.6, 2.9, 2.6), (2.9, 2.6, 2.9, 2.4)]
    r = rc.reconstruir(segs)
    assert len(r["recintos"]) == 1 and r["recintos"][0]["huecos"] == 1 and r["recintos"][0]["area_neta_m2"] < r["recintos"][0]["area_m2"]


def test_el_ruido_de_trazos_diminutos_no_crea_recintos():
    ruido = [(i * 0.011, 20.0, i * 0.011 + 0.01, 20.0) for i in range(500)]            # hatch explotado: segmentos de 1 cm
    r = rc.reconstruir(caja_doble(0, 0, 4, 3) + ruido)
    assert len(r["recintos"]) == 1 and r["diagnostico"]["segmentos"] == 8


def test_un_dibujo_en_milimetros_devuelve_coordenadas_en_milimetros_y_areas_en_metros():
    segs = [(a * 1000, b * 1000, c * 1000, d * 1000) for a, b, c, d in caja_doble(0, 0, 4, 3)]
    r = rc.reconstruir(segs, u=0.001)
    assert len(r["recintos"]) == 1 and r["recintos"][0]["area_m2"] == pytest.approx(12.0, abs=0.8)
    xs = [x for x, _ in r["recintos"][0]["pts"]]
    assert max(xs) - min(xs) == pytest.approx(4000, abs=150)


def test_una_sola_cara_de_muro_tambien_cierra_la_habitacion():
    simples = [(0, 0, 5, 0), (5, 0, 5, 4), (5, 4, 0, 4), (0, 4, 0, 0)]
    r = rc.reconstruir(simples)
    assert len(r["recintos"]) == 1 and r["recintos"][0]["area_m2"] == pytest.approx(20.0, abs=1.0)


def test_muros_hechos_de_poligonos_delgados_tambien_encierran():
    solidos = [[(0, 0), (5, 0), (5, 0.2), (0, 0.2)], [(0, 3.8), (5, 3.8), (5, 4), (0, 4)], [(0, 0), (0.2, 0), (0.2, 4), (0, 4)], [(4.8, 0), (5, 0), (5, 4), (4.8, 4)]]
    r = rc.reconstruir([], poligonos_muro=solidos)
    assert len(r["recintos"]) == 1 and r["recintos"][0]["area_m2"] == pytest.approx(4.6 * 3.6, abs=1.0)


def test_pocos_muros_no_inventan_recintos():
    r = rc.reconstruir([(0, 0, 3, 0), (3, 0, 3, 3)])
    assert r["ok"] and r["recintos"] == [] and "pocos muros" in r["diagnostico"]["detalle"].lower()


def test_sin_shapely_se_degrada_con_un_diagnostico_claro(monkeypatch):
    monkeypatch.setattr(rc, "disponible", lambda: False)
    r = rc.reconstruir(caja_doble(0, 0, 4, 3))
    assert not r["ok"] and r["error"] == "geometria_avanzada_no_disponible" and r["recintos"] == []


def test_rendimiento_con_miles_de_muros():
    import time
    segs = []
    for i in range(6):
        for j in range(6):
            segs += caja_doble(i * 5.0, j * 4.0, i * 5.0 + 4.6, j * 4.0 + 3.6, huecos=[("S", 1.0, 1.9)])
    t = time.perf_counter()
    r = rc.reconstruir(segs)
    assert len(r["recintos"]) >= 30 and time.perf_counter() - t < 6.0
