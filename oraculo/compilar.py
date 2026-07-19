"""compilar — activate the oracle ONCE, leave a .py behind forever.

The compilation package = the observed history as specification + real
captured input/output examples as tests + INGENIERO.md as the standard.

Backends (multi-model by design):
  * `claude`  — Claude Code print mode, output redirected to a file
                (house-validated pattern; respects the user's subscription).
  * `manual`  — writes `.oraculo/requests/<task>.md`; ANY agent (or human)
                fulfills it and injects the result with
                `oraculo compile <task> --desde <file.py>`.

Hard budget: before compiling, the projected saving must beat the estimated
compilation cost — otherwise the task is NOT compiled and the decision is
logged (BAJO) with the numbers and the method. Estimates are always labeled
as estimates.

Every produced script passes the guardian and must replay the captured real
examples byte-exact before it may enter shadow. Failures never install.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import estado, guardian, log, observar

RUTA_INGENIERO_USUARIO = Path.home() / ".oraculo" / "INGENIERO.md"
RUTA_INGENIERO_REPO = Path(__file__).resolve().parent.parent / "INGENIERO.md"

_RE_BLOQUE_PY = re.compile(r"```(?:python|py)\n(.*?)```", re.DOTALL)


def cargar_ingeniero() -> str:
    for ruta in (RUTA_INGENIERO_USUARIO, RUTA_INGENIERO_REPO):
        try:
            return ruta.read_text(encoding="utf-8")
        except OSError:
            continue
    return "(INGENIERO.md not found — apply strict engineering defaults)"


def armar_paquete(workdir: Path, nombre: str, cura: dict[str, Any] | None = None) -> str:
    """The compilation request: history as spec, examples as tests, standard."""
    tarea = estado.cargar_tarea(workdir, nombre) or {}
    corridas = observar.leer_corridas(workdir, nombre, via="original")
    ejemplos = observar.leer_ejemplos(workdir, nombre)

    partes = [
        f"# ORÁCULO compilation request — task `{nombre}`",
        "",
        "This task was observed to be mundane: same command, same structure, "
        "only the data varied. Write ONE Python script that replaces it forever.",
        "",
        "## Contract",
        f"- Invocation: `python3 compiled.py <argv...>` with the EXACT argv of the "
        f"original command (observed command: `{tarea.get('comando')}`, "
        f"arity {tarea.get('aridad')}).",
        "- stdout must byte-match what the original command prints for the same "
        "argv (trailing newline included). stdout is ONLY the task output.",
        "- Exit 0 on success; non-zero + one clear stderr line on any failure.",
        "",
        "## Observed history (the specification)",
        f"- runs observed: {len(corridas)}; all exit 0; "
        f"mean duration {tarea.get('dur_ms_promedio', 0)} ms",
    ]
    for corrida in corridas[-10:]:
        partes.append(
            f"  - argv={json.dumps(corrida.get('argv'), ensure_ascii=False)} -> "
            f"exit {corrida.get('exit_code')}, stdout sha256 {str(corrida.get('out_hash'))[:16]}…"
        )
    partes += ["", "## Real captured examples (these ARE the tests — replayed verbatim)"]
    if ejemplos:
        for ejemplo in ejemplos:
            partes += [
                f"- argv: {json.dumps(ejemplo.get('argv'), ensure_ascii=False)}",
                "  expected stdout:",
                "  ```",
                *("  " + linea for linea in str(ejemplo.get("stdout", "")).splitlines()),
                "  ```",
            ]
    else:
        partes.append("- (no examples captured — derive behavior from the command itself)")
    if cura:
        partes += [
            "",
            "## CURE MODE — surgical fix, nothing else",
            "The previous compiled script failed in production. Fix ONLY this "
            "failure; keep every other behavior identical:",
            f"- error: {cura.get('error')}",
            f"- line: {cura.get('linea')}",
            f"- failing input argv: {json.dumps(cura.get('input'), ensure_ascii=False)}",
            "",
            "## Current script (to fix)",
            "```python",
            cura.get("codigo_actual", ""),
            "```",
        ]
    partes += [
        "",
        "## The standard (mandatory — the guardian enforces it)",
        cargar_ingeniero(),
        "",
        "Reply with the complete script in ONE ```python fenced block.",
    ]
    return "\n".join(partes)


def break_even(workdir: Path, nombre: str, prompt: str) -> dict[str, Any]:
    """ESTIMATED compile cost vs projected saving. Method always visible."""
    config = estado.cargar_config(workdir)
    presupuesto = config.get("presupuesto", {})
    ventana_dias = float(config.get("deteccion", {}).get("ventana_dias", 30))
    corridas = observar.leer_corridas(workdir, nombre, via="original")
    corridas = [
        c for c in corridas
        if c.get("ts", 0) >= (max((x.get("ts", 0) for x in corridas), default=0) - ventana_dias * 86400)
    ]
    if corridas:
        lapso_dias = max(
            (max(c["ts"] for c in corridas) - min(c["ts"] for c in corridas)) / 86400.0,
            1.0,
        )
        por_dia = len(corridas) / lapso_dias
    else:
        por_dia = 0.0
    tokens_corrida = float(presupuesto.get("tokens_por_corrida_estimados", 1500))
    horizonte = float(presupuesto.get("horizonte_dias", 30))
    costo = len(prompt) / 4.0 + float(presupuesto.get("tokens_salida_compilacion", 2000))
    ahorro = por_dia * horizonte * tokens_corrida
    return {
        "compila": ahorro > costo,
        "costo_tokens_estimado": round(costo),
        "ahorro_tokens_estimado": round(ahorro),
        "metodo": (
            f"ESTIMATE: cost = prompt_chars/4 + expected_output ({round(costo)}); "
            f"saving = {por_dia:.2f} runs/day x {horizonte:.0f} days x "
            f"{tokens_corrida:.0f} est. tokens/run ({round(ahorro)})"
        ),
    }


def extraer_codigo(texto: str) -> str | None:
    bloques = _RE_BLOQUE_PY.findall(texto or "")
    return max(bloques, key=len).strip() + "\n" if bloques else None


def _backend_claude(workdir: Path, nombre: str, prompt: str, timeout_s: int) -> str | None:
    """Print mode redirected to a file — never parse live stdout."""
    carpeta = estado.dir_estado(workdir) / "tmp"
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = carpeta / f"claude_{nombre}.json"
    try:
        with salida.open("wb") as fh:
            subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json"],
                stdout=fh, timeout=timeout_s, check=False,
            )
        datos = json.loads(salida.read_text(encoding="utf-8"))
        return extraer_codigo(str(datos.get("result", "")))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"oraculo: claude backend failed: {exc}", file=sys.stderr)
        return None


def _replay_ejemplos(workdir: Path, nombre: str, codigo: str) -> tuple[bool, str]:
    """R16: every captured example must replay byte-exact before shadow."""
    ejemplos = observar.leer_ejemplos(workdir, nombre)[:3]
    if not ejemplos:
        return True, "no captured examples to replay"
    carpeta = estado.dir_estado(workdir) / "tmp"
    carpeta.mkdir(parents=True, exist_ok=True)
    candidato = carpeta / f"candidato_{nombre}.py"
    candidato.write_text(codigo, encoding="utf-8")
    for ejemplo in ejemplos:
        argv = [str(a) for a in ejemplo.get("argv", [])]
        try:
            proc = subprocess.run(
                [sys.executable, str(candidato), *argv],
                capture_output=True, timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"replay error on argv={argv}: {exc}"
        esperado = str(ejemplo.get("stdout", ""))
        if proc.returncode != 0:
            return False, f"replay exit {proc.returncode} on argv={argv}"
        if proc.stdout.decode("utf-8", errors="replace") != esperado:
            return False, f"replay stdout mismatch on argv={argv}"
    return True, f"{len(ejemplos)} examples replayed exactly"


def _instalar(
    workdir: Path, tarea: dict[str, Any], codigo: str, cura: bool, dur_s: float
) -> dict[str, Any]:
    config = estado.cargar_config(workdir)
    requeridos = int(
        config.get("sombra", {}).get(
            "exitos_requeridos_cura" if cura else "exitos_requeridos", 3 - cura
        )
    )
    ruta = estado.ruta_compilado(workdir, tarea["nombre"])
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(codigo, encoding="utf-8")
    tarea["estado"] = "sombra"
    tarea["sombra"] = {"exitos": 0, "requeridos": requeridos}
    estado.guardar_tarea(workdir, tarea)
    log.registrar(
        workdir, "MEDIO", "curada" if cura else "compilada",
        tarea=tarea["nombre"], dur_s=round(dur_s, 1), sombra_requerida=requeridos,
    )
    return {"ok": True, "estado": "sombra", "sombra_requerida": requeridos}


def compilar(
    workdir: Path,
    nombre: str,
    backend: str | None = None,
    forzar: bool = False,
    desde: Path | None = None,
) -> dict[str, Any]:
    """Full compile step for one candidate/degraded task."""
    inicio = time.perf_counter()
    estado.validar_nombre(nombre)
    config = estado.cargar_config(workdir)
    tarea = estado.cargar_tarea(workdir, nombre)
    if tarea is None:
        return {"ok": False, "motivo": f"unknown task {nombre!r}"}
    if tarea.get("estado") not in ("candidata", "degradada"):
        return {"ok": False, "motivo": f"task is {tarea.get('estado')}, need candidata/degradada"}
    cura = tarea.get("estado") == "degradada"

    contexto_cura = None
    if cura and tarea.get("ultimo_error"):
        ruta_previa = estado.ruta_compilado(workdir, nombre)
        contexto_cura = {
            **tarea["ultimo_error"],
            "codigo_actual": ruta_previa.read_text(encoding="utf-8") if ruta_previa.exists() else "",
        }

    if desde is not None:
        codigo = Path(desde).read_text(encoding="utf-8")
    else:
        prompt = armar_paquete(workdir, nombre, cura=contexto_cura)
        if not forzar:
            balance = break_even(workdir, nombre, prompt)
            if not balance["compila"]:
                log.registrar(workdir, "BAJO", "break_even_no_cierra", tarea=nombre, **balance)
                return {"ok": False, "motivo": "break-even negative", **balance}
        elegido = backend or config.get("backend", "auto")
        if elegido == "auto":
            elegido = "claude" if shutil.which("claude") else "manual"
        if elegido == "manual":
            carpeta = estado.dir_requests(workdir)
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta_req = carpeta / f"{nombre}.md"
            ruta_req.write_text(prompt, encoding="utf-8")
            log.registrar(workdir, "MEDIO", "request_manual", tarea=nombre, archivo=str(ruta_req))
            return {
                "ok": True, "estado": "pendiente_manual", "request": str(ruta_req),
                "siguiente": f"fulfill the request, then: oraculo compile {nombre} --desde <file.py>",
            }
        codigo = _backend_claude(workdir, nombre, prompt, int(config.get("backend_timeout_s", 600)))
        if not codigo:
            log.registrar(workdir, "MEDIO", "backend_fallo", tarea=nombre, backend=elegido)
            return {"ok": False, "motivo": f"backend {elegido!r} produced no code"}

    veredicto = guardian.verificar(codigo)
    if not veredicto["aprobado"]:
        log.registrar(
            workdir, "MEDIO", "guardian_rechazo", tarea=nombre,
            errores=[e["mensaje"] for e in veredicto["errores"]][:5],
        )
        return {"ok": False, "motivo": "guardian rejected", "veredicto": veredicto}
    if veredicto["indecidibles"]:
        log.registrar(
            workdir, "BAJO", "guardian_indecidible", tarea=nombre,
            contexto=guardian.contexto_para_llm(veredicto),
        )

    replay_ok, replay_msg = _replay_ejemplos(workdir, nombre, codigo)
    if not replay_ok:
        log.registrar(workdir, "MEDIO", "tests_fallo", tarea=nombre, motivo=replay_msg)
        return {"ok": False, "motivo": f"example replay failed: {replay_msg}"}

    return _instalar(workdir, tarea, codigo, cura, time.perf_counter() - inicio)
