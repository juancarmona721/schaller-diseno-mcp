"""Pista 0A: instrumentacion opcional, estado del MCP, autoprueba nivel 1 y formato de informes. Nada de esto toca AutoCAD."""
import json
import time

import pytest

import autoprueba
import informe_benchmark as ib
import metricas
import salud
import server


# ------------------------------------------------------------------------------------------------ instrumentacion
def test_apagada_no_hace_nada_y_devuelve_none():
    llamada, etapa, resumen, absorber, volcar, reiniciar = metricas.crear(False)
    assert llamada("InsertBlock") is None and resumen() is None and volcar() is None
    with etapa("x") as e:
        assert e is None
    assert etapa("a") is etapa("b")                  # un unico contexto vacio compartido: sin asignaciones por llamada


def test_apagada_no_escribe_nada_en_disco(tmp_path):
    _, _, _, _, volcar, _ = metricas.crear(False)
    volcar(tmp_path / "m.jsonl", {"herramienta": "t"})
    assert not (tmp_path / "m.jsonl").exists()


def test_encendida_cuenta_por_tipo_y_acumula_etapas():
    llamada, etapa, resumen, *_ = metricas.crear(True)
    for _ in range(3):
        llamada("InsertBlock")
    llamada("Layer", 5)
    with etapa("insercion"):
        pass
    r = resumen()
    assert r["llamadas_com"] == {"InsertBlock": 3, "Layer": 5} and r["total_llamadas_com"] == 8
    assert r["etapas_ms"]["insercion"]["n"] == 1


def test_encendida_vuelca_UNA_linea_agrupada_y_reinicia(tmp_path):
    llamada, etapa, resumen, absorber, volcar, _ = metricas.crear(True)
    for _ in range(300):
        llamada("GetBoundingBox")                     # 300 llamadas COM -> una sola linea de log
    ruta = tmp_path / "logs" / "m.jsonl"
    volcar(ruta, {"herramienta": "ubicar_varios"})
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1 and json.loads(lineas[0])["llamadas_com"]["GetBoundingBox"] == 300
    assert volcar(ruta) is None and resumen()["total_llamadas_com"] == 0     # reiniciado: sin datos no escribe


def test_el_servidor_absorbe_lo_medido_por_la_sonda():
    llamada, etapa, resumen, absorber, *_ = metricas.crear(True)
    absorber({"llamadas_com": {"InsertBlock": 15}, "etapas_ms": {"insercion": {"n": 1, "total": 40.0, "max": 40.0}}})
    r = resumen()
    assert r["llamadas_com"]["InsertBlock"] == 15 and "sonda.insercion" in r["etapas_ms"]


def test_la_instrumentacion_apagada_deja_el_resultado_de_insertar_identico():
    import sondas.sonda_diseno as sd
    assert sd.resumen() is None or metricas.ACTIVA          # apagada: no se agrega "_metricas" al resultado


# ------------------------------------------------------------------------------------------------ estado del MCP
def test_estado_basico_no_toca_autocad_y_marca_que_no_esta_verificado(monkeypatch, tmp_path):
    def prohibido(*a, **k):
        raise AssertionError("el estado basico no debe conectarse a AutoCAD")
    monkeypatch.setattr(server.acad, "estado", prohibido)
    monkeypatch.setattr(server, "RUTA_CONEXION", tmp_path / "c.json")
    r = server.estado_mcp()
    assert r["ok"] and r["autocad"]["estado_actual_verificado"] is False and r["autocad"]["ultima_conexion"] == "sin_medir"
    assert r["capacidades"]["imagenes_en_cliente"] == "no_verificado" and r["version_mcp"] and r["herramientas"] >= 40


def test_estado_basico_es_rapido(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUTA_CONEXION", tmp_path / "c.json")
    t = []
    for _ in range(7):
        t0 = time.perf_counter()
        server.estado_mcp()
        t.append(time.perf_counter() - t0)
    t.sort()
    assert t[len(t) // 2] < 0.2 and max(t) < 1.0              # mediana < 200 ms, siempre < 1 s


def test_verificar_hace_una_conexion_guarda_la_latencia_y_la_siguiente_consulta_la_reutiliza(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUTA_CONEXION", tmp_path / "c.json")
    llamadas = []
    monkeypatch.setattr(server.acad, "estado", lambda **k: llamadas.append(1) or {"ok": True, "version_interna": "25.0"})
    r1 = server.estado_mcp(verificar=True)
    assert len(llamadas) == 1 and r1["autocad"]["estado_actual_verificado"] and r1["autocad"]["ultima_conexion"] == "disponible"
    r2 = server.estado_mcp()
    assert len(llamadas) == 1 and r2["autocad"]["ultima_conexion"] == "disponible" and r2["autocad"]["estado_actual_verificado"] is False
    assert r2["autocad"]["ultima_conexion_ms"] is not None


def test_verificar_con_autocad_cerrado_lo_registra_como_no_disponible(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUTA_CONEXION", tmp_path / "c.json")
    monkeypatch.setattr(server.acad, "estado", lambda **k: {"ok": False, "error": "autocad_no_abierto"})
    assert server.estado_mcp(verificar=True)["autocad"]["ultima_conexion"] == "no_disponible"


def test_lo_guardado_de_la_conexion_no_incluye_datos_del_dibujo(tmp_path):
    salud.guardar_conexion(tmp_path / "c.json", True, 110.4, "25.0")
    assert set(json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))) == {"estado", "ms", "marca_tiempo", "autocad_version"}


def test_la_version_sale_del_repositorio_sin_ejecutar_git(tmp_path):
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (tmp_path / ".git" / "refs" / "heads" / "main").write_text("abcdef1234567890\n", encoding="utf-8")
    assert salud.version_mcp(tmp_path) == "abcdef1"
    (tmp_path / "otro").mkdir()
    assert salud.version_mcp(tmp_path / "otro") == "desconocida"


def test_perfil_completo_solo_con_shapely_y_pillow():
    assert salud.perfil_instalacion({"geometria_avanzada": "instalado", "render_imagenes": "instalado"}) == "completo"
    assert salud.perfil_instalacion({"geometria_avanzada": "no_instalado", "render_imagenes": "instalado"}) == "compatibilidad"


# ------------------------------------------------------------------------------------------------ autoprueba nivel 1
def test_autoprueba_corre_sin_autocad_y_deja_todo_como_estaba(tmp_path):
    antes = sorted(p.name for p in server.AQUI.iterdir())
    res = autoprueba.ejecutar(server.AQUI, tmp_path / "perfiles", configs=[])
    ids = {c["id"] for c in res["comprobaciones"]}
    assert {"sistema", "python", "pywin32", "geometria_avanzada", "mcp_sdk", "dependencias", "rutas_y_permisos", "integridad", "cliente_mcp", "autocad_registrado"} <= ids
    assert sorted(p.name for p in server.AQUI.iterdir()) == antes           # sin archivos temporales sobrantes
    assert list((tmp_path / "perfiles").glob("*")) == []                    # el ciclo de prueba se limpia
    c = {x["id"]: x for x in res["comprobaciones"]}
    assert c["pywin32"]["estado"] == "ok" and c["mcp_sdk"]["estado"] == "ok" and c["rutas_y_permisos"]["estado"] == "ok" and c["integridad"]["estado"] == "ok"


def test_autoprueba_es_repetible(tmp_path):
    a = autoprueba.ejecutar(server.AQUI, tmp_path / "p", configs=[])
    b = autoprueba.ejecutar(server.AQUI, tmp_path / "p", configs=[])
    assert [c["estado"] for c in a["comprobaciones"]] == [c["estado"] for c in b["comprobaciones"]]


def test_autoprueba_no_modifica_la_configuracion_del_cliente_y_detecta_rutas_rotas(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    contenido = json.dumps({"mcpServers": {"schaller-diseno": {"command": str(tmp_path / "no_existe.exe"), "args": [str(tmp_path / "x.py")]},
                                           "otro": {"command": "x"}}, "preferencia": 1})
    cfg.write_text(contenido, encoding="utf-8")
    res = autoprueba.ejecutar(server.AQUI, tmp_path / "p", configs=[cfg])
    c = {x["id"]: x for x in res["comprobaciones"]}
    assert c["cliente_mcp"]["estado"] == "fallo" and "ejecutable" in c["cliente_mcp"]["detalle"]
    assert cfg.read_text(encoding="utf-8") == contenido and not list(tmp_path.glob("*.bak"))


def test_autoprueba_cliente_sin_registro_es_un_aviso_no_un_fallo(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"mcpServers": {"otro": {"command": "x"}}}), encoding="utf-8")
    c = {x["id"]: x for x in autoprueba.ejecutar(server.AQUI, tmp_path / "p", configs=[cfg])["comprobaciones"]}
    assert c["cliente_mcp"]["estado"] == "aviso" and "1 otros" in c["cliente_mcp"]["detalle"]


def test_la_autoprueba_tambien_se_puede_lanzar_desde_la_linea_de_comandos(capsys, monkeypatch, tmp_path):
    import schaller_cli
    monkeypatch.setattr(server, "CARPETA_PERFILES", tmp_path / "p")
    codigo = schaller_cli.main(["autoprueba"])
    salida = capsys.readouterr().out
    assert "Autoprueba nivel 1:" in salida and codigo in (0, 1)


# ------------------------------------------------------------------------------------------------ formato de informes
def test_un_informe_nuevo_tiene_metricas_null_no_cero_y_es_valido():
    inf = ib.nuevo_informe("insert_200", "abc1234", entidades=200, definiciones=4)
    assert all(v is None for v in inf["metrics"].values()) and ib.validar(inf) == []


def test_una_metrica_en_cero_o_una_ruta_privada_invalidan_el_informe():
    inf = ib.nuevo_informe("x", "v")
    inf["metrics"]["total_ms"] = 0
    inf["result"]["warnings"].append(r"leyo C:\Users\alguien\plano.dwg")
    problemas = ib.validar(inf)
    assert any("total_ms es 0" in p for p in problemas) and any("ruta de usuario" in p for p in problemas)


def test_el_entorno_no_lleva_datos_personales():
    assert set(ib.entorno()) == {"windows_version", "python_version", "python_architecture", "autocad_version", "autocad_language", "client_version"}


def test_p95_solo_con_veinte_o_mas_muestras():
    assert ib.resumir(list(range(1, 11)))["p95"] is None
    r = ib.resumir(list(range(1, 41)))
    assert r["p95"] == 38 and r["mediana"] == 20.5 and len(r["muestras"]) == 40
    assert ib.resumir([])["mediana"] is None


@pytest.mark.parametrize("ref,nuevo,estricto,investigar", [
    (200, 290, False, False), (200, 310, False, True),          # general: max(5%, 100 ms) -> 100 ms
    (3000, 3140, False, False), (3000, 3160, False, True),      # 5% de 3000 = 150 ms
    (200, 209, True, False), (200, 211, True, True),            # estricto: max(1%, 10 ms) -> 10 ms
    (12000, 12100, True, False), (12000, 12130, True, True),    # 1% de 12000 = 120 ms
])
def test_umbrales_de_regresion(ref, nuevo, estricto, investigar):
    assert ib.comparar(ref, nuevo, estricto)["investigar"] is investigar
