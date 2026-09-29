# cuenca-insumos

**Descarga automáticamente los insumos geoespaciales para analizar una cuenca hidrográfica a partir de su punto de salida.**

Das la coordenada donde el río desemboca (y, si quieres, donde nace). La herramienta decide qué datos hacen falta, qué tiles del modelo de elevación cubren la cuenca, delinea la cuenca para comprobar que el DEM la contiene entera, y descarga, verifica, recorta, reproyecta y organiza todo en una carpeta de proyecto lista para QGIS o ArcMap, con un reporte que explica cada decisión.

```text
$ cuenca-insumos analizar --config examples/huacara.toml

Área de análisis identificada
  Método:     rectángulo de cabecera y salida + margen: L = 5.03 km, margen = 3.02 km
  Superficie: 74.8 km² (preliminar; se ajusta tras delinear la cuenca)

DEM (GLO-30) encontrados: 1
DEM (GLO-30) necesarios:  1
DEM (GLO-30) descartados: 0
   + S12W076: cubre el 100.0 % del área de análisis

Unidades hidrográficas: disponible — HydroBASINS v1c, nivel 12, 72.7 MB (se reutiliza)
Red hidrográfica de referencia: disponible — HydroRIVERS v1.0, 95.3 MB (se reutiliza)
Límites administrativos: disponible — GADM versión 4.1 (niveles 0 a 3), 14.7 MB (se reutiliza)
Toponimia y centros poblados: disponible — GeoNames, 3.1 MB (se reutiliza)
Imagen satelital: disponible — Sentinel-2 L2A (se evaluará la nubosidad local de 5 escenas)

Carta Nacional IGN 1:100 000 (descarga manual en SIGMED): hoja(s) 23-m
Descarga estimada: ≈225.7 MB (sin contar lo que ya está en la caché)
```

## Qué la distingue

- **Solo descarga lo necesario.** Los tiles se eligen por intersección con el área de la cuenca, no por cercanía a un punto: si un corredor diagonal toca 4 tiles del rectángulo pero atraviesa 3, baja 3 y explica por qué descartó el cuarto.
- **Nunca se queda corta.** Delinea la cuenca con el DEM descargado; si toca el borde del área, la amplía y baja solo los tiles nuevos, hasta que la cuenca quepa entera.
- **Las capas temáticas se recortan a la cuenca real** (más un margen), no a un rectángulo aproximado.
- **Valida las coordenadas como lo haría un docente**: zona UTM equivocada (sugiere la correcta), X e Y intercambiadas, punto en el océano, cabecera que drena a otro río.
- **Cada archivo tiene procedencia**: URL, tamaño, SHA-256, fecha y licencia en un manifiesto.
- **Sin dependencias difíciles**: la delineación está escrita en numpy; no necesita GRASS, SAGA ni compilar nada. Corre también dentro del Python de QGIS.

## Instalación

Requiere **Python 3.10 o superior, de 64 bits** (probado en 3.10 y 3.14; las pruebas automáticas corren en Windows, Linux y macOS con 3.10, 3.12 y 3.13). Necesita internet para instalar las librerías (unos 60 MB) y para descargar los datos.

### En Windows, con doble clic (lo más fácil)

1. Instala Python desde [python.org/downloads](https://www.python.org/downloads/). En el instalador marca **«Add python.exe to PATH»**.
2. Descarga este repositorio (**Code → Download ZIP**) y **descomprímelo** (clic derecho → «Extraer todo»). Desde dentro del .zip no funciona.
3. Haz doble clic en **`Abrir cuenca-insumos.bat`**. La primera vez comprueba tu Python, te ofrece instalar lo que falte y luego abre la ventana. Las siguientes veces la abre directo.

### Desde la terminal (cualquier sistema)

```bash
git clone https://github.com/stivensbarja-lang/cuenca-insumos.git
cd cuenca-insumos
python -m venv .venv
.venv\Scripts\activate          # Windows  (en Linux/macOS: source .venv/bin/activate)
python -m pip install -e .
python -m cuenca_insumos --version
```

### Si no se ejecuta

Desde la carpeta del proyecto, ejecuta:

```bash
python diagnostico.py
```

Revisa uno por uno lo que suele fallar en una computadora nueva y dice cómo arreglarlo: Python ausente o demasiado antiguo, Python de 32 bits (las librerías geoespaciales no existen para 32 bits), Python sin Tkinter (la ventana no abre; la terminal sí funciona), librerías sin instalar, paquete instalado desde otra carpeta, falta de permiso para escribir y acceso bloqueado a las fuentes de datos. Si pides ayuda, copia su resultado completo.

Otros casos:

| Síntoma | Causa y solución |
|---|---|
| `"python" no se reconoce…` o se abre la Microsoft Store | Python no está instalado o no está en el PATH: reinstálalo marcando «Add python.exe to PATH». |
| `"cuenca-insumos" no se reconoce…` | La carpeta `Scripts` de Python no está en el PATH. Usa `python -m cuenca_insumos …`, que funciona siempre. |
| `No module named cuenca_insumos` | Falta instalarlo en ese Python: `python -m pip install -e .` desde la carpeta del proyecto. |
| Al instalar aparece `error: Microsoft Visual C++ 14.0 is required` o fallan `rasterio`/`pyogrio` | Tu Python es de 32 bits o no hay versión compilada de alguna librería para él: instala Python de 64 bits. Como alternativa: `conda install -c conda-forge rasterio geopandas` y después `pip install -e .`. |
| Se movió o renombró la carpeta del proyecto y dejó de funcionar | La instalación apunta a la carpeta anterior: repite `python -m pip install -e .` desde la nueva. |

## Uso

### 1. Ver qué se descargaría (no baja datos)

```bash
cuenca-insumos analizar --salida 459329.724 8769071.156 --cabecera 458566.19 8764100.15 \
                        --zona 18 --hemisferio S --nombre "Quebrada Huacara"
```

### 2. Descargar

```bash
cuenca-insumos descargar --config examples/huacara.toml --proyecto Proyecto_Huacara
```

Pregunta antes de descargar (`--si` para no preguntar). Lo ya descargado queda en la caché y no se vuelve a bajar; con `--cache RUTA` la caché se comparte entre proyectos.

### 3. Otras formas

```bash
cuenca-insumos interactivo            # pide los datos paso a paso
cuenca-insumos fuentes                # fichas de las fuentes y sus licencias
cuenca-insumos descargar ... --incluir osm,cobertura --excluir imagen --formato shp
```

Si Windows dice que no encuentra `cuenca-insumos`, la carpeta `Scripts` de Python no está en el PATH: usa `python -m cuenca_insumos` en su lugar (por ejemplo `python -m cuenca_insumos analizar --config examples/huacara.toml`).

### 4. Interfaz gráfica

```bash
python -m cuenca_insumos ventana
```

En Windows también basta con hacer doble clic en `Abrir cuenca-insumos.bat` (ver [Instalación](#instalación)). Es una ventana simple (Tkinter, que ya viene con Python: no hay que instalar nada más) con el mismo flujo que la terminal:

1. Escribe la salida (y, si la tienes, la cabecera), la zona y el hemisferio; o pulsa **Ejemplo Huacará** o **Abrir .toml…**.
2. Marca los insumos que quieres y el formato (GeoPackage o Shapefile para ArcMap).
3. **1. Analizar** muestra el plan sin descargar nada y dibuja un esquema del área.
4. **2. Descargar** pide confirmación con el tamaño estimado, muestra el avance y, al terminar, dibuja la cuenca delineada y su cauce principal. **Abrir carpeta** y **Abrir reporte** llevan a los resultados.

Si cambias cualquier dato después de analizar, hay que volver a analizar: así el plan siempre corresponde a lo que se ve en la ventana.

### Como librería

```python
from cuenca_insumos import EntradaCuenca, ProyectoCuenca, Punto, resolver_sistema

sis = resolver_sistema(zona=18, hemisferio="S")
entrada = EntradaCuenca(salida=Punto(459329.724, 8769071.156, sis.epsg, "salida"), sistema=sis,
                        cabecera=Punto(458566.19, 8764100.15, sis.epsg, "cabecera"))
proyecto = ProyectoCuenca(entrada, "Proyecto_Huacara")
plan = proyecto.analizar()
resultado = proyecto.descargar(plan)
print(resultado.reporte)
```

## Datos de entrada

| Dato | ¿Obligatorio? |
|---|---|
| Punto de **salida** (X, Y) | **Sí** |
| EPSG, o zona UTM + hemisferio | **Sí** (WGS 84, SIRGAS 2000 y PSAD56 en UTM, o EPSG:4326) |
| Punto de **cabecera** (X, Y) | Recomendado: ajusta el área inicial y verifica la salida |
| Área estimada en km² | Opcional, si no hay cabecera |

## Qué descarga

La lista sale de revisar qué insumos exige de verdad un análisis de delimitación y morfometría de una cuenca: por defecto se incluye solo eso.

| Insumo | Fuente | Por defecto |
|---|---|---|
| Modelo de elevación digital | Copernicus DEM GLO-30 (ESA), o GLO-90 en cuencas muy grandes | Siempre |
| Unidades hidrográficas | HydroBASINS nivel 12 (Pfafstetter) | Sí |
| Red hidrográfica de referencia | HydroRIVERS | Sí |
| Límites administrativos | GADM 4.1, niveles 0–3 | Sí |
| Toponimia y centros poblados | GeoNames | Sí |
| Imagen satelital | Sentinel-2 L2A color verdadero (la escena con menos nubes *dentro* de la cuenca) | Sí |
| Cursos de agua menores y lugares | OpenStreetMap (Overpass); en Huacará trae el caserío y parte de la quebrada que las otras fuentes omiten | `--incluir osm` |
| Cobertura del suelo | ESA WorldCover 2021 | `--incluir cobertura` |

Las fuentes oficiales peruanas (ANA, IGN, INEI, SENAMHI) no permiten descarga automática: el reporte las lista con instrucciones y calcula qué hoja de la Carta Nacional hay que bajar. La ficha de cada fuente (institución, resolución, formato, sistema de referencia, licencia) se consulta con `python -m cuenca_insumos fuentes`.

## ¿Por qué el punto de salida y no dos puntos?

Porque se midió. Sobre **240 cuencas reales** de 1 a 150 km² (Chanchamayo, Junín) se comparó qué fracción de cada cuenca queda dentro del área que genera cada estrategia:

| Estrategia | Cuencas contenidas por completo |
|---|---:|
| Un punto + círculo de 10 km | 69 % (0 % de las de 60–150 km²) |
| **Dos puntos solos** (rectángulo de inicio y salida) | **0 %** |
| Dos puntos + margen (rectángulo, k = 0.6) | 92 % |
| **Salida + delineación con expansión iterativa** (lo que hace esta herramienta) | **100 %** |

Los dos puntos no bastan porque la cuenca se ensancha a los lados del río y su divisoria queda más allá del nacimiento: en Huacará, el rectángulo de los dos puntos cubre solo el 8 % de la cuenca. La cabecera sí sirve, pero para otra cosa: **dimensiona el área inicial y verifica que la salida esté en el río correcto**. La garantía la da la delineación. Con el área inicial recomendada, la herramienta descarga en promedio 1.26 tiles por cuenca, solo 0.10 innecesarios, y en el 98.4 % de los casos no necesita una segunda ronda de descarga.

## Lo que genera

Ejemplo real con la quebrada Huacará: 214 MB descargados, cuenca de 6.95 km² contenida al primer intento, 7 ríos, las 9 provincias de Junín y los 6 distritos de Chanchamayo con San Ramón marcado, y una imagen Sentinel-2 con 0 % de nubes dentro de la cuenca (recorte de 0.8 MB en vez de la escena completa).

```text
Proyecto_Huacara/
├── 01_Coordenadas/          puntos de entrada, áreas de análisis, toponimia
├── 02_DEM/                  DEM en UTM con margen alrededor de la cuenca (NoData fuera, nunca 0)
├── 03_Hidrografia/          ríos HydroRIVERS, unidades HydroBASINS
├── 04_Cobertura_Uso_Suelo/  (si se incluye)
├── 05_Suelos/  06_Clima/    (reservadas)
├── 07_Limites/              país, departamentos, provincias y distritos (campo SEL = unidad de la cuenca)
├── 08_Imagenes_Satelitales/ Sentinel-2
├── 09_Procesados/           cuenca delineada, salida ajustada, cauce principal
├── 10_Resultados/           REPORTE.md, manifiesto.json, manifiesto_descargas.csv
└── _cache/                  descargas originales, reutilizables
```

La delineación es preliminar y sirve para decidir qué descargar. El análisis morfométrico definitivo hazlo en tu SIG sobre el DEM de `02_DEM`.

## Validación con un caso real

Frente a la cuenca de la quebrada Huacará delineada con GRASS (`r.fill.dir` + `r.watershed` + `r.water.outlet`):

| | cuenca-insumos (D8) | GRASS |
|---|---|---|
| Área | 6.92 km² | 6.87 km² (+0.8 %) |
| Coincidencia espacial (IoU) | 0.966 | — |
| Salida ajustada | misma celda | — |
| Tiempo | 0.19 s | — |

## Pruebas

```bash
pip install -e ".[dev]"
pytest
```

67 pruebas: validación de coordenadas, selección de tiles (incluido el caso «4 encontrados, 3 necesarios, 1 descartado»), delineación contra soluciones analíticas, descargas contra un servidor HTTP local (caché, archivos corruptos, duplicados, 404), el formulario de la ventana, el diagnóstico de instalación y la integración con el caso Huacará (se omite si esos datos no están). Ninguna necesita internet. GitHub Actions las corre en Windows, Linux y macOS con Python 3.10, 3.12 y 3.13 (`.github/workflows/pruebas.yml`).

## Limitaciones

- La delineación usa D8: en zonas muy planas (llanura amazónica, altiplano) conviene verificarla con métodos de flujo múltiple.
- HydroRIVERS no incluye cursos con cuencas menores de 10 km² y su trazo es esquemático (puede quedar a unos cientos de metros del cauce real): sirve de contexto, no para medir. Para microcuencas usa la red derivada del DEM.
- La delineación depende del DEM de 30 m: en Huacará difiere un 1 % en área de la hecha con GRASS sobre el mismo DEM, y la diferencia puede crecer en cuencas muy pequeñas (< 1 km²).
- El servidor público de Overpass (OSM) suele estar saturado; por eso es opcional.
- Probado sobre todo en los Andes peruanos. La detección automática de región HydroSHEDS es aproximada fuera de Sudamérica: usa `--continente`.

## Licencias de los datos

El código es MIT, pero **cada fuente tiene su licencia**: GADM es solo para uso académico y no comercial; Copernicus, HydroSHEDS y Sentinel-2 exigen atribución; GeoNames y WorldCover son CC BY 4.0; OSM es ODbL. El reporte de cada proyecto incluye las citas en APA 7.

## Agregar una fuente

Crea una subclase de `Proveedor` en `src/cuenca_insumos/proveedores/` con su ficha técnica (institución, licencia, resolución…) y dos métodos: `planificar(ctx)`, que decide qué hace falta sin descargar, y `ejecutar(ctx, plan)`, que descarga y recorta. Regístrala en `proveedores/__init__.py`. El resto de la herramienta no cambia.

## Licencia

MIT © 2026 Barja Stivens. Facultad de Ingeniería Forestal y Ambiental, Universidad Nacional del Centro del Perú.
