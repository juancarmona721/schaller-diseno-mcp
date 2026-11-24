import json

import pytest

import referencias
import server


@pytest.fixture
def ref_json(tmp_path, monkeypatch):
    ruta = tmp_path / "referencias_finales.json"
    monkeypatch.setattr(server, "REF_JSON", ruta)
    return ruta


def test_instrucciones_del_servidor_incluyen_la_regla():
    ins = server.mcp.instructions
    assert "POR DEFINIR" in ins and "cotizacion" in ins.lower() and "pedir_referencias_finales" in ins


def test_pedir_lista_todo_pendiente_y_redacta_solicitud(ref_json):
    r = server.pedir_referencias_finales(["Mira R", "Ohm"])
    assert r["ok"] and r["sin_referencia"] == ["Mira R", "Ohm"] and r["con_referencia"] == []
    assert "cotizacion" in r["mensaje_para_el_usuario"] and "Mira R" in r["mensaje_para_el_usuario"]


def test_registrar_exige_confirmacion_y_no_guarda(ref_json):
    r = server.registrar_referencias([{"producto": "Mira R", "referencia": "ABC-1"}], "cotizacion v1")
    assert not r["ok"] and r["error"] == "falta_confirmacion" and not ref_json.exists()


def test_registrar_y_luego_ya_no_esta_pendiente(ref_json):
    r = server.registrar_referencias([{"producto": " mira  r ", "referencia": "ABC-1"}], "cotizacion v1", True)
    assert r["ok"] and r["guardadas"] == 1
    p = server.pedir_referencias_finales(["Mira R", "Ohm"])
    assert p["sin_referencia"] == ["Ohm"] and p["con_referencia"][0]["referencia"] == "ABC-1"
    assert json.loads(ref_json.read_text(encoding="utf-8"))["mira r"]["fuente"] == "cotizacion v1"


@pytest.mark.parametrize("ref", ["", "  ", "POR DEFINIR (cotizacion)"])
def test_rechaza_referencias_vacias_o_marcador(ref_json, ref):
    r = server.registrar_referencias([{"producto": "Ohm", "referencia": ref}], "x", True)
    assert not r["ok"] and r["error"] == "item_invalido" and not ref_json.exists()


def test_rechaza_sin_fuente(ref_json):
    r = server.registrar_referencias([{"producto": "Ohm", "referencia": "R1"}], " ", True)
    assert r["error"] == "falta_fuente"


def test_lote_invalido_no_guarda_nada(ref_json):
    r = server.registrar_referencias([{"producto": "A", "referencia": "R1"}, {"producto": "B", "referencia": ""}], "x", True)
    assert not r["ok"] and not ref_json.exists()
