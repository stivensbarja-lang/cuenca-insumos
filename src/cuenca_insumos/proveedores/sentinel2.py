"""Imagen Sentinel-2 L2A en color verdadero, elegida por nubosidad **local**.

El porcentaje de nubes del catálogo es el de la escena entera (≈110 × 110 km).
En ceja de selva la cuenca puede estar cubierta aunque la escena salga despejada,
así que se lee la banda SCL (clasificación de escena) solo en la ventana del
área y se elige la escena con menos nubes y sombras *dentro* de ella.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio import windows
from rasterio.warp import transform_bounds
from shapely.geometry import mapping, shape

from ..procesamiento import cog_por_ventana
from .base import Plan, Proveedor, Recurso, Salida

STAC = "https://earth-search.aws.element84.com/v1/search"
_SCL_NUBE = (3, 8, 9, 10)          # sombra de nube, nube media, nube alta, cirros
_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")


def nubosidad_local(url_scl: str, aoi_utm, epsg: int) -> float:
    with rasterio.Env(**_ENV), rasterio.open(url_scl) as src:
        lim = transform_bounds(epsg, src.crs, *aoi_utm.bounds, densify_pts=21)
        win = windows.from_bounds(*lim, transform=src.transform).round_offsets().round_lengths()
        a = src.read(1, window=win.intersection(windows.Window(0, 0, src.width, src.height)))
    validos = a > 0
    return 100.0 * np.isin(a, _SCL_NUBE).sum() / max(1, validos.sum())


class Sentinel2(Proveedor):
    clave = "imagen"
    carpeta = "imagenes"
    insumo = "Imagen satelital (verificación visual y mapa base)"
    dataset = "Sentinel-2 L2A, composición color verdadero (TCI)"
    institucion = "ESA / Copernicus; catálogo STAC Earth Search (Element 84) sobre AWS Open Data"
    resolucion = "10 m"
    formato = "COG leído por ventana (solo el área), guardado como GeoTIFF RGB"
    cobertura = "Global terrestre, desde 2015"
    crs = "UTM de la escena (reproyectado a la del proyecto)"
    url_info = "https://registry.opendata.aws/sentinel-2-l2a-cogs/"
    metodo = "Búsqueda STAC + lectura HTTP por rangos de la ventana del área"
    requiere_auth = False
    licencia = "Datos Copernicus Sentinel: libres y abiertos, con atribución"
    cita = "Contiene datos modificados de Copernicus Sentinel [año], procesados por ESA."
    por_defecto = True
    uso = ("Verificación visual de la salida y del cauce, y fondo de los mapas. Alternativa descargable, "
           "citable y de licencia abierta a las imágenes de Google (que no pueden descargarse).")

    def planificar(self, ctx) -> Plan:
        cuerpo = {"collections": ["sentinel-2-l2a"], "intersects": mapping(ctx.aoi_ll), "limit": 8,
                  "query": {"eo:cloud_cover": {"lt": 30}},
                  "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}]}
        try:
            res = ctx.descargador.post_json(STAC, cuerpo, timeout=90)
        except Exception as e:  # noqa: BLE001
            return Plan(False, f"catálogo STAC no disponible ({type(e).__name__})")
        feats = res.get("features", [])
        completas = [f for f in feats if shape(f["geometry"]).buffer(1e-9).contains(ctx.aoi_ll)]
        if not feats:
            return Plan(False, "no hay escenas con < 30 % de nubes sobre el área")
        usar = completas or feats
        rec = [Recurso(f["assets"]["visual"]["href"], f["id"], "ventana COG", None,
                       extra={"scl": f["assets"]["scl"]["href"], "fecha": f["properties"]["datetime"][:10],
                              "nubes_escena": f["properties"]["eo:cloud_cover"],
                              "completa": f in completas})
               for f in usar[:5]]
        return Plan(True, f"{len(feats)} escenas candidatas; se evaluará la nubosidad local de {len(rec)}", rec)

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        mejor, puntaje = None, None
        for r in plan.recursos:
            try:
                n = nubosidad_local(r.extra["scl"], ctx.aoi.geom, ctx.epsg)
            except Exception as e:  # noqa: BLE001
                ctx.log(f"   Sentinel-2 {r.descripcion}: no se pudo leer SCL ({type(e).__name__})")
                continue
            r.extra["nubes_locales"] = round(n, 2)
            ctx.log(f"   Sentinel-2 {r.descripcion}: nubes en la escena {r.extra['nubes_escena']:.1f} %, "
                    f"dentro del área {n:.1f} %")
            clave = (not r.extra["completa"], round(n, 1), -int(r.extra["fecha"].replace("-", "")))  # desempate: la más reciente
            if puntaje is None or clave < puntaje:
                mejor, puntaje = r, clave
            if n < 1 and r.extra["completa"]:
                break                             # suficientemente despejada: no leer más escenas
        if mejor is None:
            return [Salida(None, "Sentinel-2: no se pudo evaluar ninguna escena")]
        dest = ctx.carpeta("imagenes") / f"Sentinel2_{mejor.extra['fecha']}_{mejor.descripcion}_RGB.tif"
        cog_por_ventana(mejor.url, ctx.aoi.geom, ctx.epsg, dest, res=10.0)
        ctx.extra["imagen"] = (mejor.descripcion, mejor.extra["fecha"], mejor.extra["nubes_locales"])
        nota = "" if mejor.extra["completa"] else " (la escena no cubre toda el área)"
        return [Salida(dest, f"Sentinel-2 {mejor.extra['fecha']}, {mejor.extra['nubes_locales']:.1f} % de "
                             f"nubes en el área{nota}")]
