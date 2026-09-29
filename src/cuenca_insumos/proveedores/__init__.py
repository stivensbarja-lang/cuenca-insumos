"""Registro de proveedores de datos."""
from __future__ import annotations

from .base import Plan, Proveedor, Recurso, Salida
from .copernicus_dem import CopernicusDEM
from .gadm import GADM
from .geonames import GeoNames
from .hydrosheds import HydroBASINS, HydroRIVERS
from .osm import OSMOverpass
from .sentinel2 import Sentinel2
from .worldcover import WorldCover

__all__ = ["Plan", "Proveedor", "Recurso", "Salida", "CopernicusDEM", "TEMATICOS", "tematicos_activos"]

# Orden = orden de ejecución y de presentación en el reporte.
TEMATICOS: dict[str, type[Proveedor]] = {
    "unidades": HydroBASINS,
    "rios": HydroRIVERS,
    "limites": GADM,
    "toponimia": GeoNames,
    "imagen": Sentinel2,
    "osm": OSMOverpass,
    "cobertura": WorldCover,
}


def tematicos_activos(incluir: set[str], excluir: set[str]) -> list[Proveedor]:
    desconocidos = (incluir | excluir) - set(TEMATICOS) - {"dem"}
    if desconocidos:
        raise ValueError(f"Insumos desconocidos: {', '.join(sorted(desconocidos))}. "
                         f"Disponibles: {', '.join(TEMATICOS)}")
    if "dem" in excluir:
        raise ValueError("El DEM no se puede excluir: todo el análisis de cuenca depende de él.")
    return [cls() for k, cls in TEMATICOS.items()
            if (cls.por_defecto or k in incluir) and k not in excluir]
