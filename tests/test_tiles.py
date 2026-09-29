from shapely.geometry import LineString, box

from cuenca_insumos.proveedores.copernicus_dem import nombre_tile
from cuenca_insumos.tiles import Tile, candidatos, seleccionar


def test_nombre_copernicus_huacara():
    # Huacará: lat -11.13, lon -75.37 → esquina SO del tile = (-12, -76)
    t = candidatos((-75.40, -11.19, -75.36, -11.12))
    assert t == [Tile(-12, -76)]
    assert nombre_tile(t[0]) == "Copernicus_DSM_COG_10_S12_00_W076_00_DEM"
    assert nombre_tile(Tile(0, 6), "90") == "Copernicus_DSM_COG_30_N00_00_E006_00_DEM"


def test_limite_exacto_de_la_grilla_no_agrega_tile():
    assert candidatos((-75.5, -11.5, -75.0, -11.0)) == [Tile(-12, -76)]


def test_dos_puntos_en_un_mismo_tile():
    sel = seleccionar(box(-75.6, -11.6, -75.2, -11.2))
    assert len(sel.encontrados) == len(sel.necesarios) == 1 and not sel.descartados
    assert sel.cobertura_pct == 100.0


def test_area_que_cruza_cuatro_tiles():
    sel = seleccionar(box(-75.2, -11.2, -74.8, -10.8))
    assert len(sel.necesarios) == 4


def test_corredor_diagonal_4_encontrados_3_necesarios_1_descartado():
    """El ejemplo de las instrucciones: el rectángulo envolvente toca 4 tiles, pero un
    corredor diagonal solo atraviesa 3; el cuarto se descarta y se explica por qué."""
    # recta y = x + 64.3: pasa a 0.21° de la esquina común (−75, −11), más que el semiancho 0.08°
    corredor = LineString([(-75.9, -11.6), (-74.4, -10.1)]).buffer(0.08)
    sel = seleccionar(corredor)
    assert (len(sel.encontrados), len(sel.necesarios), len(sel.descartados)) == (4, 3, 1)
    descartado, motivo = sel.descartados[0]
    assert descartado.codigo == "S12W075"            # el cuadrante sureste queda fuera
    assert "fuera del área" in motivo
    assert sel.cobertura_pct > 99.99


def test_tile_de_oceano_se_descarta_con_motivo():
    aoi = box(-76.2, -11.4, -75.8, -11.0)      # cruza a W077, que simulamos inexistente
    sel = seleccionar(aoi, existe=lambda t: t.lon0 != -77)
    assert [t.codigo for t in sel.necesarios] == ["S12W076"]
    assert "no existe en el catálogo" in sel.descartados[0][1]
    assert sel.sin_datos_pct > 0


def test_grilla_de_3_grados_worldcover():
    assert candidatos((-75.4, -11.2, -75.3, -11.1), tam=3) == [Tile(-12, -78, 3)]
