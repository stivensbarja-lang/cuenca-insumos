"""Validación de coordenadas de entrada y conversión entre sistemas de referencia.

La herramienta trabaja con coordenadas UTM (lo habitual en los trabajos de campo
y en la cartografía peruana), pero acepta cualquier EPSG proyectado o geográfico.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

__all__ = [
    "ErrorCoordenadas", "SistemaReferencia", "Punto",
    "resolver_sistema", "validar_puntos", "verificar_en_tierra", "a_lonlat", "transformador",
]

# Familias de EPSG UTM por datum: base + número de zona.
_BASES_UTM = {
    ("WGS84", "N"): 32600, ("WGS84", "S"): 32700,
    ("SIRGAS2000", "S"): 31960,   # 31977 = zona 17S … 31979 = 19S
    ("PSAD56", "S"): 24860,       # 24877 = zona 17S … 24879 = 19S
}

# Extensiones aproximadas por país (lon_min, lat_min, lon_max, lat_max) para
# detectar zonas UTM equivocadas. Ampliable.
EXTENSION_PAIS = {
    "PER": (-81.4, -18.4, -68.6, 0.0),
    "BOL": (-69.7, -22.9, -57.4, -9.6),
    "ECU": (-81.1, -5.1, -75.1, 1.5),
    "COL": (-79.1, -4.3, -66.8, 12.5),
    "CHL": (-75.8, -56.0, -66.4, -17.4),
}


class ErrorCoordenadas(ValueError):
    """Error de validación de las coordenadas de entrada (mensaje para el usuario)."""


@dataclass(frozen=True)
class SistemaReferencia:
    epsg: int
    nombre: str
    zona: int | None
    hemisferio: str | None
    geografico: bool

    @property
    def crs(self) -> CRS:
        return CRS.from_epsg(self.epsg)


@dataclass(frozen=True)
class Punto:
    x: float
    y: float
    epsg: int
    etiqueta: str = ""

    def lonlat(self) -> tuple[float, float]:
        return a_lonlat(self.x, self.y, self.epsg)


def transformador(origen: int, destino: int) -> Transformer:
    return Transformer.from_crs(origen, destino, always_xy=True)


def a_lonlat(x: float, y: float, epsg: int) -> tuple[float, float]:
    if epsg == 4326:
        return float(x), float(y)
    lon, lat = transformador(epsg, 4326).transform(x, y)
    return float(lon), float(lat)


def resolver_sistema(epsg: int | None = None, zona: int | None = None,
                     hemisferio: str | None = None, datum: str = "WGS84") -> SistemaReferencia:
    """Determina el sistema de referencia a partir del EPSG y/o zona + hemisferio,
    comprobando que ambos sean coherentes cuando se dan los dos."""
    if hemisferio is not None:
        hemisferio = hemisferio.strip().upper()[:1]
        if hemisferio not in {"N", "S"}:
            raise ErrorCoordenadas('El hemisferio debe ser "N" (norte) o "S" (sur).')
    if zona is not None and not 1 <= int(zona) <= 60:
        raise ErrorCoordenadas(f"La zona UTM {zona} no existe (debe estar entre 1 y 60).")

    if epsg is None:
        if zona is None or hemisferio is None:
            raise ErrorCoordenadas("Indica el EPSG, o bien la zona UTM y el hemisferio.")
        clave = (datum.upper().replace(" ", "").replace("-", ""), hemisferio)
        if clave not in _BASES_UTM:
            raise ErrorCoordenadas(f"Datum no soportado para zona/hemisferio: {datum}. "
                                   "Usa WGS84, SIRGAS2000 o PSAD56, o indica el EPSG directamente.")
        epsg = _BASES_UTM[clave] + int(zona)

    try:
        crs = CRS.from_epsg(int(epsg))
    except CRSError as e:
        raise ErrorCoordenadas(f"El EPSG {epsg} no existe.") from e

    geografico = crs.is_geographic
    zona_crs = hemi_crs = None
    if crs.utm_zone:
        zona_crs, hemi_crs = int(crs.utm_zone[:-1]), crs.utm_zone[-1]
    elif not geografico:
        raise ErrorCoordenadas(
            f"EPSG:{epsg} ({crs.name}) no es UTM ni geográfico. Usa un sistema UTM "
            "(p. ej. EPSG:32718 = WGS 84 / UTM zona 18S) o EPSG:4326.")

    if zona is not None and zona_crs is not None and int(zona) != zona_crs:
        raise ErrorCoordenadas(
            f"Incoherencia: indicaste la zona {zona}, pero EPSG:{epsg} corresponde a la zona {zona_crs}{hemi_crs}.")
    if hemisferio is not None and hemi_crs is not None and hemisferio != hemi_crs:
        raise ErrorCoordenadas(
            f"Incoherencia: indicaste hemisferio {hemisferio}, pero EPSG:{epsg} es del hemisferio {hemi_crs}.")

    return SistemaReferencia(int(epsg), crs.name, zona_crs, hemi_crs, geografico)


def _validar_rango(p: Punto, sis: SistemaReferencia) -> None:
    nom = p.etiqueta or "punto"
    if sis.geografico:
        if not (-180 <= p.x <= 180 and -90 <= p.y <= 90):
            raise ErrorCoordenadas(f"{nom}: longitud/latitud fuera de rango ({p.x}, {p.y}).")
        return
    if not 100_000 <= p.x <= 900_000:
        raise ErrorCoordenadas(
            f"{nom}: X = {p.x:,.0f} no es un Este UTM válido (debe estar entre 100 000 y 900 000 m). "
            "¿Intercambiaste X e Y?")
    if not 0 <= p.y <= 10_000_000:
        raise ErrorCoordenadas(f"{nom}: Y = {p.y:,.0f} no es un Norte UTM válido (0 a 10 000 000 m).")


def _dentro(lon: float, lat: float, ext: tuple[float, float, float, float]) -> bool:
    return ext[0] <= lon <= ext[2] and ext[1] <= lat <= ext[3]


def _sugerir_zona(p: Punto, sis: SistemaReferencia, ext=None,
                  en_tierra: Callable[[float, float], bool] | None = None) -> str:
    """Prueba zonas vecinas para ver en cuál el punto caería en tierra y dentro del país."""
    if sis.zona is None or sis.hemisferio is None:
        return ""
    base = sis.epsg - sis.zona
    for z in sorted(range(max(1, sis.zona - 3), min(60, sis.zona + 3) + 1), key=lambda z: abs(z - sis.zona)):
        if z == sis.zona:
            continue
        try:
            lon, lat = a_lonlat(p.x, p.y, base + z)
        except Exception:
            continue
        if (ext is None or _dentro(lon, lat, ext)) and (en_tierra is None or en_tierra(lon, lat)):
            return f" Con la zona {z}{sis.hemisferio} (EPSG:{base + z}) el punto sí cae en tierra, dentro del país."
    return ""


def verificar_en_tierra(p: Punto, sis: SistemaReferencia, en_tierra: Callable[[float, float], bool],
                        pais: str | None = "PER") -> None:
    """Error si el punto cae donde no hay DEM (océano). Es el síntoma típico de una
    zona UTM equivocada que el rectángulo del país no alcanza a detectar: con la
    zona 17, las coordenadas de San Ramón (zona 18) caen en el Pacífico, a −81.4°."""
    lon, lat = p.lonlat()
    if en_tierra(lon, lat):
        return
    ext = EXTENSION_PAIS.get((pais or "").upper())
    raise ErrorCoordenadas(
        f"{p.etiqueta or 'punto'} cae en lon {lon:.4f}°, lat {lat:.4f}°, en el océano (no hay modelo "
        "de elevación ahí). Lo más probable es una zona UTM equivocada." + _sugerir_zona(p, sis, ext, en_tierra))


def validar_puntos(salida: Punto, cabecera: Punto | None,
                   sis: SistemaReferencia, pais: str | None = "PER") -> list[str]:
    """Valida los puntos de entrada. Lanza ``ErrorCoordenadas`` ante errores y
    devuelve una lista de advertencias no bloqueantes."""
    avisos: list[str] = []
    puntos = [salida] + ([cabecera] if cabecera else [])
    for p in puntos:
        if p.epsg != sis.epsg:
            raise ErrorCoordenadas(
                f"{p.etiqueta or 'Un punto'} está en EPSG:{p.epsg} y el proyecto en EPSG:{sis.epsg}. "
                "Ambas coordenadas deben estar en el mismo sistema de referencia.")
        if any(math.isnan(v) or math.isinf(v) for v in (p.x, p.y)):
            raise ErrorCoordenadas(f"{p.etiqueta or 'punto'}: coordenada vacía o no numérica.")
        _validar_rango(p, sis)

        lon, lat = p.lonlat()
        au = sis.crs.area_of_use
        if au is not None and not sis.geografico:
            tol = 1.5  # grados: UTM se usa a menudo algo fuera de su huso nominal
            if not (au.west - tol <= lon <= au.east + tol and au.south - tol <= lat <= au.north + tol):
                raise ErrorCoordenadas(
                    f"{p.etiqueta or 'punto'} cae en lon {lon:.3f}°, lat {lat:.3f}°, fuera del área de uso "
                    f"de {sis.nombre}. Revisa la zona UTM y el hemisferio.")
        ext = EXTENSION_PAIS.get((pais or "").upper())
        if ext and not _dentro(lon, lat, ext):
            raise ErrorCoordenadas(
                f"{p.etiqueta or 'punto'} cae en lon {lon:.4f}°, lat {lat:.4f}°, fuera de {pais}. "
                "Lo más probable es una zona UTM equivocada." + _sugerir_zona(p, sis, ext))

    if cabecera:
        if sis.geografico:
            (x1, y1), (x2, y2) = salida.lonlat(), cabecera.lonlat()
            d = math.hypot((x2 - x1) * 111_320 * math.cos(math.radians(y1)), (y2 - y1) * 110_570)
        else:
            d = math.hypot(cabecera.x - salida.x, cabecera.y - salida.y)
        if d < 60:
            raise ErrorCoordenadas(
                f"La cabecera y la salida están a solo {d:.0f} m: son prácticamente el mismo punto.")
        if d > 1_000_000:
            raise ErrorCoordenadas(
                f"La cabecera y la salida están a {d / 1000:,.0f} km. Revisa las coordenadas.")
        if d < 300:
            avisos.append(f"Cabecera y salida están a solo {d:.0f} m: la cabecera aporta poca información.")
    return avisos
