"""conmutar — the harness that makes same-day launch safe.

Three jobs, one router:

  * SHADOW  while a task is `sombra`, every run executes BOTH ways: the
    original command stays authoritative, the compiled .py runs alongside.
    Promotion requires K consecutive 100% output matches (exit code + stdout
    hash). One mismatch resets the count and sends the task back to
    `candidata` for recompilation.
  * INTERCEPT  once `promovida`, the .py catches the task BEFORE it touches
    the LLM/original path. 0 tokens, milliseconds.
  * DEGRADE  if the promoted .py fails, the failure is captured (error, line,
    input), the task is marked `degradada` and THE SAME INVOCATION falls back
    to the original path. Automatic, instant, nothing breaks. CRITICAL log.

The compiled script contract: `python3 .oraculo/compiled/<name>.py <argv...>`
receives the exact original argv, prints the result to stdout, exits 0.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import detectar, estado, log, observar

_RE_LINEA_TB = re.compile(r'File "[^"]*", line (\d+)')


def ejecutar_original(argv: list[str]) -> tuple[int, bytes, float]:
    """Run the original command capturing stdout; stderr passes through."""
    inicio = time.perf_counter()
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, check=False)
        codigo, salida = proc.returncode, proc.stdout or b""
    except OSError as exc:
        print(f"oraculo: cannot run {argv[0]!r}: {exc}", file=sys.stderr)
        codigo, salida = 127, b""
    return codigo, salida, (time.perf_counter() - inicio) * 1000.0


def ejecutar_py(
    workdir: Path, nombre: str, argv: list[str]
) -> tuple[int, bytes, float, dict[str, Any] | None]:
    """Run the compiled .py. Returns (exit, stdout, ms, error-detail-or-None)."""
    ruta = estado.ruta_compilado(workdir, nombre)
    inicio = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(ruta), *argv],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
        codigo, salida, err = proc.returncode, proc.stdout or b"", proc.stderr or b""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, b"", (time.perf_counter() - inicio) * 1000.0, {
            "error": f"{type(exc).__name__}: {exc}",
            "linea": None,
            "input": list(argv),
        }
    dur = (time.perf_counter() - inicio) * 1000.0
    if codigo == 0:
        return codigo, salida, dur, None
    texto_err = err.decode("utf-8", errors="replace").strip()
    lineas = _RE_LINEA_TB.findall(texto_err)
    return codigo, salida, dur, {
        "error": texto_err[-2000:] or f"exit {codigo}",
        "linea": int(lineas[-1]) if lineas else None,
        "input": list(argv),
    }


def degradar(workdir: Path, tarea: dict[str, Any], detalle: dict[str, Any]) -> None:
    """Automatic, instant demotion: the task goes back to the original path."""
    tarea["estado"] = "degradada"
    tarea["degradaciones"] = int(tarea.get("degradaciones", 0)) + 1
    tarea["ultimo_error"] = {**detalle, "ts": estado.ahora()}
    estado.guardar_tarea(workdir, tarea)
    log.registrar(
        workdir,
        "CRITICO",
        "fallo_produccion",
        tarea=tarea["nombre"],
        error=detalle.get("error"),
        linea=detalle.get("linea"),
        input=detalle.get("input"),
    )


def _correr_sombra(
    workdir: Path, tarea: dict[str, Any], argv: list[str], config: dict[str, Any]
) -> tuple[int, bytes]:
    """Shadow round: original stays authoritative; compare against the .py."""
    import hashlib

    nombre = tarea["nombre"]
    codigo_orig, salida_orig, dur_orig = ejecutar_original(argv)
    observar.registrar_corrida(
        workdir, nombre, argv, codigo_orig, dur_orig, salida_orig, via="original"
    )
    codigo_py, salida_py, dur_py, detalle = ejecutar_py(workdir, nombre, argv)

    tarea = estado.cargar_tarea(workdir, nombre) or tarea  # refresh counters
    sombra = tarea.setdefault("sombra", {})
    requeridos = int(
        sombra.get("requeridos") or config.get("sombra", {}).get("exitos_requeridos", 3)
    )
    coincide = (
        detalle is None
        and codigo_py == codigo_orig
        and hashlib.sha256(salida_py).hexdigest() == hashlib.sha256(salida_orig).hexdigest()
    )
    if coincide:
        sombra["exitos"] = int(sombra.get("exitos", 0)) + 1
        sombra["requeridos"] = requeridos
        if sombra["exitos"] >= requeridos:
            tarea["estado"] = "promovida"
            log.registrar(
                workdir, "MEDIO", "promovida", tarea=nombre,
                coincidencias=f"{sombra['exitos']}/{requeridos}",
            )
        estado.guardar_tarea(workdir, tarea)
        if tarea["estado"] == "sombra":
            log.registrar(
                workdir, "MEDIO", "sombra_ok", tarea=nombre,
                avance=f"{sombra['exitos']}/{requeridos}", dur_py_ms=round(dur_py, 1),
            )
    else:
        tarea["estado"] = "candidata"  # one mismatch = start over, recompile
        sombra["exitos"] = 0
        tarea["ultimo_error"] = None if detalle is None else {**detalle, "ts": estado.ahora()}
        estado.guardar_tarea(workdir, tarea)
        log.registrar(
            workdir, "MEDIO", "sombra_fallo", tarea=nombre,
            motivo="output mismatch" if detalle is None else detalle.get("error"),
        )
    return codigo_orig, salida_orig


def correr(workdir: Path, nombre: str, argv: list[str]) -> tuple[int, bytes]:
    """The router behind `oraculo run`. Returns (exit_code, stdout)."""
    estado.validar_nombre(nombre)
    if not argv:
        raise ValueError("empty command: usage is `oraculo run <name> -- <command...>`")
    config = estado.cargar_config(workdir)
    tarea = estado.cargar_tarea(workdir, nombre)
    situacion = tarea.get("estado") if tarea else None

    if situacion == "promovida" and estado.ruta_compilado(workdir, nombre).exists():
        codigo, salida, dur, detalle = ejecutar_py(workdir, nombre, argv)
        if detalle is None:
            observar.registrar_corrida(
                workdir, nombre, argv, codigo, dur, salida, via="py"
            )
            return codigo, salida
        degradar(workdir, tarea, detalle)  # falls through to the original path

    if situacion == "sombra" and estado.ruta_compilado(workdir, nombre).exists():
        return _correr_sombra(workdir, tarea, argv, config)

    codigo, salida, dur = ejecutar_original(argv)
    observar.registrar_corrida(workdir, nombre, argv, codigo, dur, salida, via="original")
    if situacion in (None, "observada"):
        detectar.detectar(workdir, nombre)  # cheap, deterministic, local
    return codigo, salida
