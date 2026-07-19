"""guardian — catches the universal LLM code errors BEFORE anything runs.

Every freshly compiled .py passes through three layers, always, between
compilation and shadow:

  1. What Python + standard tooling already solve: `ast.parse`, `compile()`,
     and `ruff` when it is installed (detected, never required).
  2. The ecosystem rule pack (`guardian_rules/reglas.json`, versioned in the
     repo, auto-updatable via `oraculo update-guardian`): hallucinated
     imports, non-stdlib dependencies, credential literals, Hermes/Claude
     Code hook names that do not exist, junior vices.
  3. What code cannot decide (semantics) is MARKED and returned to the LLM
     with surgical context — never silently approved.

Verdict: `aprobado` only with zero layer-1/layer-2 errors. `indecidibles`
travel back to the compiler for LLM review; `avisos` never block.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

RUTA_PACK_USUARIO = Path.home() / ".oraculo" / "guardian_rules" / "reglas.json"
RUTA_PACK_REPO = Path(__file__).resolve().parent.parent / "guardian_rules" / "reglas.json"

# Real hook events of the ecosystems we compile for. A generated .py that
# registers anything else is hallucinating.
HOOKS_CONOCIDOS = {
    # Hermes shell hooks
    "pre_tool_call", "post_tool_call", "session_start", "session_end",
    # Claude Code hooks
    "PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart",
    "SessionEnd", "Notification", "Stop", "SubagentStop", "PreCompact",
}


def cargar_pack() -> dict[str, Any]:
    """User-updated pack first, packaged/repo pack as fallback."""
    for ruta in (RUTA_PACK_USUARIO, RUTA_PACK_REPO):
        try:
            pack = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(pack, dict) and isinstance(pack.get("reglas"), list):
                pack["_origen"] = str(ruta)
                return pack
        except (OSError, ValueError):
            continue
    return {"version": 0, "reglas": [], "_origen": None}


# --- layer 1: what the platform already solves -----------------------------

def _capa_plataforma(codigo: str) -> tuple[list[dict], ast.AST | None]:
    errores = []
    arbol = None
    try:
        arbol = ast.parse(codigo)
        compile(codigo, "<generado>", "exec")
    except SyntaxError as exc:
        errores.append(
            {"regla": "sintaxis", "linea": exc.lineno, "mensaje": f"SyntaxError: {exc.msg}"}
        )
    except ValueError as exc:
        errores.append({"regla": "sintaxis", "linea": None, "mensaje": str(exc)})
    return errores, arbol


def _avisos_ruff(codigo: str) -> list[dict]:
    """Optional fast linter. Detected, never a hard dependency."""
    if not shutil.which("ruff"):
        return []
    try:
        proc = subprocess.run(
            ["ruff", "check", "--quiet", "--stdin-filename", "generado.py", "-"],
            input=codigo.encode(),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    avisos = []
    for linea in proc.stdout.decode("utf-8", errors="replace").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith(("Found ", "[*]", "warning:")):
            avisos.append({"regla": "ruff", "linea": None, "mensaje": linea})
    return avisos[:20]


# --- layer 2: AST checks the generic tooling does not know -----------------

def _chequeos_ast(arbol: ast.AST, permitidos: set[str]) -> dict[str, list[dict]]:
    hallazgos: dict[str, list[dict]] = {}

    def anotar(regla: str, linea: int | None, mensaje: str) -> None:
        hallazgos.setdefault(regla, []).append(
            {"regla": regla, "linea": linea, "mensaje": mensaje}
        )

    tiene_main_guard = False
    tiene_argparse = False
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            if isinstance(nodo, ast.Import):
                modulos = [a.name.split(".")[0] for a in nodo.names]
            else:
                modulos = [nodo.module.split(".")[0]] if nodo.module and nodo.level == 0 else []
            for modulo in modulos:
                if modulo == "argparse":
                    tiene_argparse = True
                if modulo not in sys.stdlib_module_names and modulo not in permitidos:
                    anotar(
                        "import_no_stdlib", nodo.lineno,
                        f"import {modulo!r}: not stdlib and not approved — "
                        "hallucinated or an unapproved dependency",
                    )
        elif isinstance(nodo, ast.ExceptHandler) and nodo.type is None:
            anotar("except_desnudo", nodo.lineno, "bare `except:` hides real failures")
        elif isinstance(nodo, ast.Call):
            fn = nodo.func
            nombre_fn = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None
            )
            if nombre_fn in ("eval", "exec"):
                anotar("eval_exec", nodo.lineno, f"`{nombre_fn}()` on generated code is forbidden")
            if nombre_fn == "system" and isinstance(fn, ast.Attribute):
                base = fn.value
                if isinstance(base, ast.Name) and base.id == "os":
                    anotar("os_system", nodo.lineno, "use subprocess.run, never os.system")
            for kw in nodo.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    anotar("shell_true", nodo.lineno, "subprocess with shell=True: injection surface")
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for defecto in nodo.args.defaults + nodo.args.kw_defaults:
                if isinstance(defecto, (ast.List, ast.Dict, ast.Set)):
                    anotar(
                        "default_mutable", nodo.lineno,
                        f"mutable default argument in {nodo.name}()",
                    )
        elif isinstance(nodo, ast.If):
            prueba = nodo.test
            if (
                isinstance(prueba, ast.Compare)
                and isinstance(prueba.left, ast.Name)
                and prueba.left.id == "__name__"
            ):
                tiene_main_guard = True

    if not tiene_main_guard:
        anotar("sin_main_guard", None, 'missing `if __name__ == "__main__":` entry point')
    if not tiene_argparse:
        anotar("sin_argparse", None, "missing argparse-based main() (INGENIERO.md structure)")
    return hallazgos


def verificar(
    codigo: str, pack: dict[str, Any] | None = None, permitidos: set[str] | None = None
) -> dict[str, Any]:
    """Run the three layers over one generated script."""
    pack = pack or cargar_pack()
    permitidos = permitidos or set()
    errores: list[dict] = []
    avisos: list[dict] = []
    indecidibles: list[dict] = []

    errores_sintaxis, arbol = _capa_plataforma(codigo)
    errores.extend(errores_sintaxis)
    avisos.extend(_avisos_ruff(codigo))

    hallazgos_ast = _chequeos_ast(arbol, permitidos) if arbol is not None else {}
    lineas = codigo.splitlines()

    for regla in pack.get("reglas", []):
        rid = regla.get("id")
        tipo = regla.get("tipo")
        destino = {"error": errores, "aviso": avisos}.get(regla.get("severidad"), avisos)
        if tipo == "ast":
            for hallazgo in hallazgos_ast.get(rid, []):
                destino.append({**hallazgo, "mensaje": regla.get("mensaje", hallazgo["mensaje"])})
        elif tipo in ("regex", "llm"):
            try:
                patron = re.compile(regla.get("patron", r"$^"))
            except re.error:
                continue
            for numero, linea in enumerate(lineas, 1):
                if patron.search(linea):
                    item = {
                        "regla": rid,
                        "linea": numero,
                        "mensaje": regla.get("mensaje", ""),
                        "contexto": linea.strip()[:160],
                    }
                    (indecidibles if tipo == "llm" else destino).append(item)

    # hallucinated hook names (ast rules cannot see string literals)
    for numero, linea in enumerate(lineas, 1):
        m = re.search(r'["\'](pre_|post_|Pre|Post|Session|session_)[A-Za-z_]*["\']', linea)
        if m:
            candidato = m.group(0).strip("\"'")
            if ("hook" in linea.lower() or "event" in linea.lower()) and candidato not in HOOKS_CONOCIDOS:
                errores.append({
                    "regla": "hook_inexistente", "linea": numero,
                    "mensaje": f"hook/event name {candidato!r} does not exist in Hermes or Claude Code",
                })

    return {
        "aprobado": not errores,
        "errores": errores,
        "avisos": avisos,
        "indecidibles": indecidibles,
        "pack_version": pack.get("version"),
        "pack_origen": pack.get("_origen"),
    }


def actualizar_pack(url_base: str) -> tuple[bool, str]:
    """`oraculo update-guardian`: fetch the latest rule pack, hash-verified.

    Downloads `reglas.json` + `MANIFEST.sha256` from the repo and installs to
    `~/.oraculo/guardian_rules/` only if the sha256 matches. One user's new
    universal-error rule becomes everyone's rule — through this channel only.
    """
    import hashlib
    import urllib.request

    base = url_base.rstrip("/") + "/"
    try:
        with urllib.request.urlopen(base + "reglas.json", timeout=30) as resp:
            datos = resp.read()
        with urllib.request.urlopen(base + "MANIFEST.sha256", timeout=30) as resp:
            manifiesto = resp.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return False, f"download failed: {exc}"
    esperado = None
    for linea in manifiesto.splitlines():
        partes = linea.split()
        if len(partes) >= 2 and partes[-1].endswith("reglas.json"):
            esperado = partes[0]
    if not esperado:
        return False, "MANIFEST.sha256 has no entry for reglas.json"
    real = hashlib.sha256(datos).hexdigest()
    if real != esperado:
        return False, f"hash mismatch: manifest {esperado[:12]}… vs downloaded {real[:12]}…"
    try:
        pack = json.loads(datos.decode("utf-8"))
        version = pack.get("version")
    except ValueError:
        return False, "downloaded pack is not valid JSON"
    RUTA_PACK_USUARIO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_PACK_USUARIO.write_bytes(datos)
    return True, f"guardian pack updated to version {version} ({len(pack.get('reglas', []))} rules)"


def contexto_para_llm(resultado: dict[str, Any]) -> str:
    """Surgical context for what code could not decide."""
    partes = []
    for item in resultado.get("indecidibles", []):
        partes.append(
            f"- line {item.get('linea')}: {item.get('mensaje')} -> `{item.get('contexto', '')}`"
        )
    return "\n".join(partes)
