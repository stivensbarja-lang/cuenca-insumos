"""Estado compartido que el orquestador entrega a cada proveedor."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shapely.geometry import Polygon

from .aoi import AOI
from .config import CARPETAS, Parametros
from .descarga import Descargador

__all__ = ["Contexto"]


@dataclass
class Contexto:
    raiz: Path
    epsg: int
    aoi: AOI
    params: Parametros
    descargador: Descargador
    salida_xy: tuple[float, float]
    cuenca: Polygon | None = None
    log: Callable[[str], None] = print
    extra: dict = field(default_factory=dict)

    @property
    def aoi_ll(self) -> Polygon:
        return self.aoi.lonlat()

    def carpeta(self, clave: str) -> Path:
        p = self.raiz / CARPETAS[clave]
        p.mkdir(parents=True, exist_ok=True)
        return p
