import pytest

from cuenca_insumos.coords import (ErrorCoordenadas, Punto, a_lonlat, resolver_sistema, validar_puntos,
                                   verificar_en_tierra)

SAL = (459329.724, 8769071.156)       # salida real de la quebrada Huacará (UTM 18S)
CAB = (458566.19, 8764100.15)


def test_zona_y_hemisferio_dan_el_epsg():
    assert resolver_sistema(zona=18, hemisferio="S").epsg == 32718
    assert resolver_sistema(zona=17, hemisferio="s").epsg == 32717
    assert resolver_sistema(zona=18, hemisferio="N").epsg == 32618


@pytest.mark.parametrize("datum,epsg", [("PSAD56", 24878), ("SIRGAS2000", 31978), ("SIRGAS 2000", 31978)])
def test_datums_usados_en_peru(datum, epsg):
    assert resolver_sistema(zona=18, hemisferio="S", datum=datum).epsg == epsg


def test_epsg_incoherente_con_la_zona():
    with pytest.raises(ErrorCoordenadas, match="Incoherencia"):
        resolver_sistema(epsg=32718, zona=17, hemisferio="S")
    with pytest.raises(ErrorCoordenadas, match="hemisferio"):
        resolver_sistema(epsg=32718, hemisferio="N")


def test_epsg_no_utm_se_rechaza():
    with pytest.raises(ErrorCoordenadas, match="no es UTM"):
        resolver_sistema(epsg=3857)


def test_epsg_geografico_se_acepta():
    s = resolver_sistema(epsg=4326)
    assert s.geografico and s.zona is None


def test_conversion_a_lonlat_huacara():
    lon, lat = a_lonlat(*SAL, 32718)
    assert lon == pytest.approx(-75.3725, abs=1e-3)
    assert lat == pytest.approx(-11.1350, abs=1e-3)


def test_puntos_validos_sin_avisos():
    s = resolver_sistema(zona=18, hemisferio="S")
    assert validar_puntos(Punto(*SAL, 32718, "salida"), Punto(*CAB, 32718, "cabecera"), s) == []


def test_x_e_y_intercambiadas():
    s = resolver_sistema(zona=18, hemisferio="S")
    with pytest.raises(ErrorCoordenadas, match="Intercambiaste"):
        validar_puntos(Punto(SAL[1], SAL[0], 32718, "salida"), None, s)


def test_zona_equivocada_pasa_el_rectangulo_del_pais():
    """Con la zona 17, la salida cae en −81.37°: dentro del rectángulo del Perú
    (−81.4°), aunque a esa latitud es mar abierto. El rectángulo no basta..."""
    s = resolver_sistema(zona=17, hemisferio="S")
    assert validar_puntos(Punto(*SAL, 32717, "salida"), None, s, pais="PER") == []


def test_zona_equivocada_se_detecta_en_el_oceano_y_se_sugiere_la_correcta():
    """...por eso se verifica contra el catálogo del DEM: sin tile = océano."""
    s = resolver_sistema(zona=17, hemisferio="S")
    tierra = lambda lon, lat: lon > -80.0          # catálogo simulado: a 11° S el mar empieza en ~−78°
    with pytest.raises(ErrorCoordenadas, match="océano.*zona 18S"):
        verificar_en_tierra(Punto(*SAL, 32717, "salida"), s, tierra, pais="PER")
    verificar_en_tierra(Punto(*SAL, 32718, "salida"), resolver_sistema(zona=18, hemisferio="S"), tierra)


def test_puntos_en_sistemas_distintos():
    s = resolver_sistema(zona=18, hemisferio="S")
    with pytest.raises(ErrorCoordenadas, match="mismo sistema"):
        validar_puntos(Punto(*SAL, 32718, "salida"), Punto(*CAB, 32717, "cabecera"), s)


def test_puntos_casi_identicos():
    s = resolver_sistema(zona=18, hemisferio="S")
    with pytest.raises(ErrorCoordenadas, match="mismo punto"):
        validar_puntos(Punto(*SAL, 32718), Punto(SAL[0] + 10, SAL[1], 32718), s)
