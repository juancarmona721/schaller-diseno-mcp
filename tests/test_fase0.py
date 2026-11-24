import subprocess

import pytest

import acad
import server


def test_ping():
    assert server.ping() == "ok"


def test_config_tiene_timeout_10():
    assert float(server.CFG["autocad"]["timeout_s"]) <= 10


def test_timeout_devuelve_error_claro(monkeypatch):
    def colgado(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=k.get("timeout", 10))

    monkeypatch.setattr(acad.subprocess, "run", colgado)
    r = acad.estado(timeout_s=10)
    assert r["ok"] is False and r["error"] == "autocad_no_responde"
    assert "10" in r["detalle"]


def test_sonda_no_hereda_stdin_del_servidor(monkeypatch):
    """Regresion: heredar el stdin (canal MCP) colgaba la sonda hasta el timeout."""
    visto = {}

    class R:
        stdout, stderr = '{"ok": true}', ""

    def falso(*a, **k):
        visto.update(k)
        return R()

    monkeypatch.setattr(acad.subprocess, "run", falso)
    acad.estado()
    assert visto["stdin"] == acad.subprocess.DEVNULL


def test_salida_invalida(monkeypatch):
    class R:
        stdout, stderr = "basura", "traceback"

    monkeypatch.setattr(acad.subprocess, "run", lambda *a, **k: R())
    assert acad.estado()["error"] == "respuesta_invalida"


@pytest.mark.autocad
def test_estado_con_autocad_abierto():
    r = acad.estado()
    assert r["ok"] is True
    assert r["es_version_completa_con_com"] is True
