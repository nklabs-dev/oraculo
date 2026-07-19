"""log_sync — the simple git bridge for ORACULO.log.

Deterministic, 0 tokens. Commits ONLY `ORACULO.log` to the USER'S OWN repo
and branch, then pushes. Nothing else is staged, ever. If the workdir is not
a git repo, it says so and exits cleanly — never a failure.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import estado


def _git(workdir: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(workdir), *args],
            capture_output=True, text=True, timeout=120, check=False,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def sincronizar(workdir: Path, push: bool = True) -> tuple[bool, str]:
    """Returns (changed_anything, human message)."""
    ruta = estado.ruta_log(workdir)
    if not ruta.exists():
        return False, "no ORACULO.log yet — nothing to sync"
    codigo, _ = _git(workdir, "rev-parse", "--is-inside-work-tree")
    if codigo != 0:
        return False, "workdir is not a git repo — log-sync does nothing (and that is fine)"
    codigo, salida = _git(workdir, "status", "--porcelain", "--", ruta.name)
    if codigo != 0:
        return False, f"git status failed: {salida}"
    if not salida.strip():
        return False, "ORACULO.log unchanged since last sync"
    codigo, salida = _git(workdir, "add", "--", ruta.name)
    if codigo != 0:
        return False, f"git add failed: {salida}"
    codigo, salida = _git(workdir, "commit", "-m", "oraculo: sync ORACULO.log", "--", ruta.name)
    if codigo != 0:
        return False, f"git commit failed: {salida}"
    if push:
        codigo, salida = _git(workdir, "push")
        if codigo != 0:
            return True, f"committed locally; push failed: {salida.splitlines()[-1] if salida else 'unknown'}"
    return True, "ORACULO.log committed" + (" and pushed" if push else "")
