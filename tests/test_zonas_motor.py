from pathlib import Path

import pytest

import zonas_motor as zm

V = zm.cargar_vocabulario()
RAIZ = Path(__file__).resolve().parent.parent


def cuadro(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def poli(x0, y0, x1, y1, capa="MUROS"):
    return {"capa": capa, "pts": cuadro(x0, y0, x1, y1)}


def txt(t, x, y, capa="TEXTO"):
    return {"t": t, "x": x, "y": y, "capa": capa}


def blk(n, x0, y0, x1, y1, capa="MOBILIARIO"):
    return {"n": n, "capa": capa, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def tipos(res):
    return {z["nombre"]: z["tipo_espacio"] for z in res["zonas"]}


# ----------------------------------------------------------------------------------------------- distintos tipos de proyecto
def test_vivienda_con_textos_y_poligonos():
    raw = {"unidad_m": 1, "textos": [txt("Cocina", 2, 2), txt("ALCOBA PRINCIPAL", 8, 2), txt("Baño 1", 8, 6)],
           "poligonos": [poli(0, 0, 5, 4), poli(6, 0, 11, 4), poli(6, 4.5, 9, 7)], "bloques": []}
    r = zm.construir_zonas(raw, V)
    assert tipos(r) == {"Cocina": "cocina", "ALCOBA PRINCIPAL": "alcoba", "Baño 1": "baño"}
    cocina = next(z for z in r["zonas"] if z["nombre"] == "Cocina")
    assert cocina["origen"] == "texto+poligono" and cocina["confianza"] == "alta" and cocina["area_m2"] == 20.0
    assert (cocina["x"], cocina["y"]) == (2.5, 2.0) and cocina["bbox"] == [0, 0, 5, 4]
    assert r["tipologia"] == "vivienda"


def test_oficina_no_se_confunde_con_vivienda():
    raw = {"unidad_m": 1, "textos": [txt("Sala de juntas", 2, 2), txt("Recepción", 8, 2), txt("Open space", 14, 2), txt("Gerencia", 2, 8)],
           "poligonos": [], "bloques": []}
    r = zm.construir_zonas(raw, V)
    assert tipos(r) == {"Sala de juntas": "sala_juntas", "Recepción": "recepcion", "Open space": "oficina", "Gerencia": "oficina"}
    assert r["tipologia"] == "oficina"


def test_hotel_y_restaurante():
    r = zm.construir_zonas({"unidad_m": 1, "textos": [txt("Lobby", 0, 0), txt("Suite 201", 9, 0), txt("Spa", 18, 0), txt("Salón de eventos", 0, 9)],
                            "poligonos": [], "bloques": []}, V)
    assert tipos(r) == {"Lobby": "lobby", "Suite 201": "habitacion_hotel", "Spa": "spa", "Salón de eventos": "salon_eventos"}
    assert r["tipologia"] == "hotel"
    r = zm.construir_zonas({"unidad_m": 1, "textos": [txt("Restaurante", 0, 0), txt("Bar", 9, 0), txt("Cocina industrial", 0, 9)],
                            "poligonos": [], "bloques": []}, V)
    assert tipos(r) == {"Restaurante": "restaurante", "Bar": "bar", "Cocina industrial": "cocina_industrial"}


def test_comercial_salud_educacion_industrial():
    assert tipos(zm.construir_zonas({"textos": [txt("Showroom", 0, 0), txt("Probadores", 9, 0), txt("Bodega", 0, 9)]}, V)) == \
        {"Showroom": "tienda", "Probadores": "probadores", "Bodega": "bodega"}
    assert tipos(zm.construir_zonas({"textos": [txt("Consultorio 3", 0, 0), txt("Quirófano", 9, 0)]}, V)) == \
        {"Consultorio 3": "consultorio", "Quirófano": "quirofano"}
    assert tipos(zm.construir_zonas({"textos": [txt("Aula 101", 0, 0), txt("Auditorio", 9, 0)]}, V)) == {"Aula 101": "aula", "Auditorio": "auditorio"}
    assert tipos(zm.construir_zonas({"textos": [txt("Nave de producción", 0, 0), txt("Muelle de carga", 9, 0)]}, V)) == \
        {"Nave de producción": "produccion", "Muelle de carga": "muelle"}


def test_plano_en_italiano_e_ingles():
    r = zm.construir_zonas({"textos": [txt("Camera da letto", 0, 0), txt("Bagno", 9, 0), txt("Cucina", 0, 9), txt("Soggiorno", 9, 9),
                                       txt("Meeting room", 18, 0), txt("Kitchen", 18, 9)]}, V)
    assert tipos(r) == {"Camera da letto": "alcoba", "Bagno": "baño", "Cucina": "cocina", "Soggiorno": "sala",
                        "Meeting room": "sala_juntas", "Kitchen": "cocina"}


def test_lo_que_no_es_un_espacio_se_descarta():
    ruido = [txt("ESCALA 1:100", 0, 0), txt("Proyecto Casa Demo", 1, 0), txt("NPT +0.00", 2, 0), txt("3.50 m", 3, 0), txt("Fecha 12/11", 4, 0),
             txt("Notas generales", 5, 0), txt("AB", 6, 0), txt("Cinta LED perimetral", 7, 0)]
    assert zm.construir_zonas({"textos": ruido}, V)["total"] == 0


def test_nombre_desconocido_solo_vale_dentro_de_un_recinto_y_en_capa_de_rotulos():
    raw = {"unidad_m": 1, "textos": [txt("Atelier", 2, 2, "ROTULO"), txt("Atelier", 20, 20, "ROTULO"), txt("Atelier", 2.5, 2.5, "OTRA")],
           "poligonos": [poli(0, 0, 5, 4)], "bloques": []}
    r = zm.construir_zonas(raw, V)
    assert [(z["nombre"], z["tipo_espacio"]) for z in r["zonas"]] == [("Atelier", "otro")]   # el de fuera y el de capa comun se ignoran


def test_texto_con_formato_mtext():
    assert zm.limpiar_texto(r"{\fCalibri|b0;\C1;SALA DE ESTAR}\P") == "SALA DE ESTAR"
    assert zm.clasificar_texto(zm.limpiar_texto(r"\A1;COCINA"), V)[0] == "cocina"


# ----------------------------------------------------------------------------------------------- unidades
def test_plano_en_milimetros_calcula_areas_en_m2():
    raw = {"unidad_m": 0.001, "textos": [txt("Oficina", 1500, 2000)], "poligonos": [poli(0, 0, 3000, 4000)], "bloques": []}
    z = zm.construir_zonas(raw, V)["zonas"][0]
    assert z["area_m2"] == pytest.approx(12.0) and z["origen"] == "texto+poligono"


def test_poligono_demasiado_pequeno_o_enorme_no_cuenta_como_recinto():
    raw = {"unidad_m": 1, "textos": [txt("Cocina", 0.5, 0.5)], "poligonos": [poli(0, 0, 1, 1), poli(-1e3, -1e3, 1e3, 1e3)]}
    assert zm.construir_zonas(raw, V)["zonas"][0]["origen"] == "texto"      # 1 m2 y 4e6 m2 quedan fuera


def test_se_usa_el_poligono_mas_pequeno_que_contiene_el_texto():
    raw = {"unidad_m": 1, "textos": [txt("Cocina", 2, 2)], "poligonos": [poli(0, 0, 30, 30), poli(0, 0, 5, 4)]}
    assert zm.construir_zonas(raw, V)["zonas"][0]["area_m2"] == 20.0


# ----------------------------------------------------------------------------------------------- mobiliario y perfil
def test_roles_por_vocabulario_sin_nombres_de_ningun_proyecto():
    cases = {"BED_KING_01": "cama", "Cama doble": "cama", "WC suspendido": "sanitario", "Escritorio L": "escritorio",
             "Mostrador recepcion": "mostrador", "Gondola 2": "vitrina_exhibidor", "Sofa 3 plazas": "sofa", "Mesa reuniones 10p": "mesa_reuniones"}
    for nombre, rol in cases.items():
        assert zm.rol_de_bloque(nombre, "0", V, zm.perfil_vacio()) == (rol, False), nombre


def test_bloques_ignorados():
    for n in ("Puerta 90", "DOOR_900", "Ventana corrediza", "North arrow", "Vegetación 3"):
        assert zm.rol_de_bloque(n, "0", V, zm.perfil_vacio()) == (None, True), n


def test_perfil_del_proyecto_manda_sobre_el_vocabulario():
    perfil = {"roles_bloques": {"Mod-77": "cama", "Mesa": "escritorio"}, "ignorar_bloques": ["BED_KING_01"]}
    assert zm.rol_de_bloque("Mod-77", "0", V, perfil) == ("cama", False)
    assert zm.rol_de_bloque("mesa", "0", V, perfil) == ("escritorio", False)            # sin importar mayusculas
    assert zm.rol_de_bloque("BED_KING_01", "0", V, perfil) == (None, True)


def test_mobiliario_se_asocia_a_la_zona_que_lo_contiene():
    raw = {"unidad_m": 1, "textos": [txt("Dormitorio", 2, 2), txt("Cocina", 8, 2)], "poligonos": [poli(0, 0, 5, 4), poli(6, 0, 11, 4)],
           "bloques": [blk("BED_A", 1, 1, 3, 3), blk("Sink 1", 7, 1, 8, 2), blk("Puerta 90", 5, 1, 6, 2)]}
    z = {z["nombre"]: z for z in zm.construir_zonas(raw, V)["zonas"]}
    assert z["Dormitorio"]["muebles"] == ["BED_A"] and z["Cocina"]["muebles"] == ["Sink 1"]
    assert z["Dormitorio"]["muebles_detalle"][0]["rol"] == "cama"


def test_sin_textos_ni_poligonos_se_infieren_zonas_por_agrupamiento():
    raw = {"unidad_m": 1, "textos": [], "poligonos": [],
           "bloques": [blk("BED_1", 0, 0, 2, 2.2), blk("Mesa noche", 2.2, 0, 2.7, 0.5), blk("BED_2", 20, 0, 22, 2.2),
                       blk("Desk 1", 40, 0, 41.5, 0.8), blk("Desk 2", 41.7, 0, 43.2, 0.8)]}
    r = zm.construir_zonas(raw, V)
    por_tipo = {}
    for z in r["zonas"]:
        por_tipo.setdefault(z["tipo_espacio"], []).append(z)
    assert len(por_tipo["alcoba"]) == 2 and len(por_tipo["oficina"]) == 1          # 2 camas lejanas, 2 escritorios juntos = 1 zona
    assert all(z["origen"] == "mobiliario" and z["confianza"] == "baja" for z in r["zonas"])
    assert len(por_tipo["oficina"][0]["muebles"]) == 2


def test_bloques_anonimos_se_sugieren_con_pista_de_tamano():
    raw = {"unidad_m": 1, "textos": [], "poligonos": [], "bloques": [blk("Mod-120", 0, 0, 2.1, 2.4), blk("Mod-8", 5, 0, 5.2, 0.2)]}
    r = zm.construir_zonas(raw, V)
    assert r["zonas"] == [] and r["bloques_sin_rol"] == 2
    assert r["sugerencias_roles"][0]["nombre"] == "Mod-120" and "cama" in r["sugerencias_roles"][0]["pista"]
    assert all(s["nombre"] != "Mod-8" for s in r["sugerencias_roles"])             # demasiado pequeno para ser relevante
    raw["bloques"] = raw["bloques"][:1]
    perfil = {"roles_bloques": {"Mod-120": "cama"}}
    z = zm.construir_zonas(raw, V, perfil)["zonas"]
    assert len(z) == 1 and z[0]["tipo_espacio"] == "alcoba"                         # el perfil resuelve el bloque anonimo


def test_zona_manual_del_perfil():
    z = zm.construir_zonas({"textos": []}, V, {"zonas_manuales": [{"nombre": "Atrio", "tipo": "lobby", "x": 5, "y": 6}]})["zonas"]
    assert z[0]["nombre"] == "Atrio" and z[0]["origen"] == "manual" and (z[0]["x"], z[0]["y"]) == (5.0, 6.0)


def test_tipologia_se_deduce_y_se_puede_forzar():
    raw = {"textos": [txt("Showroom", 0, 0), txt("Bodega", 9, 0), txt("Caja", 18, 0)]}
    assert zm.construir_zonas(raw, V)["tipologia"] == "comercial"
    assert zm.construir_zonas(raw, V, tipologia="restaurante")["tipologia"] == "restaurante"
    assert zm.construir_zonas({"textos": [txt("Baño", 0, 0)]}, V)["tipologia"] == "indeterminada"      # un espacio ubicuo no decide


# ----------------------------------------------------------------------------------------------- perfil en disco y cache
def test_perfil_ida_y_vuelta_y_slug(tmp_path):
    assert zm.slug_proyecto("V5_ MOLTENI VILLA- CASA.dwg") == "v5_molteni_villa_casa"
    p = zm.perfil_vacio()
    p["roles_bloques"]["X"] = "cama"
    zm.guardar_perfil(tmp_path, "Mi Proyecto.dwg", p)
    assert zm.cargar_perfil(tmp_path, "mi proyecto")["roles_bloques"] == {"X": "cama"}
    assert zm.cargar_perfil(tmp_path, "otro")["roles_bloques"] == {}


def test_clave_de_cache_cambia_con_dibujo_objetos_y_perfil():
    base = zm.clave_cache("A.dwg", 100, {})
    assert base == zm.clave_cache("a.dwg", 100, {})                     # mayusculas no importan
    assert len({base, zm.clave_cache("B.dwg", 100, {}), zm.clave_cache("A.dwg", 101, {}), zm.clave_cache("A.dwg", 100, {"x": 1}),
                zm.clave_cache("A.dwg", 100, {}, "hotel")}) == 5


# ----------------------------------------------------------------------------------------------- guardian anti-literales
@pytest.mark.parametrize("archivo", ["zonas_motor.py", "sondas/sonda_zonas.py", "vocabulario_espacios.json"])
def test_el_escaner_no_lleva_datos_de_un_proyecto_concreto(archivo):
    src = (RAIZ / archivo).read_text(encoding="utf-8").lower()
    for prohibido in ("gruppo", "simbolo-", "dtjrtj", "molteni", "schaller", "4203.8", "1466.32", "villa"):
        assert prohibido not in src, f"{prohibido!r} en {archivo}: eso va en perfiles/<proyecto>.json"


# ----------------------------------------------------------------------------------------------- agrupamiento por hueco y tipologia inferida
def test_sofas_enfrentados_son_una_sola_sala_y_su_centro_esta_entre_ellos():
    # Dos sofas con 2.5 m entre cajas (centros a 3.8 m): una sala; antes se partian en dos.
    raw = {"unidad_m": 1, "textos": [], "poligonos": [], "bloques": [blk("Sofa A", 0, 0, 1.3, 3.9), blk("Sofa B", 3.8, 0, 5.1, 3.9)]}
    zs = zm.construir_zonas(raw, V)["zonas"]
    assert len(zs) == 1 and zs[0]["tipo_espacio"] == "sala" and len(zs[0]["muebles"]) == 2
    assert (zs[0]["x"], zs[0]["y"]) == (2.55, 1.95)        # punto medio del conjunto, sin ninguna coordenada escrita en el codigo


def test_habitaciones_distintas_no_se_juntan():
    raw = {"unidad_m": 1, "textos": [], "poligonos": [], "bloques": [blk("Bed 1", 0, 0, 2, 2.2), blk("Bed 2", 6, 0, 8, 2.2)]}   # 4 m de hueco
    assert len(zm.construir_zonas(raw, V)["zonas"]) == 2


def test_mesas_auxiliares_no_cuentan_como_mesa_de_comedor():
    for n in ("Mesa de noche", "mesita", "Coffee table", "Nightstand 2"):
        assert zm.rol_de_bloque(n, "0", V, zm.perfil_vacio()) == (None, True), n
    assert zm.rol_de_bloque("Mesa comedor 8p", "0", V, zm.perfil_vacio())[0] == "mesa_comedor"


def test_tipologia_se_infiere_tambien_del_mobiliario():
    raw = {"unidad_m": 1, "textos": [], "poligonos": [],
           "bloques": [blk("Bed A", 0, 0, 2, 2), blk("Bed B", 30, 0, 32, 2), blk("Kitchen island", 60, 0, 63, 1), blk("Dining table", 90, 0, 93, 1.2),
                       blk("Sofa 1", 120, 0, 122, 1)]}
    assert zm.construir_zonas(raw, V)["tipologia"] == "vivienda"


def test_la_cache_se_invalida_si_cambia_el_vocabulario_o_el_motor(tmp_path):
    voc = tmp_path / "v.json"
    voc.write_text("{}", encoding="utf-8")
    v1 = zm.version_motor(voc)
    voc.write_text('{"cambio": 1}', encoding="utf-8")
    v2 = zm.version_motor(voc)
    assert v1 != v2 and zm.clave_cache("A", 1, {}, None, v1) != zm.clave_cache("A", 1, {}, None, v2)
    assert v1.startswith(f"{zm.VERSION_MOTOR}-")


def test_un_dormitorio_pegado_a_un_bano_o_cocina_no_se_fusionan():
    # La cama y el bano estan a 1 m uno del otro (apartamento tipico): deben seguir siendo zonas distintas.
    raw = {"unidad_m": 1, "textos": [], "poligonos": [], "bloques": [blk("Bed A", 0, 0, 2, 2.2), blk("WC 1", 3, 0, 3.6, 0.8), blk("Kitchen sink", 3, 1.5, 5, 2.3)]}
    assert sorted(z["tipo_espacio"] for z in zm.construir_zonas(raw, V)["zonas"]) == ["alcoba", "baño", "cocina"]
