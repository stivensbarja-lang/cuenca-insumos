"""Límites administrativos (GADM 4.1): país, departamentos, provincias y distritos.

Pensado para los mapas de ubicación: los departamentos se guardan completos
(para un minimapa nacional), las provincias
solo del departamento que contiene la cuenca y los distritos solo de su
provincia. El campo ``SEL`` = 1 marca la unidad que contiene el área de estudio.
"""
from __future__ import annotations

import zipfile

import geopandas as gpd

from ..procesamiento import guardar_vector
from .base import Plan, Proveedor, Recurso, Salida

# Se usa el shapefile y no el GeoJSON: en la versión GeoJSON de GADM 4.1 los nombres
# vienen sin espacios en todos los niveles («SanRamon», «MadredeDios», «LaLibertad»);
# en el shapefile están bien («San Ramon», «Madre de Dios»). Un ZIP trae los 4 niveles.
_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_{iso}_shp.zip"
_NOMBRES = {0: "pais", 1: "nivel1_departamentos", 2: "nivel2_provincias", 3: "nivel3_distritos"}


class GADM(Proveedor):
    clave = "limites"
    carpeta = "limites"
    insumo = "Límites administrativos"
    dataset = "GADM versión 4.1 (niveles 0 a 3)"
    institucion = "GADM project — Universidad de California, Davis"
    resolucion = "Vectorial; generalizado (adecuado hasta ≈1:100 000)"
    formato = "Shapefile comprimido por país (los 4 niveles en un ZIP)"
    cobertura = "Global"
    crs = "EPSG:4326"
    url_info = "https://gadm.org/"
    metodo = "HTTPS directo, un archivo por país; se lee cada nivel dentro del ZIP"
    requiere_auth = False
    licencia = "Libre para uso académico y no comercial; prohibida la redistribución comercial"
    cita = "GADM. (2022). Database of Global Administrative Areas (Versión 4.1) [Conjunto de datos]. https://gadm.org"
    por_defecto = True
    uso = ("Mapas de ubicación (país, departamento, provincia, distrito) y ubicación política "
           "de la cuenca.")

    def planificar(self, ctx) -> Plan:
        iso = ctx.params.pais
        url = _URL.format(iso=iso)
        return Plan(True, f"país {iso}, niveles 0-3",
                    [Recurso(url, f"GADM {iso}", "descarga", ctx.descargador.tamano(url), reutilizable=True)])

    def _leer(self, zip_ruta, iso: str, nivel: int) -> gpd.GeoDataFrame | None:
        with zipfile.ZipFile(zip_ruta) as z:
            interno = next((n for n in z.namelist() if n.lower() == f"gadm41_{iso}_{nivel}.shp".lower()), None)
        if interno is None:
            return None                              # algunos países tienen menos niveles
        return gpd.read_file(f"/vsizip/{zip_ruta.as_posix()}/{interno}", engine="pyogrio")

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        zip_ruta = ctx.descargador.obtener(plan.recursos[0].url, subcarpeta="limites").ruta
        ref = ctx.cuenca if ctx.cuenca is not None else ctx.aoi.geom
        ref_ll = gpd.GeoSeries([ref], crs=ctx.epsg).to_crs(4326).iloc[0]
        dest = ctx.carpeta("limites") / "limites_administrativos"
        fmt = ctx.params.formato_vector
        salidas, ruta_txt, filtro = [], [], None
        for n in range(4):
            g = self._leer(zip_ruta, ctx.params.pais, n)
            if g is None:
                continue
            if n >= 2 and filtro is not None:            # solo hijos de la unidad seleccionada
                g = g[g[f"GID_{n - 1}"].isin(filtro)]
            if n >= 1:
                g["SEL"] = g.intersects(ref_ll).astype(int)
                sel = g[g["SEL"] == 1]
                filtro = set(sel[f"GID_{n}"])
                if len(sel):
                    ruta_txt.append(f"{_NOMBRES[n].split('_')[1].rstrip('s').capitalize()}: "
                                    + ", ".join(sel[f"NAME_{n}"]))
            g = g.to_crs(ctx.epsg)
            if fmt == "gpkg":
                p = guardar_vector(g, dest, "gpkg", capa=_NOMBRES[n])
            else:
                p = guardar_vector(g, dest.with_name(f"limites_{_NOMBRES[n]}"), "shp")
            salidas.append(Salida(p, f"GADM nivel {n} ({_NOMBRES[n]})", len(g)))
        ctx.extra["ubicacion_politica"] = ruta_txt
        return salidas
