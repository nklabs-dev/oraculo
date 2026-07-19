"""Benchmarks for the numbers the README claims. Run: python3 scripts/bench.py

Measures, on THIS machine:
  1. detection verdict over synthetic histories of 1k / 10k / 100k runs
  2. guardian full 3-layer pass over a realistic generated script
  3. interception overhead: compiled .py via subprocess vs the bare command
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from oraculo import detectar, estado, guardian  # noqa: E402

SCRIPT_REALISTA = (RAIZ / "tests" / "test_oraculo.py").read_text(encoding="utf-8").split(
    'PY_CORRECTO = \'\'\'\\\n'
)[1].split("'''")[0]


def medir(fn, repeticiones: int = 5) -> float:
    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        fn()
        tiempos.append((time.perf_counter() - inicio) * 1000.0)
    return statistics.median(tiempos)


def main() -> int:
    config = estado.CONFIG_DEFECTO
    print("# ORÁCULO benchmarks (median of 5, this machine)\n")

    for n in (1_000, 10_000, 100_000):
        historia = [
            {"ts": 1000.0 + i, "comando": "x", "aridad": 3, "exit_code": 0}
            for i in range(n)
        ]
        ms = medir(lambda h=historia: detectar.evaluar(h, config))
        print(f"detection verdict over {n:>7,} runs: {ms:8.2f} ms")

    ms = medir(lambda: guardian.verificar(SCRIPT_REALISTA))
    pack = guardian.cargar_pack()
    print(f"\nguardian 3-layer pass ({len(pack['reglas'])} rules): {ms:.2f} ms")

    py = RAIZ / "scripts" / "_bench_echo.py"
    py.write_text(
        '"""bench task."""\nimport sys\n\n\ndef main() -> int:\n'
        "    print(sys.argv[-1])\n    return 0\n\n\n"
        'if __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
    )
    try:
        ms_py = medir(
            lambda: subprocess.run(
                [sys.executable, str(py), "42"], capture_output=True, check=True
            ),
            repeticiones=20,
        )
        print(f"\ncompiled .py end-to-end (subprocess): {ms_py:.1f} ms")
    finally:
        py.unlink(missing_ok=True)
    print("\n(compare with seconds-to-minutes for the same task through an LLM)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
