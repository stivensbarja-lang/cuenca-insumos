"""Integración con el caso de estudio real: la cuenca de la quebrada Huacará.

Compara la delineación de esta herramienta con una hecha en QGIS con GRASS
(r.fill.dir + r.watershed + r.water.outlet) sobre el mismo DEM.
"""
import geopandas as gpd
import numpy as np
import pytest

from cuenca_insumos.delineacion import delinear
from cuenca_insumos.procesamiento import leer_dem

pytestmark = pytest.mark.huacara
SALIDA = (459329.724, 8769071.156)     # la coordenada que se usó en r.water.outlet


def test_delineacion_coincide_con_grass(sig_huacara):
    z, validos, tr = leer_dem(sig_huacara / "00_DEM" / "recorte.tif")
    ref = gpd.read_file(sig_huacara / "limites Huacará.shp").geometry.iloc[0]
    cab = gpd.read_file(sig_huacara / "04_Resultados" / "Cauce_principal_Huacara.shp").geometry.iloc[0].coords[0]

    r = delinear(z, validos, tr, SALIDA, cab)

    iou = r.poligono.intersection(ref).area / r.poligono.union(ref).area
    assert iou > 0.95
    assert r.area_km2 == pytest.approx(ref.area / 1e6, rel=0.02)        # GRASS: 6.8664 km²
    assert r.desplazamiento_m < 22                     # misma celda: a lo sumo media diagonal (21 m)
    assert r.cabecera_drena is True
    assert not r.truncada
    assert r.cota_salida == pytest.approx(894.2, abs=0.5)


def test_dem_recortado_con_ceros_se_distingue_del_correcto(sig_huacara):
    """El error del primer cálculo: recorte-huacará.tif tiene 0 (no NoData) fuera de la
    cuenca. La herramienta siempre escribe −9999; este test documenta la diferencia."""
    import rasterio
    with rasterio.open(sig_huacara / "recorte-huacará.tif") as ds:
        a = ds.read(1)
        assert ds.nodata is None
    assert (a == 0).sum() > 10_000                                       # 10 622 celdas con 0 m
    assert np.nanmin(np.where(a > 0, a, np.nan)) > 890                   # la cota real mínima es 894 m
