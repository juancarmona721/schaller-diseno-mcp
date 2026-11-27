"""Perfiles compartidos: lo aprendido de un plano viaja con el repositorio y un PC recien instalado lo recibe; lo local manda encima."""
import json
from pathlib import Path

import zonas_motor

REPO = Path(zonas_motor.__file__).resolve().parent


def _guardar(carpeta: Path, nombre: str, datos: dict):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.json").write_text(json.dumps(datos), encoding="utf-8")


def test_pc_recien_instalado_recibe_el_perfil_compartido(tmp_path):
    comp, local = tmp_path / "comp", tmp_path / "local"          # local no existe: PC sin historial
    _guardar(comp, "plano_a", {"roles_bloques": {"Gruppo-1": "sofa"}, "ignorar_bloques": ["elevation"], "tipologia": "vivienda"})
    p = zonas_motor.cargar_perfil(local, "Plano A.dwg", compartidos=comp)
    assert p["roles_bloques"] == {"Gruppo-1": "sofa"} and p["ignorar_bloques"] == ["elevation"] and p["tipologia"] == "vivienda"
    assert p["capas_muros"] == [] and p["zonas_manuales"] == []     # los campos que el archivo no trae quedan con su valor base


def test_lo_local_manda_y_se_suma_a_lo_compartido(tmp_path):
    comp, local = tmp_path / "comp", tmp_path / "local"
    _guardar(comp, "plano_a", {"roles_bloques": {"G1": "sofa", "G2": "cama"}, "ignorar_bloques": ["a"], "tipologia": "vivienda"})
    _guardar(local, "plano_a", {"roles_bloques": {"G2": "mesa_comedor", "G3": "isla"}, "ignorar_bloques": ["a", "b"], "tipologia": None})
    p = zonas_motor.cargar_perfil(local, "plano_a", compartidos=comp)
    assert p["roles_bloques"] == {"G1": "sofa", "G2": "mesa_comedor", "G3": "isla"}      # el local cambia G2 y agrega G3; G1 se conserva
    assert p["ignorar_bloques"] == ["a", "b"]                                              # unidas, sin repetir
    assert p["tipologia"] == "vivienda"                                                    # un valor vacio local no borra el compartido


def test_sin_ningun_perfil_queda_vacio_y_un_archivo_roto_no_rompe(tmp_path):
    assert zonas_motor.cargar_perfil(tmp_path / "x", "nuevo", compartidos=tmp_path / "y") == zonas_motor.perfil_vacio()
    comp = tmp_path / "comp"
    comp.mkdir()
    (comp / "roto.json").write_text("{no es json", encoding="utf-8")
    assert zonas_motor.cargar_perfil(tmp_path / "x", "roto", compartidos=comp) == zonas_motor.perfil_vacio()


def test_los_perfiles_compartidos_del_repositorio_son_validos():
    carpeta = REPO / "perfiles_compartidos"
    archivos = sorted(carpeta.glob("*.json"))
    assert archivos, "debe haber al menos un perfil compartido"
    for a in archivos:
        d = json.loads(a.read_text(encoding="utf-8"))
        assert isinstance(d, dict) and a.stem == zonas_motor.slug_proyecto(a.stem)       # el nombre del archivo es el identificador del plano
        assert isinstance(d.get("roles_bloques", {}), dict) and isinstance(d.get("ignorar_bloques", []), list)
        assert not any("confirmacion" in k.lower() or "token" in k.lower() or "password" in k.lower() for k in d)   # nada sensible viaja en el repositorio
