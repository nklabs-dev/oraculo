"""log_admin — deterministic curation of ORACULO.log. 0 tokens.

The public log grows in value, not in weight (admin manual, §3):

  * CRITICO   preserved forever, verbatim, with their resolution context.
  * MEDIO     older than --dias-medio (default 30): compacted to one summary
              line per (task, event) with count and time range.
  * BAJO      older than --dias-bajo (default 7): aggregated into statistical
              counters (one line per event type).
  * The scope-notice header and every recent entry stay untouched.

Always run --dry-run first: it prints a unified diff and writes nothing.
The community sees exactly how the log is curated — this script IS the policy.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def cargar(ruta: Path) -> list[dict[str, Any]]:
    entradas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            dato = json.loads(linea)
        except ValueError:
            continue  # malformed lines are dropped by curation, by design
        if isinstance(dato, dict):
            entradas.append(dato)
    return entradas


def curar(
    entradas: list[dict[str, Any]],
    ahora: float,
    dias_medio: float = 30.0,
    dias_bajo: float = 7.0,
) -> list[dict[str, Any]]:
    """Pure function: same input, same curated output, always."""
    corte_medio = ahora - dias_medio * 86400.0
    corte_bajo = ahora - dias_bajo * 86400.0

    salida: list[dict[str, Any]] = []
    medios: dict[tuple[str, str], list[dict[str, Any]]] = {}
    bajos: list[dict[str, Any]] = []

    for entrada in entradas:
        nivel = entrada.get("nivel")
        ts = float(entrada.get("ts", 0))
        evento = str(entrada.get("evento", ""))
        if evento == "alcance" or nivel == "CRITICO" or evento.startswith("resumen_"):
            # the header, every CRITICAL, and already-curated summaries: verbatim
            salida.append(entrada)
        elif nivel == "MEDIO" and ts < corte_medio:
            clave = (str(entrada.get("tarea", "")), str(entrada.get("evento", "")))
            medios.setdefault(clave, []).append(entrada)
        elif nivel == "BAJO" and ts < corte_bajo:
            bajos.append(entrada)
        else:
            salida.append(entrada)

    for (tarea, evento), grupo in sorted(medios.items()):
        resumen: dict[str, Any] = {
            "ts": max(float(e.get("ts", 0)) for e in grupo),
            "nivel": "MEDIO",
            "evento": "resumen_medio",
            "evento_original": evento,
            "n": len(grupo),
            "desde": min(float(e.get("ts", 0)) for e in grupo),
            "hasta": max(float(e.get("ts", 0)) for e in grupo),
        }
        if tarea:
            resumen["tarea"] = tarea
        salida.append(resumen)

    if bajos:
        conteos = Counter(str(e.get("evento", "?")) for e in bajos)
        salida.append({
            "ts": max(float(e.get("ts", 0)) for e in bajos),
            "nivel": "BAJO",
            "evento": "resumen_bajo",
            "conteos": dict(sorted(conteos.items())),
            "n": len(bajos),
            "desde": min(float(e.get("ts", 0)) for e in bajos),
            "hasta": max(float(e.get("ts", 0)) for e in bajos),
        })

    salida.sort(key=lambda e: (float(e.get("ts", 0)), str(e.get("evento", ""))))
    return salida


def volcar(entradas: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False, default=str) for e in entradas) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, default=Path("ORACULO.log"))
    parser.add_argument("--dias-medio", type=float, default=30.0)
    parser.add_argument("--dias-bajo", type=float, default=7.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the unified diff, write nothing")
    args = parser.parse_args()

    if not args.log.exists():
        print(f"log_admin: {args.log} not found", file=sys.stderr)
        return 1
    original = args.log.read_text(encoding="utf-8")
    curado = volcar(curar(cargar(args.log), time.time(), args.dias_medio, args.dias_bajo))

    if curado == original:
        print("log already curated — nothing to do")
        return 0
    diff = difflib.unified_diff(
        original.splitlines(keepends=True), curado.splitlines(keepends=True),
        fromfile=str(args.log), tofile=f"{args.log} (curated)",
    )
    sys.stdout.writelines(diff)
    if args.dry_run:
        print("\n--dry-run: nothing written", file=sys.stderr)
        return 0
    respaldo = args.log.with_suffix(".log.bak")
    respaldo.write_text(original, encoding="utf-8")
    args.log.write_text(curado, encoding="utf-8")
    print(f"\ncurated: {args.log} (backup: {respaldo})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
