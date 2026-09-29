"""HydroSHEDS: unidades hidrográficas (HydroBASINS) y red fluvial (HydroRIVERS).

Son los equivalentes automatizables de las capas de la ANA («Unidades
hidrográficas» y «Ríos y quebradas»). Se distribuyen por
continente, así que la primera descarga es pesada (70–100 MB) y luego se
reutiliza desde la caché para cualquier cuenca del mismo continente.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from ..procesamiento import guardar_vector, recortar_vector
from .base import Plan, Proveedor, Recurso, Salida

_URL_BAS = "https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_{c}_lev{n:02d}_v1c.zip"
_URL_RIV = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{c}_shp.zip"

# Regiones HydroSHEDS por rectángulo aproximado (lon_min, lat_min, lon_max, lat_max).
_REGIONES = {
    "sa": (-93.0, -56.0, -32.0, 15.0),
    "na": (-170.0, 5.0, -52.0, 62.0),
    "af": (-26.0, -35.0, 60.0, 38.0),
    "eu": (-25.0, 12.0, 70.0, 82.0),
    "as": (57.0, -12.0, 150.0, 56.0),
    "au": (95.0, -56.0, 180.0, 24.0),
}


def region_hydrosheds(lon: float, lat: float, forzada: str | None = None) -> str:
    if forzada:
        return forzada.lower()
    hits = [k for k, (w, s, e, n) in _REGIONES.items() if w <= lon <= e and s <= lat <= n]
    if lon <= -32 and lat < 5 and "sa" in hits:
        return "sa"
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"No se puede deducir la región HydroSHEDS para ({lon:.2f}, {lat:.2f}); "
                     f"candidatas: {hits or 'ninguna'}. Indícala con --continente (sa, na, af, eu, as, au).")


def _shp_en_zip(ruta: Path) -> str:
    with zipfile.ZipFile(ruta) as z:
        shp = next(n for n in z.namelist() if n.lower().endswith(".shp"))
    return f"/vsizip/{ruta.as_posix()}/{shp}"


class _HydroSHEDS(Proveedor):
    carpeta = "hidrografia"
    institucion = "WWF / McGill University (programa HydroSHEDS)"
    formato = "Shapefile comprimido por continente"
    cobertura = "Global (hasta 60° N)"
    crs = "EPSG:4326"
    url_info = "https://www.hydrosheds.org/"
    metodo = "HTTPS directo; lectura con filtro espacial desde el ZIP (sin descomprimir)"
    requiere_auth = False
    licencia = "Libre, incluido uso comercial, con atribución (licencia HydroSHEDS)"

    def _region(self, ctx) -> str:
        c = ctx.aoi_ll.centroid
        return region_hydrosheds(c.x, c.y, ctx.params.continente)


class HydroBASINS(_HydroSHEDS):
    clave = "unidades"
    insumo = "Unidades hidrográficas (codificación Pfafstetter)"
    dataset = "HydroBASINS v1c, nivel 12"
    resolucion = "Polígonos derivados de un DEM de 15 segundos de arco (≈500 m)"
    cita = ("Lehner, B., & Grill, G. (2013). Global river hydrography and network routing. "
            "Hydrological Processes, 27(15), 2171–2186. https://doi.org/10.1002/hyp.9740")
    por_defecto = True
    uso = ("Ubica la cuenca dentro de las unidades hidrográficas mayores (codificación Pfafstetter), "
           "para el mapa de ubicación hidrográfica. Equivalente abierto de las unidades de la ANA.")

    def planificar(self, ctx) -> Plan:
        url = _URL_BAS.format(c=self._region(ctx), n=12)
        return Plan(True, "nivel 12 (el más detallado)",
                    [Recurso(url, "HydroBASINS nivel 12", "descarga", ctx.descargador.tamano(url),
                             reutilizable=True)])

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        r = ctx.descargador.obtener(plan.recursos[0].url, subcarpeta="hydrosheds")
        g = gpd.read_file(_shp_en_zip(r.ruta), bbox=tuple(ctx.aoi_ll.bounds), engine="pyogrio")
        g = g[g.intersects(ctx.aoi_ll)]
        if len(g) == 0:
            return [Salida(None, "HydroBASINS: sin unidades en el área", 0)]
        sal = gpd.GeoSeries([Point(ctx.salida_xy)], crs=ctx.epsg).to_crs(4326).iloc[0]
        g["SEL"] = g.contains(sal).astype(int)
        cont = g[g["SEL"] == 1]
        if len(cont):
            u = cont.iloc[0]
            ctx.extra["unidad_hidrografica"] = (int(u["PFAF_ID"]), float(u["UP_AREA"]), int(u["HYBAS_ID"]))
        g = g.to_crs(ctx.epsg)
        p = guardar_vector(g, ctx.carpeta("hidrografia") / "unidades_hydrobasins_nivel12",
                           ctx.params.formato_vector)
        return [Salida(p, "Unidades HydroBASINS nivel 12 (SEL = 1 contiene la salida)", len(g))]


class HydroRIVERS(_HydroSHEDS):
    clave = "rios"
    insumo = "Red hidrográfica de referencia"
    dataset = "HydroRIVERS v1.0"
    resolucion = "Ríos con cuenca > 10 km² o caudal medio > 0.1 m³/s"
    cita = ("Lehner, B., & Grill, G. (2013). Global river hydrography and network routing. "
            "Hydrological Processes, 27(15), 2171–2186. https://doi.org/10.1002/hyp.9740")
    por_defecto = True
    uso = ("Contexto del mapa de ubicación y control de la red de drenaje derivada del DEM. "
           "Equivale a «Ríos y quebradas» de la ANA y, como ella, omite cursos con cuencas < 10 km².")

    def planificar(self, ctx) -> Plan:
        url = _URL_RIV.format(c=self._region(ctx))
        return Plan(True, "red continental", [Recurso(url, "HydroRIVERS", "descarga",
                                                       ctx.descargador.tamano(url), reutilizable=True)])

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        r = ctx.descargador.obtener(plan.recursos[0].url, subcarpeta="hydrosheds")
        p, n = recortar_vector(_shp_en_zip(r.ruta), ctx.aoi_ll, ctx.epsg,
                               ctx.carpeta("hidrografia") / "rios_hydrorivers", ctx.params.formato_vector)
        if p is None:
            return [Salida(None, "HydroRIVERS: ningún río mayor de 10 km² dentro del área (normal en "
                                 "microcuencas; usa la red derivada del DEM)", 0)]
        return [Salida(p, "Ríos HydroRIVERS recortados al área", n)]
