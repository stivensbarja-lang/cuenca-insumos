import os
from pathlib import Path

import pytest

# Carpeta con el caso de estudio real (opcional): permite correr las pruebas de integración.
# Por defecto se busca junto a la carpeta del repositorio; en otra computadora no existe y
# esas pruebas se omiten.
SIG_HUACARA = Path(os.environ.get(
    "CUENCA_INSUMOS_HUACARA",
    Path(__file__).resolve().parents[2] / "SIG - Río Huacará"))


@pytest.fixture
def sig_huacara() -> Path:
    if not (SIG_HUACARA / "00_DEM" / "recorte.tif").exists():
        pytest.skip("datos del caso Huacará no disponibles (define CUENCA_INSUMOS_HUACARA)")
    return SIG_HUACARA
