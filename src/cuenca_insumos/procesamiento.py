"""Mosaico, recorte y reproyección de rásteres y vectores.

Toda la E/S ráster pasa por este módulo, así que para un plugin de QGIS (donde
``rasterio`` puede no estar disponible) basta con reimplementarlo sobre GDAL.
"""
from __future__ import annotations

import math
import warnings
from pathlib import Path

import numpy as np
import rasterio
from rasterio import windows
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from shapely.geometry import Polygon, mapping

__all__ = ["mosaico_utm", "leer_dem", "recortar_vector", "guardar_vector", "cog_por_ventana"]

NODATA = -9999.0
_PERFIL = dict(driver="GTiff", compress="deflate", predictor=2, tiled=True,
               blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")


def _malla_utm(aoi_utm: Polygon, res: float) -> tuple[rasterio.Affine, int, int]:
    minx, miny, maxx, maxy = aoi_utm.bounds
    minx = math.floor(minx / res) * res
    maxy = math.ceil(maxy / res) * res
    w = int(math.ceil((maxx - minx) / res))
    h = int(math.ceil((maxy - miny) / res))
    return from_origin(minx, maxy, res, res), w, h


def mosaico_utm(tiles: list[Path], aoi_utm: Polygon, epsg: int, destino: Path,
                res: float = 30.0, max_celdas: int = 30_000_000) -> Path:
    """Une los tiles (EPSG:4326), recorta al AOI y reproyecta a la UTM del proyecto.

    Las celdas fuera del polígono del AOI quedan con NoData (−9999), **nunca con 0**:
    un 0 crearía un escalón artificial que arruina pendientes, curvas de nivel y
    altitud media (error visto en la práctica).
    """
    transform, w, h = _malla_utm(aoi_utm, res)
    if w * h > max_celdas:
        raise MemoryError(f"El área requiere {w * h:,} celdas a {res:.0f} m (tope {max_celdas:,}). "
                          "Usa --dem 90 o un área menor.")
    lim_ll = transform_bounds(epsg, 4326, *aoi_utm.bounds, densify_pts=21)
    pad = 0.01
    lim_ll = (lim_ll[0] - pad, lim_ll[1] - pad, lim_ll[2] + pad, lim_ll[3] + pad)

    fuentes = [rasterio.open(t) for t in tiles]
    try:
        arr, tr_ll = merge(fuentes, bounds=lim_ll, nodata=NODATA, dtype="float32")
        crs_src = fuentes[0].crs
    finally:
        for f in fuentes:
            f.close()

    dst = np.full((h, w), NODATA, dtype="float32")
    reproject(arr[0], dst, src_transform=tr_ll, src_crs=crs_src, src_nodata=NODATA,
              dst_transform=transform, dst_crs=f"EPSG:{epsg}", dst_nodata=NODATA,
              resampling=Resampling.bilinear)
    fuera = geometry_mask([mapping(aoi_utm)], out_shape=(h, w), transform=transform, invert=False)
    dst[fuera] = NODATA

    destino.parent.mkdir(parents=True, exist_ok=True)
    perfil = dict(_PERFIL, height=h, width=w, count=1, dtype="float32",
                  crs=f"EPSG:{epsg}", transform=transform, nodata=NODATA)
    with rasterio.open(destino, "w", **perfil) as ds:
        ds.write(dst, 1)
        ds.update_tags(FUENTE="Copernicus DEM (ESA)", UNIDADES="m s.n.m.",
                       AVISO="NoData = -9999 fuera del area de analisis")
    return destino


def leer_dem(ruta: Path) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
    with rasterio.open(ruta) as ds:
        z = ds.read(1).astype("float64")
        nd = ds.nodata
        tr = ds.transform
    validos = np.isfinite(z) & ((z != nd) if nd is not None else True)
    return z, validos, tr


def guardar_vector(gdf, destino: Path, formato: str = "gpkg", capa: str | None = None) -> Path:
    destino = destino.with_suffix(".gpkg" if formato == "gpkg" else ".shp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if formato == "gpkg":
        gdf.to_file(destino, layer=capa or destino.stem, driver="GPKG", engine="pyogrio")
    else:
        with warnings.catch_warnings():  # nombres de campo > 10 caracteres se truncan en .shp
            warnings.simplefilter("ignore")
            gdf.to_file(destino, driver="ESRI Shapefile", engine="pyogrio", encoding="utf-8")
    return destino


def recortar_vector(fuente: str | Path, aoi_ll: Polygon, epsg: int, destino: Path,
                    formato: str = "gpkg", capa: str | None = None, recortar: bool = True,
                    columnas: list[str] | None = None):
    """Lee solo lo que cae en el rectángulo del AOI (filtro espacial en el lector),
    recorta al polígono y reproyecta. Devuelve (ruta | None, n_elementos)."""
    import geopandas as gpd

    kw = {"bbox": tuple(aoi_ll.bounds), "engine": "pyogrio"}
    if capa:
        kw["layer"] = capa
    if columnas:
        kw["columns"] = columnas
    gdf = gpd.read_file(fuente, **kw)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    if gdf.crs.to_epsg() != 4326:
        aoi_src = gpd.GeoSeries([aoi_ll], crs=4326).to_crs(gdf.crs).iloc[0]
    else:
        aoi_src = aoi_ll
    gdf = gdf[gdf.intersects(aoi_src)]
    if recortar and len(gdf):
        gdf = gdf.clip(aoi_src)
    if len(gdf) == 0:
        return None, 0
    gdf = gdf.to_crs(epsg)
    return guardar_vector(gdf, destino, formato), len(gdf)


def cog_por_ventana(url: str, aoi_utm: Polygon, epsg: int, destino: Path,
                    res: float | None = None, remuestreo: Resampling = Resampling.nearest) -> Path:
    """Lee de un Cloud-Optimized GeoTIFF remoto **solo** la ventana del AOI y la
    reproyecta a la UTM del proyecto. Transfiere unos pocos MB en vez del archivo completo."""
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff",
               GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
               VSI_CACHE="TRUE", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2")
    with rasterio.Env(**env):
        with rasterio.open(url) as src:
            lim = transform_bounds(epsg, src.crs, *aoi_utm.bounds, densify_pts=21)
            win = windows.from_bounds(*lim, transform=src.transform).round_offsets().round_lengths()
            win = win.intersection(windows.Window(0, 0, src.width, src.height))
            datos = src.read(window=win, boundless=False)
            tr_win = src.window_transform(win)
            if res is None:  # resolución nativa; ~10 m si el COG está en grados (p. ej. WorldCover)
                res = abs(src.res[0]) if src.crs.is_projected else 10.0
            transform, w, h = _malla_utm(aoi_utm, res)
            nd = src.nodata if src.nodata is not None else 0
            dst = np.full((src.count, h, w), nd, dtype=src.dtypes[0])
            for b in range(src.count):
                reproject(datos[b], dst[b], src_transform=tr_win, src_crs=src.crs, src_nodata=nd,
                          dst_transform=transform, dst_crs=f"EPSG:{epsg}", dst_nodata=nd,
                          resampling=remuestreo)
            perfil = dict(_PERFIL, height=h, width=w, count=src.count, dtype=src.dtypes[0],
                          crs=f"EPSG:{epsg}", transform=transform, nodata=nd)
            perfil.pop("predictor")
            colores = None
            try:
                colores = src.colormap(1)
            except ValueError:
                pass
    destino.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(destino, "w", **perfil) as ds:
        ds.write(dst)
        if colores:
            ds.write_colormap(1, colores)
    return destino
