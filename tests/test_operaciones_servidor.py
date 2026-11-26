"""Fase 1A (servidor): la escritura deja constancia (diario + marcas), el reintento no duplica y una operacion a medias se reconcilia."""
import pytest

import operaciones
import server

H = {"nombre": "Cama X", "handle": "8A21", "x0": 0, "y0": 0, "x1": 2.1, "y1": 2.4, "w": 2.1, "h": 2.4}
ITEM = {"receta": "centro", "anfitrion": "Cama X", "opciones": {"producto": "ci160"}}


def _ctx(existentes=None):
    return {"ok": True, "plano": "Oficina_A.dwg", "hosts": [{"nombre": "Cama X", "host": H}], "muros": [], "n_muros": 0,
            "existentes": existentes or [], "objetos_en_modelo": 50}


def _montar(monkeypatch, existentes=None, insertar=None):
    vistos = []

    def diseno(args, **kw):
        vistos.append(args)
        if args["op"] == "contexto_varios":
            return _ctx(existentes)
        return insertar(args) if insertar else {"ok": True, "ejecutado": args["ejecutar"], "insertados": len(args["colocaciones"]),
                                                  "operacion": {"id": (args.get("operacion") or {}).get("id"), "piezas_marcadas": len(args["colocaciones"]), "fallos_xdata": 0}}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    return vistos


def _estado(op_id):
    return server._diario().cargar(op_id)["estado"]


def test_una_escritura_deja_el_diario_con_la_intencion_y_marca_cada_pieza(monkeypatch):
    vistos = _montar(monkeypatch)
    r = server.ubicar_varios([ITEM], ejecutar=True)
    ins = vistos[-1]
    assert r["ok"] and r["operacion_id"].startswith("op_") and ins["operacion"]["id"] == r["operacion_id"]
    assert all(c["item_id"].startswith("d1|8A21|centro|") for c in ins["colocaciones"])
    d = server._diario().cargar(r["operacion_id"])
    assert d["estado"] == "aplicada" and d["items"][0]["item_id"] == ins["colocaciones"][0]["item_id"] and d["plan_hash"]


def test_un_ensayo_no_crea_diario_ni_operacion(monkeypatch):
    vistos = _montar(monkeypatch)
    r = server.ubicar_varios([ITEM], ejecutar=False)
    assert "operacion_id" not in r and "operacion" not in vistos[-1] and not server.RUTA_OPERACIONES.exists()


def test_repetir_con_las_piezas_ya_marcadas_no_duplica(monkeypatch):
    vistos = _montar(monkeypatch)
    ids = [c["item_id"] for c in (server.ubicar_varios([ITEM], ejecutar=False), vistos[-1])[1]["colocaciones"]]
    pos = [(c["x"], c["y"], c["bloque"]) for c in vistos[-1]["colocaciones"]]
    existentes = [{"item_id": i, "bloque": b, "x": x, "y": y, "handle": str(n), "op_id": "op_antigua"} for n, (i, (x, y, b)) in enumerate(zip(ids, pos))]
    _montar(monkeypatch, existentes=existentes)
    r = server.ubicar_varios([ITEM], ejecutar=True)
    assert r["a_colocar"] == 0 and "No hay nada nuevo" in r["aviso"]


def test_una_pieza_marcada_pero_con_otro_producto_se_reporta_como_cambiada_y_no_se_mueve(monkeypatch):
    vistos = _montar(monkeypatch)
    server.ubicar_varios([ITEM], ejecutar=False)
    c0 = vistos[-1]["colocaciones"][0]
    _montar(monkeypatch, existentes=[{"item_id": c0["item_id"], "bloque": "OTRO", "x": c0["x"], "y": c0["y"], "handle": "1", "op_id": "op_x"}])
    r = server.ubicar_varios([ITEM], ejecutar=False)
    assert r["items"][0]["cambiadas"][0]["bloque_existente"] == "OTRO"


def test_un_fallo_antes_de_escribir_no_deja_rastro_en_el_diario(monkeypatch):
    _montar(monkeypatch, insertar=lambda a: {"ok": False, "error": "dibujo_grande_requiere_confirmacion"})
    r = server.ubicar_varios([ITEM], ejecutar=True)
    assert not r["ok"] and "operacion_id" not in r
    assert not server.RUTA_OPERACIONES.exists() or list(server.RUTA_OPERACIONES.glob("op_*.json")) == []        # nada que reconciliar


def test_el_diario_limpia_lo_cerrado_hace_mas_de_30_dias_y_conserva_lo_pendiente(tmp_path):
    import os
    import time
    d = operaciones.Diario(tmp_path)
    for op_id, estado in (("op_vieja_ok", "aplicada"), ("op_vieja_incierta", "incierta"), ("op_nueva_ok", "aplicada")):
        d.iniciar(op_id, "docA", "h", [])
        d.finalizar(op_id, estado)
    viejo = time.time() - 40 * 86400
    for n in ("op_vieja_ok", "op_vieja_incierta"):
        os.utime(tmp_path / f"{n}.json", (viejo, viejo))
    assert d.limpiar(30) == 1
    assert sorted(p.stem for p in tmp_path.glob("op_*.json")) == ["op_nueva_ok", "op_vieja_incierta"]


def test_un_fallo_a_mitad_deja_la_operacion_incierta_y_la_siguiente_llamada_la_reconcilia(monkeypatch):
    _montar(monkeypatch, insertar=lambda a: {"ok": False, "error": "autocad_no_responde"})
    r1 = server.ubicar_varios([ITEM], ejecutar=True)
    assert _estado(r1["operacion_id"]) == "incierta"
    esperados = server._diario().cargar(r1["operacion_id"])["items"]
    # en el dibujo quedaron marcadas las piezas 1..n-1 (la ultima se perdio)
    existentes = [{"item_id": e["item_id"], "bloque": e["bloque"], "x": e["x"], "y": e["y"], "handle": str(i), "op_id": r1["operacion_id"]}
                  for i, e in enumerate(esperados[:-1])]
    vistos = _montar(monkeypatch, existentes=existentes)
    r2 = server.ubicar_varios([ITEM], ejecutar=True)
    prev = r2["operaciones_previas"][0]
    assert r2["ok"] and prev["estado"] == "parcial" and prev["faltan"] == 1 and _estado(r1["operacion_id"]) == "parcial"
    assert [c["item_id"] for c in vistos[-1]["colocaciones"]] == [esperados[-1]["item_id"]]      # solo repone lo que faltaba


def test_si_una_operacion_previa_es_ambigua_no_se_escribe_nada(monkeypatch):
    _montar(monkeypatch, insertar=lambda a: {"ok": False, "error": "autocad_no_responde"})
    r1 = server.ubicar_varios([ITEM], ejecutar=True)
    esperado = server._diario().cargar(r1["operacion_id"])["items"][0]
    dos_candidatos = [{"bloque": esperado["bloque"], "x": esperado["x"], "y": esperado["y"], "handle": "8"},
                      {"bloque": esperado["bloque"], "x": esperado["x"] + 0.01, "y": esperado["y"], "handle": "9"}]
    vistos = _montar(monkeypatch, existentes=dos_candidatos)
    r2 = server.ubicar_varios([ITEM], ejecutar=True)
    assert not r2["ok"] and r2["error"] == "operacion_previa_ambigua" and not any(v["op"] == "insertar" for v in vistos)


def test_lo_que_ya_existia_antes_no_se_adopta_como_parte_de_la_operacion(monkeypatch):
    _montar(monkeypatch, existentes=[{"bloque": "X", "x": 9, "y": 9, "handle": "77"}], insertar=lambda a: {"ok": False, "error": "autocad_no_responde"})
    r1 = server.ubicar_varios([ITEM], ejecutar=True)
    assert "77" in server._diario().cargar(r1["operacion_id"])["previos"]


def test_sin_diario_no_se_escribe(monkeypatch, tmp_path):
    archivo = tmp_path / "archivo_no_carpeta"
    archivo.write_text("x", encoding="utf-8")
    monkeypatch.setattr(server, "RUTA_OPERACIONES", archivo)               # no se puede crear una carpeta ahi
    vistos = _montar(monkeypatch)
    r = server.ubicar_varios([ITEM], ejecutar=True)
    assert not r["ok"] and r["error"] == "diario_no_disponible" and not any(v["op"] == "insertar" for v in vistos)


def test_ubicar_en_anfitrion_tambien_usa_la_operacion(monkeypatch):
    vistos = []

    def diseno(args, **kw):
        vistos.append(args)
        if args["op"] == "contexto":
            return {"ok": True, "plano": "Oficina_A.dwg", "anfitrion": H, "muros": [], "n_muros": 0, "existentes": []}
        return {"ok": True, "ejecutado": True, "insertados": len(args["colocaciones"])}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    r = server.ubicar_en_anfitrion("centro", anfitrion="Cama X", opciones={"producto": "ci160"}, ejecutar=True)
    assert r["ok"] and r["operacion_id"] and vistos[-1]["operacion"]["id"] == r["operacion_id"]
    assert all(c["item_id"] for c in vistos[-1]["colocaciones"])


def test_el_modo_de_marca_cabe_en_un_campo_xdata():
    for it in ("d1|8A21|cama|cctevo58_12", operaciones.logical_item_id("diseno largo", "FFFF", "pared_frente", "ci200qs_3") + "#rotulo"):
        assert len(it.encode("utf-8")) < 255


def test_la_reconciliacion_se_informa_aunque_no_quede_nada_por_colocar(monkeypatch):
    _montar(monkeypatch, insertar=lambda a: {"ok": False, "error": "autocad_no_responde"})
    r1 = server.ubicar_varios([ITEM], ejecutar=True)
    esperados = server._diario().cargar(r1["operacion_id"])["items"]
    todas_marcadas = [{"item_id": e["item_id"], "bloque": e["bloque"], "x": e["x"], "y": e["y"], "handle": str(i), "op_id": r1["operacion_id"],
                       "capa_incorrecta": "0"} for i, e in enumerate(esperados)]
    _montar(monkeypatch, existentes=todas_marcadas)
    r2 = server.ubicar_varios([ITEM], ejecutar=True)
    prev = r2["operaciones_previas"][0]
    assert r2["a_colocar"] == 0 and prev["estado"] == "aplicada" and prev["con_capa_incorrecta"] == len(esperados)


# ------------------------------------------------------------------------------------------------ reemplazar el producto de una posicion
def _colocacion_actual(monkeypatch):
    vistos = _montar(monkeypatch)
    server.ubicar_varios([ITEM], ejecutar=False)
    return vistos[-1]["colocaciones"][0]


def test_cambiar_el_producto_sin_reemplazar_no_apila_ni_toca_nada(monkeypatch):
    c0 = _colocacion_actual(monkeypatch)
    previa = {"item_id": c0["item_id"], "bloque": "OTRO_PRODUCTO", "x": c0["x"], "y": c0["y"], "handle": "A1", "op_id": "op_x"}
    vistos = _montar(monkeypatch, existentes=[previa])
    r = server.ubicar_varios([ITEM], ejecutar=True)
    assert r["items"][0]["cambiadas"][0]["handle"] == "A1" and not any(v["op"] == "insertar" for v in vistos)


def test_con_reemplazar_se_pide_retirar_la_pieza_anterior_y_se_coloca_la_nueva(monkeypatch):
    c0 = _colocacion_actual(monkeypatch)
    previa = {"item_id": c0["item_id"], "bloque": "OTRO_PRODUCTO", "x": c0["x"], "y": c0["y"], "handle": "A1", "op_id": "op_x"}
    vistos = _montar(monkeypatch, existentes=[previa])
    r = server.ubicar_varios([ITEM], ejecutar=True, reemplazar=True)
    ins = [v for v in vistos if v["op"] == "insertar"][-1]
    assert r["ok"] and ins["reemplazos"] == [{"item_id_previo": c0["item_id"], "handle": "A1"}] and len(ins["colocaciones"]) >= 1
    assert r["reemplazos"]["retiradas"] == 1
    assert server._diario().cargar(r["operacion_id"])["reemplazos"] == ins["reemplazos"]


def test_un_ensayo_con_reemplazar_informa_cuantas_piezas_se_retirarian(monkeypatch):
    c0 = _colocacion_actual(monkeypatch)
    _montar(monkeypatch, existentes=[{"item_id": c0["item_id"], "bloque": "OTRO", "x": c0["x"], "y": c0["y"], "handle": "A1"}])
    r = server.ubicar_varios([ITEM], ejecutar=False, reemplazar=True)
    assert r["reemplazos"] == {"piezas_a_retirar": 1}


def test_quitar_parcial_pasa_los_filtros_a_la_sonda(monkeypatch):
    vistos = []
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: vistos.append(args) or {"ok": True})
    server.quitar_colocaciones(ejecutar=False, operacion_id="op_1", bloque_contiene="Moon")
    server.quitar_colocaciones(ejecutar=False)
    assert vistos[0]["operacion_id"] == "op_1" and vistos[0]["bloque_contiene"] == "Moon"
    assert "operacion_id" not in vistos[1] and "bloque_contiene" not in vistos[1]


def test_el_registro_de_uso_guarda_el_detalle_de_los_fallos(monkeypatch, tmp_path):
    import asyncio
    monkeypatch.setattr(server, "RUTA_USO", tmp_path / "uso.jsonl")
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: {"ok": False, "error": "fallo_diseno", "detalle": "com_error: Numero de parametros no valido"})
    asyncio.run(server.mcp.call_tool("ubicar_varios", {"items": [{"receta": "cama", "anfitrion": "X"}]}))
    r = server.ver_uso()
    assert r["recientes"][-1]["error"] == "fallo_diseno" and "parametros" in r["recientes"][-1]["detalle"]


def test_las_descripciones_dirigen_al_reemplazo_y_el_resultado_trae_la_pista(monkeypatch):
    import asyncio
    d = {t.name: (t.description or "") for t in asyncio.run(server.mcp.list_tools())}
    assert "reemplazar=True" in d["ubicar_varios"].split("\n")[0] + d["ubicar_varios"].split("\n")[1]       # en las primeras lineas, no escondido al final
    assert "ubicar_varios(reemplazar=True)" in d["quitar_colocaciones"] and "NO la uses para CAMBIAR" in d["quitar_colocaciones"]
    c0 = _colocacion_actual(monkeypatch)
    _montar(monkeypatch, existentes=[{"item_id": c0["item_id"], "bloque": "OTRO", "x": c0["x"], "y": c0["y"], "handle": "A1", "op_id": "op_x"}])
    r = server.ubicar_varios([ITEM], ejecutar=True)
    assert "reemplazar=True" in r["siguiente_paso"] and "NO borres todo" in r["siguiente_paso"]


def test_un_recinto_del_escaneo_es_anfitrion_y_la_cuadricula_se_reparte_en_el_(monkeypatch):
    """'recinto 2' se resuelve desde el escaneo (no desde un bloque); la cuadricula 2x2 sin separaciones reparte celdas iguales y queda dentro del recinto."""
    vistos = _montar(monkeypatch)
    zonas = [{"n": 1, "bbox": [0, 0, 2, 2], "medidas": {"angulo_grados": 0}}, {"n": 2, "bbox": [10, 10, 14, 16], "medidas": {"angulo_grados": 90}}]
    monkeypatch.setattr(server, "_zonas_del_plano", lambda *a, **k: {"ok": True, "zonas": zonas, "unidad_m": 1.0})
    item = {"receta": "cuadricula", "anfitrion": "recinto 2", "opciones": {"producto": "ci160", "filas": 2, "columnas": 2, "etiquetar": False}}
    r = server.ubicar_varios([item], ejecutar=False)
    assert r["ok"] and r["a_colocar"] == 4 and r["items"][0]["anfitrion"] == "Recinto 2"
    xs = sorted({round(p[1], 2) for p in r["items"][0]["piezas"]})
    ys = sorted({round(p[2], 2) for p in r["items"][0]["piezas"]})
    assert xs == [11.0, 13.0] and ys == [11.5, 14.5]                 # celdas de 2 x 3 m en el recinto de 4 x 6 m


def test_un_recinto_inexistente_se_omite_con_motivo(monkeypatch):
    _montar(monkeypatch)
    monkeypatch.setattr(server, "_zonas_del_plano", lambda *a, **k: {"ok": True, "zonas": [{"n": 1, "bbox": [0, 0, 1, 1]}], "unidad_m": 1.0})
    r = server.ubicar_varios([{"receta": "centro", "anfitrion": "Recinto 9", "opciones": {"producto": "ci160"}}], ejecutar=False)
    assert r["omitidos"] and r["omitidos"][0]["motivo"].startswith("El escaneo no trae un recinto numero 9")


def test_cuadricula_con_separacion_que_no_cabe_avisa():
    import motor_ubicacion as mu
    plan, avisos = mu.planear("cuadricula", {"nombre": "R", "x0": 0, "y0": 0, "x1": 2, "y1": 2}, {"producto": "ci160", "filas": 1, "columnas": 3, "separacion_x": 1.5, "etiquetar": False})
    assert len(plan) == 3 and any("no cabe" in a for a in avisos)


def test_recinto_en_L_reparte_en_el_rectangulo_inscrito_y_ninguna_pieza_cae_fuera(monkeypatch):
    """Un recinto en L: la caja envolvente incluye espacio que no es del recinto. La rejilla se calcula en el mayor rectangulo que cabe y cada pieza se comprueba."""
    import medidas
    vistos = _montar(monkeypatch)
    L = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]]
    zonas = [{"n": 1, "bbox": [0, 0, 10, 10], "area_m2": 64.0, "contorno": L, "medidas": {"angulo_grados": 0}}]
    monkeypatch.setattr(server, "_zonas_del_plano", lambda *a, **k: {"ok": True, "zonas": zonas, "unidad_m": 1.0})
    item = {"receta": "cuadricula", "anfitrion": "recinto 1", "producto": "ci160", "filas": 2, "columnas": 3, "etiquetar": False}      # parametros sueltos: se toman como opciones
    r = server.ubicar_varios([item], ejecutar=False)
    it = r["items"][0]
    assert r["ok"] and it["anfitrion_usado"]["tipo"] == "mayor_rectangulo_inscrito" and len(it["piezas"]) == 6
    assert all(medidas._en_poligono(p[1], p[2], [tuple(q) for q in L]) for p in it["piezas"])
    assert not any("FUERA" in a for a in (it["avisos"] or []))
    caja = server.ubicar_varios([{**item, "opciones": {"caja_completa": True}}], ejecutar=False)["items"][0]
    assert caja["anfitrion_usado"]["tipo"] == "caja_del_recinto" and any("FUERA" in a for a in caja["avisos"])


def test_rectangulo_inscrito_de_una_L_y_de_un_rectangulo():
    import medidas
    q = medidas.rectangulo_inscrito([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])
    assert abs(q["area"] - 40.0) < 1e-6                              # 10x4 (la franja horizontal) o 4x10 (la vertical)
    r = medidas.rectangulo_inscrito([(0, 0), (5, 0), (5, 3), (0, 3)])
    assert (r["x0"], r["y0"], r["x1"], r["y1"]) == (0, 0, 5, 3)
