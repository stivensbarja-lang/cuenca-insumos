"""Registro de procedencia: qué se descargó, de dónde, con qué licencia y qué se generó."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

__all__ = ["Manifiesto", "RegistroDescarga", "RegistroProducto"]


@dataclass
class RegistroDescarga:
    insumo: str
    dataset: str
    institucion: str
    licencia: str
    url: str
    metodo: str
    ruta: str
    bytes: int | None
    sha256: str | None
    fecha: str
    estado: str


@dataclass
class RegistroProducto:
    insumo: str
    descripcion: str
    ruta: str | None
    n_elementos: int | None
    nota: str = ""


@dataclass
class Manifiesto:
    raiz: Path
    entrada: dict
    descargas: list[RegistroDescarga] = field(default_factory=list)
    productos: list[RegistroProducto] = field(default_factory=list)
    decisiones: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    def rel(self, p) -> str | None:
        if p is None:
            return None
        try:
            return str(Path(p).resolve().relative_to(self.raiz.resolve())).replace("\\", "/")
        except ValueError:
            return str(p)

    def guardar(self, carpeta: Path) -> tuple[Path, Path]:
        carpeta.mkdir(parents=True, exist_ok=True)
        js = carpeta / "manifiesto.json"
        doc = {
            "herramienta": f"cuenca-insumos {__version__}",
            "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entrada": self.entrada,
            "decisiones": self.decisiones,
            "descargas": [asdict(d) for d in self.descargas],
            "productos": [asdict(p) for p in self.productos],
            "errores": self.errores,
        }
        js.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        cs = carpeta / "manifiesto_descargas.csv"
        with open(cs, "w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig: Excel abre bien las tildes
            w = csv.DictWriter(fh, fieldnames=list(RegistroDescarga.__dataclass_fields__))
            w.writeheader()
            for d in self.descargas:
                w.writerow(asdict(d))
        return js, cs
