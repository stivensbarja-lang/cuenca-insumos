"""Interfaz de línea de comandos.

    cuenca-insumos analizar    --salida X Y [--cabecera X Y] --zona 18 --hemisferio S
    cuenca-insumos descargar   --salida X Y ... --proyecto Proyecto_Cuenca [--si]
    cuenca-insumos interactivo
    cuenca-insumos ventana       (interfaz gráfica)
    cuenca-insumos fuentes
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .config import Parametros
from .coords import ErrorCoordenadas, Punto, resolver_sistema
from .proyecto import EntradaCuenca, ProyectoCuenca
from .proveedores import TEMATICOS, CopernicusDEM
from .reporte import texto_plan

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


class _Barra:
    """Progreso mínimo en una línea, sin dependencias."""

    def __init__(self):
        self._t = 0.0

    def __call__(self, nombre: str, hecho: int, total: int | None) -> None:
        ahora = time.monotonic()
        if ahora - self._t < 0.5 and (total is None or hecho < total):
            return
        self._t = ahora
        txt = f"{hecho / 1e6:7.1f} MB" + (f" / {total / 1e6:.1f} MB ({100 * hecho / total:3.0f} %)" if total else "")
        sys.stdout.write(f"\r   ↓ {nombre[:48]:48} {txt}")
        sys.stdout.flush()
        if total and hecho >= total:
            sys.stdout.write("\n")


def _lista(v: str | None) -> set[str]:
    return {x.strip().lower() for x in v.split(",") if x.strip()} if v else set()


def _argumentos_comunes(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("ubicación")
    g.add_argument("--config", type=Path, help="archivo .toml con los datos (ver examples/)")
    g.add_argument("--salida", nargs=2, type=float, metavar=("X", "Y"), help="punto de salida (desembocadura)")
    g.add_argument("--cabecera", nargs=2, type=float, metavar=("X", "Y"),
                   help="punto de inicio del río (opcional, mejora el área y valida la salida)")
    g.add_argument("--epsg", type=int, help="EPSG de las coordenadas, p. ej. 32718")
    g.add_argument("--zona", type=int, help="zona UTM (Perú: 17, 18 o 19)")
    g.add_argument("--hemisferio", choices=["N", "S", "n", "s"])
    g.add_argument("--datum", default="WGS84", help="WGS84 (defecto), SIRGAS2000 o PSAD56")
    g.add_argument("--nombre", default=None)
    g.add_argument("--area-estimada", type=float, help="área aproximada en km² (si no hay cabecera)")
    o = p.add_argument_group("opciones")
    o.add_argument("--pais", default=None, help="ISO3 del país (defecto PER)")
    o.add_argument("--dem", choices=["auto", "30", "90"], default=None)
    o.add_argument("--incluir", help=f"insumos opcionales separados por coma ({', '.join(TEMATICOS)})")
    o.add_argument("--excluir", help="insumos a omitir, separados por coma")
    o.add_argument("--sin-delinear", action="store_true", help="no delinear: usar solo el área preliminar")
    o.add_argument("--forma-aoi", choices=["rectangulo", "corredor"],
                   help="forma del área preliminar cuando hay cabecera (defecto: rectangulo)")
    o.add_argument("--k-corredor", type=float, help="margen como fracción de la distancia cabecera-salida")
    o.add_argument("--continente", help="región HydroSHEDS si no se detecta (sa, na, af, eu, as, au)")
    o.add_argument("--formato", choices=["gpkg", "shp"], default=None, help="formato vectorial de salida")
    o.add_argument("--cache", type=Path, help="carpeta de caché compartida entre proyectos")


def _desde_args(a: argparse.Namespace) -> tuple[EntradaCuenca, Parametros]:
    cfg: dict = {}
    if a.config:
        with open(a.config, "rb") as fh:
            cfg = tomllib.load(fh)
    pc = cfg.get("parametros", {})

    def val(nombre, defecto=None):
        v = getattr(a, nombre.replace("-", "_"), None)
        return v if v not in (None, False) else cfg.get(nombre, defecto)

    sal = a.salida or ([cfg["salida"]["x"], cfg["salida"]["y"]] if "salida" in cfg else None)
    cab = a.cabecera or ([cfg["cabecera"]["x"], cfg["cabecera"]["y"]] if "cabecera" in cfg else None)
    if sal is None:
        raise ErrorCoordenadas("Falta el punto de salida (--salida X Y o [salida] en el .toml).")
    sis = resolver_sistema(val("epsg"), val("zona"), val("hemisferio"), val("datum", "WGS84"))
    entrada = EntradaCuenca(
        salida=Punto(float(sal[0]), float(sal[1]), sis.epsg, "Punto de salida"),
        cabecera=Punto(float(cab[0]), float(cab[1]), sis.epsg, "Punto de cabecera") if cab else None,
        sistema=sis, nombre=val("nombre", "Cuenca"), area_estimada_km2=val("area_estimada"))

    p = Parametros(**{k: v for k, v in pc.items() if k not in ("incluir", "excluir")})
    p.incluir = _lista(a.incluir) | set(pc.get("incluir", []))
    p.excluir = _lista(a.excluir) | set(pc.get("excluir", []))
    for attr, arg in (("pais", a.pais), ("resolucion_dem", a.dem), ("k_corredor", a.k_corredor),
                      ("forma_aoi", getattr(a, "forma_aoi", None)),
                      ("continente", a.continente), ("formato_vector", a.formato)):
        if arg is not None:
            setattr(p, attr, arg)
    if a.sin_delinear:
        p.delinear = False
    p.validar()
    return entrada, p


def _confirmar(msg: str) -> bool:
    try:
        return input(f"{msg} [s/N]: ").strip().lower() in {"s", "si", "sí", "y", "yes"}
    except EOFError:
        return False


def _ejecutar(entrada, params, carpeta: Path | None, cache, descargar: bool, si: bool) -> int:
    carpeta = carpeta or Path(f"Proyecto_{entrada.nombre.replace(' ', '_')}")
    proy = ProyectoCuenca(entrada, carpeta, params, cache, log=print, progreso=_Barra())
    print("Analizando el área (sin descargar datos)…")
    plan = proy.analizar()
    print(texto_plan(plan))
    if not descargar:
        print("\nPara descargar: repite el comando con «descargar» en lugar de «analizar».")
        return 0
    if not si and not _confirmar("\n¿Desea descargar los insumos?"):
        print("Cancelado.")
        return 1
    res = proy.descargar(plan)
    print(f"\nListo. Proyecto en: {res.raiz.resolve()}")
    print(f"Reporte: {res.reporte.resolve()}")
    if res.manifiesto.errores:
        print(f"Avisos: {len(res.manifiesto.errores)} (ver «Avisos y capas no disponibles» en el reporte)")
    return 0


def _interactivo() -> int:
    print("cuenca-insumos — modo interactivo (Enter deja el valor por defecto)\n")

    def num(msg, opcional=False):
        while True:
            v = input(msg).strip().replace(",", ".")
            if not v and opcional:
                return None
            try:
                return float(v)
            except ValueError:
                print("   Escribe un número.")

    print("Ingrese coordenada del punto de SALIDA (desembocadura):")
    sx, sy = num("  X: "), num("  Y: ")
    print("Ingrese coordenada del punto INICIAL del río (Enter para omitir):")
    cx = num("  X: ", opcional=True)
    cy = num("  Y: ") if cx is not None else None
    zona = input("Zona UTM [18]: ").strip() or "18"
    hemi = input("Hemisferio [S]: ").strip() or "S"
    epsg = input("EPSG (Enter para deducirlo de la zona): ").strip()
    nombre = input("Nombre de la cuenca [Cuenca]: ").strip() or "Cuenca"
    sis = resolver_sistema(int(epsg) if epsg else None, int(zona), hemi)
    print(f"   → {sis.nombre} (EPSG:{sis.epsg})")
    entrada = EntradaCuenca(Punto(sx, sy, sis.epsg, "Punto de salida"), sis,
                            Punto(cx, cy, sis.epsg, "Punto de cabecera") if cx is not None else None, nombre)
    return _ejecutar(entrada, Parametros(), None, None, descargar=True, si=False)


def _fuentes() -> int:
    provs = [CopernicusDEM()] + [c() for c in TEMATICOS.values()]
    for p in provs:
        f = p.ficha()
        print(f"\n[{f['clave']}] {f['insumo']}  {'(por defecto)' if p.por_defecto else '(opcional: --incluir ' + p.clave + ')'}")
        for k in ("dataset", "institucion", "resolucion", "formato", "cobertura", "crs", "url_info",
                  "metodo", "requiere_auth", "licencia", "uso"):
            print(f"   {k:14} {f[k]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cuenca-insumos", description=__doc__.splitlines()[0] if __doc__ else "",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("analizar", help="muestra qué se descargaría, sin descargar datos")
    _argumentos_comunes(a1)
    a2 = sub.add_parser("descargar", help="descarga, verifica, recorta y organiza los insumos")
    _argumentos_comunes(a2)
    a2.add_argument("--proyecto", type=Path, help="carpeta de salida (defecto Proyecto_<nombre>)")
    a2.add_argument("--si", action="store_true", help="no pedir confirmación")
    sub.add_parser("interactivo", help="pide los datos paso a paso")
    av = sub.add_parser("ventana", help="abre la interfaz gráfica")
    av.add_argument("--sin-consola", action="store_true", help="abrirla aparte, sin ventana de consola (Windows)")
    sub.add_parser("fuentes", help="lista las fuentes de datos y sus licencias")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        if a.cmd == "fuentes":
            return _fuentes()
        if a.cmd == "interactivo":
            return _interactivo()
        if a.cmd == "ventana":
            from . import gui  # Tkinter solo se carga si se pide la ventana
            return gui.main_sin_consola() if a.sin_consola else gui.main()
        entrada, params = _desde_args(a)
        return _ejecutar(entrada, params, getattr(a, "proyecto", None), a.cache,
                         descargar=a.cmd == "descargar", si=getattr(a, "si", False))
    except ErrorCoordenadas as e:
        print(f"\nERROR en las coordenadas: {e}", file=sys.stderr)
        return 2
    except (ValueError, MemoryError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido. Lo ya descargado queda en la caché y se reutilizará.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
