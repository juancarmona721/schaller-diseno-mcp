"""Unidad efectiva: detecta un dibujo declarado en milimetros pero dibujado en metros (y al reves), sin adivinar cuando hay duda."""
import unidades
import zonas_motor

VOCAB = zonas_motor.cargar_vocabulario()


def test_unidad_declarada_plausible_se_respeta():
    assert unidades.unidad_efectiva(0.001, [800, 2000, 1500, 600]) == (0.001, None)      # mobiliario en mm
    assert unidades.unidad_efectiva(1.0, [0.8, 2.0, 1.5, 0.6]) == (1.0, None)


def test_declarado_mm_pero_dibujado_en_metros_se_corrige_y_avisa():
    u, aviso = unidades.unidad_efectiva(0.001, [0.168, 0.131, 0.192, 0.6, 19.568])       # el caso real: simbolos de ~0.2 y una base de 19.6
    assert u == 1.0 and "declara milimetros" in aviso and "se asume metros" in aviso


def test_declarado_metros_pero_dibujado_en_mm_se_corrige():
    u, aviso = unidades.unidad_efectiva(1.0, [800, 2000, 1500, 600, 2100])
    assert u == 0.001 and "se asume milimetros" in aviso


def test_pocas_muestras_no_se_corrige_nada():
    assert unidades.unidad_efectiva(0.001, [0.2, 0.3]) == (0.001, None)
    assert unidades.unidad_efectiva(0.001, []) == (0.001, None)
    assert unidades.unidad_efectiva(0.001, [0, 0, -1, 0]) == (0.001, None)


def test_si_ninguna_unidad_explica_lo_dibujado_no_se_inventa():
    u, aviso = unidades.unidad_efectiva(0.001, [1e9, 2e9, 3e9, 4e9])
    assert u == 0.001 and "no se corrigieron" in aviso


# ------------------------------------------------------------------------------------------------ integracion en el escaner
def poli(x0, y0, x1, y1):
    return {"capa": "M", "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def bloque(n, x0, y0, x1, y1):
    return {"n": n, "capa": "0", "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def test_el_escaner_corrige_las_unidades_y_entonces_encuentra_los_recintos():
    polis = [poli(0, 0, 4, 3.5), poli(5, 0, 9.5, 3.5), poli(0, 4, 4, 8), poli(5, 4, 9.5, 8)]
    simbolos = [bloque(f"s{i}", i, 0.5, i + 0.18, 0.7) for i in range(4)]
    raw = {"unidad_m": 0.001, "textos": [], "poligonos": polis, "bloques": simbolos}       # declarado mm, dibujado en metros
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert r["unidad_m"] == 1.0 and r["unidad_declarada_m"] == 0.001 and "se asume metros" in r["aviso_unidades"]
    assert r["total"] == 4 and all(z["origen"] == "poligono" for z in r["zonas"])


def test_con_la_unidad_correcta_no_hay_aviso_ni_cambios():
    raw = {"unidad_m": 1.0, "textos": [], "poligonos": [poli(0, 0, 4, 3.5)], "bloques": [bloque("a", 0, 0, 1.0, 0.6), bloque("b", 2, 0, 2.5, 0.4), bloque("c", 3, 0, 3.3, 1.2)]}
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert r["unidad_m"] == 1.0 and r.get("aviso_unidades") is None


# ------------------------------------------------------------------------------------------------ las recetas en un dibujo que NO esta en metros
import math

import pytest

import motor_ubicacion as mu


def host_m(x0, y0, w, h, u=1.0, **extra):
    """Un anfitrion de w x h metros con esquina en (x0, y0) metros, expresado en las unidades del dibujo."""
    return {"nombre": "Cama", "x0": x0 / u, "y0": y0 / u, "x1": (x0 + w) / u, "y1": (y0 + h) / u, "w": w / u, "h": h / u, **extra}


@pytest.mark.parametrize("u", [0.001, 0.01, 0.0254])
@pytest.mark.parametrize("receta,opciones", [("cama", {"cabecera": "N"}), ("centro", {"producto": "ci160", "du": 0.3}), ("mesa_4x", {"producto": "ci160"}),
                                             ("linea", {"producto": "ci160", "n": 3, "offset": 0.4}), ("tira_borde", {"borde": "N", "producto": "durastrip_ip68"})])
def test_un_dibujo_en_otra_unidad_da_las_mismas_posiciones_fisicas(receta, opciones, u):
    en_m, _ = mu.planear(receta, host_m(10.0, 20.0, 2.0, 2.2), opciones)
    en_u, _ = mu.planear_en_unidades(receta, host_m(10.0, 20.0, 2.0, 2.2, u), opciones, [], u)
    assert len(en_m) == len(en_u)
    for a, b in zip(en_m, en_u):
        assert (b["x"] * u, b["y"] * u) == pytest.approx((a["x"], a["y"]), abs=2 * u + 1e-3), receta
        assert b["rot"] == pytest.approx(a["rot"], abs=1e-4)


def test_el_rotulo_conserva_su_altura_fisica_en_milimetros():
    plan, _ = mu.planear_en_unidades("centro", host_m(0, 0, 2.0, 2.2, 0.001), {"producto": "cctevo58"}, [], 0.001)
    et = plan[0].get("etiqueta")
    if et:
        assert et["altura"] * 0.001 == pytest.approx(mu.ALTURA_ROTULO)            # 0.035 m = 35 mm


def test_los_muros_y_los_puntos_se_convierten():
    u = 0.001
    muro_m = (-1.0, 22.35, 3.0, 22.35)
    muro_u = tuple(v / u for v in muro_m)
    plan_m, av_m = mu.planear("cama", host_m(0, 20.0, 2.0, 2.2), {}, muros=[muro_m])
    plan_u, av_u = mu.planear_en_unidades("cama", host_m(0, 20.0, 2.0, 2.2, u), {}, [muro_u], u)
    assert any("Cabecera N deducida" in a for a in av_u) and len(plan_u) == len(plan_m)
    p, _ = mu.planear_en_unidades("en_puntos", host_m(0, 0, 1, 1, u), {"producto": "ci160", "puntos": [[1500.0, 2500.0]]}, [], u)
    assert (p[0]["x"], p[0]["y"]) == (1500.0, 2500.0)                            # el punto exacto vuelve tal cual


def test_el_anfitrion_girado_tambien_se_calcula_en_mm():
    u = 0.001
    inst = {"ins": [10000.0, 20000.0], "rot_rad": math.radians(45), "sx": 1.0, "sy": 1.0, "caja_local": [0.0, 0.0, 2000.0, 2200.0]}
    en_mm, _ = mu.planear_en_unidades("centro", {"nombre": "C", "instancia": inst}, {"producto": "ci160"}, [], u)
    inst_m = {"ins": [10.0, 20.0], "rot_rad": math.radians(45), "sx": 1.0, "sy": 1.0, "caja_local": [0.0, 0.0, 2.0, 2.2]}
    en_m, _ = mu.planear("centro", {"nombre": "C", "instancia": inst_m}, {"producto": "ci160"})
    assert (en_mm[0]["x"] * u, en_mm[0]["y"] * u) == pytest.approx((en_m[0]["x"], en_m[0]["y"]), abs=2e-3)


def test_en_metros_planear_en_unidades_es_identico_a_planear():
    h = host_m(1, 2, 2.0, 2.2)
    assert mu.planear_en_unidades("cama", h, {"cabecera": "N"}, [], 1.0) == mu.planear("cama", h, {"cabecera": "N"}, muros=[])


def test_la_tolerancia_de_duplicados_va_en_unidades_del_dibujo():
    import operaciones as op
    plan = op.asignar_ids([{"producto": "a", "bloque": "A", "x": 1000.0, "y": 2000.0, "rot": 0.0, "capa": "L"}], "d", "H", "r")
    cerca_mm = [{"bloque": "A", "x": 1100.0, "y": 2000.0}]                       # a 10 cm en un dibujo en mm
    nuevas, ya, _ = op.sin_duplicados_logico(plan, cerca_mm, tol=0.30 / 0.001, u=0.001)
    assert nuevas == [] and len(ya) == 1
    lejos = [{"bloque": "A", "x": 1500.0, "y": 2000.0}]                           # a 50 cm
    assert len(op.sin_duplicados_logico(plan, lejos, tol=0.30 / 0.001, u=0.001)[0]) == 1


# ------------------------------------------------------------------------------------------------ caso real: plano importado de PDF
def test_miles_de_trazos_finos_no_enganan_a_la_deteccion():
    """Un plano declarado en mm y dibujado en metros, con la arquitectura hecha de muchos trazos de unos centimetros (importado de PDF)."""
    trazos = [0.02 + (i % 40) * 0.03 for i in range(120)]            # 2 cm a 1.2 m (mediana ~0.07 en el caso real)
    trazos += [0.001] * 5
    u, aviso = unidades.unidad_efectiva(0.001, trazos + [0.6, 0.17, 0.12, 19.57])
    assert u == 1.0 and "se asume metros" in aviso


def test_la_estimacion_real_del_plano_importado_de_pdf():
    # distribucion medida en un plano real: min 0.001, p10 0.022, mediana 0.071, p90 1.199, max 19.57
    dims = [0.001] * 6 + [0.022] * 12 + [0.045] * 25 + [0.071] * 25 + [0.15] * 25 + [0.5] * 20 + [1.199] * 12 + [3.0] * 3 + [19.57]
    assert unidades.unidad_efectiva(0.001, dims)[0] == 1.0


def test_un_dibujo_en_mm_con_detalles_pequenos_conserva_mm():
    dims = [5.0] * 20 + [50.0] * 30 + [800.0] * 30 + [2000.0] * 15 + [3600.0] * 5             # trazos de 5 mm, mobiliario de 0.8 a 3.6 m
    assert unidades.unidad_efectiva(0.001, dims) == (0.001, None)


def test_si_podria_ser_mm_o_cm_no_se_adivina():
    u, aviso = unidades.unidad_efectiva(1.0, [300.0, 500.0, 800.0, 1200.0, 600.0, 400.0])      # declarado m: 300 m es imposible; mm (0.3-1.2 m) o cm (3-12 m)
    assert (u == 0.001 and "se asume milimetros" in aviso) or (u == 1.0 and "podrian ser" in aviso)
