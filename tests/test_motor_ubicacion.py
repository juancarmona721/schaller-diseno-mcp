import math

import pytest

import motor_ubicacion as mu

# Anfitriones reales de la Villa Schaller (bbox leidos de AutoCAD) y el diseno APROBADO por el usuario.
CAMA2 = {"nombre": "Gruppo-120", "x0": 4246.39, "y0": 1464.729, "x1": 4248.5, "y1": 1467.124}
CAMA1 = {"nombre": "Gruppo-203", "x0": 4196.704, "y0": 1455.218, "x1": 4199.194, "y1": 1458.182}
APROBADO_58_HAB2 = [(4245.90, 1466.42), (4245.90, 1465.45), (4248.84, 1466.42), (4248.84, 1465.45), (4247.05, 1464.35), (4247.85, 1464.35)]
APROBADO_58_HAB1 = [(4197.60, 1458.15), (4198.80, 1458.15), (4197.60, 1455.25), (4198.80, 1455.25), (4199.65, 1456.15), (4199.65, 1457.25)]


def emparejar(plan, esperado, tol):
    """Cada punto esperado debe tener un punto del plan a <= tol (sin repetir)."""
    libres = list(plan)
    peor = 0.0
    for ex, ey in esperado:
        mejor = min(libres, key=lambda c: math.hypot(c["x"] - ex, c["y"] - ey))
        d = math.hypot(mejor["x"] - ex, mejor["y"] - ey)
        peor = max(peor, d)
        libres.remove(mejor)
    assert peor <= tol, f"desviacion {peor:.3f} m > {tol}"


def solo(plan, prod):
    return [c for c in plan if c["producto"] == prod]


def test_cama_hab2_reproduce_diseno_aprobado_con_valores_por_defecto():
    plan, avisos = mu.planear("cama", CAMA2, {"cabecera": "N"})
    spots = solo(plan, "cctevo58")
    assert len(spots) == 6
    emparejar(spots, APROBADO_58_HAB2, 0.13)
    tira = solo(plan, "durastrip_ip68")[0]
    assert math.hypot(tira["x"] - 4247.45, tira["y"] - 1467.12) < 0.08 and tira["rot"] == 0.0


def test_cama_hab1_reproduce_diseno_aprobado_ajustando_opciones():
    # El bloque Gruppo-203 incluye mesas de noche: su bbox (2.96 m) es mas ancho que la cama (2.0 m).
    plan, _ = mu.planear("cama", CAMA1, {"cabecera": "O", "ancho_cama": 2.0, "filas": (0.9, 2.1)})
    emparejar(solo(plan, "cctevo58"), APROBADO_58_HAB1, 0.13)
    tira = solo(plan, "durastrip_ip68")[0]
    assert math.hypot(tira["x"] - 4196.80, tira["y"] - 1456.70) < 0.12
    assert tira["rot"] == pytest.approx(math.pi / 2, abs=1e-3)


def test_cama_exige_cabecera():
    with pytest.raises(mu.ErrorUbicacion):
        mu.planear("cama", CAMA2, {})


def test_cama_gira_con_la_cabecera():
    # Misma cama con cabecera al sur: las luces a los pies quedan al norte.
    plan, _ = mu.planear("cama", CAMA2, {"cabecera": "S"})
    pies = [c for c in solo(plan, "cctevo58") if c["nota"] == "a los pies"]
    assert all(c["y"] > CAMA2["y1"] for c in pies)


def test_rotulos_solo_en_bloques_sin_referencia_estampada():
    plan, _ = mu.planear("cama", CAMA2, {"cabecera": "N"})
    assert all("etiqueta" not in c for c in solo(plan, "cctevo58"))            # trae "58A" dibujado
    assert solo(plan, "durastrip_ip68")[0]["etiqueta"]["texto"] == "Durastrip IP68"
    plan, _ = mu.planear("centro", {"x0": 0, "y0": 0, "x1": 1, "y1": 1}, {"producto": "ci160"})
    assert plan[0]["etiqueta"]["texto"] == "Ci160CRDS" and plan[0]["etiqueta"]["altura"] == 0.035


def test_escalas_del_catalogo():
    c = mu.colocacion("cctevo58", 0, 0)
    assert c["escala"] == 0.001 and mu.colocacion("ci160", 0, 0)["escala"] == 1.0
    assert mu.colocacion("simbiosis", 0, 0)["escala"] == 1.0 and mu.colocacion("simbiosis", 0, 0)["ancla"] == "bbox"


def test_mesa_4x_centrada_y_simetrica():
    mesa = {"x0": 10, "y0": 20, "x1": 13.6, "y1": 21.2}
    plan, _ = mu.planear("mesa_4x", mesa)
    assert len(plan) == 4
    assert sum(c["x"] for c in plan) / 4 == pytest.approx(11.8) and sum(c["y"] for c in plan) / 4 == pytest.approx(20.6)


def test_linea_reparte_sobre_el_eje_largo():
    plan, _ = mu.planear("linea", {"x0": 0, "y0": 0, "x1": 3, "y1": 1}, {"producto": "cctevo160", "n": 2})
    assert [c["x"] for c in plan] == [1.0, 2.0] and all(c["y"] == 0.5 for c in plan)


def test_tira_borde_oeste_va_vertical():
    plan, _ = mu.planear("tira_borde", {"x0": 0, "y0": 0, "x1": 2, "y1": 1}, {"borde": "O"})
    assert plan[0]["x"] == pytest.approx(0.05, abs=1e-3) and plan[0]["y"] == pytest.approx(0.5, abs=1e-3) and plan[0]["rot"] == pytest.approx(math.pi / 2, abs=1e-3)


def test_idempotencia_no_duplica_lo_ya_puesto():
    plan, _ = mu.planear("cama", CAMA2, {"cabecera": "N"})
    existentes = [{"bloque": c["bloque"], "x": c["x"] + 0.03, "y": c["y"] - 0.02} for c in plan[:3]]
    nuevas, omitidas = mu.sin_duplicados(plan, existentes)
    assert len(omitidas) == 3 and len(nuevas) == len(plan) - 3
    n2, o2 = mu.sin_duplicados(plan, [{"bloque": "otro", "x": plan[0]["x"], "y": plan[0]["y"]}])
    assert len(o2) == 0   # otro bloque en el mismo sitio no cuenta como duplicado


def test_avisa_si_el_anfitrion_no_parece_el_mueble():
    _, avisos = mu.planear("cama", {"x0": 0, "y0": 0, "x1": 0.4, "y1": 0.4}, {"cabecera": "N"})
    assert any("pequeno" in a for a in avisos)


def test_receta_o_producto_desconocidos():
    with pytest.raises(mu.ErrorUbicacion):
        mu.planear("nada", CAMA2)
    with pytest.raises(mu.ErrorUbicacion):
        mu.colocacion("inexistente", 0, 0)


# ------------------------------------------------------------------------------------------------ rayos a muros y direcciones
# Muro sur de la Habitacion 2 (polilinea real de H-MUROS: cara interior en y = 1463.93, x de 4246.78 a 4250.04).
MURO_SUR_HAB2 = (4246.78, 1463.93, 4250.04, 1463.93)


def test_rayo_distancia_y_sentido():
    assert mu.rayo_a_segmento(0, 0, 1, 0, (5, -1, 5, 1)) == pytest.approx(5)
    assert mu.rayo_a_segmento(0, 0, -1, 0, (5, -1, 5, 1)) is None       # el muro queda detras
    assert mu.rayo_a_segmento(0, 0, 1, 0, (5, 1, 5, 3)) is None         # no lo cruza
    assert mu.rayo_a_segmento(0, 0, 1, 0, (0, 1, 4, 1)) is None         # paralelo


def test_el_rayo_se_detiene_en_el_primer_muro_y_no_salta_de_ambiente():
    d, seg = mu.rayo_a_muros(0, 0, 0, -1, [(-1, -5, 1, -5), (-1, -2, 1, -2)])
    assert d == pytest.approx(2) and seg == (-1, -2, 1, -2)


def test_cabecera_se_deduce_por_muro_pegado():
    cama = {"x0": 0, "y0": 0, "x1": 2.1, "y1": 2.4}
    lado, dist = mu.inferir_cabecera(mu.rect(cama), [(-1, 2.5, 4, 2.5)])   # muro a 0.1 m del borde norte
    assert lado == "N" and dist["N"] == pytest.approx(0.1) and dist["S"] is None


def test_cabecera_sin_muros_o_ambigua_no_se_adivina():
    cama = {"x0": 0, "y0": 0, "x1": 2.1, "y1": 2.4}
    assert mu.inferir_cabecera(mu.rect(cama), [])[0] is None
    esquina = [(-1, 2.5, 4, 2.5), (2.2, -1, 2.2, 4)]     # N a 0.1 y E a 0.1: ambiguo
    assert mu.inferir_cabecera(mu.rect(cama), esquina)[0] is None
    with pytest.raises(mu.ErrorUbicacion):
        mu.planear("cama", cama, {})                     # sin cabecera ni muros: pide la cabecera


def test_cama_usa_cabecera_deducida():
    cama = {"x0": 0, "y0": 0, "x1": 2.1, "y1": 2.4}
    plan, avisos = mu.planear("cama", cama, {}, muros=[(-1, 2.5, 4, 2.5)])
    assert any("deducida" in a for a in avisos)
    assert all(c["y"] < 2.5 for c in plan)


def test_parlantes_de_pared_reproducen_diseno_aprobado():
    # Aprobado: 2 Ci200QS en (4246.80, 1463.93) y (4248.10, 1463.93), rotacion pi (rejilla al norte, hacia la cama).
    plan, _ = mu.planear("pared_frente", CAMA2, {"cabecera": "N"}, muros=[MURO_SUR_HAB2])
    emparejar(plan, [(4246.80, 1463.93), (4248.10, 1463.93)], 0.06)
    assert all(c["rot"] == pytest.approx(math.pi, abs=1e-3) for c in plan)


def test_rotacion_hacia_donde_apunta():
    assert mu.rot_para_apuntar("ci200qs", 0, 1) == pytest.approx(math.pi, abs=1e-9)        # norte (parlante aprobado)
    assert mu.rot_para_apuntar("ci200qs", 0, -1) == pytest.approx(0.0, abs=1e-9)           # sur = frente natural
    assert mu.rot_para_apuntar("l7", 1, 0) == pytest.approx(0.0, abs=1e-9)                 # L7 izquierdo aprobado mira al este
    assert mu.rot_para_apuntar("l7", -1, 0) == pytest.approx(math.pi, abs=1e-9)            # L7 derecho aprobado mira al oeste
    with pytest.raises(mu.ErrorUbicacion):
        mu.rot_para_apuntar("ci160", 1, 0)                                                 # de techo: sin direccion


def test_pared_frente_sin_muro_da_error_claro():
    with pytest.raises(mu.ErrorUbicacion, match="No hay muro"):
        mu.planear("pared_frente", CAMA1, {"cabecera": "O"}, muros=[MURO_SUR_HAB2])


def test_luz_casi_duplicada_cuenta_como_ya_colocada():
    # Caso real: el plan pone una luz a 4248.95 y ya hay una aprobada a 4248.84 (0.11 m): no debe duplicarse.
    plan, _ = mu.planear("cama", CAMA2, {"cabecera": "N"})
    existentes = [{"bloque": c["bloque"], "x": c["x"] - 0.11, "y": c["y"]} for c in plan if c["producto"] == "cctevo58"]
    nuevas, omitidas = mu.sin_duplicados(plan, existentes)
    assert len(omitidas) == 6 and [c["producto"] for c in nuevas] == ["durastrip_ip68"]


# ------------------------------------------------------------------------------------------------ autocalibracion de escala
@pytest.mark.parametrize("d_def,tam,unidad,esperada", [
    (253.0, 0.254, 1.0, 0.001),      # CCTEvo en mm, plano en metros
    (0.254, 0.254, 1.0, 1.0),        # definicion ya en metros, plano en metros
    (253.0, 0.254, 0.001, 1.0),      # plano en milimetros con bloque en mm
    (0.254, 0.254, 0.001, 1000.0),   # plano en mm con bloque en metros
    (1807.0, 1.808, 1.0, 0.001),     # Durastrip de la biblioteca (mm) en plano en metros
    (1.808, 1.808, 1.0, 1.0),        # Durastrip ya convertida (V5)
    (0.548, 0.548, 0.01, 100.0),     # plano en centimetros
])
def test_escala_por_medida_en_cualquier_combinacion_de_unidades(d_def, tam, unidad, esperada):
    esc, como = mu.escala_por_medida(d_def, tam, unidad, 7.0)
    assert esc == esperada and como == "medida"


def test_escala_por_medida_sin_dato_usa_catalogo():
    assert mu.escala_por_medida(None, 0.25, 1.0, 0.001) == (0.001, "catalogo (no se pudo medir)")
    esc, como = mu.escala_por_medida(77.7, 0.25, 1.0, 0.5)     # 77.7 no encaja con ninguna unidad conocida
    assert esc == 0.5 and "no cuadra" in como


def test_todos_los_productos_tienen_tamano_esperado():
    assert all(mu.TAM_M.get(k) for k in mu.PRODUCTOS)


def test_simbiosis_con_alias_y_rotulo_correcto():
    c = mu.colocacion("simbiosi", 0, 0)                     # alias de quien lo escribe sin la ultima S
    assert c["producto"] == "simbiosis" and c["bloque"] == "SIMBIOSI"      # el bloque del plano se llama SIMBIOSI
    assert c["etiqueta"]["texto"] == "SIMBIOSIS"                          # el rotulo es el nombre real del producto
