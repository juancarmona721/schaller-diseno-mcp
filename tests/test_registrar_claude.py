import json

import pytest

import registrar_claude as rc


def test_crea_config_nueva(tmp_path):
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    assert rc.registrar(cfg, "py.exe", "server.py") == "creado"
    assert json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["schaller-diseno"] == {"command": "py.exe", "args": ["server.py"]}


def test_conserva_otros_servidores_y_ajustes(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"mcpServers": {"otro": {"command": "x"}}, "preferences": {"a": 1}}), encoding="utf-8")
    rc.registrar(cfg, "py.exe", "server.py")
    d = json.loads(cfg.read_text(encoding="utf-8"))
    assert d["mcpServers"]["otro"] == {"command": "x"} and d["preferences"] == {"a": 1} and "schaller-diseno" in d["mcpServers"]
    assert (tmp_path / "c.json.bak").is_file()


def test_reinstalar_actualiza_sin_duplicar(tmp_path):
    cfg = tmp_path / "c.json"
    rc.registrar(cfg, "a.exe", "s.py")
    assert rc.registrar(cfg, "b.exe", "s.py") == "actualizado"
    assert json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["schaller-diseno"]["command"] == "b.exe"


def test_json_danado_no_se_toca(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text("{roto", encoding="utf-8")
    with pytest.raises(ValueError):
        rc.registrar(cfg, "py.exe", "server.py")
    assert cfg.read_text(encoding="utf-8") == "{roto"


def test_acepta_bom_utf8(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": {}}).encode())
    assert rc.registrar(cfg, "py.exe", "server.py") == "creado"
