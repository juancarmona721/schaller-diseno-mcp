"""Solo interiores: terrazas, patios, jardines y todo lo que cae fuera de la casa no se convierte en zona (y se informa como excluido)."""
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


def test_una_terraza_rotulada_dentro_de_un_poligono_no_es_zona_y_su_contorno_no_vuelve_como_recinto():
    raw = _raw(textos=[_txt("TERRAZA", 21, 4), _txt("SALA", 3, 4)], poligonos=[{"capa": "ARQ", "pts": _caja(18, 2, 24, 6)}])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert not any("terraza" in n.lower() for n in _nombres(r))
    assert [e["nombre"] for e in r["excluidas_exterior"]].count("TERRAZA") == 1
    assert not any(18 <= z["x"] <= 24 for z in r["zonas"])                      # ni la terraza ni su contorno quedaron como zona


def test_una_terraza_con_rotulo_pegada_a_la_casa_tambien_se_excluye_aunque_este_dentro_del_casco():
    raw = _raw(textos=[_txt("Terraza", 3, 4), _txt("Sala", 10, 4)])             # el texto cae dentro de la casa: se excluye por el NOMBRE
    r = zonas_motor.construir_zonas(raw, VOCAB)
    ex = r["excluidas_exterior"]
    assert len(ex) == 1 and "nombre" in ex[0]["motivo"]
    assert "Sala" in _nombres(r)


def test_un_poligono_sin_rotulo_fuera_de_la_casa_no_es_recinto_candidato():
    raw = _raw(poligonos=[{"capa": "ARQ", "pts": _caja(20, 0, 26, 5)}])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert not any(z["x"] > 15 for z in r["zonas"])
    assert any("fuera de la casa" in e["motivo"] for e in r["excluidas_exterior"])


def test_un_nombre_de_interior_cuyo_poligono_esta_fuera_de_la_casa_se_excluye():
    raw = _raw(textos=[_txt("Sala", 22, 3)], poligonos=[{"capa": "ARQ", "pts": _caja(20, 0, 26, 5)}])
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert "Sala" not in _nombres(r) and r["excluidas_exterior"][0]["nombre"] == "Sala"


def test_un_mueble_de_afuera_no_forma_una_zona_interior_y_uno_de_adentro_si():
    cama = lambda x: {"n": "cama king", "capa": "MOB", "x0": x, "y0": 2, "x1": x + 2.0, "y1": 4.2}
    r = zonas_motor.construir_zonas(_raw(bloques=[cama(40)]), VOCAB)         # a 40 m de la casa
    assert not any(z["x"] > 15 for z in r["zonas"]) and any(e["motivo"].startswith("fuera") for e in r["excluidas_exterior"])
    r2 = zonas_motor.construir_zonas(_raw(bloques=[cama(2)]), VOCAB)
    assert r2["excluidas_exterior"] == []


def test_sin_casco_fiable_solo_se_filtra_por_nombre():
    raw = {"unidad_m": 1.0, "textos": [_txt("Patio", 5, 5), _txt("Sala", 25, 5)], "bloques": [], "muros": {"segmentos": [], "capas": []},
           "lineas": {"segmentos": [], "entidades_leidas": 0}, "definiciones": {},
           "poligonos": [{"capa": "ARQ", "pts": _caja(0, 0, 10, 8)}, {"capa": "ARQ", "pts": _caja(20, 0, 30, 8)}]}
    r = zonas_motor.construir_zonas(raw, VOCAB)
    assert "Sala" in _nombres(r) and [e["nombre"] for e in r["excluidas_exterior"]] == ["Patio"]
