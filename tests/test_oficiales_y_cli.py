import pytest
from shapely.geometry import box

from cuenca_insumos.cli import _desde_args, main
from cuenca_insumos.oficiales import hoja_ign, hojas_ign
from cuenca_insumos.proveedores import TEMATICOS, tematicos_activos
from cuenca_insumos.proveedores.hydrosheds import region_hydrosheds


@pytest.mark.parametrize("lugar,lon,lat,hoja", [
    ("San Ramón (Huacará)", -75.3725, -11.1350, "23-m"),
    ("Oxapampa", -75.40, -10.58, "22-m"),
    ("Satipo", -74.64, -11.25, "23-n"),
    ("Jauja", -75.498, -11.78, "24-m"),
    ("Puno", -70.02, -15.84, "32-v"),
    ("Juliaca", -70.1333, -15.4833, "31-v"),
    ("Ilave", -69.64, -16.08, "33-x"),
    ("Juli", -69.46, -16.21, "33-y"),        # confirma que la secuencia omite la «w»
])
def test_hoja_ign_verificada_contra_sigmed(lugar, lon, lat, hoja):
    assert hoja_ign(lon, lat) == hoja


def test_hojas_de_un_area_en_la_esquina_de_cuatro():
    assert hojas_ign(box(-75.1, -11.1, -74.9, -10.9)) == ["22-m", "22-n", "23-m", "23-n"]


def test_region_hydrosheds():
    assert region_hydrosheds(-75.37, -11.13) == "sa"
    assert region_hydrosheds(10, 50, forzada="EU") == "eu"
    with pytest.raises(ValueError, match="continente"):
        region_hydrosheds(-80, 9)                    # Panamá: ambigua entre na y sa


def test_seleccion_de_insumos():
    por_defecto = {p.clave for p in tematicos_activos(set(), set())}
    assert por_defecto == {k for k, c in TEMATICOS.items() if c.por_defecto}
    assert "cobertura" in {p.clave for p in tematicos_activos({"cobertura"}, set())}
    assert "rios" not in {p.clave for p in tematicos_activos(set(), {"rios"})}
    with pytest.raises(ValueError, match="DEM no se puede excluir"):
        tematicos_activos(set(), {"dem"})
    with pytest.raises(ValueError, match="desconocidos"):
        tematicos_activos({"lluvia"}, set())


def test_config_toml(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('nombre = "Qda. Huacará"\nzona = 18\nhemisferio = "S"\n'
                   "[salida]\nx = 459329.724\ny = 8769071.156\n"
                   "[cabecera]\nx = 458566.19\ny = 8764100.15\n"
                   '[parametros]\nk_corredor = 0.8\nincluir = ["osm"]\n', encoding="utf-8")
    import argparse
    ns = argparse.Namespace(config=cfg, salida=None, cabecera=None, epsg=None, zona=None, hemisferio=None,
                            datum="WGS84", nombre=None, area_estimada=None, pais=None, dem=None, incluir=None,
                            excluir="imagen", sin_delinear=False, k_corredor=None, continente=None,
                            formato=None, forma_aoi=None)
    e, p = _desde_args(ns)
    assert e.sistema.epsg == 32718 and e.nombre == "Qda. Huacará" and e.cabecera is not None
    assert p.k_corredor == 0.8 and p.incluir == {"osm"} and p.excluir == {"imagen"}


def test_cli_coordenada_invalida_devuelve_codigo_2(capsys):
    codigo = main(["analizar", "--salida", "8769071", "459329", "--zona", "18", "--hemisferio", "S"])
    assert codigo == 2
    assert "Intercambiaste" in capsys.readouterr().err
