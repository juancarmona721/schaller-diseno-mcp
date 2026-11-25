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


def test_informe_diagnostico_todo_bien_y_cada_falta():
    ok = cli.informe_diagnostico({"ok": True, "dibujo_activo": "plano.dwg", "biblioteca_abierta": True, "biblioteca_corregida_abierta": True})
    assert ok[0].startswith("[OK] AutoCAD responde") and ok[1].startswith("[OK] bloques_schaller_corregido")
    antigua = cli.informe_diagnostico({"ok": True, "dibujo_activo": "plano.dwg", "biblioteca_abierta": True, "biblioteca_corregida_abierta": False})
    assert antigua[1].startswith("[ ] Tienes abierta la biblioteca ANTIGUA")
    sin_lib = cli.informe_diagnostico({"ok": True, "dibujo_activo": "plano.dwg", "biblioteca_abierta": False, "biblioteca_corregida_abierta": False})
    assert sin_lib[1].startswith("[ ] Falta abrir bloques_schaller_corregido")
    cerrado = cli.informe_diagnostico({"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto"})
    assert len(cerrado) == 1 and "AutoCAD no esta abierto" in cerrado[0]
    assert cli.informe_diagnostico({"ok": False, "error": "raro", "detalle": "x"})[0].startswith("[X]")


def test_diagnostico_devuelve_codigo_segun_el_estado(monkeypatch, capsys):
    import server
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: {"ok": True, "dibujo_activo": "p.dwg", "biblioteca_abierta": True, "biblioteca_corregida_abierta": True})
    assert cli.main(["diagnostico"]) == 0 and "todo listo" in capsys.readouterr().out
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: {"ok": True, "dibujo_activo": "p.dwg", "biblioteca_abierta": True, "biblioteca_corregida_abierta": False})
    assert cli.main(["diagnostico"]) == 1          # solo la biblioteca antigua: aun no esta listo
    monkeypatch.setattr(server.acad, "diseno", lambda args, **kw: {"ok": True, "dibujo_activo": "p.dwg", "biblioteca_abierta": False, "biblioteca_corregida_abierta": False})
    assert cli.main(["diagnostico"]) == 1
