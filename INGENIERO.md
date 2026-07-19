# INGENIERO.md — the standard every compiled .py must meet

> This file IS part of the product. `compilar.py` injects it into every
> compilation request, and `guardian.py` enforces the verifiable subset.
> Rules, not advice: each item is checkable by reading the script.

## 1. Structure (mandatory)

- **R1** Module docstring, first statement, stating: task name, that it was
  compiled by ORÁCULO from observed runs, the source (`observed runs of
  <command>`), and a version line (`v<N> — <date>`).
- **R2** A `main() -> int` function that parses arguments with `argparse`,
  does the work, and returns an exit code.
- **R3** `if __name__ == "__main__": raise SystemExit(main())` — and nothing
  else at module level besides imports, constants and definitions.
- **R4** The script receives the EXACT argv the original command received
  (`python3 compiled.py <argv...>`), prints the task's result to **stdout**,
  and must byte-match the original command's stdout for the same input.

## 2. Errors (mandatory)

- **R5** Explicit exception handling: catch the narrowest exception that can
  actually happen; never `except:`; never `except Exception` without
  re-raising or exiting non-zero.
- **R6** Every failure path exits with a non-zero code and one clear line on
  **stderr**. Failure must be loud — ORÁCULO's degrader depends on it.
- **R7** No fallback that silently returns an empty/default result: an empty
  answer that looks like success is a False Green and will poison the shadow
  comparison.

## 3. Dependencies and IO (mandatory)

- **R8** Standard library only. A third-party import requires explicit
  approval recorded in the compilation request — otherwise the guardian
  rejects the script.
- **R9** No hardcoded credentials, tokens or API keys. Ever. Secrets come
  from the environment, and only when the task already used them.
- **R10** No absolute personal paths (`/home/<user>/...`). Paths come from
  argv, cwd or env.
- **R11** Text IO pins `encoding="utf-8"`. Subprocess calls use argv lists —
  no `shell=True`, no `os.system`.

## 4. Style (verifiable)

- **R12** Type hints on every function signature.
- **R13** Logging (progress, diagnostics) goes to **stderr** — stdout belongs
  exclusively to the task's output (R4 depends on this).
- **R14** No mutable default arguments. No `eval`/`exec`. No dead code, no
  commented-out blocks, no `TODO` left behind.
- **R15** Deterministic by default: no randomness, no wall-clock dependence
  in the output, unless the observed runs themselves show it — in that case
  document it in the docstring, because the shadow comparison must still pass.

## 5. Tests (mandatory)

- **R16** The captured real runs ARE the specification: for each provided
  example, `python3 compiled.py <example argv>` must produce the example's
  stdout exactly (trailing newline included) and exit 0.
- **R17** Ship the check: either an embedded `--self-test` mode that replays
  the examples, or an adjacent pytest file. Either must be runnable offline
  in under a second.
