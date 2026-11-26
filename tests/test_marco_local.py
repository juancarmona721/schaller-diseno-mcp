"""Fase 1C (puro): anfitriones girados, reflejados y escalados se calculan en su marco local y no sobre la caja envolvente."""
import math

import pytest

import motor_ubicacion as mu

W, H = 2.0, 2.2                                        # dibujo del bloque cama: de (0,0) a (W,H), cabecera hacia +Y local (N)


def host(ins=(0.0, 0.0), rot=0.0, sx=1.0, sy=1.0, con_caja=True, bbox=None):
    inst = {"ins": list(ins), "rot_rad": rot, "sx": sx, "sy": sy}
    if con_caja:
        inst["caja_local"] = [0.0, 0.0, W, H]
    h = {"nombre": "Cama", "instancia": inst}
    if bbox:
        h.update(dict(zip(("x0", "y0", "x1", "y1"), bbox)), w=bbox[2] - bbox[0], h=bbox[3] - bbox[1])
    return h


def a_mundo(h, q):
    """Referencia independiente: mundo = insercion + R(giro) * diag(sx, sy) * punto del dibujo del bloque."""
    i = h["instancia"]
    c, s = math.cos(i["rot_rad"]), math.sin(i["rot_rad"])
    x, y = q[0] * i["sx"], q[1] * i["sy"]
    return i["ins"][0] + c * x - s * y, i["ins"][1] + s * x + c * y


def base(receta, opciones):
    """Plan en las coordenadas del dibujo del bloque (instancia sin giro ni escala en el origen)."""
    plan, _ = mu.planear(receta, host(), {**opciones, "marco": "local"})
    return [{**c, "x": c["x"], "y": c["y"]} for c in plan]


CASOS = [(0, 1, 1), (45, 1, 1), (90, 1, 1), (180, 1, 1), (270, 1, 1), (33.3, 1, 1), (45, -1, 1), (45, 1, -1), (90, -1, -1), (200, -1, 1)]


@pytest.mark.parametrize("grados,sx,sy", CASOS)
@pytest.mark.parametrize("receta,opciones", [("cama", {"cabecera": "N"}), ("centro", {"producto": "ci160", "du": 0.3, "dv": 0.5}),
                                             ("mesa_4x", {"producto": "ci160"}), ("linea", {"producto": "ci160", "n": 3, "offset": 0.4})])
def test_la_receta_en_marco_local_es_la_misma_en_cualquier_giro_o_reflejo(receta, opciones, grados, sx, sy):
    """El plan calculado sobre la instancia girada/reflejada = el plan del dibujo sin girar, llevado al plano con la transformacion de la instancia."""
    h = host(ins=(10.0, 20.0), rot=math.radians(grados), sx=sx, sy=sy)
    esperado = base(receta, opciones)
    plan, avisos = mu.planear(receta, h, {**opciones, "marco": "local"})
    assert len(plan) == len(esperado)
    for c, e in zip(plan, esperado):
        # el plan base (instancia sin giro en el origen) YA esta en coordenadas del dibujo del bloque
        x, y = a_mundo(h, (e["x"], e["y"]))
        assert (c["x"], c["y"]) == pytest.approx((x, y), abs=2e-3), (c["producto"], grados, sx, sy)
    assert any("marco local" in a for a in avisos)


def test_la_cabecera_sigue_al_dibujo_del_bloque_aunque_la_cama_gire_180():
    pos = {}
    for grados in (0, 180):
        h = host(ins=(0.0, 0.0), rot=math.radians(grados))
        plan, _ = mu.planear("cama", h, {"cabecera": "N", "marco": "local"})
        tira = [c for c in plan if c["producto"] == "durastrip_ip68"][0]
        assert (tira["x"], tira["y"]) == pytest.approx(a_mundo(h, (W / 2, H - 0.05)), abs=2e-3)     # siempre en el borde +Y del DIBUJO
        pos[grados] = (tira["x"], tira["y"])
    assert pos[0][1] > 0 > pos[180][1]                    # misma caja envolvente, cabecera en lados contrarios del plano


def test_un_reflejo_en_x_lleva_la_pieza_izquierda_del_dibujo_al_lado_derecho_del_plano():
    for sx in (1.0, -1.0):
        h = host(sx=sx)
        plan, _ = mu.planear("cama", h, {"cabecera": "N", "marco": "local"})
        laterales = [c for c in plan if c["producto"] == "cctevo58"]
        centro_x = a_mundo(h, (W / 2, 0))[0]
        # la pieza con menor X en el DIBUJO del bloque (su lado izquierdo): sin reflejo cae a la izquierda del centro y con reflejo a la derecha
        locales = [(x, c) for c in laterales for x in [(c["x"] - centro_x) * sx]]
        izq = min(locales, key=lambda t: t[0])[1]
        assert (izq["x"] - centro_x) * sx < 0
        assert (izq["x"] < centro_x) == (sx > 0)


def test_la_escala_no_uniforme_cambia_las_dimensiones_del_marco():
    marco = mu.marco_desde_instancia(host(sx=2.0, sy=0.5))
    assert marco[4:] == pytest.approx((2 * W, 0.5 * H))


def test_un_giro_de_45_no_usa_la_caja_envolvente():
    h = host(ins=(0, 0), rot=math.radians(45), bbox=(-1.56, 0.0, 1.56, 2.97))
    marco = mu.marco_desde_instancia(h)
    assert marco[4:] == pytest.approx((W, H))                                # dimensiones del DIBUJO, no las de la caja envolvente (3.12 x 2.97)
    plan, _ = mu.planear("centro", h, {"producto": "ci160"})                  # sin pedir marco: 45 grados no es ortogonal, se usa solo
    assert (plan[0]["x"], plan[0]["y"]) == pytest.approx(a_mundo(h, (W / 2, H / 2)), abs=2e-3)


def test_giro_ortogonal_sin_pedir_marco_conserva_el_resultado_de_siempre():
    bbox = (10.0, 20.0, 12.2, 22.0)                                            # cama girada 90: caja de 2.2 x 2.0 en el plano
    con = {**host(ins=(12.2, 20.0), rot=math.pi / 2), **dict(zip(("x0", "y0", "x1", "y1"), bbox)), "w": 2.2, "h": 2.0}
    sin = {k: v for k, v in con.items() if k != "instancia"}
    a, _ = mu.planear("cama", con, {"cabecera": "N"})
    b, _ = mu.planear("cama", sin, {"cabecera": "N"})
    assert [(c["x"], c["y"], c["rot"]) for c in a] == [(c["x"], c["y"], c["rot"]) for c in b]


def test_sin_caja_local_un_giro_no_ortogonal_avisa_en_vez_de_callar():
    h = host(rot=math.radians(30), con_caja=False, bbox=(0, 0, 3, 3))
    plan, avisos = mu.planear("centro", h, {"producto": "ci160"})
    assert plan and any("no pude leer la caja de su definicion" in a for a in avisos)
    with pytest.raises(mu.ErrorUbicacion):
        mu.planear("centro", h, {"producto": "ci160", "marco": "local"})


def test_los_muros_se_llevan_al_marco_local_y_la_cabecera_se_deduce_en_el_giro():
    h = host(ins=(5.0, 5.0), rot=math.radians(45))
    pared_local = [(-1.0, H + 0.15), (W + 1.0, H + 0.15)]                      # muro paralelo al borde +Y del dibujo, a 0.15 m
    muro = (*a_mundo(h, pared_local[0]), *a_mundo(h, pared_local[1]))
    plan, avisos = mu.planear("cama", h, {}, muros=[muro])
    assert any("Cabecera N deducida" in a for a in avisos) and plan


def test_la_cabecera_local_del_perfil_activa_el_marco_local_en_giros_ortogonales():
    h = host(ins=(0.0, 0.0), rot=math.pi)
    plan, avisos = mu.planear("cama", h, {"cabecera_local": "N"})
    assert any("marco local" in a for a in avisos)
    tira = [c for c in plan if c["producto"] == "durastrip_ip68"][0]
    assert tira["y"] == pytest.approx(a_mundo(h, (W / 2, H - 0.05))[1], abs=2e-3)         # a 180 grados la cabecera cae hacia abajo en el plano


def test_en_puntos_no_se_transforma_porque_recibe_coordenadas_del_plano():
    h = host(ins=(0, 0), rot=math.radians(45))
    plan, _ = mu.planear("en_puntos", h, {"producto": "ci160", "puntos": [[7.0, 8.0]]})
    assert (plan[0]["x"], plan[0]["y"]) == (7.0, 8.0)


def test_el_rotulo_viaja_con_su_pieza():
    h = host(ins=(0, 0), rot=math.radians(90))
    plan, _ = mu.planear("centro", h, {"producto": "cctevo58", "marco": "local"})
    c = plan[0]
    if c.get("etiqueta"):
        # el rotulo se desplaza (+0.12, +0.06) en el marco local; girado 90 grados queda en (-0.06, +0.12) en el plano
        assert (c["etiqueta"]["x"] - c["x"], c["etiqueta"]["y"] - c["y"]) == pytest.approx((-0.06, 0.12), abs=2e-3)


def test_normal_no_z_no_se_calcula_en_marco_local():
    h = host(rot=math.radians(30))
    h["instancia"]["normal_no_z"] = True
    assert mu.marco_desde_instancia(h) is None
    with pytest.raises(mu.ErrorUbicacion):
        mu.planear("centro", h, {"producto": "ci160", "marco": "local"})


def test_las_opciones_explicitas_mandan_y_la_cabecera_local_del_perfil_no_se_mezcla_con_una_global():
    assert mu.combinar_opciones({"cabecera_local": "N"}, {"cabecera": "S"}) == {"cabecera": "S"}
    assert mu.combinar_opciones({"cabecera": "E"}, {"filas": [1.0]}) == {"cabecera": "E", "filas": [1.0]}
    assert mu.combinar_opciones({"cabecera": "E", "cabecera_local": "N"}, {}) == {"cabecera_local": "N"}
    assert mu.combinar_opciones({"ancho_cama": 2.0}, None) == {"ancho_cama": 2.0}
