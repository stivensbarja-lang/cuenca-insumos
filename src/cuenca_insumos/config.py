"""Parámetros por defecto y constantes de la herramienta.

Los valores del área preliminar (forma, margen) salen de un experimento con 240
cuencas reales de 1 a 150 km² en Chanchamayo (Junín, Perú); el resumen está en
el README, sección «¿Por qué el punto de salida y no dos puntos?».
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Parametros", "CARPETAS", "USER_AGENT"]

USER_AGENT = (
    "cuenca-insumos/0.1 (+https://github.com/stivensbarja-lang/cuenca-insumos; "
    "herramienta academica de hidrologia)"
)
"""Algunos servidores (p. ej. Overpass) rechazan con HTTP 406 las peticiones sin
un User-Agent identificable. Cámbialo por tu propio repositorio al publicar."""

CARPETAS: dict[str, str] = {
    "coordenadas": "01_Coordenadas",
    "dem": "02_DEM",
    "hidrografia": "03_Hidrografia",
    "cobertura": "04_Cobertura_Uso_Suelo",
    "suelos": "05_Suelos",
    "clima": "06_Clima",
    "limites": "07_Limites",
    "imagenes": "08_Imagenes_Satelitales",
    "procesados": "09_Procesados",
    "resultados": "10_Resultados",
}


@dataclass
class Parametros:
    """Parámetros ajustables del análisis. Los valores por defecto funcionan
    para microcuencas y subcuencas andinas (1 a 5 000 km²)."""

    # --- Área de interés preliminar -------------------------------------------
    forma_aoi: str = "rectangulo"
    """"rectangulo" (rectángulo de los dos puntos + margen) o "corredor" (franja
    alrededor del segmento). En el experimento, el rectángulo descargó menos tiles."""
    k_corredor: float = 0.6
    """Margen como fracción de la distancia L entre cabecera y salida. Con el
    rectángulo y k = 0.6, en 240 cuencas de prueba: 88 % resueltas sin ampliar,
    1.26 tiles descargados por cuenca y 0.10 innecesarios (la menor cifra de
    todas las estrategias). k = 0.8 casi elimina las segundas descargas a cambio
    de procesar un 35 % más de área."""
    buffer_minimo_m: float = 1000.0
    """Semiancho mínimo del corredor: evita corredores ridículos si L es corta."""
    radio_sin_cabecera_m: float = 10_000.0
    """Radio alrededor de la salida cuando no hay cabecera ni área estimada."""
    factor_radio_area: float = 1.5
    """Con área estimada A, radio = factor · 1.78 · A^0.49 (Montgomery y Dietrich, 1992)."""

    # --- Delineación y expansión iterativa --------------------------------------
    delinear: bool = True
    factor_expansion: float = 1.6
    max_iteraciones: int = 4
    umbral_cauce_km2: float = 0.1
    """Área de aporte mínima para considerar que una celda es cauce (ajuste de la salida)."""
    radio_ajuste_m: float = 150.0
    """Distancia máxima a la que se mueve el punto de salida para caer sobre el cauce."""
    max_celdas: int = 30_000_000
    """Tope de celdas del DEM a procesar en memoria (evita colgar equipos modestos)."""

    # --- Área final para las capas temáticas -----------------------------------
    margen_final_min_m: float = 1000.0
    margen_final_frac: float = 0.10
    """Margen del área final = max(mínimo, fracción · longitud de la cuenca)."""

    # --- DEM ---------------------------------------------------------------------
    resolucion_dem: str = "auto"
    """"30", "90" o "auto" (90 m si el área preliminar supera ``umbral_glo90_km2``)."""
    umbral_glo90_km2: float = 20_000.0
    relleno_tiles_m: float = 100.0
    """Colchón extra (≈3 celdas) al elegir tiles, para que el remuestreo no deje bordes vacíos."""

    # --- Salida ------------------------------------------------------------------
    formato_vector: str = "gpkg"
    """"gpkg" (recomendado) o "shp" (por compatibilidad con ArcMap 10.x)."""
    pais: str = "PER"
    """Código ISO3 del país para límites administrativos y toponimia (GADM, GeoNames)."""
    continente: str | None = None
    """Región HydroSHEDS ("sa", "na", "af"…). None = detección automática."""

    incluir: set[str] = field(default_factory=set)
    excluir: set[str] = field(default_factory=set)

    def validar(self) -> None:
        if not 0.05 <= self.k_corredor <= 5:
            raise ValueError("k_corredor debe estar entre 0.05 y 5")
        if self.forma_aoi not in {"rectangulo", "corredor"}:
            raise ValueError('forma_aoi debe ser "rectangulo" o "corredor"')
        if self.resolucion_dem not in {"auto", "30", "90"}:
            raise ValueError('resolucion_dem debe ser "auto", "30" o "90"')
        if self.formato_vector not in {"gpkg", "shp"}:
            raise ValueError('formato_vector debe ser "gpkg" o "shp"')
        if len(self.pais) != 3 or not self.pais.isalpha():
            raise ValueError("pais debe ser un código ISO3, p. ej. PER")
        self.pais = self.pais.upper()
