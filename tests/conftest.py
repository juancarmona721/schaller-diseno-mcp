import pytest


@pytest.fixture(autouse=True)
def _diario_de_operaciones_aislado(monkeypatch, tmp_path):
    """Ninguna prueba escribe el diario de operaciones real del usuario."""
    import server
    monkeypatch.setattr(server, "RUTA_OPERACIONES", tmp_path / "operaciones_prueba")


@pytest.fixture(autouse=True)
def _datos_del_usuario_aislados(monkeypatch, tmp_path):
    """Ninguna prueba toca los datos reales del usuario (ajustes, registro de uso, depuracion, cache, perfiles): antes, las pruebas dejaban archivos de lectura
    de depuracion con nombres de planos ficticios en su carpeta y contaban perfiles de prueba."""
    import server
    raiz = tmp_path / "usuario"
    monkeypatch.setattr(server, "_RAIZ_USUARIO", raiz)
    monkeypatch.setattr(server, "RUTA_AJUSTES", raiz / "ajustes.json")
    monkeypatch.setattr(server, "RUTA_USO", raiz / "logs" / "uso.jsonl")
    monkeypatch.setattr(server, "RUTA_CONEXION", raiz / "estado_conexion.json")
    monkeypatch.setattr(server, "CARPETA_CACHE", tmp_path / "cache_prueba")
    monkeypatch.setattr(server, "CARPETA_PERFILES", raiz / "perfiles")


@pytest.fixture(autouse=True)
def _perfiles_compartidos_aislados(monkeypatch, tmp_path):
    """Las pruebas no leen los perfiles compartidos reales del repositorio (se prueban aparte, con carpetas propias)."""
    import zonas_motor
    monkeypatch.setattr(zonas_motor, "CARPETA_COMPARTIDOS", tmp_path / "sin_compartidos")
