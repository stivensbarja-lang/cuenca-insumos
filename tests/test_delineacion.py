"""Pruebas de la delineación sobre superficies sintéticas de solución conocida."""
import numpy as np
import pytest
from affine import Affine
from rasterio.transform import xy as _xy

from cuenca_insumos.delineacion import (acumulacion, delinear, direcciones_d8, drena_a,
                                        rellenar_depresiones)

TR = Affine(30.0, 0, 0, 0, -30.0, 30.0 * 60)     # grilla de 60 × 60 celdas de 30 m


def centro(fila, col):
    return _xy(TR, fila, col)             # centro de la celda (fila, col)


def valle_en_v(n=60):
    """Dos laderas que caen hacia una quebrada central (columna n//2) que desciende al sur."""
    f, c = np.indices((n, n))
    return 1000 - 5.0 * f + 3.0 * np.abs(c - n // 2)


def test_relleno_elimina_pozos_y_no_baja_el_terreno():
    z = valle_en_v()
    z[20, 30] -= 50                                   # pozo artificial en la quebrada
    v = np.ones_like(z, dtype=bool)
    f = rellenar_depresiones(z, v)
    assert (f >= z - 1e-9).all()
    # el pozo se llena hasta apenas por encima de su punto de desborde (la celda aguas abajo)
    assert z[21, 30] < f[20, 30] < z[21, 30] + 1e-6


def test_toda_celda_drena_y_no_hay_ciclos():
    z = valle_en_v()
    z[10:14, 5:9] = 900                              # depresión cerrada grande
    v = np.ones_like(z, dtype=bool)
    f = rellenar_depresiones(z, v)
    ab = direcciones_d8(f, v, 30, 30)
    acc = acumulacion(ab, f, v)
    # la suma de lo que sale del dominio debe ser el total de celdas (conservación)
    salidas = np.flatnonzero(ab < 0)
    assert acc.ravel()[salidas].sum() == z.size
    for i in (0, 612, 1830, 3599):
        pasos, j = 0, i
        while ab[j] >= 0:
            j = ab[j]
            pasos += 1
            assert pasos < z.size, "ciclo en la red de flujo"


def test_cuenca_del_valle_coincide_con_la_solucion_analitica():
    """En las laderas la bajada diagonal (Δz = 5 + 3 en 42.4 m) es la más empinada, así que
    una celda llega a la quebrada |c − 30| filas más abajo: drena a la salida (fila 50)
    si fila + |c − 30| ≤ 50. La cuenca es un triángulo invertido."""
    z = valle_en_v()
    v = np.ones_like(z, dtype=bool)
    x, y = centro(50, 30)
    r = delinear(z, v, TR, (x, y), umbral_cauce_km2=0.01)
    assert r.desplazamiento_m == pytest.approx(0, abs=1e-6)   # la coordenada ya era el centro
    f, c = np.indices(z.shape)
    d = f + np.abs(c - 30)
    dentro, fuera = (d <= 48) & (c > 0) & (c < 59), d >= 52
    assert r.mascara[dentro].mean() > 0.98
    assert not r.mascara[fuera].any()
    assert r.truncada                                 # llega al borde norte del dominio


def test_salida_desplazada_se_ajusta_al_cauce():
    z = valle_en_v()
    v = np.ones_like(z, dtype=bool)
    x, y = centro(50, 33)                             # 3 celdas (90 m) al este de la quebrada
    r = delinear(z, v, TR, (x, y), umbral_cauce_km2=0.05, radio_ajuste_m=150)
    assert r.desplazamiento_m == pytest.approx(90, abs=1)
    assert r.salida_ajustada[0] == pytest.approx(centro(50, 30)[0])


def test_cabecera_en_otro_valle_genera_aviso():
    n = 60
    f, c = np.indices((n, n))
    # dos quebradas paralelas (columnas 15 y 45) separadas por una divisoria en la 30
    z = 1000 - 5.0 * f + 3.0 * np.minimum(np.abs(c - 15), np.abs(c - 45))
    v = np.ones_like(z, dtype=bool)
    sal = centro(50, 15)
    cab_otro_valle = centro(5, 45)
    r = delinear(z, v, TR, sal, cab_otro_valle, umbral_cauce_km2=0.01, radio_ajuste_m=60)
    assert r.cabecera_drena is False
    assert any("NO drena" in a for a in r.avisos)


def test_drena_a():
    ab = np.array([1, 2, -1, 2])
    assert drena_a(ab, 0, 2) and not drena_a(ab, 2, 0) and drena_a(ab, 3, 2)
