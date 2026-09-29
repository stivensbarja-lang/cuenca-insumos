"""Pruebas del descargador contra un servidor HTTP local (sin internet)."""
import http.server
import threading
import zipfile
from functools import partial

import pytest

from cuenca_insumos.descarga import Descargador, ErrorDescarga, verificar_archivo


@pytest.fixture
def servidor(tmp_path):
    raiz = tmp_path / "www"
    raiz.mkdir()
    with zipfile.ZipFile(raiz / "bueno.zip", "w") as z:
        z.writestr("datos.txt", "hola cuenca\n" * 1000)
    (raiz / "copia.zip").write_bytes((raiz / "bueno.zip").read_bytes())
    (raiz / "roto.zip").write_bytes(b"PK\x03\x04 esto no es un zip")
    (raiz / "texto.txt").write_text("abc", encoding="utf-8")

    manejador = partial(http.server.SimpleHTTPRequestHandler, directory=str(raiz))
    manejador.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_descarga_verifica_y_reutiliza(servidor, tmp_path):
    d = Descargador(tmp_path / "cache", reintentos=0)
    r1 = d.obtener(f"{servidor}/bueno.zip")
    assert r1.estado == "descargado" and r1.ruta.exists() and len(r1.sha256) == 64
    r2 = d.obtener(f"{servidor}/bueno.zip")
    assert r2.estado == "reutilizado" and r2.sha256 == r1.sha256
    # una instancia nueva lee el índice en disco: sigue reutilizando
    assert Descargador(tmp_path / "cache", reintentos=0).obtener(f"{servidor}/bueno.zip").estado == "reutilizado"


def test_duplicado_por_contenido(servidor, tmp_path):
    d = Descargador(tmp_path / "cache", reintentos=0)
    d.obtener(f"{servidor}/bueno.zip")
    r = d.obtener(f"{servidor}/copia.zip")
    assert r.estado == "duplicado" and r.duplicado_de.endswith("bueno.zip")


def test_zip_corrupto_se_rechaza(servidor, tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    d = Descargador(tmp_path / "cache", reintentos=0)
    with pytest.raises(ErrorDescarga, match="No se pudo descargar"):
        d.obtener(f"{servidor}/roto.zip")
    assert not (tmp_path / "cache" / "roto.zip").exists()


def test_404_informa(servidor, tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    d = Descargador(tmp_path / "cache", reintentos=0)
    with pytest.raises(ErrorDescarga, match="404"):
        d.obtener(f"{servidor}/no_existe.tif")
    assert not d.existe(f"{servidor}/no_existe.tif")
    assert d.existe(f"{servidor}/texto.txt")


def test_tamano_remoto(servidor, tmp_path):
    d = Descargador(tmp_path / "cache", reintentos=0)
    assert d.tamano(f"{servidor}/texto.txt") == 3


def test_verificar_tamano_incompleto(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"12345")
    verificar_archivo(f, 5)
    with pytest.raises(ErrorDescarga, match="incompleta"):
        verificar_archivo(f, 10)


def test_verificar_por_tipo_aunque_sea_parcial(tmp_path):
    f = tmp_path / "x.tif.part"
    f.write_bytes(b"no es un tiff")
    with pytest.raises(ErrorDescarga, match="no se puede abrir"):
        verificar_archivo(f, tipo="x.tif")
