"""Shared state for ORÁCULO: paths, config and per-task records.

Everything lives under the user's workdir:

    .oraculo/               state dir (gitignore it)
        config.json         user config (defaults created on first read)
        runs.ndjson         append-only run history
        tasks/<name>.json   one state file per task
        compiled/<name>.py  graduated scripts
        ejemplos/<name>/    captured real input/output examples
        requests/<name>.md  manual-backend compilation requests
    ORACULO.log             public, append-only event log (workdir root)

Task lifecycle: observada -> candidata -> sombra -> promovida
                                              \\-> degradada (on failure, back to LLM)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

ESTADOS = ("observada", "candidata", "sombra", "promovida", "degradada")

NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

CONFIG_DEFECTO: dict[str, Any] = {
    "deteccion": {
        # Conservative by default: precision over coverage.
        "min_corridas": 3,
        "ventana_dias": 30,
    },
    "sombra": {
        "exitos_requeridos": 3,
        "exitos_requeridos_cura": 2,
    },
    "presupuesto": {
        # All token figures are ESTIMATES; the method is always shown in logs
        # and reports. Never presented as measured.
        "tokens_por_corrida_estimados": 1500,
        "tokens_salida_compilacion": 2000,
        "horizonte_dias": 30,
    },
    "backend": "auto",  # auto | claude | manual
    "backend_timeout_s": 600,
    "captura": {
        "max_ejemplos": 10,
        "max_bytes_ejemplo": 65536,
    },
    # Fully functional from day one; inactive until the user records global
    # consent with `oraculo manada on --acepto` (MANADA.md §4.5).
    "manada": "off",
    "manada_url": "https://raw.githubusercontent.com/nklabs-dev/oraculo/main/herramientas/",
    "guardian": {
        "url_pack": "https://raw.githubusercontent.com/nklabs-dev/oraculo/main/guardian_rules/",
        "auto_update_dias": 7,
    },
    "log_sync": {
        "auto": True,
    },
}


def ahora() -> float:
    return time.time()


def dir_estado(workdir: Path) -> Path:
    return Path(workdir) / ".oraculo"


def ruta_log(workdir: Path) -> Path:
    return Path(workdir) / "ORACULO.log"


def ruta_runs(workdir: Path) -> Path:
    return dir_estado(workdir) / "runs.ndjson"


def dir_tareas(workdir: Path) -> Path:
    return dir_estado(workdir) / "tasks"


def dir_compilados(workdir: Path) -> Path:
    return dir_estado(workdir) / "compiled"


def dir_ejemplos(workdir: Path, nombre: str) -> Path:
    return dir_estado(workdir) / "ejemplos" / nombre


def dir_requests(workdir: Path) -> Path:
    return dir_estado(workdir) / "requests"


def ruta_compilado(workdir: Path, nombre: str) -> Path:
    return dir_compilados(workdir) / f"{nombre}.py"


def validar_nombre(nombre: str) -> str:
    if not NOMBRE_VALIDO.match(nombre or ""):
        raise ValueError(
            f"invalid task name {nombre!r}: use letters, digits, '_', '-', '.' (max 64 chars)"
        )
    return nombre


def _fusionar(base: dict, extra: dict) -> dict:
    salida = dict(base)
    for clave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(salida.get(clave), dict):
            salida[clave] = _fusionar(salida[clave], valor)
        else:
            salida[clave] = valor
    return salida


def cargar_config(workdir: Path) -> dict[str, Any]:
    """User config merged over defaults. Unknown keys are kept."""
    ruta = dir_estado(workdir) / "config.json"
    try:
        propia = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(propia, dict):
            propia = {}
    except (OSError, ValueError):
        propia = {}
    return _fusionar(CONFIG_DEFECTO, propia)


def tarea_nueva(nombre: str) -> dict[str, Any]:
    ts = ahora()
    return {
        "nombre": nombre,
        "estado": "observada",
        "creado": ts,
        "actualizado": ts,
        "comando": None,
        "aridad": None,
        "corridas": 0,
        "exitos": 0,
        "dur_ms_promedio": 0.0,
        "sombra": {"exitos": 0, "requeridos": None},
        "intercepciones": 0,
        "degradaciones": 0,
        "ultimo_error": None,
    }


def cargar_tarea(workdir: Path, nombre: str) -> dict[str, Any] | None:
    ruta = dir_tareas(workdir) / f"{validar_nombre(nombre)}.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError):
        return None


def guardar_tarea(workdir: Path, tarea: dict[str, Any]) -> None:
    carpeta = dir_tareas(workdir)
    carpeta.mkdir(parents=True, exist_ok=True)
    tarea["actualizado"] = ahora()
    ruta = carpeta / f"{tarea['nombre']}.json"
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tarea, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def listar_tareas(workdir: Path) -> list[dict[str, Any]]:
    carpeta = dir_tareas(workdir)
    tareas = []
    if carpeta.is_dir():
        for ruta in sorted(carpeta.glob("*.json")):
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(datos, dict) and datos.get("nombre"):
                tareas.append(datos)
    return tareas
