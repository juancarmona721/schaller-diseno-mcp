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
