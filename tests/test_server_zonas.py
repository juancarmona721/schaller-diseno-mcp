"""Pegamento del servidor para zonas (cache por dibujo, perfil de proyecto) con AutoCAD simulado."""
import pytest

import server


@pytest.fixture
def autocad(monkeypatch, tmp_path):
    estado = {"dibujo": "Oficina_A.dwg", "objetos": 100}
    lecturas = []
    planos = {
        "Oficina_A.dwg": {"ok": True, "plano": "A", "unidad_m": 1.0, "textos": [{"t": "Sala de juntas", "x": 2, "y": 2, "capa": "T"}],
                          "poligonos": [{"capa": "M", "pts": [[0, 0], [5, 0], [5, 4], [0, 4]]}], "bloques": []},
        "Casa_B.dwg": {"ok": True, "plano": "B", "unidad_m": 1.0, "textos": [{"t": "Cocina", "x": 2, "y": 2, "capa": "T"}], "poligonos": [],
                       "bloques": [{"n": "Mod-9", "capa": "X", "x0": 10, "y0": 10, "x1": 12.1, "y1": 12.4}]},
    }
    monkeypatch.setattr(server.acad, "estado", lambda timeout_s=10: {"ok": True, "dibujo_activo": estado["dibujo"], "objetos_en_modelo": estado["objetos"]})

    def crudo(**kw):
        lecturas.append(estado["dibujo"])
        return planos[estado["dibujo"]]
    monkeypatch.setattr(server.acad, "plano_crudo", crudo)
    monkeypatch.setattr(server, "CARPETA_PERFILES", tmp_path / "perfiles")
    monkeypatch.setattr(server, "CARPETA_CACHE", tmp_path / "cache")
    return estado, lecturas


def nombres(r):
    return sorted(z["nombre"] for z in r["zonas"])


def test_segunda_llamada_sale_de_la_cache(autocad):
    _, lecturas = autocad
    a = server.escanear_zonas()
    b = server.escanear_zonas()
    assert a["origen_datos"] == "lectura" and b["origen_datos"] == "cache" and len(lecturas) == 1
    assert nombres(a) == ["Sala de juntas"] and a["zonas"][0]["tipo_espacio"] == "sala_juntas" and a["zonas"][0]["area_m2"] == 20.0


def test_cambiar_de_dibujo_no_devuelve_zonas_del_anterior(autocad):
    estado, lecturas = autocad
    server.escanear_zonas()
    estado["dibujo"] = "Casa_B.dwg"
    r = server.escanear_zonas()
    assert nombres(r) == ["Cocina"] and r["origen_datos"] == "lectura" and lecturas == ["Oficina_A.dwg", "Casa_B.dwg"]
    estado["dibujo"] = "Oficina_A.dwg"
    assert nombres(server.escanear_zonas()) == ["Sala de juntas"]            # y volver al primero sirve su propia cache
    assert len(lecturas) == 2


def test_cambia_el_numero_de_objetos_se_relee(autocad):
    estado, lecturas = autocad
    server.escanear_zonas()
    estado["objetos"] = 101
    assert server.escanear_zonas()["origen_datos"] == "lectura" and len(lecturas) == 2


def test_forzar_recarga(autocad):
    _, lecturas = autocad
    server.escanear_zonas()
    assert server.escanear_zonas(forzar_recarga=True)["origen_datos"] == "lectura" and len(lecturas) == 2


def test_el_perfil_resuelve_bloques_anonimos_y_renueva_la_cache(autocad):
    estado, lecturas = autocad
    estado["dibujo"] = "Casa_B.dwg"
    antes = server.escanear_zonas()
    assert [z["tipo_espacio"] for z in antes["zonas"]] == ["cocina"] and antes["sugerencias_roles"][0]["pista"]
    r = server.perfil_proyecto("rol", bloque="Mod-9", rol="cama")
    assert r["ok"] and r["perfil"]["roles_bloques"] == {"Mod-9": "cama"}
    despues = server.escanear_zonas()
    assert despues["origen_datos"] == "lectura"                              # el perfil cambio: la cache anterior ya no vale
    assert sorted(z["tipo_espacio"] for z in despues["zonas"]) == ["alcoba", "cocina"]


def test_perfil_valida_y_persiste_por_proyecto(autocad):
    estado, _ = autocad
    assert server.perfil_proyecto("rol", bloque="X", rol="inventado")["error"] == "rol_desconocido"
    assert server.perfil_proyecto("tipologia", tipologia="marte")["error"] == "tipologia_desconocida"
    server.perfil_proyecto("ignorar", bloque="Marco")
    server.perfil_proyecto("zona", nombre="Atrio", tipo="lobby", x=1, y=2)
    server.perfil_proyecto("tipologia", tipologia="hotel")
    p = server.perfil_proyecto("ver")["perfil"]
    assert p["ignorar_bloques"] == ["Marco"] and p["zonas_manuales"][0]["nombre"] == "Atrio" and p["tipologia"] == "hotel"
    estado["dibujo"] = "Casa_B.dwg"
    assert server.perfil_proyecto("ver")["perfil"]["ignorar_bloques"] == []   # otro proyecto, otro perfil
    assert server.perfil_proyecto("zona", nombre="X")["error"] == "faltan_datos"
    assert server.perfil_proyecto("baila")["error"] == "accion_desconocida"


def test_consultar_y_buscar_usan_el_escaner_nuevo(autocad):
    assert server.consultar_zona("juntas")["zonas"][0]["nombre"] == "Sala de juntas"
    assert server.buscar_en_plano("sala_juntas")["total"] == 1
    assert server.consultar_zona("no existe")["error"] == "zona_no_encontrada"


# ------------------------------------------------------------------------------------------------ quitar_colocaciones
def test_quitar_pasa_ensayo_y_candado_a_la_sonda_y_solo_borra_con_ejecutar(monkeypatch):
    llamadas = []
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: (llamadas.append(args) or {"ok": True, "a_borrar": 35}))
    r = server.quitar_colocaciones()
    assert r["ok"] and llamadas[-1]["op"] == "quitar" and llamadas[-1]["ejecutar"] is False        # ensayo por defecto
    server.quitar_colocaciones(ejecutar=True, confirmacion="ABCD")
    assert llamadas[-1]["ejecutar"] is True and llamadas[-1]["confirmacion"] == "ABCD" and llamadas[-1]["max_objetos"] >= 1


def test_quitar_respeta_el_interruptor_de_escritura(monkeypatch):
    monkeypatch.setattr(server, "CFG", {**server.CFG, "escritura": {"habilitada": False}})
    assert server.quitar_colocaciones(ejecutar=True)["error"] == "escritura_desactivada"


def test_la_sonda_solo_puede_borrar_las_capas_sch():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "sondas" / "sonda_diseno.py").read_text(encoding="utf-8")
    assert 'CAPAS_SCH = ("SCH_ILUMINACION", "SCH_AUDIO")' in src
    cuerpo = src[src.index("def op_quitar"):src.index("def main")]
    assert cuerpo.count(".Delete()") == 3 and "Layer) not in CAPAS_SCH" in cuerpo    # 2x SelectionSet.Delete + 1 entidad, con barrera de capa


# ------------------------------------------------------------------------------------------------ guia para el asistente
def test_el_servidor_entrega_la_guia_completa_como_instrucciones_y_como_prompt():
    import asyncio
    ins = server.mcp.instructions
    for clave in ("escanear_zonas", "perfil_proyecto", "ubicar_en_anfitrion", "ensayo", "quitar_colocaciones", "bloques_schaller_corregido",
                  "linea de comandos", "regla de referencias", "pedir_referencias_finales"):
        assert clave in ins.lower(), clave
    prompts = asyncio.run(server.mcp.list_prompts())
    assert [p.name for p in prompts] == ["guia_de_diseno"]
    r = asyncio.run(server.mcp.get_prompt("guia_de_diseno"))
    assert "GUIA DE DISENO" in r.messages[0].content.text and "estado de AutoCAD" in r.messages[0].content.text


def test_la_guia_no_contradice_las_reglas_del_equipo():
    import guia_diseno
    assert "POR DEFINIR (cotizacion)" in guia_diseno.FLUJO and "DEFENSA" not in guia_diseno.FLUJO
    assert "nunca lo inventes" in guia_diseno.FLUJO.lower() or "nunca lo inventes" in guia_diseno.FLUJO


def test_los_perfiles_viven_en_un_solo_sitio_por_usuario_y_no_en_la_carpeta_de_cada_copia():
    # Causa real de "0 zonas" en Claude Desktop: el perfil se creo en la carpeta de desarrollo y el MCP instalado tenia otra, vacia.
    import importlib
    import os
    from pathlib import Path
    assert server.CARPETA_PERFILES != server.AQUI / "perfiles" or server.AQUI == Path.home() / ".schaller-diseno"
    anterior = os.environ.get("SCHALLER_PERFILES")
    try:
        os.environ.pop("SCHALLER_PERFILES", None)
        recargado = importlib.reload(server)
        assert recargado.CARPETA_PERFILES == Path.home() / ".schaller-diseno" / "perfiles"
        os.environ["SCHALLER_PERFILES"] = "X:/otra/carpeta"
        assert importlib.reload(server).CARPETA_PERFILES == Path("X:/otra/carpeta")
    finally:
        if anterior is None:
            os.environ.pop("SCHALLER_PERFILES", None)
        else:
            os.environ["SCHALLER_PERFILES"] = anterior
        importlib.reload(server)


# ------------------------------------------------------------------------------------------------ el perfil recuerda las respuestas
def test_atributos_se_fusionan_borran_y_no_distinguen_mayusculas(autocad):
    server.perfil_proyecto("atributos", bloque="Cama X", atributos={"cabecera": "N", "ancho_cama": 2.0})
    server.perfil_proyecto("atributos", bloque="cama x", atributos={"filas": [0.9, 2.1], "ancho_cama": None})        # fusiona; null borra una clave
    assert server.perfil_proyecto("ver")["perfil"]["atributos_bloques"] == {"Cama X": {"cabecera": "N", "filas": [0.9, 2.1]}}
    server.perfil_proyecto("atributos", bloque="CAMA X", atributos={})                                              # {} borra el bloque entero
    assert server.perfil_proyecto("ver")["perfil"]["atributos_bloques"] == {}
    assert server.perfil_proyecto("atributos", bloque="X")["error"] == "faltan_datos"
    assert server.perfil_proyecto("atributos", atributos={"a": 1})["error"] == "faltan_datos"


def test_el_escaner_devuelve_los_atributos_de_cada_mueble(autocad):
    estado, _ = autocad
    estado["dibujo"] = "Casa_B.dwg"
    server.perfil_proyecto("rol", bloque="Mod-9", rol="cama")
    server.perfil_proyecto("atributos", bloque="Mod-9", atributos={"cabecera": "O"})
    z = server.escanear_zonas()["zonas"][-1]
    assert z["muebles_detalle"][0]["nombre"] == "Mod-9" and z["muebles_detalle"][0]["atributos"] == {"cabecera": "O"}


def test_ubicar_usa_solos_los_atributos_guardados_y_lo_explicito_manda(autocad, monkeypatch):
    server.perfil_proyecto("atributos", bloque="Cama X", atributos={"cabecera": "N", "ancho_cama": 2.0, "nota": "no es una opcion"})

    def diseno(args, **kw):
        if args["op"] == "contexto":
            return {"ok": True, "plano": "Oficina_A.dwg", "muros": [], "n_muros": 0, "existentes": [],
                    "anfitrion": {"nombre": "Cama X", "x0": 0, "y0": 0, "x1": 2.9, "y1": 2.4, "w": 2.9, "h": 2.4}}
        return {"ok": True, "ejecutado": False, "colocaciones": len(args["colocaciones"])}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    r = server.ubicar_en_anfitrion(receta="cama", anfitrion="Cama X")                  # sin cabecera ni ancho: salen del perfil, sin preguntar
    assert r["ok"] and r["a_colocar"] == 7 and r["opciones_del_perfil"] == {"cabecera": "N", "ancho_cama": 2.0}
    tira = next(c for c in r["colocaciones"] if c["producto"] == "durastrip_ip68")
    assert tira["y"] > 2.3                                                             # cabecera N: la tira va en el borde norte (y1 = 2.4)
    lateral = [c for c in r["colocaciones"] if c["producto"] == "cctevo58" and "lateral" in c["nota"]]
    assert min(c["x"] for c in lateral) == pytest.approx(1.45 - 1.0 - 0.45, abs=0.02)   # ancho 2.0 (no 2.9): lo guardado se uso de verdad
    r2 = server.ubicar_en_anfitrion(receta="cama", anfitrion="Cama X", opciones={"cabecera": "S"})
    assert next(c for c in r2["colocaciones"] if c["producto"] == "durastrip_ip68")["y"] < 0.5      # lo explicito gana al perfil


def test_en_puntos_con_los_puntos_del_perfil_no_necesita_preguntar_nada(autocad, monkeypatch):
    server.perfil_proyecto("atributos", bloque="Bano 1", atributos={"puntos": [[4242.38, 1466.32]]})

    def diseno(args, **kw):
        if args["op"] == "contexto":
            return {"ok": True, "plano": "Oficina_A.dwg", "muros": [], "n_muros": 0, "existentes": [],
                    "anfitrion": {"nombre": "Bano 1", "x0": 0, "y0": 0, "x1": 3, "y1": 4, "w": 3, "h": 4}}
        return {"ok": True, "ejecutado": False, "colocaciones": len(args["colocaciones"])}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    r = server.ubicar_en_anfitrion(receta="en_puntos", anfitrion="Bano 1", opciones={"producto": "ci160"})
    assert r["ok"] and [(c["x"], c["y"]) for c in r["colocaciones"]] == [(4242.38, 1466.32)]


def test_la_guia_manda_autonomia_velocidad_y_pocas_preguntas():
    import guia_diseno
    g = guia_diseno.FLUJO
    for frase in ("AUTONOMIA", "EJECUTA directamente", "SUPUESTOS", "ubicar_varios", "UNA sola llamada", "NO llames a las herramientas en paralelo",
                  'perfil_proyecto(accion="atributos")', "en_puntos", "modo_prueba"):
        assert frase in g, frase
    assert "Pregunta SOLO" in g
    assert "pregúntamelo" not in g.lower() and "UNA aprobacion" not in g and "no pidas ensayo previo" in g      # ya no exige ensayo ni aprobacion


# ------------------------------------------------------------------------------------------------ concurrencia (llamadas en paralelo)
def test_las_llamadas_a_autocad_en_paralelo_se_ejecutan_de_una_en_una(monkeypatch):
    # Causa real de "Selection Set was deleted": Claude Desktop lanza varias herramientas a la vez y se pisaban en AutoCAD.
    import subprocess
    import threading
    import time
    import acad
    dentro, maximo, lock = [0], [0], threading.Lock()

    class R:
        stdout = '{"ok": true}'
        stderr = ""

    def falso_run(*a, **kw):
        with lock:
            dentro[0] += 1
            maximo[0] = max(maximo[0], dentro[0])
        time.sleep(0.05)
        with lock:
            dentro[0] -= 1
        return R()
    monkeypatch.setattr(subprocess, "run", falso_run)
    hilos = [threading.Thread(target=lambda: acad._correr(acad.PROBE_ESTADO, 5)) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert maximo[0] == 1


def test_una_operacion_de_varios_pasos_no_se_intercala_con_otra(autocad, monkeypatch):
    import threading
    import time
    orden = []

    def diseno(args, **kw):
        orden.append((threading.current_thread().name, args["op"]))
        time.sleep(0.03)
        if args["op"] == "contexto":
            return {"ok": True, "plano": "Oficina_A.dwg", "muros": [], "n_muros": 0, "existentes": [],
                    "anfitrion": {"nombre": "M", "x0": 0, "y0": 0, "x1": 2, "y1": 1, "w": 2, "h": 1}}
        return {"ok": True, "ejecutado": False, "colocaciones": 1}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    hilos = [threading.Thread(name=f"h{i}", target=lambda: server.ubicar_en_anfitrion(receta="centro", anfitrion="M", opciones={"producto": "ci160"})) for i in range(4)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    for i in range(0, len(orden), 2):
        assert orden[i][0] == orden[i + 1][0] and orden[i][1] == "contexto" and orden[i + 1][1] == "insertar"   # contexto e insertar, juntos


def test_los_conjuntos_de_seleccion_son_unicos_por_proceso():
    import os
    from pathlib import Path
    for f in ("sondas/sonda_diseno.py", "sondas/sonda_zonas.py"):
        src = (Path(__file__).resolve().parent.parent / f).read_text(encoding="utf-8")
        assert 'nombre = f"{nombre}_{os.getpid()}"' in src, f


# ------------------------------------------------------------------------------------------------ ubicar_varios (todo el diseno en una llamada)
def _ctx_varios(hosts, existentes=None, muros=None):
    return {"ok": True, "plano": "Oficina_A.dwg", "hosts": hosts, "muros": muros or [], "n_muros": len(muros or []), "existentes": existentes or [],
            "objetos_en_modelo": 100}


H1 = {"nombre": "Cama X", "x0": 0, "y0": 0, "x1": 2.1, "y1": 2.4, "w": 2.1, "h": 2.4}
H2 = {"nombre": "Mesa Y", "x0": 10, "y0": 0, "x1": 13.6, "y1": 1.2, "w": 3.6, "h": 1.2}


def test_ubicar_varios_resuelve_todo_en_dos_llamadas_a_autocad_y_omite_sin_frenar(autocad, monkeypatch):
    llamadas = []

    def diseno(args, **kw):
        llamadas.append(args)
        if args["op"] == "contexto_varios":
            return _ctx_varios([{"nombre": "Cama X", "host": H1}, {"nombre": "Mesa Y", "host": H2},
                                {"nombre": "No existe", "error": "anfitrion_no_encontrado", "detalle": "No hay ningun bloque llamado 'No existe'."},
                                {"nombre": "Mesa Y", "host": H2}])
        return {"ok": True, "ejecutado": args["ejecutar"], "insertados": len(args["colocaciones"])}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    items = [{"receta": "cama", "anfitrion": "Cama X", "opciones": {"cabecera": "N"}},
             {"receta": "centro", "anfitrion": "Mesa Y", "opciones": {"producto": "simbiosis"}},
             {"receta": "centro", "anfitrion": "No existe", "opciones": {"producto": "ci160"}},
             {"receta": "inventada", "anfitrion": "Mesa Y"}]
    r = server.ubicar_varios(items, ejecutar=True)
    assert [x["op"] for x in llamadas] == ["contexto_varios", "insertar"]            # el plano se lee UNA vez y se inserta UNA vez
    assert r["ok"] and r["a_colocar"] == 8 and r["por_producto"] == {"durastrip_ip68": 1, "cctevo58": 6, "simbiosis": 1}
    assert [d["estado"] for d in r["items"]] == ["ok", "ok", "omitido", "omitido"]
    assert {o["anfitrion"] for o in r["omitidos"]} == {"No existe", "Mesa Y"} and llamadas[1]["ejecutar"] is True and len(llamadas[1]["colocaciones"]) == 8
    assert r["insercion"]["insertados"] == 8 and "aviso" not in r


def test_ubicar_varios_en_ensayo_no_escribe_y_no_duplica_dentro_del_lote(autocad, monkeypatch):
    llamadas = []

    def diseno(args, **kw):
        llamadas.append(args)
        if args["op"] == "contexto_varios":
            return _ctx_varios([{"nombre": "Mesa Y", "host": H2}, {"nombre": "Mesa Y", "host": H2}])
        return {"ok": True, "ejecutado": False, "insertados": None}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    r = server.ubicar_varios([{"receta": "centro", "anfitrion": "Mesa Y", "opciones": {"producto": "ci160"}}] * 2, ejecutar=False)
    assert r["a_colocar"] == 1 and [d["a_colocar"] for d in r["items"]] == [1, 0] and r["items"][1]["ya_colocadas"] == 1   # el 2.o ya estaba en el lote
    assert llamadas[1]["ejecutar"] is False and "ENSAYO" in r["aviso"]


def test_ubicar_varios_usa_el_perfil_y_lo_ya_colocado(autocad, monkeypatch):
    server.perfil_proyecto("atributos", bloque="Cama X", atributos={"cabecera": "N", "ancho_cama": 2.0})
    previo = [{"bloque": "Durastrip IP68_45W_Targetti", "x": 1.05, "y": 2.35}]            # la tira ya estaba puesta

    def diseno(args, **kw):
        if args["op"] == "contexto_varios":
            return _ctx_varios([{"nombre": "Cama X", "host": H1}], existentes=previo)
        return {"ok": True, "ejecutado": False}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    r = server.ubicar_varios([{"receta": "cama", "anfitrion": "Cama X"}], ejecutar=False)
    d = r["items"][0]
    assert d["opciones_del_perfil"] == {"cabecera": "N", "ancho_cama": 2.0} and d["a_colocar"] == 6 and d["ya_colocadas"] == 1


def test_ubicar_varios_valida_la_entrada_y_respeta_el_interruptor_de_escritura(autocad, monkeypatch):
    assert server.ubicar_varios([])["error"] == "items_invalidos" and server.ubicar_varios("x")["error"] == "items_invalidos"
    monkeypatch.setattr(server, "CFG", {**server.CFG, "escritura": {"habilitada": False}})
    assert server.ubicar_varios([{"receta": "cama", "anfitrion": "X"}])["error"] == "escritura_desactivada"


# ------------------------------------------------------------------------------------------------ ajustes y registro de uso
def test_modo_prueba_quita_el_codigo_de_confirmacion_y_se_puede_revertir(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUTA_AJUSTES", tmp_path / "ajustes.json")
    assert server._max_objetos() == 300 and server.ajustes()["candado_de_planos_grandes"] == "activo"
    r = server.ajustes(modo_prueba=True)
    assert r["ajustes"] == {"modo_prueba": True} and "DESACTIVADO" in r["candado_de_planos_grandes"] and server._max_objetos() > 10 ** 6
    assert server.ajustes(modo_prueba=False)["candado_de_planos_grandes"] == "activo" and server._max_objetos() == 300


def test_modo_prueba_llega_a_la_insercion(autocad, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUTA_AJUSTES", tmp_path / "ajustes.json")
    server.ajustes(modo_prueba=True)
    vistos = []

    def diseno(args, **kw):
        vistos.append(args)
        if args["op"] == "contexto_varios":
            return _ctx_varios([{"nombre": "Mesa Y", "host": H2}])
        return {"ok": True, "ejecutado": True, "insertados": 1}
    monkeypatch.setattr(server.acad, "diseno", diseno)
    server.ubicar_varios([{"receta": "centro", "anfitrion": "Mesa Y", "opciones": {"producto": "ci160"}}], ejecutar=True)
    assert vistos[-1]["max_objetos"] > 10 ** 6                      # el candado no se activa: AutoCAD no pedira codigo


def test_cada_llamada_queda_registrada_con_su_duracion_y_ver_uso_la_resume(monkeypatch, tmp_path):
    import asyncio
    monkeypatch.setattr(server, "RUTA_USO", tmp_path / "logs" / "uso.jsonl")
    asyncio.run(server.mcp.call_tool("catalogo_ubicacion", {}))
    asyncio.run(server.mcp.call_tool("catalogo_ubicacion", {}))
    r = server.ver_uso()
    assert r["llamadas"] == 2 and r["por_herramienta"]["catalogo_ubicacion"]["n"] == 2 and r["por_herramienta"]["catalogo_ubicacion"]["fallos"] == 0
    assert r["recientes"][0]["ms"] >= 0 and r["recientes"][0]["herramienta"] == "catalogo_ubicacion"


def test_el_registro_marca_como_fallo_lo_que_devuelve_ok_false(monkeypatch, tmp_path):
    import asyncio
    monkeypatch.setattr(server, "RUTA_USO", tmp_path / "uso.jsonl")
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: {"ok": False, "error": "sin_dibujo"})
    asyncio.run(server.mcp.call_tool("ubicar_varios", {"items": [{"receta": "cama", "anfitrion": "X"}]}))
    r = server.ver_uso()
    assert r["por_herramienta"]["ubicar_varios"]["fallos"] == 1 and r["recientes"][-1]["error"] == "sin_dibujo"


def test_ver_uso_sin_registro_no_falla(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUTA_USO", tmp_path / "no_existe.jsonl")
    assert server.ver_uso() == {"ok": True, "llamadas": 0, "detalle": "Todavia no hay registro de uso."}


# ------------------------------------------------------------------------------------------------ diagnostico con 0 zonas y modo consulta
def test_sin_zonas_el_escaneo_explica_por_que_y_que_hacer(autocad, monkeypatch):
    res = {"ok": True, "total": 0, "zonas": [], "resumen_lectura": {"textos": 37, "textos_con_nombre_de_espacio": 0, "poligonos": 199,
                                                                    "poligonos_con_area_de_recinto": 0, "bloques": 418, "bloques_con_rol": 0, "bloques_sin_rol": 400}}
    monkeypatch.setattr(server, "_zonas_del_plano", lambda *a, **k: res)
    r = server.escanear_zonas()
    d = r["diagnostico"]
    assert len(d["por_que_no_hay_zonas"]) == 3 and "37" in d["por_que_no_hay_zonas"][0] and "199" in d["por_que_no_hay_zonas"][1]
    assert any("capturas" in p for p in d["que_hacer"])
    assert "CONSULTAR" in r["siguiente_paso"] and "no coloques nada" in r["siguiente_paso"]


def test_con_zonas_no_hay_diagnostico(autocad, monkeypatch):
    monkeypatch.setattr(server, "_zonas_del_plano", lambda *a, **k: {"ok": True, "total": 2, "zonas": [{}, {}]})
    assert "diagnostico" not in server.escanear_zonas()


def test_construir_zonas_cuenta_lo_que_leyo():
    import zonas_motor
    raw = {"unidad_m": 1.0, "textos": [{"t": "SALA", "x": 1, "y": 1, "capa": "T"}, {"t": "A", "x": 5, "y": 5, "capa": "T"}], "poligonos": [], "bloques": []}
    r = zonas_motor.construir_zonas(raw, zonas_motor.cargar_vocabulario())["resumen_lectura"]
    assert r["textos"] == 2 and r["textos_con_nombre_de_espacio"] == 1 and r["poligonos_con_area_de_recinto"] == 0


def test_ninguna_herramienta_manda_a_confirmar_con_la_persona_fuera_de_borrar_codigos_o_referencias():
    """Las descripciones no deben contradecir la autonomia: solo se pregunta para borrar, el codigo de AutoCAD, cotizaciones o contradicciones."""
    import asyncio
    import re
    herramientas = asyncio.run(server.mcp.list_tools())
    permitido = re.compile(r"codigo|c[oó]digo|borr|cotizaci|referencia|candado|confirmacion|confirmado_por_usuario|quitar", re.I)
    for t in herramientas:
        texto = t.description or ""
        if re.search(r"con la persona|a la persona|al usuario", texto, re.I) and re.search(r"confirm|pregunt|pide|pedir", texto, re.I):
            assert permitido.search(texto), f"{t.name}: manda a confirmar o preguntar sin ser borrado, codigo de AutoCAD ni referencias"
        assert "hay que confirmar los espacios" not in texto


def test_la_guia_explica_los_planos_sin_rotulos_y_los_anfitriones_girados():
    import guia_diseno
    for frase in ("PLANOS SIN ROTULOS", "rol_origen", "NO tomes capturas", "ANFITRION GIRADO", "cabecera_local", "VARIAS PLANTAS", "NO es un piso"):
        assert frase in guia_diseno.FLUJO, frase
