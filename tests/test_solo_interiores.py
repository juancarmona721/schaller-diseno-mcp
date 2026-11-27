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


def test_sin_casco_fiable_el_nombre_exterior_con_contorno_se_marca_y_sin_contorno_se_excluye():
    raw = {"unidad_m": 1.0, "textos": [_txt("Patio", 5, 5), _txt("Sala", 25, 5), _txt("Jardin", 50, 50)], "bloques": [], "muros": {"segmentos": [], "capas": []},
           "lineas": {"segmentos": [], "entidades_leidas": 0}, "definiciones": {},
           "poligonos": [{"capa": "ARQ", "pts": _caja(0, 0, 10, 8)}, {"capa": "ARQ", "pts": _caja(20, 0, 30, 8)}]}
    r = zonas_motor.construir_zonas(raw, VOCAB)
    por_nombre = {z["nombre"]: z for z in r["zonas"]}
    assert por_nombre["Patio"]["exterior"] is True and "exterior" not in por_nombre["Sala"]
    assert [e["nombre"] for e in r["excluidas_exterior"]] == ["Jardin"]
