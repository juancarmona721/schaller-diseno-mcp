import json

import pytest

import schaller_cli as cli


def test_quitar_sin_ejecutar_es_ensayo(monkeypatch, capsys):
    llamadas = []
    import server
    monkeypatch.setattr(server, "quitar_colocaciones", lambda ejecutar, confirmacion: (llamadas.append((ejecutar, confirmacion)) or {"ok": True, "a_borrar": 35}))
    assert cli.main(["quitar"]) == 0
    assert llamadas == [(False, None)] and json.loads(capsys.readouterr().out)["a_borrar"] == 35


def test_quitar_con_codigo_ejecuta(monkeypatch):
    import server
    llamadas = []
    monkeypatch.setattr(server, "quitar_colocaciones", lambda ejecutar, confirmacion: (llamadas.append((ejecutar, confirmacion)) or {"ok": True, "borrados": 35}))
    assert cli.main(["quitar", "--ejecutar", "--codigo", "ab12"]) == 0
    assert llamadas == [(True, "ab12")]


def test_codigo_incorrecto_devuelve_error_y_explica(monkeypatch, capsys):
    import server
    monkeypatch.setattr(server, "quitar_colocaciones", lambda ejecutar, confirmacion: {"ok": False, "error": "dibujo_grande_requiere_confirmacion"})
    assert cli.main(["quitar", "--ejecutar"]) == 1
    assert "linea de comandos de AutoCAD" in capsys.readouterr().err


def test_comando_desconocido_o_ausente():
    with pytest.raises(SystemExit):
        cli.main([])
    with pytest.raises(SystemExit):
        cli.main(["borrar_todo"])
