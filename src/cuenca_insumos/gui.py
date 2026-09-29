"""Interfaz gráfica simple (Tkinter, incluido con Python: no hay que instalar nada).

    python -m cuenca_insumos ventana

Usa el mismo núcleo que la terminal (``ProyectoCuenca``): la ventana solo reúne
los datos, muestra el plan y el avance, y dibuja un esquema del área. El trabajo
pesado corre en un hilo aparte para que la ventana no se congele; los mensajes
vuelven al hilo principal por una cola, porque Tkinter no admite que otro hilo
toque sus controles.
"""
from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .config import Parametros
from .coords import ErrorCoordenadas, Punto, resolver_sistema
from .proyecto import EntradaCuenca, ProyectoCuenca
from .proveedores import TEMATICOS
from .reporte import texto_plan

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = ["main"]

# mismo contenido que examples/huacara.toml (la carpeta examples/ no viaja con el paquete)
HUACARA = {"nombre": "Quebrada Huacara", "zona": 18, "hemisferio": "S",
           "salida": {"x": 459329.724, "y": 8769071.156},
           "cabecera": {"x": 458566.19, "y": 8764100.15},
           "parametros": {"pais": "PER"}}

ETIQUETAS = {
    "unidades": "Unidades HydroBASINS",
    "rios": "Ríos HydroRIVERS",
    "limites": "Límites GADM",
    "toponimia": "Toponimia GeoNames",
    "imagen": "Imagen Sentinel-2",
    "osm": "OpenStreetMap (lento)",
    "cobertura": "Cobertura WorldCover",
}

# paleta validada de las figuras del proyecto (+ un azul oscuro para el cauce)
AZUL, NARANJA, VERDE = "#2a78d6", "#eb6834", "#1baf7a"
AZUL_CLARO, AZUL_OSCURO, GRIS, TINTA = "#cfe0f5", "#123f7a", "#8a8a8a", "#333333"


def _abrir(ruta: Path) -> None:
    """Abre un archivo o carpeta con el programa predeterminado del sistema."""
    if sys.platform == "win32":
        os.startfile(ruta)  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(ruta)])


class Ventana:
    def __init__(self, raiz: tk.Tk):
        self.r = raiz
        raiz.title(f"cuenca-insumos {__version__}")
        # tamaño según la pantalla: con la escala de Windows al 125 % o 150 % los controles crecen
        ancho, alto = raiz.winfo_screenwidth(), raiz.winfo_screenheight()
        raiz.geometry(f"{min(1320, ancho - 60)}x{min(900, alto - 110)}+20+10")
        raiz.minsize(900, 600)
        self.cola: queue.Queue = queue.Queue()
        self.hilo: threading.Thread | None = None
        self.proy: ProyectoCuenca | None = None
        self.plan = None
        self.resultado = None
        self.plan_texto = ""
        self.params_toml: dict = {}
        self.version = 0  # sube con cada cambio en el formulario: invalida el plan anterior
        self._t_prog = 0.0

        self.v = {k: tk.StringVar() for k in
                  ("nombre", "sx", "sy", "cx", "cy", "zona", "hemisferio", "datum", "epsg", "carpeta")}
        self.v["nombre"].set("Cuenca")
        self.v["zona"].set("18")
        self.v["hemisferio"].set("S")
        self.v["datum"].set("WGS84")
        self.v["carpeta"].set(str(Path.cwd()))
        self.insumos = {k: tk.BooleanVar(value=cls.por_defecto) for k, cls in TEMATICOS.items()}
        self.formato = tk.StringVar(value="gpkg")
        self.destino = tk.StringVar()

        self._estilos()
        self._construir()
        for var in [*self.v.values(), *self.insumos.values(), self.formato]:
            var.trace_add("write", self._cambio)
        self._actualizar_destino()
        self._botones()
        self.r.after(100, self._atender_cola)
        self.r.protocol("WM_DELETE_WINDOW", self._cerrar)

    # ================================================================ construcción
    def _estilos(self) -> None:
        st = ttk.Style(self.r)
        if "vista" in st.theme_names():
            st.theme_use("vista")
        st.configure("Accion.TButton", font=("Segoe UI", 10, "bold"), padding=(10, 6))
        st.configure("Nota.TLabel", foreground="#666666")
        st.configure("Titulo.TLabel", font=("Segoe UI", 13, "bold"))

    def _construir(self) -> None:
        izq = ttk.Frame(self.r, padding=(12, 10, 6, 10))
        izq.pack(side="left", fill="y")
        der = ttk.Frame(self.r, padding=(6, 10, 12, 10))
        der.pack(side="left", fill="both", expand=True)

        # los botones de acción se empaquetan primero y abajo: nunca quedan fuera de la ventana
        acciones = ttk.Frame(izq)
        acciones.pack(side="bottom", fill="x", pady=(8, 0))
        fila = ttk.Frame(acciones)
        fila.pack(fill="x")
        self.b_analizar = ttk.Button(fila, text="1. Analizar", style="Accion.TButton", command=self.analizar)
        self.b_analizar.pack(side="left", fill="x", expand=True)
        self.b_descargar = ttk.Button(fila, text="2. Descargar", style="Accion.TButton", command=self.descargar)
        self.b_descargar.pack(side="left", fill="x", expand=True, padx=(6, 0))
        fila = ttk.Frame(acciones)
        fila.pack(fill="x", pady=(6, 0))
        self.b_carpeta = ttk.Button(fila, text="Abrir carpeta", command=self.abrir_carpeta)
        self.b_carpeta.pack(side="left", fill="x", expand=True)
        self.b_reporte = ttk.Button(fila, text="Abrir reporte", command=self.abrir_reporte)
        self.b_reporte.pack(side="left", fill="x", expand=True, padx=(6, 0))

        fila = ttk.Frame(izq)
        fila.pack(fill="x", pady=(0, 4))
        ttk.Label(fila, text="Insumos para una cuenca", style="Titulo.TLabel").pack(side="left")
        ttk.Button(fila, text="Abrir .toml…", command=self.abrir_toml).pack(side="right")
        ttk.Button(fila, text="Ejemplo Huacará", command=self.ejemplo).pack(side="right", padx=6)

        f = ttk.LabelFrame(izq, text="Ubicación (coordenadas UTM, en metros)", padding=8)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Nombre").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v["nombre"]).grid(row=0, column=1, columnspan=2, sticky="we", pady=2)
        ttk.Label(f, text="Este (X)", style="Nota.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="Norte (Y)", style="Nota.TLabel").grid(row=1, column=2, sticky="w", padx=(6, 0))
        for fila_, (texto, cx, cy) in enumerate((("Salida *", "sx", "sy"), ("Cabecera", "cx", "cy")), start=2):
            ttk.Label(f, text=texto).grid(row=fila_, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(f, textvariable=self.v[cx], width=15).grid(row=fila_, column=1, sticky="w", pady=2)
            ttk.Entry(f, textvariable=self.v[cy], width=15).grid(row=fila_, column=2, sticky="w", padx=(6, 0), pady=2)
        ttk.Label(f, text="* obligatoria: la desembocadura. La cabecera (inicio del río) es opcional, "
                          "pero ajusta mejor el área.", style="Nota.TLabel", wraplength=400).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(2, 0))

        f = ttk.LabelFrame(izq, text="Sistema de coordenadas", padding=8)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Zona").grid(row=0, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v["zona"], values=["17", "18", "19"], width=4).grid(
            row=0, column=1, sticky="w", padx=(4, 10))
        ttk.Label(f, text="Hemisferio").grid(row=0, column=2, sticky="w")
        ttk.Combobox(f, textvariable=self.v["hemisferio"], values=["S", "N"], width=3,
                     state="readonly").grid(row=0, column=3, sticky="w", padx=(4, 10))
        ttk.Label(f, text="Datum").grid(row=0, column=4, sticky="w")
        ttk.Combobox(f, textvariable=self.v["datum"], values=["WGS84", "SIRGAS2000", "PSAD56"], width=11,
                     state="readonly").grid(row=0, column=5, sticky="w", padx=(4, 0))
        ttk.Label(f, text="EPSG").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(f, textvariable=self.v["epsg"], width=7).grid(row=1, column=1, sticky="w", padx=(4, 10),
                                                                  pady=(4, 0))
        ttk.Label(f, text="opcional; si lo pones, manda sobre la zona", style="Nota.TLabel").grid(
            row=1, column=2, columnspan=4, sticky="w", pady=(4, 0))

        f = ttk.LabelFrame(izq, text="Insumos a descargar", padding=8)
        f.pack(fill="x", pady=3)
        dem = ttk.Checkbutton(f, text="DEM Copernicus (siempre)")
        dem.state(["!alternate", "selected", "disabled"])
        dem.grid(row=0, column=0, sticky="w", padx=(0, 12))
        for i, (k, var) in enumerate(self.insumos.items(), start=1):
            ttk.Checkbutton(f, text=ETIQUETAS.get(k, TEMATICOS[k].insumo), variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        fila = ttk.Frame(f)
        fila.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(fila, text="Formato vectorial:").pack(side="left")
        ttk.Radiobutton(fila, text="GeoPackage", value="gpkg", variable=self.formato).pack(side="left", padx=4)
        ttk.Radiobutton(fila, text="Shapefile (ArcMap)", value="shp", variable=self.formato).pack(side="left")

        f = ttk.LabelFrame(izq, text="Guardar en", padding=8)
        f.pack(fill="x", pady=3)
        fila = ttk.Frame(f)
        fila.pack(fill="x")
        ttk.Entry(fila, textvariable=self.v["carpeta"]).pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="…", width=3, command=self.elegir_carpeta).pack(side="left", padx=(4, 0))
        ttk.Label(f, textvariable=self.destino, style="Nota.TLabel", wraplength=400).pack(anchor="w", pady=(3, 0))

        # --- lado derecho: esquema + registro + barra de estado --------------------
        panel = ttk.PanedWindow(der, orient="vertical")
        panel.pack(fill="both", expand=True)
        marco = ttk.LabelFrame(panel, text="Esquema del área (UTM)", padding=4)
        self.lienzo = tk.Canvas(marco, background="white", highlightthickness=0, height=300)
        self.lienzo.pack(fill="both", expand=True)
        self.lienzo.bind("<Configure>", lambda _e: self._dibujar())
        panel.add(marco, weight=3)
        marco = ttk.LabelFrame(panel, text="Registro", padding=4)
        self.registro = ScrolledText(marco, height=14, font=("Consolas", 9), wrap="word", state="disabled",
                                     relief="flat", background="#fbfbfb")
        self.registro.pack(fill="both", expand=True)
        panel.add(marco, weight=2)

        barra = ttk.Frame(der)
        barra.pack(fill="x", pady=(6, 0))
        self.progreso = ttk.Progressbar(barra, length=220, mode="determinate", maximum=100)
        self.progreso.pack(side="left")
        self.estado = tk.StringVar(value="Completa la salida (o carga el ejemplo) y pulsa «1. Analizar».")
        ttk.Label(barra, textvariable=self.estado).pack(side="left", padx=10)

    # ================================================================ estado
    def _cambio(self, *_a) -> None:
        self.version += 1
        if self.plan is not None or self.resultado is not None:
            self.plan = self.proy = self.resultado = None
            self.estado.set("Los datos cambiaron: vuelve a pulsar «1. Analizar».")
            self._dibujar()
        self._actualizar_destino()
        self._botones()

    def _nombre(self) -> str:
        return self.v["nombre"].get().strip() or "Cuenca"

    def _carpeta_proyecto(self) -> Path:
        return Path(self.v["carpeta"].get().strip() or ".") / f"Proyecto_{self._nombre().replace(' ', '_')}"

    def _actualizar_destino(self) -> None:
        self.destino.set(f"Se creará: {self._carpeta_proyecto()}")

    def _ocupado(self) -> bool:
        return self.hilo is not None and self.hilo.is_alive()

    def _botones(self) -> None:
        ocup = self._ocupado()
        hecho = self.resultado is not None
        for b, activo in ((self.b_analizar, not ocup), (self.b_descargar, not ocup and self.plan is not None),
                          (self.b_carpeta, (hecho or self._carpeta_proyecto().exists()) and not ocup),
                          (self.b_reporte, hecho and not ocup)):
            b.state(["!disabled"] if activo else ["disabled"])

    # ================================================================ registro
    def _log(self, texto: str) -> None:
        self.registro.configure(state="normal")
        self.registro.insert("end", texto + "\n")
        self.registro.see("end")
        self.registro.configure(state="disabled")

    def _limpiar_log(self) -> None:
        self.registro.configure(state="normal")
        self.registro.delete("1.0", "end")
        self.registro.configure(state="disabled")

    # desde el hilo de trabajo solo se escribe en la cola
    def _log_hilo(self, texto: str) -> None:
        self.cola.put(("log", texto))

    def _progreso_hilo(self, nombre: str, hecho: int, total: int | None) -> None:
        ahora = time.monotonic()
        if ahora - self._t_prog < 0.15 and (total is None or hecho < total):
            return
        self._t_prog = ahora
        self.cola.put(("prog", nombre, hecho, total))

    def _atender_cola(self) -> None:
        try:
            while True:
                m = self.cola.get_nowait()
                if m[0] == "log":
                    self._log(m[1])
                elif m[0] == "prog":
                    self._mostrar_progreso(*m[1:])
                elif m[0] == "fin":
                    _, al_terminar, version, resultado, error = m
                    self.progreso.stop()
                    self.progreso.configure(mode="determinate", value=0)
                    self.r.configure(cursor="")
                    self.hilo = None
                    if error is not None:
                        self._error(error)
                    elif version != self.version:
                        self.estado.set("Los datos cambiaron durante el proceso: vuelve a pulsar «1. Analizar».")
                    else:
                        al_terminar(resultado)
                    self._botones()
        except queue.Empty:
            pass
        self.r.after(100, self._atender_cola)

    def _mostrar_progreso(self, nombre: str, hecho: int, total: int | None) -> None:
        if total:
            if str(self.progreso.cget("mode")) != "determinate":
                self.progreso.stop()
                self.progreso.configure(mode="determinate")
            self.progreso.configure(value=100 * hecho / total)
            self.estado.set(f"Descargando {nombre[:40]}: {hecho / 1e6:.1f} de {total / 1e6:.1f} MB")
        else:
            self.estado.set(f"Descargando {nombre[:40]}: {hecho / 1e6:.1f} MB")

    def _lanzar(self, trabajo, al_terminar, mensaje: str) -> None:
        version = self.version

        def correr():
            try:
                self.cola.put(("fin", al_terminar, version, trabajo(), None))
            except Exception as ex:  # noqa: BLE001 - todo error vuelve a la ventana
                self.cola.put(("fin", al_terminar, version, None, ex))

        self.estado.set(mensaje)
        self.progreso.configure(mode="indeterminate")
        self.progreso.start(12)
        self.r.configure(cursor="watch")
        self.hilo = threading.Thread(target=correr, daemon=True)
        self.hilo.start()
        self._botones()

    def _error(self, ex: BaseException) -> None:
        if isinstance(ex, ErrorCoordenadas):
            titulo, msg = "Error en las coordenadas", str(ex)
        elif isinstance(ex, ValueError):
            titulo, msg = "Dato no válido", str(ex)
        else:
            titulo, msg = "Error", f"{type(ex).__name__}: {ex}"
        self._log(f"\n{titulo.upper()}: {msg}")
        self.estado.set(titulo)
        messagebox.showerror(titulo, msg, parent=self.r)

    # ================================================================ lectura del formulario
    def _numero(self, clave: str, etiqueta: str) -> float | None:
        t = self.v[clave].get().strip().replace(" ", "")
        if not t:
            return None
        if "," in t and "." not in t:
            t = t.replace(",", ".")  # coma decimal
        try:
            return float(t)
        except ValueError:
            raise ErrorCoordenadas(f"{etiqueta}: «{self.v[clave].get()}» no es un número.") from None

    def _leer(self) -> tuple[EntradaCuenca, Parametros, Path]:
        sx, sy = self._numero("sx", "Salida X"), self._numero("sy", "Salida Y")
        if sx is None or sy is None:
            raise ErrorCoordenadas("Falta el punto de salida: escribe su Este (X) y su Norte (Y).")
        cx, cy = self._numero("cx", "Cabecera X"), self._numero("cy", "Cabecera Y")
        if (cx is None) != (cy is None):
            raise ErrorCoordenadas("La cabecera necesita las dos coordenadas (X e Y), o ninguna.")
        epsg_t, zona_t = self.v["epsg"].get().strip(), self.v["zona"].get().strip()
        try:
            epsg = int(epsg_t) if epsg_t else None
            zona = int(zona_t) if zona_t else None
        except ValueError:
            raise ErrorCoordenadas("La zona UTM y el EPSG deben ser números enteros.") from None
        sis = resolver_sistema(epsg, zona, self.v["hemisferio"].get() or None, self.v["datum"].get() or "WGS84")
        entrada = EntradaCuenca(
            salida=Punto(sx, sy, sis.epsg, "Punto de salida"), sistema=sis,
            cabecera=Punto(cx, cy, sis.epsg, "Punto de cabecera") if cx is not None else None,
            nombre=self._nombre())
        p = Parametros(**self.params_toml)
        p.incluir = {k for k, v in self.insumos.items() if v.get() and not TEMATICOS[k].por_defecto}
        p.excluir = {k for k, v in self.insumos.items() if not v.get() and TEMATICOS[k].por_defecto}
        p.formato_vector = self.formato.get()
        p.validar()
        return entrada, p, self._carpeta_proyecto()

    def _rellenar(self, cfg: dict) -> None:
        for k in ("sx", "sy", "cx", "cy", "epsg"):
            self.v[k].set("")
        self.v["nombre"].set(cfg.get("nombre", "Cuenca"))
        if "salida" in cfg:
            self.v["sx"].set(str(cfg["salida"]["x"]))
            self.v["sy"].set(str(cfg["salida"]["y"]))
        if "cabecera" in cfg:
            self.v["cx"].set(str(cfg["cabecera"]["x"]))
            self.v["cy"].set(str(cfg["cabecera"]["y"]))
        self.v["zona"].set(str(cfg.get("zona", "")))
        self.v["hemisferio"].set(str(cfg.get("hemisferio", "S")).upper()[:1])
        self.v["datum"].set(cfg.get("datum", "WGS84"))
        if cfg.get("epsg"):
            self.v["epsg"].set(str(cfg["epsg"]))
        pc = dict(cfg.get("parametros", {}))
        incluir, excluir = set(pc.pop("incluir", [])), set(pc.pop("excluir", []))
        for k, var in self.insumos.items():
            var.set((TEMATICOS[k].por_defecto or k in incluir) and k not in excluir)
        self.formato.set(pc.pop("formato_vector", "gpkg"))
        campos = set(Parametros.__dataclass_fields__)
        self.params_toml = {k: v for k, v in pc.items() if k in campos}
        ignorados = sorted(set(pc) - campos)
        if ignorados:
            self._log(f"Aviso: parámetros desconocidos en el .toml, ignorados: {', '.join(ignorados)}")

    # ================================================================ acciones
    def ejemplo(self) -> None:
        self._rellenar(HUACARA)
        self.estado.set("Ejemplo de la quebrada Huacará cargado. Pulsa «1. Analizar».")

    def abrir_toml(self) -> None:
        ruta = filedialog.askopenfilename(parent=self.r, title="Abrir configuración",
                                          filetypes=[("Configuración TOML", "*.toml"), ("Todos", "*.*")])
        if not ruta:
            return
        try:
            with open(ruta, "rb") as fh:
                cfg = tomllib.load(fh)
            self._rellenar(cfg)
        except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as ex:
            self._error(ValueError(f"No se pudo leer {Path(ruta).name}: {ex}"))
            return
        self.estado.set(f"Cargado {Path(ruta).name}. Pulsa «1. Analizar».")

    def elegir_carpeta(self) -> None:
        d = filedialog.askdirectory(parent=self.r, title="Carpeta donde crear el proyecto",
                                    initialdir=self.v["carpeta"].get() or None)
        if d:
            self.v["carpeta"].set(d)

    def analizar(self) -> None:
        try:
            entrada, params, carpeta = self._leer()
        except ValueError as ex:  # ErrorCoordenadas es un ValueError
            self._error(ex)
            return
        self._limpiar_log()
        self.plan = self.proy = self.resultado = None
        self._dibujar()
        self._log(f"Analizando «{entrada.nombre}» en {entrada.sistema.nombre} (EPSG:{entrada.sistema.epsg}). "
                  "No se descarga ningún dato en este paso.\n")

        def trabajo():
            proy = ProyectoCuenca(entrada, carpeta, params, log=self._log_hilo, progreso=self._progreso_hilo)
            return proy, proy.analizar()

        self._lanzar(trabajo, self._analisis_listo, "Analizando el área…")

    def _analisis_listo(self, res) -> None:
        self.proy, self.plan = res
        self.plan_texto = texto_plan(self.plan)
        self._log(self.plan_texto)
        self.estado.set("Plan listo. Revísalo y pulsa «2. Descargar».")
        self._dibujar()

    def descargar(self) -> None:
        if self.plan is None or self.proy is None:
            return
        estimado = next((l.strip() for l in self.plan_texto.splitlines() if l.startswith("Descarga estimada")), "")
        if not messagebox.askyesno(
                "Descargar insumos",
                f"{estimado}\n\nSe creará la carpeta:\n{self.proy.raiz.resolve()}\n\n"
                "Puede tardar varios minutos. Lo que ya se descargó antes se reutiliza.\n¿Continuar?",
                parent=self.r):
            return
        proy, plan = self.proy, self.plan
        self._log("\n" + "=" * 60 + "\nDESCARGA\n" + "=" * 60)
        self._lanzar(lambda: proy.descargar(plan), self._descarga_lista, "Descargando y procesando…")

    def _descarga_lista(self, res) -> None:
        self.resultado = res
        dl = res.delineacion
        self._log(f"\nListo. Proyecto en: {res.raiz.resolve()}\nReporte: {res.reporte.resolve()}")
        if dl is not None:
            self._log(f"Cuenca delineada: {dl.area_km2:.2f} km² · ampliaciones del área: {res.iteraciones}")
        n = len(res.manifiesto.errores)
        if n:
            self._log(f"Avisos: {n} (ver «Avisos y capas no disponibles» en el reporte)")
        self.estado.set("Descarga terminada." + (f" {n} aviso(s): revisa el reporte." if n else ""))
        self._dibujar()
        messagebox.showinfo("Listo", f"Proyecto creado en:\n{res.raiz.resolve()}"
                            + (f"\n\nCuenca delineada: {dl.area_km2:.2f} km²" if dl else "")
                            + (f"\n{n} aviso(s): revisa el reporte." if n else ""), parent=self.r)

    def abrir_carpeta(self) -> None:
        ruta = self.resultado.raiz if self.resultado else self._carpeta_proyecto()
        if ruta.exists():
            _abrir(ruta.resolve())

    def abrir_reporte(self) -> None:
        if self.resultado and self.resultado.reporte.exists():
            _abrir(self.resultado.reporte.resolve())

    def _cerrar(self) -> None:
        if self._ocupado() and not messagebox.askyesno(
                "Proceso en curso", "Hay un proceso en curso. Lo ya descargado queda en la caché y se "
                "reutilizará la próxima vez.\n¿Cerrar de todos modos?", parent=self.r):
            return
        self.r.destroy()

    # ================================================================ esquema
    def _dibujar(self) -> None:
        c = self.lienzo
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if self.plan is None:
            c.create_text(w / 2, h / 2, fill=GRIS, font=("Segoe UI", 10),
                          text="Aquí aparecerá un esquema del área al pulsar «1. Analizar»,\n"
                               "y la cuenca delineada al terminar la descarga.", justify="center")
            return
        e = self.plan.entrada
        capas = [(self.plan.aoi.geom, dict(outline=GRIS, fill="", dash=(5, 3), width=1), "Área preliminar")]
        dl = None
        if self.resultado is not None:
            dl = self.resultado.delineacion
            capas.append((self.resultado.aoi_final.geom, dict(outline=TINTA, fill="", width=1),
                          "Área final (capas)"))
            if dl is not None:
                capas.append((dl.poligono, dict(outline=AZUL, fill=AZUL_CLARO, width=2), "Cuenca delineada"))
        puntos = [((e.salida.x, e.salida.y), NARANJA, "Salida")]
        if e.cabecera:
            puntos.append(((e.cabecera.x, e.cabecera.y), VERDE, "Cabecera"))

        xs, ys = [], []
        for g, _, _ in capas:
            x0, y0, x1, y1 = g.bounds
            xs += [x0, x1]
            ys += [y0, y1]
        for (x, y), _, _ in puntos:
            xs.append(x)
            ys.append(y)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        m = 28
        s = min((w - 2 * m) / max(x1 - x0, 1), (h - 2 * m) / max(y1 - y0, 1))
        ox = (w - s * (x1 - x0)) / 2
        oy = (h - s * (y1 - y0)) / 2

        def px(x: float, y: float) -> tuple[float, float]:
            return ox + s * (x - x0), h - (oy + s * (y - y0))

        for g, estilo, _ in capas:
            for poli in getattr(g, "geoms", [g]):
                pts = [v for xy in poli.exterior.coords for v in px(*xy)]
                c.create_polygon(*pts, **estilo)
        if dl is not None and len(dl.cauce_xy) > 1:
            c.create_line(*[v for xy in dl.cauce_xy for v in px(*xy)], fill=AZUL_OSCURO, width=2)
        for (x, y), color, _ in puntos:
            u, v = px(x, y)
            c.create_oval(u - 6, v - 6, u + 6, v + 6, fill=color, outline="white", width=2)

        # leyenda
        filas = [(n, est) for _, est, n in capas]
        if dl is not None and len(dl.cauce_xy) > 1:
            filas.append(("Cauce principal", dict(linea=AZUL_OSCURO)))
        filas += [(n, dict(punto=col)) for _, col, n in puntos]
        c.create_rectangle(8, 8, 190, 16 + 18 * len(filas), fill="white", outline="#dddddd")
        for i, (nombre, est) in enumerate(filas):
            y = 21 + 18 * i
            if "punto" in est:
                c.create_oval(16, y - 5, 26, y + 5, fill=est["punto"], outline="white")
            elif "linea" in est:
                c.create_line(14, y, 28, y, fill=est["linea"], width=2)
            else:
                c.create_rectangle(14, y - 5, 28, y + 5, outline=est["outline"], fill=est["fill"],
                                   dash=est.get("dash", ()))
            c.create_text(36, y, text=nombre, anchor="w", font=("Segoe UI", 9), fill=TINTA)

        # barra de escala: 1, 2 o 5 × 10^n metros, cerca de 1/5 del ancho
        objetivo = (w / 5) / s
        base = 10 ** math.floor(math.log10(objetivo))
        largo = max((b * base for b in (1, 2, 5) if b * base <= objetivo), default=base)
        u0, v0 = 16, h - 16
        c.create_line(u0, v0, u0 + largo * s, v0, width=3, fill=TINTA)
        c.create_text(u0 + largo * s / 2, v0 - 9, font=("Segoe UI", 8), fill=TINTA,
                      text=f"{largo / 1000:g} km" if largo >= 1000 else f"{largo:g} m")
        resumen = [f"Área preliminar: {self.plan.aoi.area_km2:.1f} km²"]
        if dl is not None:
            resumen += [f"Cuenca: {dl.area_km2:.2f} km²", f"Área final: {self.resultado.aoi_final.area_km2:.1f} km²"]
        c.create_text(w - 10, 12, text="\n".join(resumen), anchor="ne", justify="right",
                      font=("Segoe UI", 9), fill=TINTA)
        c.create_text(w - 14, h - 14, text="N ↑", anchor="se", font=("Segoe UI", 10, "bold"), fill=TINTA)


def _mostrar_fallo(raiz: tk.Misc | None, ex: BaseException) -> None:
    """Sin consola (pythonw) un error no se ve en ningún lado: se muestra en un diálogo."""
    detalle = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__)[-6:])
    messagebox.showerror("Error inesperado",
                         f"{type(ex).__name__}: {ex}\n\nSi se repite, copia este detalle al reportarlo:\n\n{detalle}",
                         parent=raiz)


def main() -> int:
    if sys.platform == "win32":
        try:  # texto nítido en pantallas con escala de Windows > 100 %
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    raiz = tk.Tk()
    # por defecto Tkinter imprime los errores de los botones en la consola, que con pythonw no existe
    raiz.report_callback_exception = lambda _t, ex, _tb: _mostrar_fallo(raiz, ex)
    try:
        Ventana(raiz)
    except Exception as ex:  # noqa: BLE001
        _mostrar_fallo(raiz, ex)
        raiz.destroy()
        return 1
    raiz.mainloop()
    return 0


def main_sin_consola() -> int:
    """Abre la ventana en un proceso ``pythonw`` aparte y termina: así el .bat no deja
    una consola negra abierta detrás. Antes, el .bat ya comprobó que todo importa."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if sys.platform != "win32" or not pythonw.exists():
        return main()
    subprocess.Popen([str(pythonw), "-m", "cuenca_insumos", "ventana"], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
