"""Toponimia (GeoNames): centros poblados, ríos, quebradas y cerros.

Además de guardar los puntos, verifica el punto de salida: informa qué río o
quebrada con nombre queda más cerca. Por ejemplo, en la quebrada
Huacará (Junín, Perú) ubica «Quebrada Huacar» a unos 100 m de la salida.
"""
from __future__ import annotations

import io
import math
import zipfile

import geopandas as gpd
import pandas as pd

from ..procesamiento import guardar_vector
from .base import Plan, Proveedor, Recurso, Salida

_BASE = "https://download.geonames.org/export/dump"
_COLS = ["geonameid", "nombre", "ascii", "alternos", "lat", "lon", "clase", "codigo", "pais",
         "cc2", "adm1", "adm2", "adm3", "adm4", "poblacion", "elevacion", "dem", "zona", "fecha"]
_CLASES = {"P": "centro poblado", "H": "hidrografía", "T": "relieve"}
_CURSOS = {"STM", "STMI", "STMX", "STMS", "STMB", "STMC", "STMD", "STMM", "STMQ", "STMSB", "CNL"}


class GeoNames(Proveedor):
    clave = "toponimia"
    carpeta = "coordenadas"
    insumo = "Toponimia y centros poblados (puntos de referencia)"
    dataset = "GeoNames — volcado por país"
    institucion = "GeoNames (base colaborativa que integra fuentes oficiales nacionales)"
    resolucion = "Puntos; precisión variable (≈100 m – 1 km)"
    formato = "Texto tabulado comprimido (un archivo por país)"
    cobertura = "Global"
    crs = "EPSG:4326"
    url_info = "https://www.geonames.org/"
    metodo = "HTTPS directo (≈3 MB para el Perú)"
    requiere_auth = False
    licencia = "CC BY 4.0"
    cita = "GeoNames. (2026). GeoNames geographical database [Conjunto de datos]. https://www.geonames.org"
    por_defecto = True
    uso = ("Puntos de referencia (centros poblados, ríos, cerros) para rotular los mapas y confirmar "
           "que la salida está sobre el río correcto.")

    def _iso2(self, ctx) -> str:
        r = ctx.descargador.obtener(f"{_BASE}/countryInfo.txt", subcarpeta="toponimia")
        for l in r.ruta.read_text(encoding="utf-8").splitlines():
            c = l.split("\t")
            if l and not l.startswith("#") and len(c) > 1 and c[1] == ctx.params.pais:
                return c[0]
        raise ValueError(f"GeoNames no reconoce el país {ctx.params.pais}")

    def planificar(self, ctx) -> Plan:
        iso2 = self._iso2(ctx)
        url = f"{_BASE}/{iso2}.zip"
        return Plan(True, f"volcado {iso2}", [Recurso(url, f"GeoNames {iso2}", "descarga",
                                                      ctx.descargador.tamano(url), reutilizable=True)])

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        rec = plan.recursos[0]
        r = ctx.descargador.obtener(rec.url, subcarpeta="toponimia")
        with zipfile.ZipFile(r.ruta) as z:
            txt = next(n for n in z.namelist() if n.endswith(".txt") and "readme" not in n.lower())
            df = pd.read_csv(io.TextIOWrapper(z.open(txt), encoding="utf-8"), sep="\t", header=None,
                             names=_COLS, usecols=range(len(_COLS)), quoting=3, low_memory=False)
        w, s, e, n = ctx.aoi_ll.bounds
        df = df[df["clase"].isin(_CLASES) & df["lon"].between(w, e) & df["lat"].between(s, n)]
        g = gpd.GeoDataFrame(df[["geonameid", "nombre", "clase", "codigo", "poblacion", "elevacion"]],
                             geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=4326)
        g = g[g.intersects(ctx.aoi_ll)].to_crs(ctx.epsg)
        g["tipo"] = g["clase"].map(_CLASES)
        if len(g) == 0:
            return [Salida(None, "GeoNames: sin topónimos en el área", 0)]
        sx, sy = ctx.salida_xy
        g["dist_salida_m"] = [round(math.hypot(p.x - sx, p.y - sy), 1) for p in g.geometry]
        cursos = g[g["codigo"].isin(_CURSOS)].sort_values("dist_salida_m")
        if len(cursos):
            c = cursos.iloc[0]
            ctx.extra["curso_cercano"] = (c["nombre"], float(c["dist_salida_m"]))
        pobl = g[g["clase"] == "P"].sort_values("dist_salida_m")
        if len(pobl):
            ctx.extra["poblado_cercano"] = (pobl.iloc[0]["nombre"], float(pobl.iloc[0]["dist_salida_m"]))
        p = guardar_vector(g, ctx.carpeta("coordenadas") / "toponimia_geonames", ctx.params.formato_vector)
        return [Salida(p, "Topónimos GeoNames (poblados, cursos de agua, cerros)", len(g))]
