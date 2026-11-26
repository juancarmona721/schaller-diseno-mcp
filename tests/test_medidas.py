"""Medidas de recintos: area, perimetro, rectangulo orientado de area minima, centro. Valores conocidos calculados a mano."""
import math

import pytest

import medidas as m


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def girar(pts, grados, cx=0.0, cy=0.0):
    c, s = math.cos(math.radians(grados)), math.sin(math.radians(grados))
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def test_area_perimetro_y_centroide_de_un_rectangulo():
    p = rect(0, 0, 4, 3)
    assert m.area(p) == 12 and m.perimetro(p) == 14 and m.centroide(p) == pytest.approx((2, 1.5))


def test_el_area_no_depende_del_sentido_de_los_vertices():
    assert m.area(rect(0, 0, 4, 3)) == m.area(list(reversed(rect(0, 0, 4, 3))))


def test_un_poligono_en_L_mide_su_area_real_y_su_rectangulo_envolvente():
    L = [(0, 0), (6, 0), (6, 2), (2, 2), (2, 5), (0, 5)]
    assert m.area(L) == 18 and m.perimetro(L) == 22
    r = m.rectangulo_minimo(L)
    assert (r["largo"], r["ancho"]) == pytest.approx((6, 5)) or r["largo"] * r["ancho"] <= 30 + 1e-6


@pytest.mark.parametrize("grados", [0, 15, 30, 45, 60, 90, 120, 179])
def test_un_cuarto_girado_conserva_su_ancho_y_largo_reales(grados):
    r = m.rectangulo_minimo(girar(rect(0, 0, 5, 3), grados, 2.5, 1.5))
    assert (r["largo"], r["ancho"]) == pytest.approx((5.0, 3.0), abs=1e-6)
    esperado = grados % 180
    assert r["angulo_grados"] == pytest.approx(esperado, abs=1e-6) or abs(r["angulo_grados"] - esperado) in (pytest.approx(180, abs=1e-6),)


def test_la_caja_del_plano_de_un_cuarto_girado_miente_y_el_rectangulo_orientado_no():
    p = girar(rect(0, 0, 5, 3), 30, 2.5, 1.5)
    xs, ys = [q[0] for q in p], [q[1] for q in p]
    caja = (max(xs) - min(xs)) * (max(ys) - min(ys))
    r = m.rectangulo_minimo(p)
    assert caja > 1.3 * 15 and r["largo"] * r["ancho"] == pytest.approx(15.0, abs=1e-6)


def test_medidas_en_metros_con_un_dibujo_en_milimetros():
    r = m.medidas_recinto([(x * 1000, y * 1000) for x, y in rect(0, 0, 4, 3)], u=0.001)
    assert r["area_m2"] == 12.0 and r["perimetro_m"] == 14.0 and (r["largo_m"], r["ancho_m"]) == (4.0, 3.0)
    assert r["relacion_aspecto"] == pytest.approx(1.33, abs=0.01) and r["rectangularidad"] == 1.0 and r["centro"] == [2000.0, 1500.0]


def test_la_compacidad_distingue_cuadrado_de_pasillo():
    cuadrado = m.medidas_recinto(rect(0, 0, 4, 4))
    pasillo = m.medidas_recinto(rect(0, 0, 12, 1.2))
    assert cuadrado["compacidad"] == pytest.approx(math.pi / 4, abs=0.01) and pasillo["compacidad"] < 0.45 and pasillo["relacion_aspecto"] == 10.0


def test_una_L_no_es_rectangular():
    L = [(0, 0), (6, 0), (6, 2), (2, 2), (2, 5), (0, 5)]
    assert m.medidas_recinto(L)["rectangularidad"] < 0.7 < m.medidas_recinto(rect(0, 0, 6, 5))["rectangularidad"]


def test_casos_degenerados_no_fallan():
    assert m.medidas_recinto([(0, 0), (1, 1)])["area_m2"] == 0
    assert m.medidas_recinto([(0, 0)])["ancho_m"] == 0
    assert m.rectangulo_minimo([])["largo"] == 0


def test_el_casco_convexo_ignora_los_puntos_interiores():
    assert sorted(m.casco_convexo([(0, 0), (4, 0), (4, 4), (0, 4), (2, 2), (1, 1)])) == [(0, 0), (0, 4), (4, 0), (4, 4)]
