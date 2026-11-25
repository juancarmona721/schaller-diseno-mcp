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



# ------------------------------------------------------------------------------------------ donde escribir (clasica vs MSIX)
def _entorno(monkeypatch, tmp_path, clasica=False, paquete=False, roaming_del_paquete=False):
    appdata, local = tmp_path / "AppData" / "Roaming", tmp_path / "AppData" / "Local"
    appdata.mkdir(parents=True)
    local.mkdir(parents=True)
    if clasica:
        (appdata / "Claude").mkdir()
    pkg = local / "Packages" / "Claude_abc123"
    if paquete:
        pkg.mkdir(parents=True)
        if roaming_del_paquete:
            (pkg / "LocalCache" / "Roaming" / "Claude").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return appdata, pkg


def test_msix_recien_instalado_escribe_en_la_carpeta_del_paquete_aunque_no_exista(monkeypatch, tmp_path):
    # Caso real: Claude Desktop (MSIX) acaba de instalarse y NUNCA se ha abierto: aun no existe ni Claude-Data ni LocalCache\Roaming\Claude.
    # Escribir en %APPDATA% no sirve. Se anticipa Claude-Data\claude_<sufijo del paquete> (lo que la app leera al abrirse) y el del paquete.
    appdata, pkg = _entorno(monkeypatch, tmp_path, paquete=True)
    datos = tmp_path / "AppData" / "Local" / "Claude-Data" / "claude_abc123" / "claude_desktop_config.json"
    paquete = pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert rc.rutas_config() == [datos, paquete]
    assert rc.main(["py.exe", "server.py"]) == 0                       # y la escritura real crea las carpetas
    for ruta in (datos, paquete):
        assert json.loads(ruta.read_text(encoding="utf-8"))["mcpServers"]["schaller-diseno"]["command"] == "py.exe"
    assert not (appdata / "Claude").exists()


def test_instalacion_clasica_escribe_en_appdata(monkeypatch, tmp_path):
    appdata, _ = _entorno(monkeypatch, tmp_path, clasica=True)
    assert rc.rutas_config() == [appdata / "Claude" / "claude_desktop_config.json"]


def test_clasica_y_msix_a_la_vez_escribe_en_las_dos(monkeypatch, tmp_path):
    appdata, pkg = _entorno(monkeypatch, tmp_path, clasica=True, paquete=True, roaming_del_paquete=True)
    assert set(rc.rutas_config()) == {appdata / "Claude" / "claude_desktop_config.json",
                                      tmp_path / "AppData" / "Local" / "Claude-Data" / "claude_abc123" / "claude_desktop_config.json",
                                      pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"}


def test_sin_claude_instalado_cae_a_appdata(monkeypatch, tmp_path):
    appdata, _ = _entorno(monkeypatch, tmp_path)
    assert rc.rutas_config() == [appdata / "Claude" / "claude_desktop_config.json"]



def test_msix_reciente_escribe_en_claude_data_y_conserva_las_preferencias_de_la_app(monkeypatch, tmp_path):
    # Caso real: Claude Desktop (2026) lee %LOCALAPPDATA%\Claude-Data\<id>\claude_desktop_config.json y guarda ahi sus preferencias.
    appdata, pkg = _entorno(monkeypatch, tmp_path, paquete=True)
    datos = tmp_path / "AppData" / "Local" / "Claude-Data" / "claude_abc123"
    datos.mkdir(parents=True)
    real = datos / "claude_desktop_config.json"
    real.write_text(json.dumps({"preferences": {"sidebarMode": "x", "anidado": {"a": [1, 2]}}, "coworkUserFilesPath": "C:\\Claude"}), encoding="utf-8")
    assert real in rc.rutas_config()
    assert rc.main(["py.exe", "server.py"]) == 0
    d = json.loads(real.read_text(encoding="utf-8"))
    assert d["mcpServers"]["schaller-diseno"]["command"] == "py.exe"
    assert d["preferences"] == {"sidebarMode": "x", "anidado": {"a": [1, 2]}} and d["coworkUserFilesPath"] == "C:\\Claude"
    assert (datos / "claude_desktop_config.json.bak").is_file()               # copia de seguridad antes de tocarlo


def test_si_claude_data_ya_existe_no_se_duplica_la_ruta(monkeypatch, tmp_path):
    _, pkg = _entorno(monkeypatch, tmp_path, paquete=True)
    (tmp_path / "AppData" / "Local" / "Claude-Data" / "claude_abc123").mkdir(parents=True)
    rutas = rc.rutas_config()
    assert len(rutas) == len(set(rutas)) == 2
