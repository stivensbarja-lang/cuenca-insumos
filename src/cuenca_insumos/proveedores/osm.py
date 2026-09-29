"""OpenStreetMap vía Overpass API: cursos de agua y lugares poblados del área.

Opcional y de «mejor esfuerzo»: los servidores públicos de Overpass se saturan
con frecuencia (en las pruebas respondieron 406, 504 y 200 en minutos
consecutivos). Si ninguno responde, la herramienta sigue sin esta capa.
"""
from __future__ import annotations

import geopandas as gpd
import requests
from shapely.geometry import LineString, Point

from ..procesamiento import guardar_vector
from .base import Plan, Proveedor, Recurso, Salida

ESPEJOS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
_CONSULTA = """[out:json][timeout:120];
(
  way["waterway"~"^(river|stream|canal|drain|ditch)$"]({s},{w},{n},{e});
  node["place"~"^(city|town|village|hamlet|isolated_dwelling|locality)$"]({s},{w},{n},{e});
);
out geom;"""


class OSMOverpass(Proveedor):
    clave = "osm"
    carpeta = "hidrografia"
    insumo = "Cursos de agua menores y lugares (complementario)"
    dataset = "OpenStreetMap (consulta Overpass)"
    institucion = "Fundación OpenStreetMap y colaboradores"
    resolucion = "Vectorial; detalle variable según la zona"
    formato = "JSON (Overpass) convertido a GeoPackage"
    cobertura = "Global"
    crs = "EPSG:4326"
    url_info = "https://wiki.openstreetmap.org/wiki/Overpass_API"
    metodo = "API Overpass con varios servidores espejo y reintentos"
    requiere_auth = False
    licencia = "ODbL 1.0 (atribución «© colaboradores de OpenStreetMap»)"
    cita = "OpenStreetMap contributors. (2026). OpenStreetMap [Conjunto de datos]. https://www.openstreetmap.org"
    por_defecto = False
    uso = ("Complementa la hidrografía y la toponimia con quebradas menores y caseríos que las fuentes "
           "globales y la ANA suelen omitir.")

    def planificar(self, ctx) -> Plan:
        w, s, e, n = ctx.aoi_ll.bounds
        q = _CONSULTA.format(s=s, w=w, n=n, e=e)
        return Plan(True, "consulta por rectángulo del área",
                    [Recurso(ESPEJOS[0], "Overpass: waterway + place", "API", None, extra={"consulta": q})])

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        q = plan.recursos[0].extra["consulta"]
        datos, errores = None, []
        for url in ESPEJOS:
            try:
                datos = ctx.descargador.post_json(url, q, timeout=150)
                ctx.extra["osm_servidor"] = url
                break
            except (requests.RequestException, ValueError) as e:
                errores.append(f"{url.split('/')[2]}: {type(e).__name__}")
        if datos is None:
            return [Salida(None, "OSM no disponible ahora (servidores Overpass saturados): "
                                 + "; ".join(errores))]
        lineas, puntos = [], []
        for el in datos.get("elements", []):
            t = el.get("tags", {})
            if el["type"] == "way" and "geometry" in el and len(el["geometry"]) > 1:
                lineas.append({"nombre": t.get("name", ""), "tipo": t.get("waterway", ""),
                               "osm_id": el["id"],
                               "geometry": LineString([(p["lon"], p["lat"]) for p in el["geometry"]])})
            elif el["type"] == "node":
                puntos.append({"nombre": t.get("name", ""), "tipo": t.get("place", ""),
                               "osm_id": el["id"], "geometry": Point(el["lon"], el["lat"])})
        out = []
        for filas, nombre, desc in ((lineas, "osm_cursos_agua", "Cursos de agua OSM"),
                                    (puntos, "osm_lugares", "Lugares poblados OSM")):
            if not filas:
                out.append(Salida(None, f"{desc}: sin elementos en el área", 0))
                continue
            g = gpd.GeoDataFrame(filas, crs=4326)
            g = g[g.intersects(ctx.aoi_ll)]
            if nombre == "osm_cursos_agua":
                g = g.clip(ctx.aoi_ll)
            g = g.to_crs(ctx.epsg)
            carpeta = "hidrografia" if nombre == "osm_cursos_agua" else "coordenadas"
            out.append(Salida(guardar_vector(g, ctx.carpeta(carpeta) / nombre, ctx.params.formato_vector),
                              desc, len(g)))
        return out
