"""Fuentes oficiales peruanas equivalentes que NO pueden descargarse por script.

Se verificó (setiembre de 2026) que exigen interacción en el navegador: el
Geoservidor del MINAM y el geoportal de la ANA están detrás de un filtro
anti-bots (Incapsula) y el SIGMED del MINEDU entrega las cartas IGN solo tras
un formulario ASP.NET. La herramienta las lista con instrucciones para que el
usuario las agregue a mano si su docente o entidad exige la fuente oficial.
"""
from __future__ import annotations

__all__ = ["FUENTES_OFICIALES_PERU"]

FUENTES_OFICIALES_PERU = [
    {
        "insumo": "Red hidrográfica y unidades hidrográficas oficiales",
        "fuente": "Autoridad Nacional del Agua (ANA) — Sistema Nacional de Información de Recursos Hídricos",
        "equivalente_automatico": "HydroRIVERS + HydroBASINS",
        "carpeta": "03_Hidrografia",
        "como": "https://snirh.ana.gob.pe (capas «Ríos y quebradas» y «Unidades hidrográficas», descarga "
                "desde el navegador); o la redistribución académica de https://www.geogpsperu.com.",
    },
    {
        "insumo": "Carta Nacional 1:100 000 (curvas, ríos, cotas, centros poblados)",
        "fuente": "Instituto Geográfico Nacional (IGN), distribuida por SIGMED-MINEDU",
        "equivalente_automatico": "Curvas y red derivadas del DEM; toponimia GeoNames",
        "carpeta": "03_Hidrografia",
        "como": "https://sigmed.minedu.gob.pe/descargas/ → «Por número de hoja» → elegir la hoja "
                "(p. ej. 23-m «La Merced» para San Ramón). La hoja se calcula con la grilla IGN de 30′.",
    },
    {
        "insumo": "Límites político-administrativos oficiales",
        "fuente": "Instituto Nacional de Estadística e Informática (INEI) / IGN",
        "equivalente_automatico": "GADM 4.1",
        "carpeta": "07_Limites",
        "como": "https://www.datosabiertos.gob.pe o https://www.geogpsperu.com. Mantén el campo SEL "
                "si reemplazas las capas generadas.",
    },
    {
        "insumo": "Precipitación y estaciones meteorológicas (si se modela el caudal)",
        "fuente": "SENAMHI — datos hidrometeorológicos y PISCO",
        "equivalente_automatico": "CHIRPS v2.0 (no activado: la delimitación y la morfometría no lo requieren)",
        "carpeta": "06_Clima",
        "como": "https://www.senamhi.gob.pe/?p=descarga-datos-hidrometeorologicos (estaciones) y "
                "PISCO (grillado).",
    },
]


# --- Hojas de la Carta Nacional 1:100 000 del IGN -------------------------------
# Grilla de 30' × 30'. Filas numeradas desde el ecuador hacia el sur; columnas
# con letras desde 81°30' O. La secuencia incluye la «ñ» y omite la «w».
# Verificado contra el listado oficial de SIGMED (504 hojas) y con localidades de
# coordenadas conocidas: 23-m La Merced, 22-m Oxapampa, 32-v Puno, 33-x Ilave,
# 33-y Juli, 33-z Isla Anapia.
_LETRAS_IGN = "abcdefghijklmnñopqrstuvxyz"
_OESTE_IGN = -81.5


def hoja_ign(lon: float, lat: float) -> str | None:
    """Código de la hoja IGN 1:100 000 que contiene el punto (p. ej. '23-m')."""
    fila = int(-lat // 0.5) + 1
    col = int((lon - _OESTE_IGN) // 0.5)
    if lat > 0 or fila > 39 or not 0 <= col < len(_LETRAS_IGN):
        return None
    return f"{fila:02d}-{_LETRAS_IGN[col]}"


def hojas_ign(poligono_lonlat) -> list[str]:
    """Todas las hojas IGN que intersecta un polígono en EPSG:4326."""
    import math

    from shapely.geometry import box

    w, s, e, n = poligono_lonlat.bounds
    out = []
    lat = min(0.0, math.ceil(n / 0.5) * 0.5)      # línea de la grilla en o sobre el borde norte
    while lat > s:
        lon = _OESTE_IGN + ((w - _OESTE_IGN) // 0.5) * 0.5
        while lon < e:
            celda = box(lon, lat - 0.5, lon + 0.5, lat)
            if celda.intersection(poligono_lonlat).area > 1e-10:
                h = hoja_ign(lon + 0.25, lat - 0.25)
                if h:
                    out.append(h)
            lon += 0.5
        lat -= 0.5
    return sorted(set(out))
