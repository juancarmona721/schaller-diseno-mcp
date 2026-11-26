"""Descubrimiento minimo: clasificador de mobiliario anonimo y recintos candidatos sin rotulo."""
import clasificador as cl
import zonas_motor

VOCAB = zonas_motor.cargar_vocabulario()


def c(nombre="Gruppo-203", capa="0", w=2.0, h=2.2, interior=None):
    return cl.clasificar(nombre, capa, w, h, interior, VOCAB)


def test_un_nombre_anidado_de_cama_mas_tamano_compatible_es_alta():
    r = c(interior={"anidados": ["Letto matrimoniale"], "capas": []})
    assert r["rol"] == "cama" and r["confianza"] == "alta" and r["rol_origen"] == "inferido"
    assert {e["tipo"] for e in r["evidencias"]} == {"nombre_anidado", "tamano_compatible"}


def test_solo_el_tamano_no_basta_para_aceptar_un_rol():
    assert c(interior={"anidados": [], "capas": []}) is None and not cl.aceptado(c(interior=None))


def test_el_tamano_incompatible_resta_pero_su_ausencia_no():
    sin_tamano = cl.clasificar("G", "0", None, None, {"anidados": ["cama"]}, VOCAB)
    assert sin_tamano["confianza"] == "media"                                    # sin dato de tamano: no resta
    assert c(w=0.5, h=0.6, interior={"anidados": ["cama"]}) is None              # una "cama" de 0.5 m: la evidencia negativa la descarta
    algo_grande = c(w=3.0, h=3.0, interior={"anidados": ["cama", "cama king", "letto"]})
    assert algo_grande is None or algo_grande["confianza"] != "alta"


def test_la_capa_interna_suma_menos_que_un_nombre_anidado():
    r = cl.clasificar("G", "0", None, None, {"anidados": [], "capas": ["SANITARIOS"]}, VOCAB)
    assert r is None or r["confianza"] == "baja"                                 # 0.25 < umbral baja 0.30: no alcanza


def test_mesa_redonda_por_forma_y_nombre():
    r = c(w=1.4, h=1.4, interior={"anidados": ["dining table"], "n": {"circulos": 3}})
    assert r["rol"] == "mesa_comedor" and any(e["tipo"] == "forma_circular" for e in r["evidencias"])


def test_dos_roles_con_puntaje_parecido_no_son_alta():
    r = c(w=1.2, h=2.0, interior={"anidados": ["cama", "sofa"]})                  # ambos roles caben por tamano: empate
    assert r["confianza"] != "alta" and r["alternativas"]
    sin_rival = c(w=2.0, h=2.0, interior={"anidados": ["cama", "sofa"]})        # a 2.0 x 2.0 el sofa no cabe: gana la cama
    assert sin_rival["rol"] == "cama" and sin_rival["confianza"] == "alta"


def test_baja_confianza_se_sugiere_pero_no_se_acepta():
    r = cl.clasificar("G", "0", 1.2, 1.2, {"anidados": [], "capas": ["Escritorio"], "n": {}}, VOCAB)
    assert r is not None and r["confianza"] in ("baja", "media") or r is None
    assert not cl.aceptado({"confianza": "baja"}) and cl.aceptado({"confianza": "media"})


def test_los_datos_son_editables_y_se_pueden_pasar_por_parametro():
    datos = {"pesos": {**cl.cargar()["pesos"], "nombre_anidado": 0.9}, "umbrales": cl.cargar()["umbrales"], "rangos": {}, "circular_para": []}
    r = cl.clasificar("G", "0", None, None, {"anidados": ["cama"]}, VOCAB, datos)
    assert r["confianza"] == "alta"


# ------------------------------------------------------------------------------------------------ integracion en el escaner
def raw_base(bloques, definiciones=None, poligonos=None, textos=None):
    r = {"unidad_m": 1.0, "textos": textos or [], "poligonos": poligonos or [], "bloques": bloques}
    if definiciones is not None:
        r["definiciones"] = definiciones
    return r


def bloque(n, x0, y0, x1, y1, capa="0"):
    return {"n": n, "capa": capa, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def test_un_bloque_anonimo_con_cama_dentro_pasa_a_tener_rol_inferido_en_el_escaner():
    raw = raw_base([bloque("Gruppo-203", 0, 0, 2.0, 2.2)], {"Gruppo-203": {"anidados": ["letto"], "capas": [], "n": {}}})
    r = zonas_motor.construir_zonas(raw, VOCAB)
    z = r["zonas"][0]
    assert z["tipo_espacio"] == "alcoba" and z["origen"] == "mobiliario" and r["bloques_con_rol"] == 1
    det = z["muebles_detalle"][0]
    assert det["rol"] == "cama" and det["rol_origen"] == "inferido" and det["confianza_rol"] == "alta"


def test_el_perfil_confirmado_manda_sobre_la_inferencia():
    raw = raw_base([bloque("Gruppo-203", 0, 0, 2.0, 2.2)], {"Gruppo-203": {"anidados": ["letto"], "capas": [], "n": {}}})
    perfil = {"roles_bloques": {"Gruppo-203": "sofa"}}
    det = zonas_motor.construir_zonas(raw, VOCAB, perfil)["zonas"][0]["muebles_detalle"][0]
    assert det["rol"] == "sofa" and "rol_origen" not in det


def test_sin_definiciones_el_comportamiento_es_el_de_siempre():
    r = zonas_motor.construir_zonas(raw_base([bloque("Gruppo-203", 0, 0, 2.0, 2.2)]), VOCAB)
    assert r["total"] == 0 and r["bloques_con_rol"] == 0 and r["bloques_sin_rol"] == 1


def test_baja_confianza_no_asigna_rol_y_queda_como_sugerencia():
    raw = raw_base([bloque("Gruppo-9", 0, 0, 1.2, 1.2)], {"Gruppo-9": {"anidados": [], "capas": ["Escritorio"], "n": {}}})
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert r["bloques_con_rol"] == 0 and r["total"] == 0


# ------------------------------------------------------------------------------------------------ recintos candidatos
def rect(x0, y0, x1, y1, capa="M"):
    return {"capa": capa, "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def test_un_poligono_de_habitacion_sin_texto_es_un_recinto_candidato_de_confianza_baja():
    r = zonas_motor.construir_zonas(raw_base([], poligonos=[rect(0, 0, 4, 3.5)]), VOCAB)
    assert r["total"] == 1
    z = r["zonas"][0]
    assert z["origen"] == "poligono" and z["confianza"] == "baja" and z["candidato"] is True and z["area_m2"] == 14.0 and z["tipo_espacio"] == "otro"


def test_los_poligonos_pequenos_o_estrechos_no_son_recintos():
    pol = [rect(0, 0, 0.6, 0.6), rect(5, 0, 5.8, 6.0), rect(10, 0, 10.5, 2.0)]        # mesita, franja de 0.8 m, estantería
    assert zonas_motor.construir_zonas(raw_base([], poligonos=pol), VOCAB)["total"] == 0


def test_el_contorno_que_contiene_varias_habitaciones_no_es_un_recinto():
    contorno = rect(0, 0, 20, 10)
    hab = [rect(0.5, 0.5, 6, 5), rect(7, 0.5, 13, 5), rect(14, 0.5, 19, 5)]
    r = zonas_motor.construir_zonas(raw_base([], poligonos=[contorno] + hab), VOCAB)
    assert r["total"] == 3 and all(z["area_m2"] < 50 for z in r["zonas"])


def test_poligonos_duplicados_cuentan_una_vez():
    r = zonas_motor.construir_zonas(raw_base([], poligonos=[rect(0, 0, 4, 3.5), rect(0.01, 0, 4, 3.5)]), VOCAB)
    assert r["total"] == 1


def test_el_recinto_candidato_toma_su_tipo_del_mobiliario_que_contiene_y_lo_declara():
    raw = raw_base([bloque("Gruppo-203", 1, 1, 3.0, 3.2)], {"Gruppo-203": {"anidados": ["letto"], "capas": [], "n": {}}}, poligonos=[rect(0, 0, 4, 3.5)])
    z = zonas_motor.construir_zonas(raw, VOCAB)["zonas"][0]
    assert z["tipo_espacio"] == "alcoba" and z["origen"] == "poligono" and z["muebles"] == ["Gruppo-203"] and z["confianza"] == "baja"
    assert "inferido" in z["inferido_por"][0]


def test_un_recinto_con_texto_sigue_siendo_de_confianza_alta_y_no_se_duplica_como_candidato():
    raw = raw_base([], poligonos=[rect(0, 0, 5, 4)], textos=[{"t": "Sala de juntas", "x": 2, "y": 2, "capa": "T"}])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert r["total"] == 1 and r["zonas"][0]["confianza"] == "alta" and r["zonas"][0].get("candidato") is None


def test_el_resumen_de_lectura_cuenta_candidatos():
    r = zonas_motor.construir_zonas(raw_base([], poligonos=[rect(0, 0, 4, 3.5)]), VOCAB)
    assert r["resumen_lectura"]["recintos_candidatos"] == 1


# ------------------------------------------------------------------------------------------------ lo aprendido en un plano real (textos internos, capas de cajetin)
def test_los_textos_dentro_del_bloque_cuentan_como_evidencia():
    r = cl.clasificar("dtjrtj (2D)", "0", 6.5, 1.1, {"anidados": [], "capas": ["MB-AMOBLAMIENTO"], "textos": ['MASTERCOOL 36"', "FRIDGE-FREEZER", "OVENS"]}, VOCAB)
    assert r["rol"] == "cocina_mueble" and r["confianza"] == "media" and any(e["tipo"] == "texto_interno" for e in r["evidencias"])


def test_un_codigo_de_modelo_sin_significado_no_clasifica_nada():
    assert cl.clasificar("Gruppo-203", "0", 2.5, 3.0, {"anidados": [], "capas": ["MB-AMOBLAMIENTO"], "textos": ["TLEKS"]}, VOCAB) is None


def poligono(x0, y0, x1, y1, capa):
    return {"capa": capa, "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def test_los_poligonos_de_cajetin_y_de_mobiliario_no_son_recintos():
    polis = [poligono(0, 0, 60, 14, "ROTULO"), poligono(0, 20, 5.5, 24.8, "MB-AMOBLAMIENTO"), poligono(10, 0, 14.5, 4.0, "X-PLANO 2")]
    r = zonas_motor.construir_zonas(raw_base([], poligonos=polis), VOCAB)
    assert r["total"] == 1 and r["zonas"][0]["area_m2"] == 18.0


def test_un_poligono_enorme_es_un_contorno_no_un_recinto():
    r = zonas_motor.construir_zonas(raw_base([], poligonos=[poligono(0, 0, 40, 30, "A-MURO")]), VOCAB)       # 1200 m2
    assert r["total"] == 0


def test_los_cajetines_no_cuentan_para_las_vistas():
    from_polis = [poligono(i * 4, 0, i * 4 + 3.5, 3.5, "A") for i in range(3)] + [poligono(1000, 0, 1060, 9, "ROTULO") for _ in range(4)]
    r = zonas_motor.construir_zonas(raw_base([], poligonos=from_polis), VOCAB)
    assert len(r["vistas"]) == 1 and r["vistas"][0]["bbox"][2] < 20
