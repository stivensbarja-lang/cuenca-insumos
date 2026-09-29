"""Interfaz común de los proveedores de datos.

Agregar una fuente nueva = crear una subclase de ``Proveedor`` con su ficha
(atributos de clase) y sus métodos ``planificar`` y ``ejecutar``, y registrarla
en ``proveedores/__init__.py``. El resto de la herramienta no cambia.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # evita importaciones circulares
    from ..contexto import Contexto

__all__ = ["Recurso", "Plan", "Salida", "Proveedor"]


@dataclass
class Recurso:
    url: str
    descripcion: str
    metodo: str                        # "descarga" | "ventana COG" | "API"
    bytes_estimados: int | None = None
    nombre_archivo: str | None = None
    reutilizable: bool = False         # archivo continental/nacional que la caché reutiliza
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    disponible: bool
    mensaje: str
    recursos: list[Recurso] = field(default_factory=list)

    @property
    def bytes_estimados(self) -> int:
        return sum(r.bytes_estimados or 0 for r in self.recursos)


@dataclass
class Salida:
    ruta: Path | None
    descripcion: str
    n_elementos: int | None = None
    nota: str = ""


class Proveedor(ABC):
    # ---- ficha técnica (se imprime con `cuenca-insumos fuentes`) ----------------
    clave: str = ""
    carpeta: str = ""                  # clave de config.CARPETAS
    insumo: str = ""
    dataset: str = ""
    institucion: str = ""
    resolucion: str = ""
    formato: str = ""
    cobertura: str = ""
    crs: str = ""
    url_info: str = ""
    metodo: str = ""
    requiere_auth: bool = False
    licencia: str = ""
    cita: str = ""
    por_defecto: bool = True
    uso: str = ""
    """Para qué sirve el insumo en un análisis de cuenca."""

    @abstractmethod
    def planificar(self, ctx: "Contexto") -> Plan:
        """Decide qué recursos hacen falta para el AOI. No descarga datos pesados."""

    @abstractmethod
    def ejecutar(self, ctx: "Contexto", plan: Plan) -> list[Salida]:
        """Descarga, verifica, recorta y guarda. Devuelve los productos generados."""

    def ficha(self) -> dict[str, str]:
        return {k: str(getattr(self, k)) for k in (
            "clave", "insumo", "dataset", "institucion", "resolucion", "formato", "cobertura",
            "crs", "url_info", "metodo", "requiere_auth", "licencia", "cita", "por_defecto",
            "uso")}
