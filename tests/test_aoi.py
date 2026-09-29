import pytest
from shapely.geometry import Point

from cuenca_insumos.aoi import aoi_final, aoi_preliminar, longitud_cuenca_hack
from cuenca_insumos.config import Parametros
from cuenca_insumos.coords import Punto

SAL = Punto(459329.724, 8769071.156, 32718, "salida")
CAB = Punto(458566.19, 8764100.15, 32718, "cabecera")


@pytest.mark.parametrize("forma", ["rectangulo", "corredor"])
def test_aoi_con_cabecera_contiene_ambos_puntos_con_margen(forma):
    p = Parametros(forma_aoi=forma, k_corredor=0.6)
    a = aoi_preliminar(SAL, CAB, params=p)
    L = Point(SAL.x, SAL.y).distance(Point(CAB.x, CAB.y))
    for q in (SAL, CAB):
        assert a.geom.contains(Point(q.x, q.y).buffer(0.6 * L * 0.99))
    assert a.metodo == forma


def test_margen_minimo_si_los_puntos_estan_cerca():
    cerca = Punto(SAL.x + 200, SAL.y, 32718)
    a = aoi_preliminar(SAL, cerca, params=Parametros(k_corredor=0.6, buffer_minimo_m=1000))
    assert a.geom.contains(Point(SAL.x, SAL.y).buffer(990))


def test_solo_salida_usa_radio_fijo_o_ley_de_hack():
    assert aoi_preliminar(SAL).metodo == "radio_fijo"
    a = aoi_preliminar(SAL, area_estimada_km2=7)
    assert a.metodo == "radio_hack"
    r = 1.5 * longitud_cuenca_hack(7) * 1000
    assert a.geom.area == pytest.approx(3.14159 * r * r, rel=0.01)


def test_ampliar_agranda_y_contiene_al_original():
    a = aoi_preliminar(SAL, CAB)
    b = a.ampliar(1.6)
    assert b.geom.contains(a.geom) and b.area_km2 > a.area_km2 * 1.8


def test_aoi_final_es_la_cuenca_mas_margen():
    cuenca = Point(SAL.x, SAL.y).buffer(1500)
    f = aoi_final(cuenca, 32718, Parametros(margen_final_min_m=1000, margen_final_frac=0.1))
    assert f.geom.contains(cuenca.buffer(990))


def test_lonlat_del_aoi_esta_en_grados():
    w, s, e, n = aoi_preliminar(SAL, CAB).lonlat().bounds
    assert -76 < w < e < -75 and -12 < s < n < -11
