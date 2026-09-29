"""Área de interés (AOI): preliminar (antes de tener el DEM) y final (a partir de la cuenca delineada).

Todas las geometrías se construyen en el sistema proyectado del usuario (metros) y
solo se transforman a EPSG:4326 para cruzarlas con las grillas de tiles.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import transform as shp_transform

from .config import Parametros
from .coords import Punto, transformador

__all__ = ["AOI", "aoi_preliminar", "aoi_final", "a_4326", "longitud_cuenca_hack"]


@dataclass(frozen=True)
class AOI:
    geom: Polygon
    epsg: int
    metodo: str
    descripcion: str

    @property
    def area_km2(self) -> float:
        return self.geom.area / 1e6

    def lonlat(self) -> Polygon:
        return a_4326(self.geom, self.epsg)

    def ampliar(self, factor: float) -> "AOI":
        """Agranda el AOI escalando su 'radio' equivalente en torno al centroide."""
        r_eq = math.sqrt(self.geom.area / math.pi)
        extra = r_eq * (factor - 1.0)
        g = self.geom.buffer(extra, join_style="round")
        return replace(self, geom=g, metodo=self.metodo + "+ampliado",
                       descripcion=self.descripcion + f"; ampliado {extra / 1000:.1f} km")


def a_4326(geom, epsg: int):
    if epsg == 4326:
        return geom
    t = transformador(epsg, 4326)
    # densificar antes de reproyectar: los bordes rectos en UTM no lo son en grados
    g = geom.segmentize(250.0) if hasattr(geom, "segmentize") else geom
    return shp_transform(t.transform, g)


def longitud_cuenca_hack(area_km2: float) -> float:
    """Longitud esperada de una cuenca a partir de su área (km).

    Montgomery y Dietrich (1992): L ≈ 1.78 · A^0.49, ajuste global de la ley de Hack.
    """
    return 1.78 * area_km2 ** 0.49


def aoi_preliminar(salida: Punto, cabecera: Punto | None = None,
                   area_estimada_km2: float | None = None,
                   params: Parametros | None = None) -> AOI:
    """AOI previo a la descarga del DEM.

    * Con cabecera: corredor alrededor del segmento cabecera-salida, con semiancho
      ``max(buffer_minimo, k · L)``. Los extremos redondeados cubren también la
      divisoria que queda más allá de la cabecera.
    * Solo salida y área estimada: círculo de radio ``factor · L_Hack(A)``.
    * Solo salida: círculo de radio fijo (``radio_sin_cabecera_m``); la
      expansión iterativa tras la delineación corrige si queda corto.
    """
    p = params or Parametros()
    s = Point(salida.x, salida.y)
    if cabecera is not None:
        seg = LineString([(salida.x, salida.y), (cabecera.x, cabecera.y)])
        L = seg.length
        w = max(p.buffer_minimo_m, p.k_corredor * L)
        detalle = (f"L = {L / 1000:.2f} km, margen = {w / 1000:.2f} km "
                   f"(máx. de {p.buffer_minimo_m / 1000:.1f} km y {p.k_corredor:.2f}·L)")
        if p.forma_aoi == "rectangulo":
            x0, y0, x1, y1 = seg.bounds
            return AOI(box(x0 - w, y0 - w, x1 + w, y1 + w), salida.epsg, "rectangulo",
                       f"rectángulo de cabecera y salida + margen: {detalle}")
        return AOI(seg.buffer(w, quad_segs=16), salida.epsg, "corredor",
                   f"corredor cabecera-salida: {detalle}")
    if area_estimada_km2:
        r = p.factor_radio_area * longitud_cuenca_hack(area_estimada_km2) * 1000.0
        r = max(r, p.buffer_minimo_m)
        return AOI(s.buffer(r, quad_segs=32), salida.epsg, "radio_hack",
                   f"círculo desde la salida, r = {r / 1000:.2f} km "
                   f"({p.factor_radio_area}·1.78·A^0.49 con A = {area_estimada_km2:g} km²)")
    r = p.radio_sin_cabecera_m
    return AOI(s.buffer(r, quad_segs=32), salida.epsg, "radio_fijo",
               f"círculo desde la salida, r = {r / 1000:.1f} km (sin cabecera ni área estimada)")


def aoi_final(cuenca: Polygon, epsg: int, params: Parametros | None = None) -> AOI:
    """AOI definitivo para las capas temáticas: la cuenca delineada más un margen."""
    p = params or Parametros()
    minx, miny, maxx, maxy = cuenca.bounds
    largo = math.hypot(maxx - minx, maxy - miny)
    m = max(p.margen_final_min_m, p.margen_final_frac * largo)
    return AOI(cuenca.buffer(m, quad_segs=16), epsg, "cuenca+margen",
               f"cuenca delineada + margen de {m / 1000:.2f} km")


def aoi_rectangulo(salida: Punto, cabecera: Punto, margen_m: float = 0.0) -> AOI:
    """Opción B/C de la evaluación: rectángulo envolvente de los dos puntos (+ margen)."""
    g = box(min(salida.x, cabecera.x), min(salida.y, cabecera.y),
            max(salida.x, cabecera.x), max(salida.y, cabecera.y)).buffer(margen_m, join_style="mitre")
    return AOI(g, salida.epsg, "rectangulo", f"rectángulo de los dos puntos + {margen_m:.0f} m")
