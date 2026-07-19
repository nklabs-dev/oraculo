"""ORACULO.log — the open book.

Every lifecycle event is appended to ORACULO.log in the workdir root as one
readable ndjson line, triaged by level:

    CRITICO  a promoted .py failed in production (auto-degraded)
    MEDIO    compilation, shadow result, promotion, degradation, cure
    BAJO     detection, budget decisions, bookkeeping

Scope is locked BY DESIGN: this log records ONLY ORÁCULO's own lifecycle.
Nothing else that happens on the machine is observed or written here — the
writer below is the only code path into the file, and it is called exclusively
by ORÁCULO's own cycle. The first line of every log states this.

Logging never raises and never blocks the real task: any write failure is
reported to stderr and swallowed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import estado

NIVELES = ("CRITICO", "MEDIO", "BAJO")

AVISO_ALCANCE = (
    "ORACULO.log — public by design. Scope locked: this file records ONLY "
    "ORACULO's own lifecycle events (detection, compilation, shadow, "
    "promotion, failure, cure) for tasks routed through 'oraculo run'. "
    "Nothing else on this machine is observed or recorded."
)


def registrar(
    workdir: Path,
    nivel: str,
    evento: str,
    tarea: str | None = None,
    **detalle: Any,
) -> None:
    """Append one event. Never raises."""
    try:
        if nivel not in NIVELES:
            nivel = "BAJO"
        ruta = estado.ruta_log(workdir)
        lineas = []
        if not ruta.exists():
            lineas.append(
                json.dumps(
                    {
                        "ts": estado.ahora(),
                        "nivel": "BAJO",
                        "evento": "alcance",
                        "aviso": AVISO_ALCANCE,
                    },
                    ensure_ascii=False,
                )
            )
        entrada: dict[str, Any] = {"ts": estado.ahora(), "nivel": nivel, "evento": evento}
        if tarea:
            entrada["tarea"] = tarea
        if detalle:
            entrada.update(detalle)
        lineas.append(json.dumps(entrada, ensure_ascii=False, default=str))
        with ruta.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lineas) + "\n")
    except Exception as exc:  # noqa: BLE001 - logging must never break the task
        print(f"oraculo: log write failed: {exc}", file=sys.stderr)


def leer(workdir: Path, desde_ts: float | None = None) -> list[dict[str, Any]]:
    """Parse the log. Malformed lines are skipped, never fatal."""
    ruta = estado.ruta_log(workdir)
    eventos: list[dict[str, Any]] = []
    try:
        with ruta.open(encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    dato = json.loads(linea)
                except ValueError:
                    continue
                if not isinstance(dato, dict):
                    continue
                if desde_ts is not None and dato.get("ts", 0) < desde_ts:
                    continue
                eventos.append(dato)
    except OSError:
        pass
    return eventos
