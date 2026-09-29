"""Cobertura del suelo ESA WorldCover 2021 (opcional).

Demuestra el patrón para insumos temáticos en COG: misma lógica de tiles que el
DEM (aquí de 3° × 3°) pero leyendo solo la ventana del área.
"""
from __future__ import annotations

import rasterio
from rasterio.merge import merge

from ..procesamiento import cog_por_ventana
from ..tiles import seleccionar
from .base import Plan, Proveedor, Recurso, Salida

_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_{cod}_Map.tif")


class WorldCover(Proveedor):
    clave = "cobertura"
    carpeta = "cobertura"
    insumo = "Cobertura y uso del suelo"
    dataset = "ESA WorldCover 10 m 2021 v200"
    institucion = "Agencia Espacial Europea (ESA) y consorcio WorldCover"
    resolucion = "10 m; 11 clases"
    formato = "COG en tiles de 3° × 3°, leído por ventana"
    cobertura = "Global"
    crs = "EPSG:4326"
    url_info = "https://esa-worldcover.org/"
    metodo = "HTTPS por rangos (solo la ventana del área)"
    requiere_auth = False
    licencia = "CC BY 4.0"
    cita = ("Zanaga, D., et al. (2022). ESA WorldCover 10 m 2021 v200 [Conjunto de datos]. "
            "https://doi.org/10.5281/zenodo.7254221")
    por_defecto = False
    uso = "Necesario si el análisis incluye número de curva, erosión (USLE/RUSLE) o relación bosque-agua."

    def planificar(self, ctx) -> Plan:
        sel = seleccionar(ctx.aoi_ll, tam=3)
        rec = [Recurso(_URL.format(cod=t.codigo), f"tile {t.codigo}", "ventana COG") for t in sel.necesarios]
        return Plan(bool(rec), f"{len(rec)} tile(s) de 3°", rec)

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        dest = ctx.carpeta("cobertura") / "cobertura_worldcover_2021.tif"
        if len(plan.recursos) == 1:
            cog_por_ventana(plan.recursos[0].url, ctx.aoi.geom, ctx.epsg, dest, res=10.0)
        else:
            partes = []
            for i, r in enumerate(plan.recursos):
                p = ctx.descargador.cache / "cobertura" / f"parte_{i}.tif"
                cog_por_ventana(r.url, ctx.aoi.geom, ctx.epsg, p, res=10.0)
                partes.append(p)
            srcs = [rasterio.open(p) for p in partes]
            arr, tr = merge(srcs, nodata=0)
            perfil = srcs[0].profile | {"height": arr.shape[1], "width": arr.shape[2], "transform": tr}
            cmap = srcs[0].colormap(1)
            for s in srcs:
                s.close()
            with rasterio.open(dest, "w", **perfil) as ds:
                ds.write(arr)
                ds.write_colormap(1, cmap)
        return [Salida(dest, "Cobertura WorldCover 2021 (10 m) recortada al área")]
