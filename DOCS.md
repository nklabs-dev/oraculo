# ORÁCULO — reference

Everything the README does not cover. The README is the sale; this is the map.

## 1. Storage layout (per project/workdir)

```
.oraculo/                  state (gitignore it)
  config.json              your overrides (defaults are created in memory)
  runs.ndjson              append-only run history
  tasks/<name>.json        per-task state machine
  compiled/<name>.py       graduated scripts
  ejemplos/<name>/         captured real input/output examples (the test suite)
  requests/<name>.md       manual-backend compilation requests
ORACULO.log                the open book (workdir root, ndjson, public by design)
```

Task states: `observada → candidata → sombra → promovida`, plus `degradada`
(a promoted script failed; the task is back on the original path while it cures).

## 2. Commands

| Command | What it does |
|---|---|
| `oraculo run <name> -- <cmd...>` | Route a task. Transparent: same stdout, same exit code. Observes, shadows, intercepts or degrades depending on state. |
| `oraculo status [--json]` | Tasks by state, runs, interceptions, shadow progress, degradations. |
| `oraculo candidates` | Run detection now and list candidates. |
| `oraculo compile <name>` | Compile a candidate/degraded task. `--desde FILE.py` injects a script produced by any agent; `--backend claude\|manual`; `--forzar` skips the break-even gate. |
| `oraculo report [--horas N]` | The morning report: intercepted / compiled / cured (+real time) / estimated savings with the method shown. |
| `oraculo update-guardian` | Fetch the latest rule pack, sha256-verified against its manifest. |
| `oraculo log-sync [--no-push]` | `git add ORACULO.log && commit && push` — that one file, nothing else. Says so and does nothing if there is no git repo. |
| `oraculo doctor [--quick]` | Verify install, pack, INGENIERO.md, backend, Hermes wiring. Reuses `hermes doctor` instead of duplicating its checks. |
| `oraculo ciclo` | The daily cron body: detect → cure degraded → refresh guardian (if stale) → manada sync (if ON) → log-sync. Prints `[SILENT]` when green. |
| `oraculo manada on/off/estado/sync/publicar` | The community layer (§6). |

All commands accept `--workdir PATH` (default: current directory).

## 3. Configuration (`.oraculo/config.json`)

Everything is optional; unknown keys are preserved. Defaults:

```json
{
  "deteccion":   {"min_corridas": 3, "ventana_dias": 30},
  "sombra":      {"exitos_requeridos": 3, "exitos_requeridos_cura": 2},
  "presupuesto": {"tokens_por_corrida_estimados": 1500,
                  "tokens_salida_compilacion": 2000, "horizonte_dias": 30},
  "backend": "auto",
  "backend_timeout_s": 600,
  "captura": {"max_ejemplos": 10, "max_bytes_ejemplo": 65536},
  "manada": "off",
  "manada_url": "https://raw.githubusercontent.com/nklabs-dev/oraculo/main/herramientas/",
  "guardian": {"url_pack": "https://raw.githubusercontent.com/nklabs-dev/oraculo/main/guardian_rules/",
               "auto_update_dias": 7},
  "log_sync": {"auto": true}
}
```

Detection is deterministic and conservative on purpose: same task ≥3 runs in
the window, same command, same arity, all exit 0. Loosen with evidence, not
with hope — a wrongly promoted .py costs more than ten never compiled.

## 4. The compiled-script contract

`python3 .oraculo/compiled/<name>.py <argv...>` receives the EXACT argv of the
original command, prints the task's result to stdout (byte-identical to the
original for the same input), exits 0 on success, non-zero + one stderr line
on failure. `INGENIERO.md` (R1–R17) is the full standard; the guardian
enforces the verifiable subset and `compilar` replays the captured real
examples before anything reaches shadow.

Compilation backends:

- **claude** — Claude Code print mode, output redirected to a file
  (`claude -p ... --output-format json > file`), never parsed from live
  stdout. Uses your existing subscription/login; no API key handling.
- **manual** — writes `.oraculo/requests/<name>.md` (spec + real examples +
  standard). Any agent or human fulfills it and injects the result with
  `oraculo compile <name> --desde file.py`. This is also how Hermes itself
  can be the compiler: the `oraculo` skill teaches it.

Hard budget: before spending tokens, projected saving (observed frequency ×
estimated tokens/run × horizon) must beat the estimated compile cost, or the
task is not compiled and the decision is logged (BAJO) with both numbers.
Cures skip the gate: repairing an already-justified task is maintenance.

## 5. The harness in detail

- **Shadow**: the original command stays authoritative; the .py runs
  alongside. Promotion needs K consecutive matches (default 3) of exit code +
  stdout sha256. ONE mismatch → counter reset, back to `candidata`.
- **Interception**: `promovida` tasks run the .py first. Millisecond path.
- **Degradation**: any failure of a promoted .py → capture (error, traceback
  line, exact argv), mark `degradada`, run the original command **in the same
  invocation**, log CRITICAL. The user never sees a broken task.
- **Cure**: recompilation with ONLY the surgical context (error + line +
  failing input + current code), guardian, example replay, short shadow
  (default 2), re-promotion. Real duration is logged (`curada`, `dur_s`).

## 6. La manada

Spec: one user's promoted .py for a common tool → auto-sanitization
(personal paths → `{ORACULO_HOME}`, emails normalized, **abort on any
credential pattern**) → `herramientas/<tool>/v<N>/` with `perfil.json`
(command, arity, config note, sha256, origin history) → `index.json` catalog.

A receiving ORÁCULO with consent ON (`oraculo manada on --acepto`, logged)
matches the catalog against the tools it has actually observed locally,
downloads ONLY matching versions, verifies sha256 byte-for-byte, and installs
them **in shadow** — they graduate in the receiver's house like any local
script. Flagged (`marcada`) versions are never offered. Sync runs inside
`oraculo ciclo` or manually via `oraculo manada sync`.

## 7. Hermes wiring

- Skill: `hermes/SKILL.md` → `~/.hermes/skills/oraculo/` (installer copies it;
  never overwrites an existing one).
- Cron: `hermes/oraculo_ciclo.sh` → `~/.oraculo/bin/`; schedule it no-agent
  daily (`install.sh` prints the `hermes cron create` line; set
  `ORACULO_WORKDIR` if your project is not `$HOME`).
- AGENTS.md: optional delimited block in `hermes/AGENTS_BLOCK.md`.
- `oraculo doctor` checks all three and runs `hermes doctor` when available.

Nothing in ORÁCULO touches Hermes internals: no hooks into its process, no
dashboard hacking. The Hermes dashboard tab is tracked as an issue until
Hermes exposes an official extension mechanism (reviewed: v0.18.0).

## 8. ORACULO.log format

One JSON object per line: `ts`, `nivel` (`CRITICO|MEDIO|BAJO`), `evento`,
optional `tarea` + event fields. First line is always the scope notice.
Events: `deteccion`, `compilada`, `request_manual`, `guardian_rechazo`,
`guardian_indecidible`, `tests_fallo`, `break_even_no_cierra`, `sombra_ok`,
`sombra_fallo`, `promovida`, `fallo_produccion` (CRITICAL), `curada`,
`manada_*`. Triage: production failure = CRITICAL; lifecycle transitions =
MEDIUM; detections and bookkeeping = LOW.

## 9. Tests and benchmarks

```bash
python3 -m pytest tests/ -q     # 40 deterministic offline tests
python3 scripts/bench.py        # the README numbers, on your machine
```

The centerpiece test walks the full cycle: 3 runs → detection → injected .py
→ shadow 3/3 → promotion → interception → induced failure → automatic
degradation with correct fallback output → log levels verified.
