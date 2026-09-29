"""Diagnóstico de instalación de cuenca-insumos.

    python diagnostico.py

Solo usa la biblioteca estándar, así que funciona aunque falten las
dependencias o el propio paquete. Revisa, en orden, todo lo que suele impedir
que la herramienta arranque en una computadora nueva y dice cómo arreglarlo.
Código de salida: 0 si todo está bien; 2 si solo falta instalar el paquete o sus
librerías (se arregla con pip); 1 si hay otro problema (Python inadecuado, sin
Tkinter, sin internet...).
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import os
import platform
import struct
import sys
import tempfile
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DEPENDENCIAS = ["numpy", "rasterio", "pyproj", "shapely", "geopandas", "pyogrio", "requests"]
SITIOS = {
    "DEM Copernicus (AWS)": "https://copernicus-dem-30m.s3.amazonaws.com/tileList.txt",
    "HydroSHEDS": "https://www.hydrosheds.org/",
    "GeoNames": "https://download.geonames.org/export/dump/",
    "Sentinel-2 (Earth Search)": "https://earth-search.aws.element84.com/v1",
}
problemas: list[str] = []
falta_instalar = False


def ok(txt: str) -> None:
    print(f"  [OK]    {txt}")


def mal(txt: str, arreglo: str = "", instalable: bool = False) -> None:
    """``instalable``: se arregla instalando con pip (no cuenta como problema aparte)."""
    global falta_instalar
    print(f"  [FALLA] {txt}")
    for linea in arreglo.splitlines():
        print(f"          {linea}")
    if instalable:
        falta_instalar = True
    else:
        problemas.append(txt)


def aviso(txt: str) -> None:
    print(f"  [AVISO] {txt}")


def instalar_cmd() -> str:
    return f'"{sys.executable}" -m pip install -e "{AQUI}"'


def revisar_python() -> bool:
    print("\n1. Python")
    v = sys.version_info
    bits = struct.calcsize("P") * 8
    maquina = platform.machine().lower()
    print(f"          {sys.executable}")
    print(f"          Python {platform.python_version()}, {bits} bits, {platform.system()} {maquina}")
    listo = True
    if v < (3, 10):
        mal(f"Python {v.major}.{v.minor} es demasiado antiguo (se necesita 3.10 o superior).",
            "Instala Python 3.12 o 3.13 de 64 bits desde https://www.python.org/downloads/\n"
            "y marca «Add python.exe to PATH» en el instalador.")
        listo = False
    else:
        ok(f"versión {v.major}.{v.minor} (se necesita 3.10 o superior)")
    if bits != 64:
        mal("Python de 32 bits: rasterio, pyogrio y pandas no tienen versión para 32 bits.",
            "Desinstala este Python e instala la versión de 64 bits (Windows installer 64-bit)\n"
            "desde https://www.python.org/downloads/")
        listo = False
    else:
        ok("64 bits")
    if sys.platform == "win32" and maquina in ("arm64", "aarch64"):
        aviso("Windows en procesador ARM: algunas librerías geoespaciales no tienen versión para ARM.\n"
              "          Si la instalación falla, usa Python x64 (funciona por emulación) o conda-forge.")
    return listo


def revisar_tkinter() -> None:
    print("\n2. Tkinter (solo para la ventana; la terminal funciona sin él)")
    try:
        import tkinter
        ok(f"Tkinter {tkinter.TkVersion}")
    except ImportError:
        mal("Este Python no trae Tkinter: la ventana no puede abrirse.",
            "Vuelve a ejecutar el instalador de Python, elige «Modify» y marca «tcl/tk and IDLE».\n"
            "Mientras tanto puedes usar la terminal: python -m cuenca_insumos interactivo")


def revisar_dependencias() -> bool:
    print("\n3. Librerías")
    faltan = []
    for nombre in DEPENDENCIAS:
        try:
            importlib.import_module(nombre)
            ok(f"{nombre} {md.version(nombre)}")
        except Exception as ex:  # noqa: BLE001 - una DLL rota da OSError, no ImportError
            faltan.append(nombre)
            mal(f"{nombre}: {type(ex).__name__}: {ex}", instalable=True)
    return not faltan


def revisar_paquete() -> None:
    print("\n4. cuenca-insumos")
    try:
        dist = md.distribution("cuenca-insumos")
    except md.PackageNotFoundError:
        mal("cuenca-insumos no está instalado en este Python.", instalable=True)
        return
    ok(f"instalado, versión {dist.version}")
    try:
        mod = importlib.import_module("cuenca_insumos")
        ruta = Path(mod.__file__).resolve().parent
        ok(f"se importa desde {ruta}")
        if ruta.parent == AQUI / "src":
            return
        if (AQUI / "src" / "cuenca_insumos").exists():
            aviso("el paquete instalado no es el de esta carpeta: los cambios de aquí no se verán.\n"
                  f"          Para usar esta copia: {instalar_cmd()}")
    except Exception as ex:  # noqa: BLE001
        mal(f"está instalado pero no se puede importar: {type(ex).__name__}: {ex}",
            "Suele pasar si se movió o renombró la carpeta del proyecto después de instalarlo.",
            instalable=True)


def revisar_escritura() -> None:
    print("\n5. Permiso de escritura en la carpeta de trabajo")
    try:
        with tempfile.NamedTemporaryFile(dir=Path.cwd(), prefix=".prueba_", delete=True):
            pass
        ok(str(Path.cwd()))
    except OSError as ex:
        mal(f"no se puede escribir en {Path.cwd()}: {ex}",
            "Elige otra carpeta para guardar los proyectos (por ejemplo Documentos).")


def revisar_internet() -> None:
    print("\n6. Conexión con las fuentes de datos")
    for nombre, url in SITIOS.items():
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "cuenca-insumos-diagnostico"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ok(f"{nombre} (HTTP {r.status})")
        except Exception as ex:  # noqa: BLE001
            codigo = getattr(ex, "code", None)
            if codigo and codigo < 500:  # el servidor respondió: hay conexión
                ok(f"{nombre} (responde, HTTP {codigo})")
            else:
                mal(f"{nombre}: {type(ex).__name__}: {ex}",
                    "Revisa la conexión, el proxy o el firewall de la red (en redes de universidad\n"
                    "a veces se bloquean estas descargas).")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rapido = "--rapido" in sys.argv
    print("Diagnóstico de cuenca-insumos")
    print("=" * 60)
    if revisar_python():
        revisar_tkinter()
        revisar_dependencias()
        revisar_paquete()
        if not rapido:
            revisar_escritura()
            revisar_internet()
    print("\n" + "=" * 60)
    if not problemas and not falta_instalar:
        print("Todo en orden. Para abrir la herramienta:")
        print("  python -m cuenca_insumos ventana      (o doble clic en «Abrir cuenca-insumos.bat»)")
        return 0
    if falta_instalar:
        print("Falta instalar la herramienta o sus librerías. Ejecuta:")
        print(f"  {instalar_cmd()}")
        print("(necesita internet; descarga unos 60 MB y tarda uno o dos minutos)")
    if problemas:
        print(f"\nHay {len(problemas)} problema(s) que la instalación no resuelve: "
              "revisa las líneas [FALLA] de arriba.")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
