"""cuenca-insumos: identifica, selecciona y descarga los insumos geoespaciales
para el análisis de una cuenca hidrográfica a partir de su punto de salida.

Uso como librería::

    from cuenca_insumos import EntradaCuenca, ProyectoCuenca, Punto, resolver_sistema

    sis = resolver_sistema(zona=18, hemisferio="S")
    entrada = EntradaCuenca(salida=Punto(459329.7, 8769071.2, sis.epsg, "salida"), sistema=sis,
                            nombre="Quebrada Huacará")
    proyecto = ProyectoCuenca(entrada, "Proyecto_Huacara")
    plan = proyecto.analizar()          # no descarga datos
    resultado = proyecto.descargar(plan)
"""
__version__ = "0.1.0"

from .config import Parametros  # noqa: E402
from .coords import ErrorCoordenadas, Punto, resolver_sistema  # noqa: E402
from .proyecto import EntradaCuenca, PlanAnalisis, ProyectoCuenca, ResultadoProyecto  # noqa: E402

__all__ = ["__version__", "Parametros", "ErrorCoordenadas", "Punto", "resolver_sistema",
           "EntradaCuenca", "PlanAnalisis", "ProyectoCuenca", "ResultadoProyecto"]
