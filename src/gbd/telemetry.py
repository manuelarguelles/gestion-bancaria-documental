"""Trazas OpenTelemetry hacia el Application Insights conectado al proyecto de Foundry.

Con GBD_OTEL=1 cada corrida deja un árbol de spans (corrida → nodos → lectura por documento) que se ve en
Application Insights junto a las trazas de los agentes de Foundry. Sin GBD_OTEL no hace nada.
"""
from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator

from opentelemetry import trace

log = logging.getLogger("gbd.telemetry")
_listo = False


def iniciar() -> None:
    global _listo
    if _listo or os.getenv("GBD_OTEL") != "1":
        return
    from azure.monitor.opentelemetry import configure_azure_monitor

    from .foundry import project

    cs = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or project().telemetry.get_application_insights_connection_string()
    configure_azure_monitor(connection_string=cs, logger_name="gbd")
    _listo = True
    log.info("telemetría activa")


def tracer() -> trace.Tracer:
    return trace.get_tracer("gbd")


@contextlib.contextmanager
def span(nombre: str, **atributos) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(nombre) as s:
        for k, v in atributos.items():
            if v is not None:
                s.set_attribute(f"gbd.{k}", v if isinstance(v, (str, int, float, bool)) else str(v))
        yield s


def traced(nombre: str):
    """Decorador para handlers async de executors: abre un span por nodo del workflow."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        async def envoltura(self, *args, **kwargs):
            with span(nombre):
                return await fn(self, *args, **kwargs)
        return envoltura
    return deco


def vaciar() -> None:
    """Fuerza el envío antes de que el proceso termine."""
    prov = trace.get_tracer_provider()
    if hasattr(prov, "force_flush"):
        prov.force_flush(10_000)
