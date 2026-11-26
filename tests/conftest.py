import pytest


@pytest.fixture(autouse=True)
def _diario_de_operaciones_aislado(monkeypatch, tmp_path):
    """Ninguna prueba escribe el diario de operaciones real del usuario."""
    import server
    monkeypatch.setattr(server, "RUTA_OPERACIONES", tmp_path / "operaciones_prueba")
