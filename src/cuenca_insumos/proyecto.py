"""Orquestador: ``analizar`` (sin descargar datos) y ``descargar`` (todo el flujo).

Flujo de ``descargar``
----------------------
1. AOI preliminar (corredor o círculo) → tiles DEM que lo intersectan.
2. Descarga y mosaico del DEM → delineación desde la salida.
3. Si la cuenca toca el borde del área, se amplía el AOI y se repite, bajando
   solo los tiles nuevos (máx. ``params.max_iteraciones``).
4. AOI final = cuenca + margen → DEM final y capas temáticas recortadas a él.
5. Manifiesto de procedencia y reporte en ``10_Resultados``.

Esta clase no imprime nada por sí misma: todo pasa por ``log`` y ``progreso``,
de modo que la misma lógica sirve para la terminal, Streamlit o un plugin de QGIS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import geopandas as gpd
from shapely.geometry import LineString, Point

from .aoi import AOI, a_4326, aoi_final, aoi_preliminar
from .config import CARPETAS, Parametros
from .contexto import Contexto
from .coords import Punto, SistemaReferencia, validar_puntos, verificar_en_tierra
from .delineacion import ResultadoDelineacion, delinear
from .descarga import Descargador, ErrorDescarga
from .manifiesto import Manifiesto, RegistroDescarga, RegistroProducto
from .oficiales import FUENTES_OFICIALES_PERU, hojas_ign
from .procesamiento import guardar_vector, leer_dem, mosaico_utm
from .proveedores import CopernicusDEM, Plan, Proveedor, tematicos_activos
from .proveedores.copernicus_dem import nombre_tile
from .tiles import SeleccionTiles, Tile

__all__ = ["EntradaCuenca", "PlanAnalisis", "ResultadoProyecto", "ProyectoCuenca"]


@dataclass
class EntradaCuenca:
    salida: Punto
    sistema: SistemaReferencia
    cabecera: Punto | None = None
    nombre: str = "Cuenca"
    area_estimada_km2: float | None = None

    def como_dict(self) -> dict:
        d = {"nombre": self.nombre, "epsg": self.sistema.epsg, "sistema": self.sistema.nombre,
             "salida": {"x": self.salida.x, "y": self.salida.y}}
        if self.cabecera:
            d["cabecera"] = {"x": self.cabecera.x, "y": self.cabecera.y}
        if self.area_estimada_km2:
            d["area_estimada_km2"] = self.area_estimada_km2
        return d


@dataclass
class PlanAnalisis:
    entrada: EntradaCuenca
    aoi: AOI
    resolucion_dem: str
    seleccion_dem: SeleccionTiles
    planes: list[tuple[Proveedor, Plan]]
    hojas_ign: list[str]
    avisos: list[str] = field(default_factory=list)
    dem_en_cache: dict = field(default_factory=dict)


@dataclass
class ResultadoProyecto:
    raiz: Path
    delineacion: ResultadoDelineacion | None
    aoi_final: AOI
    iteraciones: int
    manifiesto: Manifiesto
    reporte: Path
    extra: dict = field(default_factory=dict)


class ProyectoCuenca:
    def __init__(self, entrada: EntradaCuenca, raiz: Path | str, params: Parametros | None = None,
                 cache: Path | str | None = None, log: Callable[[str], None] = print,
                 progreso: Callable[[str, int, int | None], None] | None = None):
        self.entrada = entrada
        self.raiz = Path(raiz)
        self.params = params or Parametros()
        self.params.validar()
        # validar antes de crear nada en disco: una coordenada mal escrita no deja carpetas vacías
        self.avisos = validar_puntos(entrada.salida, entrada.cabecera, entrada.sistema, self.params.pais)
        self.log = log
        self.descargador = Descargador(Path(cache) if cache else self.raiz / "_cache", progreso=progreso)

    # ================================================================== analizar
    def _resolucion(self, aoi: AOI) -> str:
        if self.params.resolucion_dem != "auto":
            return self.params.resolucion_dem
        return "90" if aoi.area_km2 > self.params.umbral_glo90_km2 else "30"

    def analizar(self) -> PlanAnalisis:
        e, p = self.entrada, self.params
        avisos = list(self.avisos)
        aoi = aoi_preliminar(e.salida, e.cabecera, e.area_estimada_km2, p)
        res = self._resolucion(aoi)
        dem = CopernicusDEM(res)
        cat = dem.catalogo(self.descargador)

        def en_tierra(lon: float, lat: float) -> bool:
            return nombre_tile(Tile(math.floor(lat), math.floor(lon)), res) in cat

        for pto in (e.salida, e.cabecera):
            if pto is not None:
                verificar_en_tierra(pto, e.sistema, en_tierra, p.pais)
        sel = dem.seleccionar(a_4326(aoi.geom.buffer(p.relleno_tiles_m), e.sistema.epsg), self.descargador)
        if not sel.necesarios:
            raise ValueError("Ningún tile del DEM cubre el área: el punto de salida parece estar en el océano.")
        ctx = self._contexto(aoi, (e.salida.x, e.salida.y))
        planes = []
        for prov in tematicos_activos(p.incluir, p.excluir):
            try:
                planes.append((prov, prov.planificar(ctx)))
            except Exception as ex:  # noqa: BLE001 - un proveedor caído no detiene el análisis
                planes.append((prov, Plan(False, f"no se pudo consultar ({type(ex).__name__}: {ex})")))
        # marcar lo que ya está en la caché para que el estimado de descarga sea honesto
        for _, pl in planes:
            for r in pl.recursos:
                r.extra["en_cache"] = self._en_cache(r.url)
        dem_en_cache = {t: self._en_cache(dem.url(t)) for t in sel.necesarios}
        hojas = hojas_ign(aoi.lonlat()) if p.pais == "PER" else []
        return PlanAnalisis(e, aoi, res, sel, planes, hojas, avisos, dem_en_cache)

    def _en_cache(self, url: str) -> bool:
        info = self.descargador.indice.get(url)
        return bool(info) and Path(info["ruta"]).exists()

    def _contexto(self, aoi: AOI, salida_xy, cuenca=None) -> Contexto:
        return Contexto(self.raiz, self.entrada.sistema.epsg, aoi, self.params, self.descargador,
                        salida_xy, cuenca, self.log)

    # ================================================================== descargar
    def descargar(self, plan: PlanAnalisis | None = None) -> ResultadoProyecto:
        plan = plan or self.analizar()
        e, p = self.entrada, self.params
        epsg = e.sistema.epsg
        for c in CARPETAS.values():
            (self.raiz / c).mkdir(parents=True, exist_ok=True)
        man = Manifiesto(self.raiz, e.como_dict())
        man.decisiones.append(f"AOI preliminar: {plan.aoi.descripcion} ({plan.aoi.area_km2:.1f} km²)")
        self._guardar_puntos()

        # ---------------- fase 1: DEM + delineación con expansión iterativa ----------
        dem = CopernicusDEM(plan.resolucion_dem)
        aoi, dl, it = plan.aoi, None, 0
        ruta_trabajo = self.raiz / CARPETAS["dem"] / f"DEM_GLO{plan.resolucion_dem}_area_trabajo.tif"
        n_hist = 0
        while True:
            sel = dem.seleccionar(a_4326(aoi.geom.buffer(p.relleno_tiles_m), epsg), self.descargador)
            self.log(f"DEM (iteración {it}): {len(sel.necesarios)} tile(s) necesarios de {len(sel.encontrados)} "
                     f"encontrados")
            rutas = dem.descargar(sel.necesarios, self.descargador, self.log)
            mosaico_utm(rutas, aoi.geom, epsg, ruta_trabajo, float(plan.resolucion_dem), p.max_celdas)
            if not p.delinear:
                break
            z, validos, tr = leer_dem(ruta_trabajo)
            cab = (e.cabecera.x, e.cabecera.y) if e.cabecera else None
            dl = delinear(z, validos, tr, (e.salida.x, e.salida.y), cab,
                          p.umbral_cauce_km2, p.radio_ajuste_m)
            self.log(f"   cuenca delineada: {dl.area_km2:.2f} km²"
                     + (" — TOCA EL BORDE del área" if dl.truncada else " — contenida en el área"))
            if not dl.truncada:
                break
            if it >= p.max_iteraciones:
                man.errores.append(f"La cuenca sigue tocando el borde tras {it} ampliaciones: puede estar "
                                   "incompleta (¿salida sobre un río muy grande o llegada a la costa?).")
                break
            aoi = aoi.ampliar(p.factor_expansion)
            it += 1
            man.decisiones.append(f"Iteración {it}: la cuenca tocaba el borde en {dl.celdas_en_borde} celdas; "
                                  f"se amplió el área a {aoi.area_km2:.1f} km².")
        self._registrar_descargas(man, dem, n_hist)
        n_hist = len(self.descargador.historial)

        # ---------------- fase 2: área final ----------------------------------------
        if dl is not None:
            fin = aoi_final(dl.poligono, epsg, p)
            salida_xy = dl.salida_ajustada
            man.decisiones.append(f"Salida ajustada al cauce: desplazamiento {dl.desplazamiento_m:.0f} m.")
            man.decisiones.append(f"AOI final: {fin.descripcion} ({fin.area_km2:.1f} km², "
                                  f"{100 * fin.area_km2 / plan.aoi.area_km2:.0f} % del preliminar).")
            man.errores.extend(dl.avisos)
            self._guardar_delineacion(dl, fin, aoi)
        else:
            fin, salida_xy = aoi, (e.salida.x, e.salida.y)
            man.decisiones.append("Delineación desactivada: se usa el AOI preliminar para todas las capas.")

        sel_fin = dem.seleccionar(a_4326(fin.geom.buffer(p.relleno_tiles_m), epsg), self.descargador)
        rutas = dem.descargar(sel_fin.necesarios, self.descargador, self.log)
        ruta_dem = self.raiz / CARPETAS["dem"] / f"DEM_GLO{plan.resolucion_dem}_UTM{epsg}.tif"
        mosaico_utm(rutas, fin.geom, epsg, ruta_dem, float(plan.resolucion_dem), p.max_celdas)
        man.productos.append(RegistroProducto("dem", f"DEM {plan.resolucion_dem} m del área final (cuenca + "
                                              "margen), NoData fuera", man.rel(ruta_dem), None))
        self._registrar_descargas(man, dem, n_hist)
        n_hist = len(self.descargador.historial)

        # ---------------- fase 3: capas temáticas -----------------------------------
        ctx = self._contexto(fin, salida_xy, dl.poligono if dl else None)
        for prov in tematicos_activos(p.incluir, p.excluir):
            self.log(f"{prov.insumo} ({prov.dataset})…")
            try:
                pl = prov.planificar(ctx)
                if not pl.disponible:
                    man.errores.append(f"{prov.insumo}: {pl.mensaje}")
                    self.log(f"   no disponible: {pl.mensaje}")
                    continue
                for s in prov.ejecutar(ctx, pl):
                    man.productos.append(RegistroProducto(prov.clave, s.descripcion, man.rel(s.ruta),
                                                          s.n_elementos, s.nota))
                    self.log(f"   {s.descripcion}" + (f" — {s.n_elementos} elementos" if s.n_elementos else ""))
                    if pl.recursos and pl.recursos[0].metodo in ("ventana COG", "API"):
                        for r in pl.recursos[:1]:
                            man.descargas.append(RegistroDescarga(
                                prov.insumo, prov.dataset, prov.institucion, prov.licencia,
                                ctx.extra.get("osm_servidor", r.url), r.metodo, man.rel(s.ruta), None, None,
                                "", "leído por ventana" if r.metodo == "ventana COG" else "consulta API"))
            except (ErrorDescarga, OSError, ValueError, RuntimeError) as ex:
                man.errores.append(f"{prov.insumo}: {type(ex).__name__}: {ex}")
                self.log(f"   ERROR: {ex}")
            self._registrar_descargas(man, prov, n_hist)
            n_hist = len(self.descargador.historial)

        # ---------------- fase 4: manifiesto y reporte -------------------------------
        from .reporte import escribir_reporte
        res = ResultadoProyecto(self.raiz, dl, fin, it, man, Path(), ctx.extra)
        man.guardar(self.raiz / CARPETAS["resultados"])
        res.reporte = escribir_reporte(res, plan, self.params)
        return res

    # ================================================================== auxiliares
    def _registrar_descargas(self, man: Manifiesto, prov: Proveedor, desde: int) -> None:
        for r in self.descargador.historial[desde:]:
            man.descargas.append(RegistroDescarga(
                prov.insumo, prov.dataset, prov.institucion, prov.licencia, r.url, "descarga",
                man.rel(r.ruta), r.bytes, r.sha256, r.fecha,
                r.estado + (f" (idéntico a {Path(r.duplicado_de).name})" if r.duplicado_de else "")))

    def _guardar_puntos(self) -> None:
        e, epsg = self.entrada, self.entrada.sistema.epsg
        filas = [{"punto": "salida", "x": e.salida.x, "y": e.salida.y, "geometry": Point(e.salida.x, e.salida.y)}]
        if e.cabecera:
            filas.append({"punto": "cabecera", "x": e.cabecera.x, "y": e.cabecera.y,
                          "geometry": Point(e.cabecera.x, e.cabecera.y)})
        guardar_vector(gpd.GeoDataFrame(filas, crs=epsg),
                       self.raiz / CARPETAS["coordenadas"] / "puntos_entrada", self.params.formato_vector)

    def _guardar_delineacion(self, dl: ResultadoDelineacion, fin: AOI, aoi_trabajo: AOI) -> None:
        epsg, fmt, d = self.entrada.sistema.epsg, self.params.formato_vector, self.raiz / CARPETAS["procesados"]
        poli = dl.poligono
        guardar_vector(gpd.GeoDataFrame([{
            "nombre": self.entrada.nombre, "area_km2": round(dl.area_km2, 4),
            "perim_km": round(poli.length / 1000, 3), "metodo": "D8 + Priority-Flood (cuenca-insumos)",
            "aviso": "delineacion preliminar: verificar con GRASS/SAGA/ArcHydro", "geometry": poli}], crs=epsg),
            d / "cuenca_delineada", fmt)
        guardar_vector(gpd.GeoDataFrame([{"punto": "salida_ajustada", "desplaz_m": round(dl.desplazamiento_m, 1),
                                          "cota_m": round(dl.cota_salida, 1),
                                          "geometry": Point(dl.salida_ajustada)}], crs=epsg),
                       d / "salida_ajustada", fmt)
        if len(dl.cauce_xy) > 1:
            L = LineString(dl.cauce_xy[::-1])
            guardar_vector(gpd.GeoDataFrame([{"long_km": round(L.length / 1000, 3), "geometry": L}], crs=epsg),
                           d / "cauce_principal", fmt)
        c = self.raiz / CARPETAS["coordenadas"]
        guardar_vector(gpd.GeoDataFrame([{"area": "trabajo (DEM)", "km2": round(aoi_trabajo.area_km2, 2),
                                          "geometry": aoi_trabajo.geom},
                                         {"area": "final (capas)", "km2": round(fin.area_km2, 2),
                                          "geometry": fin.geom}], crs=epsg), c / "areas_de_analisis", fmt)


def fuentes_oficiales() -> list[dict]:
    return FUENTES_OFICIALES_PERU
