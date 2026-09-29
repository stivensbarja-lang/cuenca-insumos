"""Copernicus DEM GLO-30 / GLO-90 desde el registro abierto de AWS."""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import Polygon

from ..descarga import Descargador
from ..procesamiento import mosaico_utm
from ..tiles import SeleccionTiles, Tile, seleccionar
from .base import Plan, Proveedor, Recurso, Salida

_BUCKET = {"30": "https://copernicus-dem-30m.s3.amazonaws.com",
           "90": "https://copernicus-dem-90m.s3.amazonaws.com"}
_COD = {"30": "10", "90": "30"}          # 10 = 1 segundo de arco, 30 = 3 segundos
_BYTES_TIPICOS = {"30": 40_000_000, "90": 5_000_000}


def nombre_tile(t: Tile, res: str = "30") -> str:
    ns = f"{'N' if t.lat0 >= 0 else 'S'}{abs(t.lat0):02d}_00"
    ew = f"{'E' if t.lon0 >= 0 else 'W'}{abs(t.lon0):03d}_00"
    return f"Copernicus_DSM_COG_{_COD[res]}_{ns}_{ew}_DEM"


class CopernicusDEM(Proveedor):
    clave = "dem"
    carpeta = "dem"
    insumo = "Modelo de Elevación Digital"
    dataset = "Copernicus DEM GLO-30 (o GLO-90 para cuencas muy grandes)"
    institucion = "Agencia Espacial Europea (ESA) / programa Copernicus de la UE; distribuido por AWS Open Data"
    resolucion = "1 segundo de arco (≈30 m); GLO-90: 3 segundos (≈90 m)"
    formato = "GeoTIFF optimizado para la nube (COG), tiles de 1° × 1°"
    cobertura = "Global (sin tiles sobre océano abierto)"
    crs = "EPSG:4326 (WGS 84); alturas ortométricas EGM2008"
    url_info = "https://registry.opendata.aws/copernicus-dem/"
    metodo = "HTTPS directo; catálogo tileList.txt para saber qué tiles existen"
    requiere_auth = False
    licencia = "Licencia Copernicus DEM: uso libre, incluido comercial, con atribución"
    cita = ("European Space Agency. (2022). Copernicus DEM GLO-30 [Conjunto de datos]. "
            "https://doi.org/10.5270/ESA-c5d3d65")
    por_defecto = True
    uso = ("Base de todo el análisis: relleno, dirección y acumulación de flujo, "
           "red de drenaje, cuenca, pendientes, curvas de nivel, hipsometría y sombreado.")

    def __init__(self, resolucion: str = "30"):
        if resolucion not in _BUCKET:
            raise ValueError("resolucion debe ser '30' o '90'")
        self.res = resolucion
        self._catalogo: set[str] | None = None

    # ---------------------------------------------------------------- catálogo
    def catalogo(self, d: Descargador) -> set[str]:
        if self._catalogo is None:
            r = d.obtener(f"{_BUCKET[self.res]}/tileList.txt",
                          nombre=f"copernicus_glo{self.res}_tileList.txt", subcarpeta="dem")
            self._catalogo = set(r.ruta.read_text().split())
        return self._catalogo

    def url(self, t: Tile) -> str:
        n = nombre_tile(t, self.res)
        return f"{_BUCKET[self.res]}/{n}/{n}.tif"

    def seleccionar(self, aoi_ll: Polygon, d: Descargador) -> SeleccionTiles:
        cat = self.catalogo(d)
        return seleccionar(aoi_ll, tam=1, existe=lambda t: nombre_tile(t, self.res) in cat)

    def descargar(self, tiles: list[Tile], d: Descargador, log=print) -> list[Path]:
        rutas = []
        for t in tiles:
            r = d.obtener(self.url(t), subcarpeta="dem")
            log(f"   DEM {t.codigo}: {r.estado} ({r.bytes / 1e6:.1f} MB)")
            rutas.append(r.ruta)
        return rutas

    # ------------------------------------------------ interfaz genérica (Proveedor)
    def planificar(self, ctx) -> Plan:
        aoi = ctx.aoi.geom.buffer(ctx.params.relleno_tiles_m)
        from ..aoi import a_4326
        sel = self.seleccionar(a_4326(aoi, ctx.epsg), ctx.descargador)
        ctx.extra["seleccion_dem"] = sel
        rec = [Recurso(self.url(t), f"tile {t.codigo}", "descarga", _BYTES_TIPICOS[self.res])
               for t in sel.necesarios]
        if not rec:
            return Plan(False, "ningún tile del DEM cubre el área (¿punto en el océano?)")
        return Plan(True, f"{len(rec)} tile(s) GLO-{self.res}", rec)

    def ejecutar(self, ctx, plan: Plan) -> list[Salida]:
        sel: SeleccionTiles = ctx.extra["seleccion_dem"]
        rutas = self.descargar(sel.necesarios, ctx.descargador, ctx.log)
        dest = ctx.carpeta("dem") / f"DEM_GLO{self.res}_UTM{ctx.epsg}.tif"
        mosaico_utm(rutas, ctx.aoi.geom, ctx.epsg, dest, res=float(self.res),
                    max_celdas=ctx.params.max_celdas)
        return [Salida(dest, f"DEM {self.res} m reproyectado a EPSG:{ctx.epsg} y recortado al área")]
