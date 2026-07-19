"""manada — one user compiles, everyone runs. Functional from day one.

The cycle (MANADA.md is the authoritative spec):

  detect -> green at home -> publish with its config profile -> matching ->
  variation -> new green version -> better matching.

  * PUBLISH   a PROMOTED .py for a common tool is auto-sanitized (personal
    paths -> placeholders, zero credentials, config travels separately as a
    template), hashed, and written to `herramientas/<tool>/v<N>/` with the
    environment profile it was born in. Versions never compete: v1 stays,
    v2 covers a different config territory.
  * MATCH     the receiving ORÁCULO observes which tools THIS user runs and
    with which config, and downloads ONLY the versions whose profile matches.
    Never the whole catalog: the repo is the library, each user takes their
    two books.
  * REVALIDATE a downloaded .py is NEVER promoted blindly: it enters the
    receiver's own harness (short shadow, in THEIR house, with THEIR data)
    before it is active. Any failure degrades locally and goes to the log.
  * CONSENT   global, upfront, explicit: `oraculo manada on --acepto` after
    reading exactly what is downloaded, when, and what is logged. What is
    removed is the per-.py question — never the transparency.

Security is ORÁCULO's own chain (guardian + shadow at origin + hash in the
channel + harness at destination + public triaged log) — no extra tollbooths.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from . import estado, guardian, log

TEXTO_CONSENTIMIENTO = """\
LA MANADA — global consent (read all of it; this is the whole mechanism)

If you turn this on, ORÁCULO will, automatically and silently:
  1. OBSERVE which common tools YOU actually run through `oraculo run`
     (command names and config profiles — nothing else, same locked scope
     as ORACULO.log).
  2. DOWNLOAD from github.com/nklabs-dev/oraculo ONLY the compiled .py whose
     recorded config profile matches yours (hash-verified, byte-for-byte
     what was published). Never the full catalog.
  3. RE-VALIDATE every downloaded .py in YOUR harness (short shadow runs in
     your environment) before it becomes active. Failures self-degrade.
  4. PUBLISH, when you run `oraculo manada publicar <task>`, a SANITIZED
     version of your promoted .py (personal paths -> placeholders, zero
     credentials — publication aborts if any credential pattern is found).
     Publishing never happens on its own.
  5. LOG every one of these events in ORACULO.log (public by design).

Activate with:  oraculo manada on --acepto
"""


def activada(workdir: Path) -> bool:
    return str(estado.cargar_config(workdir).get("manada", "off")).lower() == "on"


def _escribir_config(workdir: Path, clave: str, valor: Any) -> None:
    ruta = estado.dir_estado(workdir) / "config.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            datos = {}
    except (OSError, ValueError):
        datos = {}
    datos[clave] = valor
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def activar(workdir: Path, acepto: bool) -> tuple[bool, str]:
    if not acepto:
        return False, TEXTO_CONSENTIMIENTO
    _escribir_config(workdir, "manada", "on")
    log.registrar(workdir, "MEDIO", "manada_activada", consentimiento="explicit --acepto")
    return True, "manada ON — consent recorded in ORACULO.log"


def desactivar(workdir: Path) -> str:
    _escribir_config(workdir, "manada", "off")
    log.registrar(workdir, "MEDIO", "manada_desactivada")
    return "manada OFF — nothing will be downloaded or published"


# --- sanitization: the code travels, the user's life does not --------------

_RE_HOME = re.compile(r"(['\"])/(?:home|Users)/[A-Za-z0-9._-]+((?:/[^'\"]*)?)\1")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_CREDENCIAL = re.compile(
    r"(?i)(api[_-]?key|token|passw(or)?d|secret|bearer)\s*[=:]\s*[\"'][^\"']{8,}[\"']"
)


def sanitizar(codigo: str) -> tuple[str | None, list[str]]:
    """Paths -> placeholders; abort on any credential pattern. Automatic."""
    hallazgos: list[str] = []
    if _RE_CREDENCIAL.search(codigo):
        return None, ["credential pattern found — publication ABORTED (rule 3 of the manada)"]
    limpio, n_rutas = _RE_HOME.subn(r"\1{ORACULO_HOME}\2\1", codigo)
    if n_rutas:
        hallazgos.append(f"replaced {n_rutas} personal absolute path(s) with {{ORACULO_HOME}}")
    limpio, n_mails = _RE_EMAIL.subn("user@example.com", limpio)
    if n_mails:
        hallazgos.append(f"replaced {n_mails} email address(es)")
    return limpio, hallazgos


def _hash(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# --- publish ----------------------------------------------------------------

def publicar(
    workdir: Path,
    nombre: str,
    repo_dir: Path | None = None,
    herramienta: str | None = None,
    nota_config: str = "",
) -> dict[str, Any]:
    """Sanitize + version + hash one PROMOTED task into herramientas/."""
    tarea = estado.cargar_tarea(workdir, nombre)
    if tarea is None or tarea.get("estado") != "promovida":
        return {"ok": False, "motivo": "only a task in state `promovida` (green at home) can be published"}
    ruta_py = estado.ruta_compilado(workdir, nombre)
    if not ruta_py.exists():
        return {"ok": False, "motivo": f"compiled script missing: {ruta_py}"}

    codigo, hallazgos = sanitizar(ruta_py.read_text(encoding="utf-8"))
    if codigo is None:
        log.registrar(workdir, "MEDIO", "manada_publicacion_abortada", tarea=nombre, motivo=hallazgos[0])
        return {"ok": False, "motivo": hallazgos[0]}
    veredicto = guardian.verificar(codigo)
    if not veredicto["aprobado"]:
        return {"ok": False, "motivo": "guardian rejected the sanitized script", "veredicto": veredicto}

    util = herramienta or Path(str(tarea.get("comando") or nombre)).name
    destino_base = (
        Path(repo_dir) / "herramientas" / util if repo_dir
        else estado.dir_estado(workdir) / "publicar" / util
    )
    existentes = [
        int(m.group(1)) for d in (destino_base.glob("v*") if destino_base.is_dir() else [])
        if (m := re.match(r"v(\d+)$", d.name))
    ]
    version = max(existentes, default=0) + 1
    carpeta = destino_base / f"v{version}"
    carpeta.mkdir(parents=True, exist_ok=True)

    datos = codigo.encode("utf-8")
    (carpeta / f"{nombre}.py").write_bytes(datos)
    perfil = {
        "herramienta": util,
        "tarea": nombre,
        "version": version,
        "comando": tarea.get("comando"),
        "aridad": tarea.get("aridad"),
        "nota_config": nota_config or "(profile of the environment where it was born)",
        "hash_py": _hash(datos),
        "archivo": f"{nombre}.py",
        "origen": {
            "corridas": tarea.get("corridas"),
            "sombra": tarea.get("sombra"),
            "degradaciones": tarea.get("degradaciones", 0),
        },
        "marcada": False,
    }
    (carpeta / "perfil.json").write_text(
        json.dumps(perfil, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if repo_dir:
        _reindexar(Path(repo_dir) / "herramientas")
    log.registrar(
        workdir, "MEDIO", "manada_publicada", tarea=nombre,
        herramienta=util, version=f"v{version}", hash=perfil["hash_py"][:16],
        sanitizacion=hallazgos or ["clean"],
    )
    return {"ok": True, "carpeta": str(carpeta), "version": version, "hash": perfil["hash_py"],
            "sanitizacion": hallazgos}


def _reindexar(dir_herramientas: Path) -> dict[str, Any]:
    """Rebuild herramientas/index.json — the surgical-download catalog."""
    indice: dict[str, Any] = {"version": 1, "herramientas": {}}
    if dir_herramientas.is_dir():
        for perfil_ruta in sorted(dir_herramientas.glob("*/v*/perfil.json")):
            try:
                perfil = json.loads(perfil_ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            util = perfil.get("herramienta")
            if not util:
                continue
            entrada = {
                "version": perfil.get("version"),
                "ruta": str(perfil_ruta.parent.relative_to(dir_herramientas)),
                "comando": perfil.get("comando"),
                "aridad": perfil.get("aridad"),
                "tarea": perfil.get("tarea"),
                "archivo": perfil.get("archivo"),
                "hash_py": perfil.get("hash_py"),
                "nota_config": perfil.get("nota_config"),
                "marcada": bool(perfil.get("marcada", False)),
            }
            indice["herramientas"].setdefault(util, []).append(entrada)
    (dir_herramientas / "index.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return indice


# --- match + surgical download ---------------------------------------------

def mi_entorno(workdir: Path) -> dict[str, Any]:
    """What THIS user actually runs: observed commands + available binaries."""
    comandos = {
        t.get("comando") for t in estado.listar_tareas(workdir) if t.get("comando")
    }
    return {"comandos_observados": sorted(comandos)}


def calza(entrada: dict[str, Any], entorno: dict[str, Any]) -> bool:
    """Does a published version fit THIS environment? Conservative on purpose."""
    if entrada.get("marcada"):
        return False  # flagged as problematic by the admin triage: never offered
    comando = entrada.get("comando")
    if not comando:
        return False
    base = Path(str(comando)).name
    observados = {Path(str(c)).name for c in entorno.get("comandos_observados", [])}
    return base in observados or bool(shutil.which(base))


def sincronizar(workdir: Path, url_base: str | None = None) -> list[str]:
    """Download ONLY what matches, verify hashes, hand over to the local harness."""
    if not activada(workdir):
        return ["manada is OFF — run `oraculo manada on` to read the consent text"]
    config = estado.cargar_config(workdir)
    base = (url_base or config.get("manada_url",
            "https://raw.githubusercontent.com/nklabs-dev/oraculo/main/herramientas/")).rstrip("/") + "/"
    try:
        with urllib.request.urlopen(base + "index.json", timeout=30) as resp:
            indice = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        return [f"catalog unreachable: {exc}"]

    entorno = mi_entorno(workdir)
    acciones: list[str] = []
    for util, versiones in indice.get("herramientas", {}).items():
        for entrada in versiones:
            if not calza(entrada, entorno):
                continue
            nombre = entrada.get("tarea") or util
            try:
                estado.validar_nombre(nombre)
            except ValueError:
                continue
            tarea = estado.cargar_tarea(workdir, nombre)
            if tarea and tarea.get("manada_hash") == entrada.get("hash_py"):
                continue  # already installed, same bytes
            if tarea and tarea.get("estado") in ("sombra", "promovida"):
                continue  # never overwrite something already working locally
            try:
                with urllib.request.urlopen(
                    base + entrada["ruta"] + "/" + entrada["archivo"], timeout=30
                ) as resp:
                    datos = resp.read()
            except OSError as exc:
                acciones.append(f"{util} v{entrada.get('version')}: download failed: {exc}")
                continue
            if _hash(datos) != entrada.get("hash_py"):
                acciones.append(f"{util} v{entrada.get('version')}: HASH MISMATCH — discarded")
                log.registrar(workdir, "CRITICO", "manada_hash_invalido",
                              tarea=nombre, herramienta=util, version=entrada.get("version"))
                continue
            ruta_py = estado.ruta_compilado(workdir, nombre)
            ruta_py.parent.mkdir(parents=True, exist_ok=True)
            ruta_py.write_bytes(datos)
            tarea = tarea or estado.tarea_nueva(nombre)
            requeridos = int(config.get("sombra", {}).get("exitos_requeridos_cura", 2))
            tarea.update({
                "estado": "sombra",  # re-validated in THIS house before active
                "comando": entrada.get("comando"),
                "aridad": entrada.get("aridad"),
                "sombra": {"exitos": 0, "requeridos": requeridos},
                "manada_hash": entrada.get("hash_py"),
                "manada_origen": f"{util}/v{entrada.get('version')}",
            })
            estado.guardar_tarea(workdir, tarea)
            log.registrar(
                workdir, "MEDIO", "manada_descarga", tarea=nombre,
                herramienta=util, version=f"v{entrada.get('version')}",
                hash=str(entrada.get("hash_py"))[:16], destino="sombra local",
            )
            acciones.append(
                f"{util} v{entrada.get('version')} -> task {nombre!r} in local shadow "
                f"({requeridos} matches to go active)"
            )
    return acciones or ["nothing new matches this environment"]
