"""diagnostico.py (el script que usa «Abrir cuenca-insumos.bat» antes de abrir la ventana)."""
import subprocess
import sys
from pathlib import Path

DIAGNOSTICO = Path(__file__).resolve().parents[1] / "diagnostico.py"


def _correr(*args, python=sys.executable):
    return subprocess.run([python, str(DIAGNOSTICO), "--rapido", *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)


def test_entorno_instalado_da_codigo_0():
    r = _correr()
    assert r.returncode == 0, r.stdout
    assert "Todo en orden" in r.stdout


def test_python_sin_el_paquete_pide_instalar_con_codigo_2(tmp_path):
    # simula una computadora recién instalada: el mismo Python, pero sin site-packages
    # (-I aísla de PYTHONPATH y del sitio de usuario, -S no carga site)
    lanzador = tmp_path / "sin_paquetes.py"
    lanzador.write_text(
        "import runpy, sys\n"
        "sys.path = [p for p in sys.path if 'site-packages' not in p]\n"
        f"sys.argv = [{str(DIAGNOSTICO)!r}, '--rapido']\n"
        f"runpy.run_path({str(DIAGNOSTICO)!r}, run_name='__main__')\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "-S", str(lanzador)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "pip install -e" in r.stdout
