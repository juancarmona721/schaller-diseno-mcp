"""Extension de Claude Desktop (.mcpb): manifest valido, paquete bien formado y lanzador que arranca el servidor de verdad."""
import asyncio
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

import construir_mcpb as cm

RAIZ = Path(__file__).resolve().parent.parent
MANIFEST = RAIZ / "extension" / "manifest.json"


def test_manifest_cumple_la_especificacion():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert cm.validar(m) == []
    assert m["server"]["type"] == "node" and m["compatibility"]["platforms"] == ["win32"]
    assert m["name"] == "schaller-diseno" and "ubicar_en_anfitrion" in {t["name"] for t in m["tools"]}


def test_validador_detecta_manifests_rotos():
    base = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert any("falta 'author'" in e for e in cm.validar({k: v for k, v in base.items() if k != "author"}))
    assert any("semver" in e for e in cm.validar({**base, "version": "uno"}))
    assert any("platforms" in e for e in cm.validar({**base, "compatibility": {"platforms": ["plan9"]}}))
    assert any("mcp_config" in e for e in cm.validar({**base, "server": {"type": "node", "entry_point": "server/index.js"}}))


def test_el_paquete_versionado_esta_al_dia_y_bien_formado():
    paquete = RAIZ / "extension" / "schaller-diseno.mcpb"
    assert paquete.is_file(), "ejecuta construir_mcpb.py y versiona el resultado"
    with zipfile.ZipFile(paquete) as z:
        assert z.testzip() is None and set(z.namelist()) == {"manifest.json", "server/index.js"}      # manifest en la raiz del zip
        assert z.read("manifest.json") == MANIFEST.read_bytes()
        assert z.read("server/index.js") == (RAIZ / "extension" / "server" / "index.js").read_bytes()


def test_el_lanzador_retransmite_por_tuberias_y_no_hereda_stdio():
    # Dentro de Claude Desktop (Node de Electron) stdin no es heredable: con stdio:"inherit" Python terminaba en silencio.
    js = (RAIZ / "extension" / "server" / "index.js").read_text(encoding="utf-8")
    codigo = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert 'stdio: "inherit"' not in codigo and "stdio:\"inherit\"" not in codigo
    assert 'stdio: ["pipe", "pipe", "pipe"]' in codigo
    assert "process.stdin.pipe(hijo.stdin)" in codigo and "hijo.stdout.pipe(process.stdout)" in codigo
    assert "console.log" not in codigo          # stdout es del protocolo MCP


@pytest.mark.skipif(shutil.which("node") is None, reason="necesita Node.js (Claude Desktop trae el suyo)")
def test_el_lanzador_arranca_el_servidor_real_por_stdio():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def correr():
        entorno = {**os.environ, "SCHALLER_DIR": str(RAIZ)}
        params = StdioServerParameters(command="node", args=[str(RAIZ / "extension" / "server" / "index.js")], env=entorno)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await asyncio.wait_for(s.initialize(), 40)
                return {t.name for t in (await s.list_tools()).tools}, (await s.call_tool("ping", {})).content[0].text

    if not (RAIZ / ".venv" / "Scripts" / "python.exe").is_file():
        pytest.skip("necesita la instalacion con .venv en la raiz del proyecto")
    nombres, ping = asyncio.run(correr())
    assert ping == "ok" and {"ubicar_en_anfitrion", "escanear_zonas", "quitar_colocaciones", "estado_autocad"} <= nombres


@pytest.mark.skipif(shutil.which("node") is None, reason="necesita Node.js")
def test_sin_instalacion_el_lanzador_falla_con_mensaje_claro(tmp_path):
    import subprocess
    r = subprocess.run(["node", str(RAIZ / "extension" / "server" / "index.js")], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "SCHALLER_DIR": str(tmp_path / "no_existe")})
    assert r.returncode == 1 and "instalar.ps1" in r.stderr and r.stdout == ""
