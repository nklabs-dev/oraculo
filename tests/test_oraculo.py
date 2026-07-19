"""ORÁCULO test suite — deterministic, offline, tmp_path-isolated.

The centerpiece is the full simulated graduation cycle required by the plan:
3 runs -> detection -> hand-injected .py -> shadow 3/3 -> promotion ->
interception -> induced failure -> automatic degradation -> log levels.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from oraculo import (  # noqa: E402
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

CMD_ORIGINAL = [sys.executable, "-c", "import sys; print(int(sys.argv[1]) * 2)"]

# A compiled script that reproduces CMD_ORIGINAL exactly (hand-injected,
# as the plan's cycle test demands). argv contract: the exact original argv —
# it may contain option-looking items ("-c"), so it reads sys.argv directly
# (the sin_argparse guardian rule is a non-blocking aviso by design).
PY_CORRECTO = '''\
"""task doble — compiled by ORACULO from observed runs of python -c. v1."""
import sys


def main() -> int:
    try:
        numero = int(sys.argv[-1])
    except (IndexError, ValueError) as exc:
        print(f"doble: bad input: {exc}", file=sys.stderr)
        return 2
    print(numero * 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PY_ROTO = '''\
"""task doble — broken on purpose. v2."""
import sys


def main() -> int:
    del sys.argv
    raise RuntimeError("induced failure")


if __name__ == "__main__":
    raise SystemExit(main())
'''


def correr_n(workdir: Path, nombre: str, valores: list[int]) -> None:
    for valor in valores:
        conmutar.correr(workdir, nombre, CMD_ORIGINAL + [str(valor)])


def inyectar(workdir: Path, nombre: str, codigo: str) -> None:
    ruta = estado.ruta_compilado(workdir, nombre)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(codigo, encoding="utf-8")


# ---------------------------------------------------------------- el ciclo

def test_ciclo_completo(tmp_path: Path) -> None:
    """The plan's gate test: the whole graduation cycle, simulated."""
    w = tmp_path

    # 3 clean same-structure runs -> detection promotes to candidata (BAJO)
    correr_n(w, "doble", [1, 2, 3])
    tarea = estado.cargar_tarea(w, "doble")
    assert tarea["estado"] == "candidata"
    assert tarea["corridas"] == 3 and tarea["exitos"] == 3

    # hand-inject the compiled .py (guardian + replay) -> sombra
    ruta = w / "doble.py"
    ruta.write_text(PY_CORRECTO, encoding="utf-8")
    resultado = compilar.compilar(w, "doble", desde=ruta)
    assert resultado["ok"], resultado
    assert estado.cargar_tarea(w, "doble")["estado"] == "sombra"

    # shadow 3/3 exact matches -> promovida (MEDIO)
    correr_n(w, "doble", [4, 5, 6])
    tarea = estado.cargar_tarea(w, "doble")
    assert tarea["estado"] == "promovida"
    assert tarea["sombra"]["exitos"] == 3

    # interception: the .py answers, via="py", output identical
    codigo, salida = conmutar.correr(w, "doble", CMD_ORIGINAL + ["21"])
    assert codigo == 0 and salida == b"42\n"
    assert len(observar.leer_corridas(w, "doble", via="py")) == 1
    assert estado.cargar_tarea(w, "doble")["intercepciones"] == 1

    # induced failure -> automatic degradation + fallback answers correctly
    inyectar(w, "doble", PY_ROTO)
    codigo, salida = conmutar.correr(w, "doble", CMD_ORIGINAL + ["10"])
    assert codigo == 0 and salida == b"20\n"  # nothing broke for the user
    tarea = estado.cargar_tarea(w, "doble")
    assert tarea["estado"] == "degradada"
    assert tarea["degradaciones"] == 1
    assert "induced failure" in tarea["ultimo_error"]["error"]
    assert tarea["ultimo_error"]["linea"] is not None
    assert tarea["ultimo_error"]["input"] == CMD_ORIGINAL + ["10"]

    # degraded task keeps running by the original path, never broken
    codigo, salida = conmutar.correr(w, "doble", CMD_ORIGINAL + ["7"])
    assert codigo == 0 and salida == b"14\n"

    # the log tells the whole story with the right levels
    eventos = log.leer(w)
    por_evento = {e["evento"]: e for e in eventos}
    assert eventos[0]["evento"] == "alcance"  # scope notice heads the file
    assert por_evento["deteccion"]["nivel"] == "BAJO"
    assert por_evento["compilada"]["nivel"] == "MEDIO"
    assert por_evento["promovida"]["nivel"] == "MEDIO"
    assert por_evento["fallo_produccion"]["nivel"] == "CRITICO"


def test_sombra_mismatch_resetea(tmp_path: Path) -> None:
    w = tmp_path
    correr_n(w, "doble", [1, 2, 3])
    inyectar(w, "doble", PY_CORRECTO.replace("numero * 2", "numero * 3"))
    tarea = estado.cargar_tarea(w, "doble")
    tarea["estado"] = "sombra"
    tarea["sombra"] = {"exitos": 2, "requeridos": 3}
    estado.guardar_tarea(w, tarea)

    codigo, salida = conmutar.correr(w, "doble", CMD_ORIGINAL + ["5"])
    assert salida == b"10\n"  # the original stays authoritative in shadow
    tarea = estado.cargar_tarea(w, "doble")
    assert tarea["estado"] == "candidata"  # one mismatch = start over
    assert tarea["sombra"]["exitos"] == 0
    assert any(e["evento"] == "sombra_fallo" for e in log.leer(w))


# ---------------------------------------------------------------- detectar

def test_detectar_determinista(tmp_path: Path) -> None:
    config = estado.cargar_config(tmp_path)
    corridas = [
        {"ts": 1000.0 + i, "comando": "x", "aridad": 2, "exit_code": 0} for i in range(3)
    ]
    assert detectar.evaluar(corridas, config) == detectar.evaluar(corridas, config)
    assert detectar.evaluar(corridas, config)[0] is True


@pytest.mark.parametrize(
    "mutacion, esperado",
    [
        (lambda c: c[:2], "only 2 runs"),
        (lambda c: [{**c[0], "comando": "y"}] + c[1:], "command varied"),
        (lambda c: [{**c[0], "aridad": 5}] + c[1:], "arity varied"),
        (lambda c: [{**c[0], "exit_code": 1}] + c[1:], "non-zero exits"),
    ],
)
def test_detectar_rechazos(tmp_path: Path, mutacion, esperado) -> None:
    config = estado.cargar_config(tmp_path)
    base = [{"ts": 1000.0 + i, "comando": "x", "aridad": 2, "exit_code": 0} for i in range(3)]
    mundana, razon = detectar.evaluar(mutacion(base), config)
    assert mundana is False and esperado in razon


def test_detectar_ventana(tmp_path: Path) -> None:
    config = estado.cargar_config(tmp_path)
    viejas = [{"ts": 0.0 + i, "comando": "x", "aridad": 2, "exit_code": 0} for i in range(2)]
    nueva = [{"ts": 90 * 86400.0, "comando": "x", "aridad": 2, "exit_code": 0}]
    mundana, _ = detectar.evaluar(viejas + nueva, config)
    assert mundana is False  # old runs fell outside the window


# ---------------------------------------------------------------- observar

def test_observar_nunca_rompe(tmp_path: Path) -> None:
    observar.registrar_corrida(tmp_path / "no" / "existe", "t", ["x"], 0, 1.0)  # no raise
    observar.registrar_corrida(tmp_path, "nombre invalido!!", ["x"], 0, 1.0)  # no raise


def test_observar_captura_ejemplos(tmp_path: Path) -> None:
    observar.registrar_corrida(tmp_path, "t", ["echo", "a"], 0, 1.0, b"a\n")
    observar.registrar_corrida(tmp_path, "t", ["echo", "a"], 0, 1.0, b"a\n")  # dup input
    observar.registrar_corrida(tmp_path, "t", ["echo", "b"], 0, 1.0, b"b\n")
    observar.registrar_corrida(tmp_path, "t", ["echo", "c"], 1, 1.0, b"")  # failed: skipped
    ejemplos = observar.leer_ejemplos(tmp_path, "t")
    assert len(ejemplos) == 2
    assert {e["stdout"] for e in ejemplos} == {"a\n", "b\n"}


# ---------------------------------------------------------------- guardian

def test_guardian_aprueba_codigo_correcto() -> None:
    veredicto = guardian.verificar(PY_CORRECTO)
    assert veredicto["aprobado"], veredicto["errores"]


@pytest.mark.parametrize(
    "codigo, regla",
    [
        ("def f(:\n", "sintaxis"),
        ("import requests\n", "import_no_stdlib"),
        ("try:\n    pass\nexcept:\n    pass\n", "except_desnudo"),
        ("eval('1+1')\n", "eval_exec"),
        ("import os\nos.system('ls')\n", "os_system"),
        ("import subprocess\nsubprocess.run('ls', shell=True)\n", "shell_true"),
        ("def f(x=[]):\n    return x\n", "default_mutable"),
        ('api_key = "sk-abcdef123456789"\n', "credencial_hardcodeada"),
        ('ruta = "/home/nklabs/proyecto/x.txt"\n', "ruta_personal"),
    ],
)
def test_guardian_rechaza(codigo: str, regla: str) -> None:
    veredicto = guardian.verificar(codigo)
    assert not veredicto["aprobado"]
    assert regla in {e["regla"] for e in veredicto["errores"]}


def test_guardian_hook_alucinado() -> None:
    codigo = 'HOOK = "pre_tool_use"  # register hook event\n'
    veredicto = guardian.verificar(codigo)
    assert any(e["regla"] == "hook_inexistente" for e in veredicto["errores"])


def test_guardian_indecidible_al_llm() -> None:
    codigo = PY_CORRECTO + "\n\ndef helper(x: int) -> int:\n    return x\n"
    veredicto = guardian.verificar(codigo)
    assert veredicto["indecidibles"]
    assert "helper" in guardian.contexto_para_llm(veredicto)


def test_guardian_pack_cargado() -> None:
    pack = guardian.cargar_pack()
    assert len(pack["reglas"]) >= 10  # 10-15 real rules, per the plan


# ---------------------------------------------------------------- compilar

def test_break_even_no_cierra(tmp_path: Path) -> None:
    w = tmp_path
    correr_n(w, "raro", [1, 2, 3])
    # one giant prompt vs a tiny observed frequency -> must refuse
    (estado.dir_estado(w) / "config.json").write_text(
        json.dumps({"presupuesto": {"tokens_por_corrida_estimados": 0.001,
                                    "horizonte_dias": 1}}),
        encoding="utf-8",
    )
    resultado = compilar.compilar(w, "raro", backend="manual")
    assert resultado["ok"] is False and "break-even" in resultado["motivo"]
    assert any(e["evento"] == "break_even_no_cierra" and e["nivel"] == "BAJO"
               for e in log.leer(w))


def test_backend_manual_emite_request(tmp_path: Path) -> None:
    w = tmp_path
    correr_n(w, "doble", [1, 2, 3])
    resultado = compilar.compilar(w, "doble", backend="manual", forzar=True)
    assert resultado["ok"] and resultado["estado"] == "pendiente_manual"
    contenido = Path(resultado["request"]).read_text(encoding="utf-8")
    assert "INGENIERO" in contenido  # the standard travels with the request
    assert "argv" in contenido and "expected stdout" in contenido


def test_compilar_rechaza_replay_fallido(tmp_path: Path) -> None:
    w = tmp_path
    correr_n(w, "doble", [1, 2, 3])
    malo = w / "malo.py"
    malo.write_text(PY_CORRECTO.replace("numero * 2", "numero * 5"), encoding="utf-8")
    resultado = compilar.compilar(w, "doble", desde=malo)
    assert resultado["ok"] is False and "replay" in resultado["motivo"]
    assert estado.cargar_tarea(w, "doble")["estado"] == "candidata"  # untouched


def test_cura_desde_degradada(tmp_path: Path) -> None:
    w = tmp_path
    correr_n(w, "doble", [1, 2, 3])
    ruta = w / "doble.py"
    ruta.write_text(PY_CORRECTO, encoding="utf-8")
    assert compilar.compilar(w, "doble", desde=ruta)["ok"]
    correr_n(w, "doble", [4, 5, 6])  # -> promovida
    inyectar(w, "doble", PY_ROTO)
    conmutar.correr(w, "doble", CMD_ORIGINAL + ["10"])  # -> degradada
    resultado = compilar.compilar(w, "doble", desde=ruta)  # surgical re-inject
    assert resultado["ok"]
    tarea = estado.cargar_tarea(w, "doble")
    assert tarea["estado"] == "sombra"
    assert tarea["sombra"]["requeridos"] == 2  # short shadow for cures
    assert any(e["evento"] == "curada" for e in log.leer(w))


# ---------------------------------------------------------------- manada

def test_manada_consentimiento(tmp_path: Path) -> None:
    ok, texto = manada.activar(tmp_path, acepto=False)
    assert ok is False and "consent" in texto.lower()
    assert manada.activada(tmp_path) is False
    ok, _ = manada.activar(tmp_path, acepto=True)
    assert ok and manada.activada(tmp_path)
    assert any(e["evento"] == "manada_activada" for e in log.leer(tmp_path))
    manada.desactivar(tmp_path)
    assert manada.activada(tmp_path) is False


def test_manada_sanitiza() -> None:
    codigo, hallazgos = manada.sanitizar(
        'ruta = "/home/nklabs/x.txt"\nmail = "nk@labs.dev"\n'
    )
    assert "{ORACULO_HOME}" in codigo and "/home/nklabs" not in codigo
    assert "nk@labs.dev" not in codigo
    assert len(hallazgos) == 2


def test_manada_sanitizar_aborta_con_credencial() -> None:
    codigo, hallazgos = manada.sanitizar('token = "ghp_abc123456789"\n')
    assert codigo is None and "ABORTED" in hallazgos[0]


def _promover(w: Path) -> None:
    correr_n(w, "doble", [1, 2, 3])
    ruta = w / "doble.py"
    ruta.write_text(PY_CORRECTO, encoding="utf-8")
    assert compilar.compilar(w, "doble", desde=ruta)["ok"]
    correr_n(w, "doble", [4, 5, 6])
    assert estado.cargar_tarea(w, "doble")["estado"] == "promovida"


def test_manada_publica_solo_promovidas(tmp_path: Path) -> None:
    w = tmp_path / "casa"
    w.mkdir()
    correr_n(w, "doble", [1, 2, 3])
    assert manada.publicar(w, "doble")["ok"] is False  # candidata: not green yet


def test_manada_publicar_y_versionar(tmp_path: Path) -> None:
    w = tmp_path / "casa"
    repo = tmp_path / "repo"
    w.mkdir(), repo.mkdir()
    _promover(w)
    r1 = manada.publicar(w, "doble", repo_dir=repo, herramienta="python3")
    assert r1["ok"] and r1["version"] == 1
    r2 = manada.publicar(w, "doble", repo_dir=repo, herramienta="python3")
    assert r2["ok"] and r2["version"] == 2  # v1 stays: versions never compete
    indice = json.loads((repo / "herramientas" / "index.json").read_text(encoding="utf-8"))
    assert len(indice["herramientas"]["python3"]) == 2
    perfil = json.loads(
        (repo / "herramientas" / "python3" / "v1" / "perfil.json").read_text(encoding="utf-8")
    )
    assert perfil["hash_py"] and perfil["comando"]
    assert any(e["evento"] == "manada_publicada" for e in log.leer(w))


def test_manada_sync_descarga_y_revalida(tmp_path: Path) -> None:
    """User 1 publishes; user 2 matches, downloads, and re-validates at home."""
    casa1, casa2, repo = tmp_path / "c1", tmp_path / "c2", tmp_path / "repo"
    casa1.mkdir(), casa2.mkdir(), repo.mkdir()
    _promover(casa1)
    assert manada.publicar(casa1, "doble", repo_dir=repo, herramienta="python3")["ok"]

    # user 2 also runs this tool (observed environment) and consented
    conmutar.correr(casa2, "otra", CMD_ORIGINAL + ["1"])
    manada.activar(casa2, acepto=True)
    url = (repo / "herramientas").as_uri() + "/"
    acciones = manada.sincronizar(casa2, url_base=url)
    assert any("local shadow" in a for a in acciones), acciones
    tarea = estado.cargar_tarea(casa2, "doble")
    assert tarea["estado"] == "sombra"  # never active blindly
    assert tarea["manada_hash"]
    # and the downloaded .py graduates in user 2's own house
    correr_n(casa2, "doble", [8, 9])
    assert estado.cargar_tarea(casa2, "doble")["estado"] == "promovida"
    # idempotent: same bytes are not downloaded twice
    assert manada.sincronizar(casa2, url_base=url) == ["nothing new matches this environment"]


def test_manada_sync_exige_consentimiento(tmp_path: Path) -> None:
    acciones = manada.sincronizar(tmp_path)
    assert "OFF" in acciones[0]


def test_manada_hash_invalido_descarta(tmp_path: Path) -> None:
    casa1, casa2, repo = tmp_path / "c1", tmp_path / "c2", tmp_path / "repo"
    casa1.mkdir(), casa2.mkdir(), repo.mkdir()
    _promover(casa1)
    assert manada.publicar(casa1, "doble", repo_dir=repo, herramienta="python3")["ok"]
    py = next((repo / "herramientas" / "python3" / "v1").glob("*.py"))
    py.write_text(py.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    conmutar.correr(casa2, "otra", CMD_ORIGINAL + ["1"])
    manada.activar(casa2, acepto=True)
    acciones = manada.sincronizar(casa2, url_base=(repo / "herramientas").as_uri() + "/")
    assert any("HASH MISMATCH" in a for a in acciones)
    tarea = estado.cargar_tarea(casa2, "doble")
    assert tarea is None or tarea.get("estado") != "sombra"
    assert any(e["evento"] == "manada_hash_invalido" and e["nivel"] == "CRITICO"
               for e in log.leer(casa2))


# ---------------------------------------------------------------- log/sync

def test_log_niveles_y_alcance(tmp_path: Path) -> None:
    log.registrar(tmp_path, "NIVEL_FALSO", "x")  # unknown level degrades to BAJO
    eventos = log.leer(tmp_path)
    assert eventos[0]["evento"] == "alcance" and "Scope locked" in eventos[0]["aviso"]
    assert eventos[1]["nivel"] == "BAJO"


def test_log_sync_sin_repo(tmp_path: Path) -> None:
    log.registrar(tmp_path, "BAJO", "x")
    cambio, mensaje = log_sync.sincronizar(tmp_path)
    assert cambio is False and "not a git repo" in mensaje


def test_log_sync_commitea_solo_el_log(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "otro.txt").write_text("never staged", encoding="utf-8")
    log.registrar(tmp_path, "BAJO", "x")
    cambio, mensaje = log_sync.sincronizar(tmp_path, push=False)
    assert cambio is True, mensaje
    salida = subprocess.run(
        ["git", "-C", str(tmp_path), "show", "--stat", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "ORACULO.log" in salida and "otro.txt" not in salida


# ---------------------------------------------------------------- cli

def test_cli_run_y_status(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from oraculo import cli

    codigo = cli.main(
        ["--workdir", str(tmp_path), "run", "doble", "--", *CMD_ORIGINAL, "3"]
    )
    assert codigo == 0
    assert capsys.readouterr().out == "6\n"
    assert cli.main(["--workdir", str(tmp_path), "status"]) == 0
    assert "doble" in capsys.readouterr().out


def test_cli_report_honesto(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from oraculo import cli

    assert cli.main(["--workdir", str(tmp_path), "report"]) == 0
    salida = capsys.readouterr().out
    assert "estimate" in salida  # savings are always labeled as estimates
