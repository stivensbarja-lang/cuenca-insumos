"""Grillas de tiles regulares en grados y selección por intersección con el AOI.

Regla central: un tile se descarga solo si **intersecta el polígono** del AOI.
Los tiles que caen dentro del rectángulo envolvente pero no tocan el polígono
(típico en corredores diagonales) se descartan y se informa por qué.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

__all__ = ["Tile", "SeleccionTiles", "candidatos", "seleccionar", "etiqueta_latlon"]

_TOL_AREA = 1e-9  # grados²: intersecciones menores se consideran "solo toca el borde"


def etiqueta_latlon(lat0: int, lon0: int, ancho_lat: int = 2, ancho_lon: int = 3) -> tuple[str, str]:
    ns = f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):0{ancho_lat}d}"
    ew = f"{'E' if lon0 >= 0 else 'W'}{abs(lon0):0{ancho_lon}d}"
    return ns, ew


@dataclass(frozen=True, order=True)
class Tile:
    """Celda de una grilla regular, identificada por su esquina suroeste."""
    lat0: int
    lon0: int
    tam: int = 1

    @property
    def limites(self) -> tuple[float, float, float, float]:
        return (self.lon0, self.lat0, self.lon0 + self.tam, self.lat0 + self.tam)

    @property
    def geom(self) -> Polygon:
        return box(*self.limites)

    @property
    def codigo(self) -> str:
        ns, ew = etiqueta_latlon(self.lat0, self.lon0)
        return ns + ew


@dataclass
class SeleccionTiles:
    encontrados: list[Tile]
    necesarios: list[Tile]
    descartados: list[tuple[Tile, str]]
    fraccion_aoi: dict[Tile, float] = field(default_factory=dict)
    cobertura_pct: float = 0.0
    sin_datos_pct: float = 0.0

    def resumen(self) -> str:
        l = [f"DEM encontrados: {len(self.encontrados)}",
             f"DEM necesarios:  {len(self.necesarios)}",
             f"DEM descartados: {len(self.descartados)}"]
        for t in self.necesarios:
            l.append(f"   + {t.codigo}: cubre el {100 * self.fraccion_aoi.get(t, 0):.1f} % del área de análisis")
        for t, motivo in self.descartados:
            l.append(f"   - {t.codigo}: {motivo}")
        return "\n".join(l)


def candidatos(limites_lonlat: tuple[float, float, float, float], tam: int = 1) -> list[Tile]:
    """Todos los tiles de la grilla que tocan el rectángulo envolvente."""
    w, s, e, n = limites_lonlat
    lat_ini = math.floor(s / tam) * tam
    lon_ini = math.floor(w / tam) * tam
    # ceil exclusivo: un límite exactamente sobre una línea de la grilla no agrega tile
    lat_fin = math.ceil(n / tam) * tam
    lon_fin = math.ceil(e / tam) * tam
    out = []
    for lat in range(lat_ini, max(lat_fin, lat_ini + tam), tam):
        for lon in range(lon_ini, max(lon_fin, lon_ini + tam), tam):
            if -90 <= lat < 90:
                out.append(Tile(lat, ((lon + 180) % 360) - 180, tam))
    return sorted(set(out))


def seleccionar(aoi_lonlat: Polygon, tam: int = 1,
                existe: Callable[[Tile], bool] | None = None) -> SeleccionTiles:
    """Selecciona los tiles necesarios para cubrir el AOI.

    Parámetros
    ----------
    aoi_lonlat : polígono del AOI en EPSG:4326.
    existe : función que dice si un tile tiene datos en el catálogo
        (los tiles de océano no existen en Copernicus DEM).
    """
    enc = candidatos(aoi_lonlat.bounds, tam)
    area_aoi = aoi_lonlat.area
    nec, desc, frac = [], [], {}
    for t in enc:
        inter = aoi_lonlat.intersection(t.geom).area
        if inter <= _TOL_AREA:
            motivo = ("solo toca el borde del área de análisis" if aoi_lonlat.touches(t.geom)
                      else "está en el rectángulo envolvente pero fuera del área de análisis")
            desc.append((t, motivo))
            continue
        if existe is not None and not existe(t):
            desc.append((t, f"intersecta el área ({100 * inter / area_aoi:.1f} %) pero no existe en el "
                            "catálogo (océano o zona sin datos)"))
            continue
        nec.append(t)
        frac[t] = inter / area_aoi

    cubierto = unary_union([t.geom for t in nec]).intersection(aoi_lonlat).area if nec else 0.0
    sin_datos = sum(aoi_lonlat.intersection(t.geom).area for t, m in desc if "no existe" in m)
    return SeleccionTiles(enc, nec, desc, frac,
                          cobertura_pct=100 * cubierto / area_aoi if area_aoi else 0.0,
                          sin_datos_pct=100 * sin_datos / area_aoi if area_aoi else 0.0)


def union_limites(tiles: Iterable[Tile]) -> tuple[float, float, float, float]:
    g = unary_union([t.geom for t in tiles])
    return g.bounds
