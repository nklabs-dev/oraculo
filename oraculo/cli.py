"""oraculo — command line interface.

    oraculo run <name> -- <command...>   route a task through ORÁCULO
    oraculo status                       tasks by state
    oraculo candidates                   run detection, list candidates
    oraculo compile <name>               compile one task (see --desde)
    oraculo report [--horas N]           the morning report
    oraculo update-guardian              refresh the guardian rule pack
    oraculo log-sync                     commit ORACULO.log to the user's repo
    oraculo doctor                       verify install + Hermes integration
    oraculo ciclo                        the daily cron body (silent when green)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import (
    __version__,
    compilar,
    conmutar,
    detectar,
    estado,
    guardian,
    log,
    log_sync,
    manada,
    observar,
)


def _cmd_run(args: argparse.Namespace, workdir: Path) -> int:
    comando = list(args.comando)
    if comando and comando[0] == "--":
        comando = comando[1:]
    if not comando:
        print("usage: oraculo run <name> -- <command...>", file=sys.stderr)
        return 2
    codigo, salida = conmutar.correr(workdir, args.nombre, comando)
    sys.stdout.buffer.write(salida)
    sys.stdout.buffer.flush()
    return codigo


def _cmd_status(args: argparse.Namespace, workdir: Path) -> int:
    tareas = estado.listar_tareas(workdir)
    if args.json:
        print(json.dumps(tareas, ensure_ascii=False, indent=1))
        return 0
    if not tareas:
        print("no tasks observed yet — route one with: oraculo run <name> -- <command...>")
        return 0
    ancho = max(len(t["nombre"]) for t in tareas)
    print(f"{'task':<{ancho}}  state      runs  hits  shadow  degr")
    for tarea in tareas:
        sombra = tarea.get("sombra") or {}
        avance = (
            f"{sombra.get('exitos', 0)}/{sombra.get('requeridos')}"
            if sombra.get("requeridos") else "-"
        )
        print(
            f"{tarea['nombre']:<{ancho}}  {tarea.get('estado', '?'):<9}  "
            f"{tarea.get('corridas', 0):>4}  {tarea.get('intercepciones', 0):>4}  "
            f"{avance:>6}  {tarea.get('degradaciones', 0):>4}"
        )
    return 0


def _cmd_candidates(args: argparse.Namespace, workdir: Path) -> int:
    nuevas = detectar.detectar(workdir)
    candidatas = [t for t in estado.listar_tareas(workdir) if t.get("estado") == "candidata"]
    for tarea in candidatas:
        marca = " (new)" if tarea["nombre"] in nuevas else ""
        print(f"{tarea['nombre']}: {tarea.get('corridas', 0)} clean runs{marca}")
    if not candidatas:
        print("no candidates — keep routing runs; detection needs "
              f"{estado.cargar_config(workdir)['deteccion']['min_corridas']}+ identical-structure clean runs")
    return 0


def _cmd_compile(args: argparse.Namespace, workdir: Path) -> int:
    resultado = compilar.compilar(
        workdir, args.nombre,
        backend=args.backend,
        forzar=args.forzar,
        desde=Path(args.desde) if args.desde else None,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=1, default=str))
    return 0 if resultado.get("ok") else 1


def _cmd_report(args: argparse.Namespace, workdir: Path) -> int:
    desde = estado.ahora() - args.horas * 3600.0
    config = estado.cargar_config(workdir)
    intercepciones = observar.leer_corridas(workdir, desde_ts=desde, via="py")
    eventos = log.leer(workdir, desde_ts=desde)
    compiladas = [e for e in eventos if e.get("evento") == "compilada"]
    curadas = [e for e in eventos if e.get("evento") == "curada"]
    criticos = [e for e in eventos if e.get("nivel") == "CRITICO"]

    minutos = 0.0
    for corrida in intercepciones:
        tarea = estado.cargar_tarea(workdir, corrida.get("tarea", "")) or {}
        minutos += max(
            float(tarea.get("dur_ms_promedio", 0.0)) - float(corrida.get("dur_ms", 0.0)), 0.0
        ) / 60000.0
    tokens_corrida = config["presupuesto"]["tokens_por_corrida_estimados"]
    tareas_tocadas = sorted({c.get("tarea") for c in intercepciones if c.get("tarea")})

    print(f"ORÁCULO — last {args.horas:.0f}h")
    print(
        f"  intercepted: {len(intercepciones)} runs across {len(tareas_tocadas)} tasks "
        f"({', '.join(tareas_tocadas) if tareas_tocadas else 'none'})"
    )
    print(f"  compiled: {len(compiladas)}  |  cured: {len(curadas)}"
          + (f" (real time: {', '.join(str(e.get('dur_s')) + 's' for e in curadas)})" if curadas else ""))
    if criticos:
        print(f"  ⚠ CRITICAL events: {len(criticos)} — check ORACULO.log")
    print(
        f"  estimated saving: {len(intercepciones)} LLM calls avoided "
        f"/ ~{len(intercepciones) * tokens_corrida} tokens / {minutos:.1f} min"
    )
    print(
        f"  method: intercepted runs x {tokens_corrida} est. tokens per run "
        "(estimate, not a measurement); minutes = observed original mean minus .py duration"
    )
    return 0


def _cmd_update_guardian(args: argparse.Namespace, workdir: Path) -> int:
    config = estado.cargar_config(workdir)
    ok, mensaje = guardian.actualizar_pack(config["guardian"]["url_pack"])
    print(mensaje)
    return 0 if ok else 1


def _cmd_log_sync(args: argparse.Namespace, workdir: Path) -> int:
    _, mensaje = log_sync.sincronizar(workdir, push=not args.no_push)
    print(mensaje)
    return 0


def _cmd_doctor(args: argparse.Namespace, workdir: Path) -> int:
    fallos = 0

    def chequeo(nombre: str, ok: bool, detalle: str, critico: bool = True) -> None:
        nonlocal fallos
        simbolo = "✅" if ok else ("❌" if critico else "⚠️ ")
        print(f"{simbolo} {nombre}: {detalle}")
        if not ok and critico:
            fallos += 1

    chequeo(
        "python", sys.version_info >= (3, 10),
        f"{sys.version.split()[0]} (need >= 3.10)",
    )
    try:
        estado.dir_estado(workdir).mkdir(parents=True, exist_ok=True)
        chequeo("state dir", True, str(estado.dir_estado(workdir)))
    except OSError as exc:
        chequeo("state dir", False, str(exc))
    pack = guardian.cargar_pack()
    chequeo(
        "guardian pack", bool(pack.get("reglas")),
        f"version {pack.get('version')} — {len(pack.get('reglas', []))} rules "
        f"({pack.get('_origen') or 'NOT FOUND'})",
    )
    ingeniero = compilar.cargar_ingeniero()
    chequeo("INGENIERO.md", not ingeniero.startswith("("), f"{len(ingeniero)} chars loaded")
    chequeo(
        "backend", True,
        "claude CLI found" if shutil.which("claude") else "no claude CLI — manual backend",
        critico=False,
    )

    hermes = shutil.which("hermes")
    chequeo("hermes CLI", bool(hermes), hermes or "not in PATH", critico=False)
    skill = Path.home() / ".hermes" / "skills" / "oraculo" / "SKILL.md"
    chequeo("hermes skill", skill.exists(), str(skill), critico=False)
    if hermes:
        try:
            proc = subprocess.run(
                ["hermes", "cron", "list"], capture_output=True, text=True,
                timeout=60, check=False,
            )
            tiene_cron = "oraculo-ciclo" in proc.stdout
            chequeo("hermes cron", tiene_cron, "oraculo-ciclo scheduled" if tiene_cron
                    else "oraculo-ciclo not found (see install.sh output)", critico=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            chequeo("hermes cron", False, f"could not list crons: {exc}", critico=False)
        if not args.quick:
            # Hermes already knows how to diagnose itself — reuse, don't duplicate.
            try:
                proc = subprocess.run(
                    ["hermes", "doctor"], capture_output=True, text=True,
                    timeout=120, check=False,
                )
                chequeo(
                    "hermes doctor", proc.returncode == 0,
                    f"exit {proc.returncode}", critico=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                chequeo("hermes doctor", False, str(exc), critico=False)

    config = estado.cargar_config(workdir)
    print(f"ℹ️  manada: {config.get('manada')} (see herramientas/README.md)")
    print(f"ℹ️  {log.AVISO_ALCANCE}")
    return 1 if fallos else 0


def _cmd_ciclo(args: argparse.Namespace, workdir: Path) -> int:
    """Daily cron body: detect + cure + refresh guardian + sync log."""
    lineas: list[str] = []
    nuevas = detectar.detectar(workdir)
    if nuevas:
        lineas.append(f"detected {len(nuevas)} new candidate(s): {', '.join(nuevas)}")

    config = estado.cargar_config(workdir)
    if shutil.which("claude") or config.get("backend") == "claude":
        for tarea in estado.listar_tareas(workdir):
            if tarea.get("estado") == "degradada":
                # Cure is maintenance of an already-justified task: no break-even gate.
                resultado = compilar.compilar(workdir, tarea["nombre"], forzar=True)
                lineas.append(
                    f"cure {tarea['nombre']}: "
                    + ("recompiled, back in shadow" if resultado.get("ok") else resultado.get("motivo", "failed"))
                )

    import time as _t
    ruta_pack = guardian.RUTA_PACK_USUARIO
    edad_dias = (
        (_t.time() - ruta_pack.stat().st_mtime) / 86400.0 if ruta_pack.exists() else 1e9
    )
    if edad_dias > float(config["guardian"].get("auto_update_dias", 7)):
        ok, mensaje = guardian.actualizar_pack(config["guardian"]["url_pack"])
        if not ok:
            lineas.append(f"update-guardian: {mensaje}")

    if manada.activada(workdir):
        for accion in manada.sincronizar(workdir):
            if "nothing new" not in accion:
                lineas.append(f"manada: {accion}")

    if config.get("log_sync", {}).get("auto", True):
        cambio, mensaje = log_sync.sincronizar(workdir)
        if cambio:
            lineas.append(f"log-sync: {mensaje}")

    if lineas:
        print("\n".join(lineas))
    else:
        print("[SILENT]")
    return 0


def _cmd_manada(args: argparse.Namespace, workdir: Path) -> int:
    if args.accion == "on":
        ok, mensaje = manada.activar(workdir, args.acepto)
        print(mensaje)
        return 0 if ok else 1
    if args.accion == "off":
        print(manada.desactivar(workdir))
        return 0
    if args.accion == "estado":
        activa = manada.activada(workdir)
        print(f"manada: {'ON' if activa else 'OFF'}")
        entorno = manada.mi_entorno(workdir)
        print(f"observed commands: {', '.join(entorno['comandos_observados']) or '(none yet)'}")
        return 0
    if args.accion == "sync":
        for accion in manada.sincronizar(workdir):
            print(accion)
        return 0
    if args.accion == "publicar":
        if not args.nombre:
            print("usage: oraculo manada publicar <task> [--repo DIR]", file=sys.stderr)
            return 2
        resultado = manada.publicar(
            workdir, args.nombre, repo_dir=args.repo,
            herramienta=args.herramienta, nota_config=args.nota_config,
        )
        print(json.dumps(resultado, ensure_ascii=False, indent=1, default=str))
        return 0 if resultado.get("ok") else 1
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oraculo",
        description="Your agent did this task 3 times. The 4th is free.",
    )
    parser.add_argument("--version", action="version", version=f"oraculo {__version__}")
    parser.add_argument(
        "--workdir", type=Path, default=Path.cwd(),
        help="project root (default: current directory)",
    )
    sub = parser.add_subparsers(dest="orden", required=True)

    p = sub.add_parser("run", help="route a task: oraculo run <name> -- <command...>")
    p.add_argument("nombre")
    p.add_argument("comando", nargs=argparse.REMAINDER)
    p.set_defaults(fn=_cmd_run)

    p = sub.add_parser("status", help="tasks by state")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=_cmd_status)

    p = sub.add_parser("candidates", help="run detection and list candidates")
    p.set_defaults(fn=_cmd_candidates)

    p = sub.add_parser("compile", help="compile one candidate/degraded task")
    p.add_argument("nombre")
    p.add_argument("--backend", choices=["claude", "manual"])
    p.add_argument("--desde", metavar="FILE.py",
                   help="inject an already-written script (any agent fulfilled the request)")
    p.add_argument("--forzar", action="store_true", help="skip the break-even gate")
    p.set_defaults(fn=_cmd_compile)

    p = sub.add_parser("report", help="the morning report")
    p.add_argument("--horas", type=float, default=24.0)
    p.set_defaults(fn=_cmd_report)

    p = sub.add_parser("update-guardian", help="refresh the guardian rule pack (hash-verified)")
    p.set_defaults(fn=_cmd_update_guardian)

    p = sub.add_parser("log-sync", help="commit ORACULO.log to YOUR repo (only that file)")
    p.add_argument("--no-push", action="store_true")
    p.set_defaults(fn=_cmd_log_sync)

    p = sub.add_parser("doctor", help="verify install and Hermes integration")
    p.add_argument("--quick", action="store_true", help="skip `hermes doctor`")
    p.set_defaults(fn=_cmd_doctor)

    p = sub.add_parser("ciclo", help="daily cron body (prints [SILENT] when green)")
    p.set_defaults(fn=_cmd_ciclo)

    p = sub.add_parser("manada", help="the network layer: on/off/estado/sync/publicar")
    p.add_argument("accion", choices=["on", "off", "estado", "sync", "publicar"])
    p.add_argument("nombre", nargs="?", help="task name (publicar)")
    p.add_argument("--acepto", action="store_true",
                   help="explicit global consent (required once for `on`)")
    p.add_argument("--repo", type=Path, help="local clone of the oraculo repo (publicar)")
    p.add_argument("--herramienta", help="tool name override (publicar)")
    p.add_argument("--nota-config", default="", help="config profile note (publicar)")
    p.set_defaults(fn=_cmd_manada)

    args = parser.parse_args(argv)
    try:
        return args.fn(args, args.workdir)
    except ValueError as exc:
        print(f"oraculo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
