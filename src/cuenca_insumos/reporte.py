"""Textos para el usuario: resumen del plan (terminal) y REPORTE.md del proyecto."""
from __future__ import annotations

from pathlib import Path

from .config import CARPETAS, Parametros
from .oficiales import FUENTES_OFICIALES_PERU
from .proveedores import CopernicusDEM, TEMATICOS

__all__ = ["texto_plan", "escribir_reporte", "mb"]


def mb(b: int | None) -> str:
    if not b:
        return "tamaño no informado"
    return f"{b / 1e6:,.1f} MB" if b >= 1e5 else f"{b / 1e3:,.0f} kB"


def texto_plan(plan) -> str:
    e, sel = plan.entrada, plan.seleccion_dem
    L = ["", "Área de análisis identificada", "=" * 60,
         f"  Cuenca:     {e.nombre}",
         f"  Sistema:    EPSG:{e.sistema.epsg} ({e.sistema.nombre})",
         f"  Método:     {plan.aoi.descripcion}",
         f"  Superficie: {plan.aoi.area_km2:,.1f} km² (preliminar; se ajusta tras delinear la cuenca)", ""]
    L.append(sel.resumen().replace("DEM ", f"DEM (GLO-{plan.resolucion_dem}) ", 3))
    L.append(f"  Cobertura del área por los tiles necesarios: {sel.cobertura_pct:.1f} %"
             + (f" (sin datos: {sel.sin_datos_pct:.1f} %, océano)" if sel.sin_datos_pct > 0.05 else ""))
    por_tile = 40_000_000 if plan.resolucion_dem == "30" else 5_000_000
    total = sum(por_tile for t in sel.necesarios if not plan.dem_en_cache.get(t))
    en_cache = sum(1 for t in sel.necesarios if plan.dem_en_cache.get(t))
    if en_cache:
        L.append(f"  ({en_cache} de {len(sel.necesarios)} tile(s) ya están en la caché)")
    L.append("")
    for prov, pl in plan.planes:
        estado = "disponible" if pl.disponible else "NO disponible"
        cacheado = bool(pl.recursos) and all(r.extra.get("en_cache") for r in pl.recursos)
        tam = f"{mb(pl.bytes_estimados)}" if pl.bytes_estimados else ""
        if cacheado and tam:
            tam += ", ya en la caché"
        reu = (" (archivo regional: se descarga una vez y se reutiliza)"
               if any(r.reutilizable for r in pl.recursos) and not cacheado else "")
        L.append(f"{prov.insumo}: {estado} — {prov.dataset}" + (f", {tam}" if tam else "") + reu)
        if not pl.disponible or pl.mensaje:
            L.append(f"   {pl.mensaje}")
        total += sum(r.bytes_estimados or 0 for r in pl.recursos if not r.extra.get("en_cache"))
    if plan.hojas_ign:
        L.append(f"\nCarta Nacional IGN 1:100 000 (descarga manual en SIGMED): hoja(s) {', '.join(plan.hojas_ign)}")
    L.append("\nDescarga estimada: " + (f"≈{mb(total)} (sin contar lo que ya está en la caché)" if total
                                        else "nada nuevo: todo está en la caché"))
    for a in plan.avisos:
        L.append(f"AVISO: {a}")
    return "\n".join(L)


def _n(v: float, d: int = 2) -> str:
    """Número con espacio como separador de miles (norma castellana)."""
    return f"{v:,.{d}f}".replace(",", " ")


def _fila(*c) -> str:
    return "| " + " | ".join(str(x) for x in c) + " |"


def escribir_reporte(res, plan, params: Parametros) -> Path:
    e, dl, man, x = plan.entrada, res.delineacion, res.manifiesto, res.extra
    sel = plan.seleccion_dem
    L = [f"# Reporte de insumos — {e.nombre}", "",
         "Generado por **cuenca-insumos**. Este archivo explica qué se descargó, de dónde y por qué.", "",
         "## 1. Datos de entrada", "",
         _fila("Punto", "X / Este", "Y / Norte"), _fila("---", "---:", "---:"),
         _fila("Salida", _n(e.salida.x), _n(e.salida.y))]
    if e.cabecera:
        L.append(_fila("Cabecera", _n(e.cabecera.x), _n(e.cabecera.y)))
    L += ["", f"Sistema de referencia: **EPSG:{e.sistema.epsg}** ({e.sistema.nombre}).", "",
          "## 2. Cómo se decidió el área de análisis", ""]
    L += [f"- {d}" for d in man.decisiones]
    L += ["", "## 3. Modelo de elevación digital", "",
          f"Tiles de la grilla de 1° que tocan el rectángulo del área preliminar: **{len(sel.encontrados)}**; "
          f"necesarios: **{len(sel.necesarios)}**; descartados: **{len(sel.descartados)}**.", ""]
    for t in sel.necesarios:
        L.append(f"- `{t.codigo}` — cubre el {100 * sel.fraccion_aoi.get(t, 0):.1f} % del área")
    for t, m in sel.descartados:
        L.append(f"- ~~`{t.codigo}`~~ — {m}")
    if res.iteraciones:
        L.append(f"\nLa cuenca tocaba el borde del área preliminar: se amplió {res.iteraciones} vez/veces.")

    if dl is not None:
        L += ["", "## 4. Cuenca delineada (preliminar)", "",
              _fila("Dato", "Valor"), _fila("---", "---"),
              _fila("Área", f"{dl.area_km2:.2f} km²"),
              _fila("Perímetro", f"{dl.poligono.length / 1000:.2f} km"),
              _fila("Salida ajustada al cauce", f"{_n(dl.salida_ajustada[0])} E ; {_n(dl.salida_ajustada[1])} N "
                                                f"(a {dl.desplazamiento_m:.0f} m de la coordenada ingresada)"),
              _fila("Cota de la salida", f"{dl.cota_salida:.1f} m s. n. m.")]
        if dl.cabecera_drena is not None:
            L.append(_fila("¿La cabecera drena a la salida?", "sí" if dl.cabecera_drena else "**NO — revisar**"))
        if "curso_cercano" in x:
            n, d = x["curso_cercano"]
            L.append(_fila("Curso con nombre más cercano (GeoNames)", f"{n}, a {d:.0f} m de la salida"))
        if "poblado_cercano" in x:
            n, d = x["poblado_cercano"]
            L.append(_fila("Centro poblado más cercano (GeoNames)", f"{n}, a {d / 1000:.2f} km"))
        if x.get("ubicacion_politica"):
            L.append(_fila("Ubicación política (GADM)", "; ".join(x["ubicacion_politica"])))
        if "unidad_hidrografica" in x:
            pf, up, hid = x["unidad_hidrografica"]
            nota = (" — corresponde al río receptor, no a la cuenca: la salida está en una confluencia"
                    if up > 5 * dl.area_km2 else "")
            L.append(_fila("Unidad HydroBASINS nivel 12 que contiene la salida",
                           f"PFAF {pf} (HYBAS_ID {hid}); drena {_n(up, 0)} km² aguas arriba{nota}"))
        if plan.hojas_ign:
            L.append(_fila("Hoja(s) IGN 1:100 000", ", ".join(plan.hojas_ign)))
        L += ["", "> Es una delineación D8 hecha para **decidir qué descargar**. El análisis morfométrico "
                  "definitivo hazlo en tu SIG (GRASS `r.watershed`, SAGA o ArcHydro) sobre el DEM de "
                  f"`{CARPETAS['dem']}`, que ya incluye un margen alrededor de la cuenca."]

    L += ["", "## 5. Insumos generados", "", _fila("Insumo", "Descripción", "Archivo", "Elementos"),
          _fila("---", "---", "---", "---:")]
    for p in man.productos:
        L.append(_fila(p.insumo, p.descripcion, f"`{p.ruta}`" if p.ruta else "—",
                       p.n_elementos if p.n_elementos is not None else ""))
    nb = sum(d.bytes or 0 for d in man.descargas if d.estado.startswith("descargado"))
    L += ["", f"Transferido en esta ejecución: **{mb(nb)}**. El detalle archivo por archivo (URL, tamaño, "
              "SHA-256, fecha, licencia) está en `manifiesto.json` y `manifiesto_descargas.csv`."]
    dups = [d for d in man.descargas if "idéntico" in d.estado]
    if dups:
        L.append(f"\nDuplicados detectados por contenido: {len(dups)} (no se guardaron dos veces).")

    if man.errores:
        L += ["", "## 6. Avisos y capas no disponibles", ""] + [f"- {m}" for m in man.errores]

    if params.pais == "PER":
        L += ["", "## 7. Fuentes oficiales peruanas (descarga manual)", "",
              "No permiten descarga automática. Si tu docente o entidad exige la fuente oficial, "
              "agrégalas a mano en la carpeta indicada:", "",
              _fila("Insumo", "Fuente", "Reemplazo automático usado", "Carpeta", "Cómo obtenerla"),
              _fila("---", "---", "---", "---", "---")]
        for f in FUENTES_OFICIALES_PERU:
            L.append(_fila(f["insumo"], f["fuente"], f["equivalente_automatico"], f"`{f['carpeta']}`", f["como"]))

    usados = {p.insumo for p in man.productos}
    citas = [CopernicusDEM.cita] + [c.cita for k, c in TEMATICOS.items() if k in usados]
    if "imagen" in x:
        citas = [c.replace("[año]", x["imagen"][1][:4]) for c in citas]
    L += ["", "## 8. Cómo citar los datos (APA 7)", ""] + [f"- {c}" for c in dict.fromkeys(citas)]
    L += ["", "## 9. Siguientes pasos", "",
          f"1. Abre `{CARPETAS['dem']}` y `{CARPETAS['procesados']}/cuenca_delineada` en QGIS o ArcMap.",
          "2. Verifica la salida y la divisoria sobre la imagen de "
          f"`{CARPETAS['imagenes']}` (o un mapa base satelital).",
          "3. Repite la delineación con tu herramienta de SIG y calcula los parámetros morfométricos.",
          "4. Calcula pendientes, curvas de nivel y sombreado sobre el DEM **con margen**, y recién después "
          "recorta a la cuenca: si recortas antes, el borde genera pendientes falsas.", ""]
    k = 0                                  # numerar las secciones que realmente aparecen
    for i, linea in enumerate(L):
        if linea.startswith("## ") and linea[3:4].isdigit():
            k += 1
            L[i] = f"## {k}. " + linea.split(". ", 1)[1]
    out = res.raiz / CARPETAS["resultados"] / "REPORTE.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out
