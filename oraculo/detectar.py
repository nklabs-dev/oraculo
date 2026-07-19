"""detectar — decide, deterministically, which observed tasks are MUNDANE.

Conservative parameters by default (configurable in `.oraculo/config.json`):

    * the task ran >= `min_corridas` times inside `ventana_dias`
    * every run used the SAME structure: same command, same arity
    * only the data varied (values of the arguments), never the shape
    * every run exited 0

Verdict is a pure function of the history: same history, same verdict, always.
A task that passes goes `observada -> candidata`. Nothing is compiled here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import estado, log, observar


def evaluar(corridas: list[dict[str, Any]], config: dict[str, Any]) -> tuple[bool, str]:
    """Pure verdict over one task's original runs. Returns (mundana, reason)."""
    params = config.get("deteccion", {})
    minimo = int(params.get("min_corridas", 3))
    ventana_s = float(params.get("ventana_dias", 30)) * 86400.0

    if corridas:
        tope = max(c.get("ts", 0) for c in corridas)
        corridas = [c for c in corridas if c.get("ts", 0) >= tope - ventana_s]

    if len(corridas) < minimo:
        return False, f"only {len(corridas)} runs in window, need {minimo}"

    comandos = {c.get("comando") for c in corridas}
    if len(comandos) != 1 or None in comandos:
        return False, f"command varied across runs: {sorted(map(str, comandos))}"

    aridades = {c.get("aridad") for c in corridas}
    if len(aridades) != 1:
        return False, f"arity varied across runs: {sorted(aridades)}"

    fallidas = [c for c in corridas if c.get("exit_code") != 0]
    if fallidas:
        return False, f"{len(fallidas)} non-zero exits in window"

    return True, f"{len(corridas)} identical-structure clean runs"


def detectar(workdir: Path, nombre: str | None = None) -> list[str]:
    """Evaluate observed tasks; promote the mundane ones to `candidata`."""
    config = estado.cargar_config(workdir)
    nuevas: list[str] = []
    tareas = estado.listar_tareas(workdir)
    if nombre is not None:
        tareas = [t for t in tareas if t.get("nombre") == nombre]
    for tarea in tareas:
        if tarea.get("estado") != "observada":
            continue
        corridas = observar.leer_corridas(workdir, tarea["nombre"], via="original")
        mundana, razon = evaluar(corridas, config)
        if mundana:
            tarea["estado"] = "candidata"
            estado.guardar_tarea(workdir, tarea)
            log.registrar(
                workdir, "BAJO", "deteccion", tarea=tarea["nombre"], razon=razon
            )
            nuevas.append(tarea["nombre"])
    return nuevas
