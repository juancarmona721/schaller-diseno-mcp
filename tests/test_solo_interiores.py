"""Exteriores: un balcon/terraza/patio solo es zona si esta DELIMITADO (contorno cerrado); sin contorno no es zona y se informa como excluido."""
import pytest

import recintos
import zonas_motor

VOCAB = zonas_motor.cargar_vocabulario()


def _caja(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _casa():
    """Casa de 14 x 8 m a DOBLE linea (caras a 12 cm) con un tabique: dos recintos. Muros en capa 'MUROS'."""
    lineas = []
    for (x0, y0, x1, y1) in [(0, 0, 14, 8), (0.12, 0.12, 13.88, 7.88)]:
        lineas += [[x0, y0, x1, y0, "MUROS"], [x1, y0, x1, y1, "MUROS"], [x1, y1, x0, y1, "MUROS"], [x0, y1, x0, y0, "MUROS"]]
    lineas += [[7, 0.12, 7, 7.88, "MUROS"], [7.12, 0.12, 7.12, 7.88, "MUROS"]]
    return lineas


def _raw(textos=(), poligonos=(), bloques=()):
    return {"unidad_m": 1.0, "textos": list(textos), "poligonos": list(poligonos), "bloques": list(bloques),
            "muros": {"segmentos": [], "capas": []}, "lineas": {"segmentos": _casa(), "entidades_leidas": 0},
            "definiciones": {}}


def _txt(t, x, y):
    return {"t": t, "x": x, "y": y, "capa": "TEXTOS"}


def _nombres(r):
    return [z["nombre"] for z in r["zonas"]]


@pytest.fixture(autouse=True)
def _necesita_shapely():
    if not recintos.disponible():
        pytest.skip("sin shapely")


def test_el_casco_de_la_casa_se_expone_para_filtrar():
    r = zonas_motor.construir_zonas(_raw(), VOCAB)
    env = r["medidas_plano"]
    assert r["total"] >= 2 and r["excluidas_exterior"] == []
    pts = None
    # el casco viene en el diagnostico de la reconstruccion
    rec = recintos.reconstruir([l[:4] for l in _casa()], 1.0)
    pts = rec["diagnostico"].get("envolvente", {}).get("pts")
    assert pts and len(pts) >= 4 and env is not None


def test_un_balcon_delimitado_si_es_zona_y_queda_marcado_como_exterior():
    raw = _raw(textos=[_txt("BALCON", 21, 4), _txt("SALA", 3, 4)], poligonos=[{"capa": "ARQ", "pts": _caja(18, 2, 24, 6)}])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    b = [z for z in r["zonas"] if z["nombre"] == "BALCON"]
    assert len(b) == 1 and b[0]["exterior"] is True and b[0]["area_m2"] == 24.0
    assert r["excluidas_exterior"] == [] and r["resumen_lectura"]["exteriores_delimitadas"] == 1
    assert not any(z.get("exterior") for z in r["zonas"] if z["nombre"] != "BALCON")      # lo de adentro no se marca como exterior


def test_una_terraza_solo_con_rotulo_y_sin_contorno_no_es_zona():
    raw = _raw(textos=[_txt("Terraza", 30, 4), _txt("Sala", 10, 4)])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    ex = r["excluidas_exterior"]
    assert len(ex) == 1 and ex[0]["nombre"] == "Terraza" and "sin delimitar" in ex[0]["motivo"]
    assert "Terraza" not in _nombres(r) and "Sala" in _nombres(r)


def test_un_contorno_cerrado_sin_rotulo_fuera_de_la_casa_es_un_exterior_delimitado():
    raw = _raw(poligonos=[{"capa": "ARQ", "pts": _caja(20, 0, 26, 5)}])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    ext = [z for z in r["zonas"] if z.get("exterior")]
    assert len(ext) == 1 and ext[0]["candidato"] is True and ext[0]["x"] > 15 and r["excluidas_exterior"] == []


def test_un_mueble_de_afuera_sin_contorno_no_forma_zona_y_uno_de_adentro_si():
    cama = lambda x: {"n": "cama king", "capa": "MOB", "x0": x, "y0": 2, "x1": x + 2.0, "y1": 4.2}
    r = zonas_motor.construir_zonas(_raw(bloques=[cama(40)]), VOCAB)         # a 40 m de la casa, sin ningun contorno
    assert not any(z["x"] > 15 for z in r["zonas"]) and any("sin delimitar" in e["motivo"] for e in r["excluidas_exterior"])
    r2 = zonas_motor.construir_zonas(_raw(bloques=[cama(2)]), VOCAB)
    assert r2["excluidas_exterior"] == []


def test_un_espacio_con_nombre_de_interior_nunca_se_excluye_aunque_el_casco_sea_parcial():
    """Caso real: el casco sale solo de los muros de doble linea y dejaba fuera alcobas con nombre (sin contorno medido). Deben seguir siendo zonas."""
    raw = _raw(textos=[_txt("Alcoba 2", 40, 4), _txt("Cocina", 3, 4), _txt("Balcon", 45, 4)])        # Alcoba 2 y Balcon lejos del casco, sin contorno
    r = zonas_motor.construir_zonas(raw, VOCAB)
    por = {z["nombre"]: z for z in r["zonas"]}
    assert "Alcoba 2" in por and "exterior" not in por["Alcoba 2"] and "Cocina" in por     # la alcoba se queda, sin marcarla como exterior
    assert [e["nombre"] for e in r["excluidas_exterior"]] == ["Balcon"]                      # el balcon sin contorno si se excluye


def test_el_casco_se_amplia_con_los_nombres_interiores_y_no_marca_como_exterior_un_contorno_dentro_de_ellos():
    raw = _raw(textos=[_txt("Sala", 3, 4), _txt("Comedor", 30, 4)], poligonos=[{"capa": "ARQ", "pts": _caja(28, 2, 32, 6)}])   # contorno del comedor, lejos de los muros dobles
    r = zonas_motor.construir_zonas(raw, VOCAB)
    por = {z["nombre"]: z for z in r["zonas"]}
    assert "exterior" not in por["Comedor"] and por["Comedor"]["area_m2"] == 16.0


def test_sin_casco_fiable_el_nombre_exterior_con_contorno_se_marca_y_sin_contorno_se_excluye():
    raw = {"unidad_m": 1.0, "textos": [_txt("Patio", 5, 5), _txt("Sala", 25, 5), _txt("Jardin", 50, 50)], "bloques": [], "muros": {"segmentos": [], "capas": []},
           "lineas": {"segmentos": [], "entidades_leidas": 0}, "definiciones": {},
           "poligonos": [{"capa": "ARQ", "pts": _caja(0, 0, 10, 8)}, {"capa": "ARQ", "pts": _caja(20, 0, 30, 8)}]}
    r = zonas_motor.construir_zonas(raw, VOCAB)
    por_nombre = {z["nombre"]: z for z in r["zonas"]}
    assert por_nombre["Patio"]["exterior"] is True and "exterior" not in por_nombre["Sala"]
    assert [e["nombre"] for e in r["excluidas_exterior"]] == ["Jardin"]


def test_plano_con_nombres_no_subdivide_y_sin_nombres_si(monkeypatch):
    """El equipo dice si el plano trae nombres: con nombres las zonas no se parten en subzonas; sin nombres si (espacio grande con mobiliario de dos tipos)."""
    llamadas = []
    monkeypatch.setattr(zonas_motor, "_subdividir_por_mobiliario", lambda *a, **k: llamadas.append(1) or 0)
    zonas_motor.construir_zonas(_raw(), VOCAB, {"con_nombres": True})
    assert llamadas == []
    zonas_motor.construir_zonas(_raw(), VOCAB, {"con_nombres": False})
    zonas_motor.construir_zonas(_raw(), VOCAB, None)
    assert len(llamadas) == 2


def test_el_tipo_de_plano_se_guarda_en_el_perfil_del_plano(monkeypatch, tmp_path):
    import server
    from types import SimpleNamespace
    monkeypatch.setattr(server.acad, "estado", lambda **k: {"ok": True, "dibujo_activo": "Casa X.dwg", "objetos_en_modelo": 10, "objetos_propios": 0})
    monkeypatch.setattr(server.acad, "plano_crudo", lambda **k: {"ok": False, "error": "prueba"})
    server._zonas_del_plano(False, None, True)
    assert zonas_motor.cargar_perfil(server.CARPETA_PERFILES, "Casa X.dwg", compartidos=tmp_path / "x")["con_nombres"] is True
    server._zonas_del_plano(False, None, None)                       # sin decir nada: se conserva lo dicho antes
    assert zonas_motor.cargar_perfil(server.CARPETA_PERFILES, "Casa X.dwg", compartidos=tmp_path / "x")["con_nombres"] is True
    server._zonas_del_plano(False, None, False)
    assert zonas_motor.cargar_perfil(server.CARPETA_PERFILES, "Casa X.dwg", compartidos=tmp_path / "x")["con_nombres"] is False


def test_consultar_zona_da_el_contorno_por_nombre_o_por_numero_y_avisa_si_no_lo_tiene(monkeypatch):
    """Claude debe saber DONDE estan las divisiones de una zona sin que se dibuje nada en el plano; el escaneo normal no trae el contorno (es largo)."""
    import server
    zonas = [{"n": 1, "nombre": "Sala", "tipo_espacio": "sala", "contorno": [[0, 0], [6, 0], [6, 4], [0, 4]], "medidas": {"area_m2": 24.0}},
             {"n": 2, "nombre": "Cocina", "tipo_espacio": "cocina"}]                       # rotulo sin contorno
    monkeypatch.setattr(server, "_zonas_del_plano", lambda *a, **k: {"ok": True, "zonas": zonas, "unidad_m": 1.0})
    r = server.consultar_zona("zona 1")
    assert r["total"] == 1 and r["zonas"][0]["contorno"][2] == [6, 4] and r["zonas"][0]["rectangulo_util"] == {"x0": 0.0, "y0": 0.0, "x1": 6.0, "y1": 4.0}
    assert server.consultar_zona("Recinto 1")["zonas"][0]["nombre"] == "Sala"
    c = server.consultar_zona("cocina")["zonas"][0]
    assert "contorno" not in c and "no se pudo cerrar su contorno" in c["sin_contorno"]
    assert server.consultar_zona("zona 9")["error"] == "zona_no_encontrada"
