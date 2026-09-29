"""Delineación de la cuenca desde el punto de salida (D8), solo con numpy.

No pretende reemplazar a GRASS, SAGA o ArcHydro en el análisis final: su función
es **determinar el área que realmente ocupa la cuenca** para decidir qué datos
descargar, y verificar que el DEM descargado basta para contenerla.

Algoritmos
----------
* Relleno de depresiones: Priority-Flood + ε (Barnes, Lehman y Mulla, 2014).
  Deja todas las celdas con una vecina estrictamente más baja, así que la
  dirección D8 posterior no tiene celdas planas ni ciclos.
* Dirección de flujo: D8 de máxima pendiente (O'Callaghan y Mark, 1984).
* Acumulación: recorrido en orden topológico (elevación rellenada descendente).
* Cuenca: búsqueda aguas arriba desde la salida sobre el grafo de flujo.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np
from affine import Affine
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

__all__ = [
    "rellenar_depresiones", "direcciones_d8", "acumulacion", "red_aguas_arriba",
    "cuenca_desde", "drena_a", "cauce_principal", "ResultadoDelineacion", "delinear",
]

# Orden de vecinos: N, NE, E, SE, S, SO, O, NO  (fila crece hacia el sur)
_OFFS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))


def _semillas(validos: np.ndarray) -> np.ndarray:
    """Celdas válidas en el borde de la grilla o junto a celdas inválidas."""
    H, W = validos.shape
    pad = np.pad(~validos, 1, constant_values=True)
    toca = np.zeros_like(validos)
    for dr, dc in _OFFS:
        toca |= pad[1 + dr:1 + dr + H, 1 + dc:1 + dc + W]
    return validos & toca


def rellenar_depresiones(z: np.ndarray, validos: np.ndarray) -> np.ndarray:
    """Priority-Flood + ε. Devuelve el DEM rellenado en float64 (NaN fuera del dominio)."""
    H, W = z.shape
    Wp = W + 2
    zp = np.full((H + 2, W + 2), np.nan)
    zp[1:-1, 1:-1] = np.where(validos, z, np.nan)
    f = zp.ravel().tolist()                      # listas nativas: ~4x más rápido que indexar numpy
    cerr = bytearray(np.pad(~validos, 1, constant_values=True).ravel().astype(np.uint8).tobytes())
    offs = [dr * Wp + dc for dr, dc in _OFFS]

    sem = np.pad(_semillas(validos), 1, constant_values=False).ravel()
    idx = np.flatnonzero(sem)
    heap = list(zip(zp.ravel()[idx].tolist(), idx.tolist()))
    heapq.heapify(heap)
    for i in idx.tolist():
        cerr[i] = 1

    pop, push, nxt, inf = heapq.heappop, heapq.heappush, math.nextafter, math.inf
    while heap:
        zc, i = pop(heap)
        for o in offs:
            n = i + o
            if cerr[n]:
                continue
            cerr[n] = 1
            zn = f[n]
            if zn <= zc:
                zn = nxt(zc, inf)
                f[n] = zn
            push(heap, (zn, n))
    return np.asarray(f, dtype=np.float64).reshape(H + 2, W + 2)[1:-1, 1:-1]


def direcciones_d8(f: np.ndarray, validos: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Índice lineal de la celda receptora (-1 = drena fuera del dominio)."""
    H, W = f.shape
    fp = np.pad(np.where(validos, f, np.inf), 1, constant_values=np.inf)
    mejor = np.zeros((H, W))
    k_mejor = np.full((H, W), -1, dtype=np.int64)
    diag = math.hypot(dx, dy)
    for k, (dr, dc) in enumerate(_OFFS):
        vec = fp[1 + dr:1 + dr + H, 1 + dc:1 + dc + W]
        dist = dy if dc == 0 else (dx if dr == 0 else diag)
        with np.errstate(invalid="ignore"):
            pend = (f - vec) / dist
        mas = pend > mejor
        mejor = np.where(mas, pend, mejor)
        k_mejor = np.where(mas, k, k_mejor)
    k_mejor[~validos] = -1
    filas, cols = np.indices((H, W))
    off_r = np.array([o[0] for o in _OFFS] + [0])[k_mejor]
    off_c = np.array([o[1] for o in _OFFS] + [0])[k_mejor]
    abajo = (filas + off_r) * W + (cols + off_c)
    abajo[k_mejor < 0] = -1
    return abajo.ravel()


def acumulacion(abajo: np.ndarray, f: np.ndarray, validos: np.ndarray) -> np.ndarray:
    """Número de celdas que drenan por cada celda (incluida ella misma)."""
    fv = f.ravel()
    idx = np.flatnonzero(validos.ravel())
    orden = idx[np.argsort(-fv[idx], kind="stable")].tolist()
    acc = validos.ravel().astype(np.int64).tolist()
    ab = abajo.tolist()
    for i in orden:
        d = ab[i]
        if d >= 0:
            acc[d] += acc[i]
    return np.asarray(acc, dtype=np.int64).reshape(f.shape)


def red_aguas_arriba(abajo: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Grafo inverso (quién drena hacia cada celda) en formato CSR."""
    src = np.flatnonzero(abajo >= 0)
    dst = abajo[src]
    o = np.argsort(dst, kind="stable")
    src, dst = src[o], dst[o]
    ptr = np.searchsorted(dst, np.arange(n + 1))
    return ptr, src


def cuenca_desde(i_salida: int, ptr: np.ndarray, src: np.ndarray, n: int) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    pila = [i_salida]
    m[i_salida] = True
    p, s = ptr.tolist(), src.tolist()
    while pila:
        i = pila.pop()
        for j in s[p[i]:p[i + 1]]:
            if not m[j]:
                m[j] = True
                pila.append(j)
    return m


def drena_a(abajo: np.ndarray, i_desde: int, i_hasta: int, max_pasos: int = 10_000_000) -> bool:
    i, k = i_desde, 0
    while i >= 0 and k < max_pasos:
        if i == i_hasta:
            return True
        i = int(abajo[i])
        k += 1
    return False


def cauce_principal(i_salida: int, acc: np.ndarray, ptr: np.ndarray, src: np.ndarray,
                    umbral: int) -> list[int]:
    """Cauce principal aguas arriba: en cada confluencia sigue al afluente de mayor
    área de aporte, hasta que el área cae por debajo del umbral de cauce."""
    a = acc.ravel()
    camino, i = [i_salida], i_salida
    while True:
        ups = src[ptr[i]:ptr[i + 1]]
        if len(ups) == 0:
            break
        j = int(ups[np.argmax(a[ups])])
        if a[j] < umbral:
            break
        camino.append(j)
        i = j
    return camino


@dataclass
class ResultadoDelineacion:
    mascara: np.ndarray
    poligono: Polygon
    salida_ajustada: tuple[float, float]
    desplazamiento_m: float
    area_km2: float
    truncada: bool
    celdas_en_borde: int
    cabecera_drena: bool | None
    cauce_xy: list[tuple[float, float]]
    cota_salida: float
    avisos: list[str] = field(default_factory=list)


def _fila_col(transform: Affine, x: float, y: float) -> tuple[int, int]:
    # Fórmula explícita en vez de `~transform * (x, y)`: el operador cambia entre versiones de affine.
    a, b, c, d, e, f = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
    det = a * e - b * d
    col = (e * (x - c) - b * (y - f)) / det
    fila = (-d * (x - c) + a * (y - f)) / det
    return int(math.floor(fila)), int(math.floor(col))


def _centro(transform: Affine, i: int, W: int) -> tuple[float, float]:
    r, c = divmod(i, W)
    x = transform.c + (c + 0.5) * transform.a + (r + 0.5) * transform.b
    y = transform.f + (c + 0.5) * transform.d + (r + 0.5) * transform.e
    return float(x), float(y)


def _vectorizar(mascara: np.ndarray, transform: Affine) -> Polygon:
    from rasterio.features import shapes
    geoms = [shape(g) for g, v in shapes(mascara.astype(np.uint8), mask=mascara, transform=transform)
             if v == 1]
    g = unary_union(geoms)
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda p: p.area)
    return Polygon(g.exterior)            # sin huecos internos


def delinear(z: np.ndarray, validos: np.ndarray, transform: Affine,
             salida_xy: tuple[float, float], cabecera_xy: tuple[float, float] | None = None,
             umbral_cauce_km2: float = 0.1, radio_ajuste_m: float = 150.0) -> ResultadoDelineacion:
    """Delinea la cuenca que drena por ``salida_xy`` sobre un DEM en metros (UTM)."""
    H, W = z.shape
    dx, dy = abs(transform.a), abs(transform.e)
    area_celda = dx * dy
    avisos: list[str] = []

    r0, c0 = _fila_col(transform, *salida_xy)
    if not (0 <= r0 < H and 0 <= c0 < W) or not validos[r0, c0]:
        raise ValueError("El punto de salida cae fuera del DEM o sobre una celda sin datos.")

    f = rellenar_depresiones(z, validos)
    abajo = direcciones_d8(f, validos, dx, dy)
    acc = acumulacion(abajo, f, validos)
    ptr, src = red_aguas_arriba(abajo, H * W)

    # --- ajuste (snap) de la salida al cauce más cercano ------------------------
    umbral = max(2, int(round(umbral_cauce_km2 * 1e6 / area_celda)))
    rad = max(1, int(math.ceil(radio_ajuste_m / min(dx, dy))))
    r1, r2, c1, c2 = max(0, r0 - rad), min(H, r0 + rad + 1), max(0, c0 - rad), min(W, c0 + rad + 1)
    ventana = acc[r1:r2, c1:c2]
    rr, cc = np.nonzero((ventana >= umbral) & validos[r1:r2, c1:c2])
    if len(rr):
        d = np.hypot((rr + r1 - r0) * dy, (cc + c1 - c0) * dx)
        cand = [((r1 + a) * W + (c1 + b), float(di))
                for di, _, a, b in sorted(zip(d, -ventana[rr, cc], rr, cc)) if di <= radio_ajuste_m]
    else:
        cand = []
    if not cand:
        a, b = np.unravel_index(np.argmax(np.where(validos[r1:r2, c1:c2], ventana, -1)), ventana.shape)
        cand = [((r1 + a) * W + (c1 + b), float(math.hypot((a + r1 - r0) * dy, (b + c1 - c0) * dx)))]
        avisos.append(f"No hay cauce (área > {umbral_cauce_km2} km²) a menos de {radio_ajuste_m:.0f} m de la "
                      "salida; se usó la celda de mayor acumulación del entorno.")

    i_cab = None
    if cabecera_xy is not None:
        rc, ccab = _fila_col(transform, *cabecera_xy)
        if 0 <= rc < H and 0 <= ccab < W and validos[rc, ccab]:
            i_cab = rc * W + ccab
        else:
            avisos.append("La cabecera cae fuera del DEM descargado; no se pudo verificar.")

    i_sal, desplaz, cab_ok = cand[0][0], cand[0][1], None
    if i_cab is not None:
        for i, d_ in cand:
            if drena_a(abajo, i_cab, i):
                i_sal, desplaz, cab_ok = i, d_, True
                break
        else:
            cab_ok = False
            avisos.append("La cabecera NO drena hacia la salida: revisa que ambos puntos estén sobre "
                          "el mismo río (la salida pudo quedar en otro cauce, p. ej. el río receptor).")

    # distancia real: de la coordenada ingresada al centro de la celda elegida
    # (la de la selección es entre centros de celda y da 0 si ambas caen en la misma)
    cx, cy = _centro(transform, i_sal, W)
    desplaz = math.hypot(cx - salida_xy[0], cy - salida_xy[1])
    mascara = cuenca_desde(i_sal, ptr, src, H * W).reshape(H, W)
    en_borde = int((mascara & _semillas(validos)).sum())
    area = float(mascara.sum()) * area_celda / 1e6
    cota_sal = float(z.ravel()[i_sal])
    if i_cab is not None and cab_ok and z.ravel()[i_cab] <= cota_sal:
        avisos.append("La cabecera está más baja que la salida: ¿intercambiaste los puntos?")

    camino = cauce_principal(i_sal, acc, ptr, src, umbral)
    return ResultadoDelineacion(
        mascara=mascara,
        poligono=_vectorizar(mascara, transform),
        salida_ajustada=_centro(transform, i_sal, W),
        desplazamiento_m=desplaz,
        area_km2=area,
        truncada=en_borde > 0,
        celdas_en_borde=en_borde,
        cabecera_drena=cab_ok,
        cauce_xy=[_centro(transform, i, W) for i in camino],
        cota_salida=cota_sal,
        avisos=avisos,
    )
