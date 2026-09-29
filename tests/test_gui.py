"""La ventana: lectura del formulario, carga de .toml y validación, sin red ni descargas."""
import pytest

tk = pytest.importorskip("tkinter")

from cuenca_insumos import gui  # noqa: E402
from cuenca_insumos.coords import ErrorCoordenadas  # noqa: E402


@pytest.fixture(scope="module")
def raiz():
    # una sola raíz para todo el módulo: crear y destruir muchos tk.Tk() en el mismo proceso
    # falla de forma intermitente en Windows («Can't find a usable tk.tcl»); el programa real
    # solo crea una
    try:
        r = tk.Tk()
    except tk.TclError as ex:
        pytest.skip(f"no hay pantalla disponible para Tkinter ({ex})")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def ventana(raiz, tmp_path):
    top = tk.Toplevel(raiz)
    top.withdraw()
    v = gui.Ventana(top)
    v.v["carpeta"].set(str(tmp_path))
    yield v
    top.destroy()


def test_ejemplo_huacara_se_lee_igual_que_el_toml(ventana, tmp_path):
    ventana.ejemplo()
    e, p, carpeta = ventana._leer()
    assert e.sistema.epsg == 32718 and e.nombre == "Quebrada Huacara"
    assert (e.salida.x, e.salida.y) == (459329.724, 8769071.156)
    assert e.cabecera is not None and e.cabecera.y == 8764100.15
    assert p.incluir == set() and p.excluir == set() and p.formato_vector == "gpkg"
    assert carpeta == tmp_path / "Proyecto_Quebrada_Huacara"


def test_casillas_y_formato_pasan_a_los_parametros(ventana):
    ventana.ejemplo()
    ventana.insumos["imagen"].set(False)      # por defecto: se excluye
    ventana.insumos["cobertura"].set(True)    # opcional: se incluye
    ventana.formato.set("shp")
    _, p, _ = ventana._leer()
    assert p.excluir == {"imagen"} and p.incluir == {"cobertura"} and p.formato_vector == "shp"


def test_toml_con_parametros_y_coma_decimal(ventana, tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('nombre = "Qda. Huacará"\nzona = 18\nhemisferio = "S"\n'
                   "[salida]\nx = 459329.724\ny = 8769071.156\n"
                   '[parametros]\nk_corredor = 0.8\nincluir = ["osm"]\nformato_vector = "shp"\n', encoding="utf-8")
    gui.filedialog.askopenfilename = lambda **k: str(cfg)
    ventana.abrir_toml()
    assert ventana.v["cx"].get() == "" and ventana.insumos["osm"].get()
    ventana.v["sx"].set("459329,724")  # coma decimal, como en Excel en castellano
    e, p, _ = ventana._leer()
    assert e.salida.x == 459329.724 and e.cabecera is None
    assert p.k_corredor == 0.8 and p.formato_vector == "shp" and p.incluir == {"osm"}


@pytest.mark.parametrize("campos,mensaje", [
    ({"sx": ""}, "Falta el punto de salida"),
    ({"sy": "8769O71"}, "no es un número"),          # letra O en vez de cero
    ({"cy": ""}, "las dos coordenadas"),
    ({"zona": "dieciocho"}, "números enteros"),
    ({"epsg": "32717"}, "Incoherencia"),
])
def test_errores_del_formulario(ventana, campos, mensaje):
    ventana.ejemplo()
    for k, val in campos.items():
        ventana.v[k].set(val)
    with pytest.raises(ErrorCoordenadas, match=mensaje):
        ventana._leer()


def test_cambiar_un_dato_invalida_el_plan(ventana):
    ventana.ejemplo()
    ventana.plan = object()
    ventana._botones()
    assert not ventana.b_descargar.instate(["disabled"])
    ventana.v["sx"].set("459330")
    assert ventana.plan is None and ventana.b_descargar.instate(["disabled"])
