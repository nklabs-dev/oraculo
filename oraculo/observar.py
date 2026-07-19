"""observar — record every run that goes through ORÁCULO. 0 tokens.

Entry points:
  * the `oraculo run <name> -- <command...>` wrapper (see cli.py / conmutar.py)
  * this module's Python API, for Hermes cron scripts that want to record runs
    directly: `observar.registrar_corrida(...)`.

Guarantees, by design:
  * pure append to `.oraculo/runs.ndjson` — never blocks or slows the task
  * never raises: any failure is reported to stderr and swallowed
  * locked scope: only what is explicitly routed through ORÁCULO is recorded
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import estado


def _hash_salida(stdout_bytes: bytes | None) -> str | None:
    if stdout_bytes is None:
        return None
    return hashlib.sha256(stdout_bytes).hexdigest()


def _capturar_ejemplo(
    workdir: Path, nombre: str, argv: list[str], stdout_bytes: bytes | None,
    exit_code: int, config: dict,
) -> None:
    """Keep up to N real input/output examples: they become the test suite."""
    if stdout_bytes is None or exit_code != 0:
        return
    captura = config.get("captura", {})
    if len(stdout_bytes) > int(captura.get("max_bytes_ejemplo", 65536)):
        return
    carpeta = estado.dir_ejemplos(workdir, nombre)
    carpeta.mkdir(parents=True, exist_ok=True)
    clave = hashlib.sha256(json.dumps(argv, ensure_ascii=False).encode()).hexdigest()[:16]
    ruta = carpeta / f"{clave}.json"
    if ruta.exists():  # same input already captured
        return
    existentes = list(carpeta.glob("*.json"))
    if len(existentes) >= int(captura.get("max_ejemplos", 10)):
        return
    ruta.write_text(
        json.dumps(
            {
                "argv": argv,
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "exit_code": exit_code,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def leer_ejemplos(workdir: Path, nombre: str) -> list[dict[str, Any]]:
    ejemplos = []
    carpeta = estado.dir_ejemplos(workdir, nombre)
    if carpeta.is_dir():
        for ruta in sorted(carpeta.glob("*.json")):
            try:
                dato = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(dato, dict):
                ejemplos.append(dato)
    return ejemplos


def registrar_corrida(
    workdir: Path,
    nombre: str,
    argv: list[str],
    exit_code: int,
    dur_ms: float,
    stdout_bytes: bytes | None = None,
    via: str = "original",
) -> None:
    """Append one run and update the task's counters. Never raises."""
    try:
        estado.validar_nombre(nombre)
        config = estado.cargar_config(workdir)
        corrida = {
            "ts": estado.ahora(),
            "tarea": nombre,
            "argv": list(argv),
            "comando": argv[0] if argv else None,
            "aridad": len(argv),
            "exit_code": int(exit_code),
            "out_hash": _hash_salida(stdout_bytes),
            "out_len": None if stdout_bytes is None else len(stdout_bytes),
            "dur_ms": round(float(dur_ms), 3),
            "via": via,
        }
        ruta = estado.ruta_runs(workdir)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(corrida, ensure_ascii=False) + "\n")

        tarea = estado.cargar_tarea(workdir, nombre) or estado.tarea_nueva(nombre)
        if via == "original":
            n = int(tarea.get("corridas", 0))
            prom = float(tarea.get("dur_ms_promedio", 0.0))
            tarea["dur_ms_promedio"] = round((prom * n + float(dur_ms)) / (n + 1), 3)
            tarea["corridas"] = n + 1
            if exit_code == 0:
                tarea["exitos"] = int(tarea.get("exitos", 0)) + 1
            tarea["comando"] = corrida["comando"]
            tarea["aridad"] = corrida["aridad"]
            _capturar_ejemplo(workdir, nombre, list(argv), stdout_bytes, exit_code, config)
        elif via == "py":
            tarea["intercepciones"] = int(tarea.get("intercepciones", 0)) + 1
        estado.guardar_tarea(workdir, tarea)
    except Exception as exc:  # noqa: BLE001 - observing must never break the task
        print(f"oraculo: run record failed: {exc}", file=sys.stderr)


def leer_corridas(
    workdir: Path,
    nombre: str | None = None,
    desde_ts: float | None = None,
    via: str | None = None,
) -> list[dict[str, Any]]:
    corridas: list[dict[str, Any]] = []
    ruta = estado.ruta_runs(workdir)
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
                if nombre is not None and dato.get("tarea") != nombre:
                    continue
                if desde_ts is not None and dato.get("ts", 0) < desde_ts:
                    continue
                if via is not None and dato.get("via") != via:
                    continue
                corridas.append(dato)
    except OSError:
        pass
    return corridas
