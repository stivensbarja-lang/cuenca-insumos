"""Descargas robustas: reintentos, reanudación, verificación de integridad,
caché y detección de duplicados por contenido (SHA-256)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT

__all__ = ["Descargador", "ResultadoDescarga", "ErrorDescarga", "verificar_archivo", "sha256"]

Progreso = Callable[[str, int, int | None], None]   # (nombre, bytes_hechos, bytes_totales)


class ErrorDescarga(RuntimeError):
    pass


@dataclass
class ResultadoDescarga:
    url: str
    ruta: Path
    bytes: int
    sha256: str
    estado: str            # "descargado" | "reutilizado" | "duplicado"
    fecha: str
    duplicado_de: str | None = None


def sha256(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for b in iter(lambda: fh.read(bloque), b""):
            h.update(b)
    return h.hexdigest()


def verificar_archivo(ruta: Path, bytes_esperados: int | None = None, tipo: str | None = None) -> None:
    """Comprueba que el archivo esté completo y se pueda abrir. Lanza ErrorDescarga si no."""
    if not ruta.exists() or ruta.stat().st_size == 0:
        raise ErrorDescarga(f"{ruta.name}: archivo vacío o inexistente")
    if bytes_esperados and ruta.stat().st_size != bytes_esperados:
        raise ErrorDescarga(f"{ruta.name}: tamaño {ruta.stat().st_size:,} B, se esperaban "
                            f"{bytes_esperados:,} B (descarga incompleta)")
    suf = "".join(Path(tipo or ruta.name).suffixes[-2:]).lower()   # tipo: nombre final si ruta es .part
    try:
        if suf.endswith(".zip"):
            with zipfile.ZipFile(ruta) as z:
                malo = z.testzip()
                if malo:
                    raise ErrorDescarga(f"{ruta.name}: el miembro {malo} está dañado")
        elif suf.endswith((".tif", ".tiff")):
            import rasterio
            with rasterio.open(ruta) as ds:
                ds.read(1, window=((0, min(8, ds.height)), (0, min(8, ds.width))))
        elif suf.endswith((".json", ".geojson")):
            with open(ruta, encoding="utf-8") as fh:
                json.load(fh)
    except ErrorDescarga:
        raise
    except Exception as e:  # noqa: BLE001 - cualquier fallo de lectura invalida el archivo
        raise ErrorDescarga(f"{ruta.name}: no se puede abrir ({e})") from e


class Descargador:
    """Gestor de descargas con caché local.

    La caché se indexa por URL (``_indice.json``) y el registro de contenidos por
    SHA-256 (``_registro.json``) permite detectar dos URLs distintas que sirven el
    mismo archivo.
    """

    def __init__(self, cache: Path, reintentos: int = 4, timeout: tuple[int, int] = (20, 180),
                 progreso: Progreso | None = None):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.progreso = progreso
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = USER_AGENT
        reint = Retry(total=reintentos, backoff_factor=2.0,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET", "HEAD", "POST"}),
                      respect_retry_after_header=True)
        ad = HTTPAdapter(max_retries=reint)
        self.sesion.mount("https://", ad)
        self.sesion.mount("http://", ad)
        self._indice_f = self.cache / "_indice.json"
        self._registro_f = self.cache / "_registro.json"
        self.indice: dict[str, dict] = self._leer(self._indice_f)
        self.historial: list[ResultadoDescarga] = []   # para el manifiesto del proyecto
        self.registro: dict[str, str] = self._leer(self._registro_f)

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def _leer(f: Path) -> dict:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _guardar(self) -> None:
        self._indice_f.write_text(json.dumps(self.indice, indent=1, ensure_ascii=False), encoding="utf-8")
        self._registro_f.write_text(json.dumps(self.registro, indent=1, ensure_ascii=False), encoding="utf-8")

    def tamano(self, url: str) -> int | None:
        """Tamaño remoto (HEAD). None si el servidor no lo informa."""
        try:
            r = self.sesion.head(url, allow_redirects=True, timeout=self.timeout)
            if r.status_code == 200 and r.headers.get("Content-Length"):
                return int(r.headers["Content-Length"])
        except requests.RequestException:
            pass
        return None

    def existe(self, url: str) -> bool:
        try:
            r = self.sesion.head(url, allow_redirects=True, timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------ descarga
    def obtener(self, url: str, nombre: str | None = None, bytes_esperados: int | None = None,
                subcarpeta: str = "") -> ResultadoDescarga:
        """Descarga ``url`` a la caché (o reutiliza la copia válida) y devuelve su ruta."""
        nombre = nombre or url.rstrip("/").split("/")[-1].split("?")[0]
        destino = self.cache / subcarpeta / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)

        previo = self.indice.get(url)
        if destino.exists() and previo and previo.get("sha256"):
            try:
                verificar_archivo(destino, previo.get("bytes"))
                res = ResultadoDescarga(url, destino, destino.stat().st_size, previo["sha256"],
                                        "reutilizado", previo.get("fecha", ""))
                self.historial.append(res)
                return res
            except ErrorDescarga:
                destino.unlink(missing_ok=True)

        parcial = destino.with_name(destino.name + ".part")
        ultimo_error: Exception | None = None
        for intento in range(1, 4):
            try:
                self._bajar(url, parcial, nombre)
                verificar_archivo(parcial, bytes_esperados, tipo=destino.name)
                os.replace(parcial, destino)
                break
            except (requests.RequestException, ErrorDescarga) as e:
                ultimo_error = e
                if isinstance(e, ErrorDescarga):
                    parcial.unlink(missing_ok=True)       # corrupto: empezar de cero
                time.sleep(3 * intento)
        else:
            raise ErrorDescarga(f"No se pudo descargar {url}: {ultimo_error}")

        h = sha256(destino)
        fecha = datetime.now(timezone.utc).isoformat(timespec="seconds")
        estado, dup = "descargado", None
        if h in self.registro and self.registro[h] != str(destino):
            estado, dup = "duplicado", self.registro[h]
        self.registro.setdefault(h, str(destino))
        self.indice[url] = {"ruta": str(destino), "bytes": destino.stat().st_size,
                            "sha256": h, "fecha": fecha}
        self._guardar()
        res = ResultadoDescarga(url, destino, destino.stat().st_size, h, estado, fecha, dup)
        self.historial.append(res)
        return res

    def _bajar(self, url: str, parcial: Path, nombre: str) -> None:
        cab = {}
        hecho = parcial.stat().st_size if parcial.exists() else 0
        if hecho:
            cab["Range"] = f"bytes={hecho}-"
        with self.sesion.get(url, stream=True, timeout=self.timeout, headers=cab) as r:
            if r.status_code == 416:            # ya estaba completo
                return
            if r.status_code == 404:
                raise ErrorDescarga(f"{url} no existe (HTTP 404)")
            r.raise_for_status()
            if hecho and r.status_code != 206:  # el servidor ignoró Range: reiniciar
                hecho = 0
            total = r.headers.get("Content-Length")
            total = int(total) + hecho if total else None
            with open(parcial, "ab" if hecho else "wb") as fh:
                for bloque in r.iter_content(chunk_size=1 << 20):
                    fh.write(bloque)
                    hecho += len(bloque)
                    if self.progreso:
                        self.progreso(nombre, hecho, total)

    def post_json(self, url: str, datos: dict | str, timeout: int = 120) -> dict:
        """POST (formulario o JSON) que devuelve JSON; usado por Overpass y STAC."""
        if isinstance(datos, str):
            r = self.sesion.post(url, data={"data": datos}, timeout=(20, timeout))
        else:
            r = self.sesion.post(url, json=datos, timeout=(20, timeout))
        r.raise_for_status()
        return r.json()
