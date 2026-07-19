"""log_admin curation: deterministic, CRITICAL-preserving, compacting."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import log_admin  # noqa: E402

DIA = 86400.0
AHORA = 100 * DIA


def entradas_ejemplo() -> list[dict]:
    return [
        {"ts": 0.0, "nivel": "BAJO", "evento": "alcance", "aviso": "scope"},
        {"ts": 1 * DIA, "nivel": "CRITICO", "evento": "fallo_produccion", "tarea": "a"},
        {"ts": 2 * DIA, "nivel": "MEDIO", "evento": "promovida", "tarea": "a"},
        {"ts": 3 * DIA, "nivel": "MEDIO", "evento": "promovida", "tarea": "a"},
        {"ts": 4 * DIA, "nivel": "BAJO", "evento": "deteccion", "tarea": "a"},
        {"ts": 5 * DIA, "nivel": "BAJO", "evento": "deteccion", "tarea": "b"},
        {"ts": 99 * DIA, "nivel": "MEDIO", "evento": "compilada", "tarea": "b"},  # recent
        {"ts": 99.5 * DIA, "nivel": "BAJO", "evento": "deteccion", "tarea": "c"},  # recent
    ]


def test_curar_preserva_criticos_y_header() -> None:
    curado = log_admin.curar(entradas_ejemplo(), AHORA)
    eventos = [e["evento"] for e in curado]
    assert "alcance" in eventos and "fallo_produccion" in eventos


def test_curar_compacta_medio_y_bajo_viejos() -> None:
    curado = log_admin.curar(entradas_ejemplo(), AHORA)
    resumen_medio = next(e for e in curado if e["evento"] == "resumen_medio")
    assert resumen_medio["n"] == 2 and resumen_medio["tarea"] == "a"
    resumen_bajo = next(e for e in curado if e["evento"] == "resumen_bajo")
    assert resumen_bajo["conteos"] == {"deteccion": 2}
    # recent entries stay verbatim
    assert any(e["evento"] == "compilada" for e in curado)
    assert any(e["evento"] == "deteccion" and e.get("tarea") == "c" for e in curado)


def test_curar_determinista_e_idempotente() -> None:
    una = log_admin.curar(entradas_ejemplo(), AHORA)
    dos = log_admin.curar(entradas_ejemplo(), AHORA)
    assert una == dos
    # curating the curated output changes nothing (summaries are recent-dated)
    assert log_admin.curar(una, AHORA) == una
