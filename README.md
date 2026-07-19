# ORÁCULO

**Your agent did this task 3 times. The 4th is free.**

ORÁCULO watches what your agent repeats, has the LLM solve it ONE last time,
and leaves behind a tested `.py` that does it forever — 0 tokens, milliseconds,
self-healing. The LLM goes back to being what its name says: an oracle you
consult rarely, and every consultation leaves compiled knowledge behind.

---

> Every morning your agent re-reads the same skill, re-decides the same
> decision, re-parses the same format — and you pay for every step, every
> time, forever. It is like hiring a doctor to tie your shoes every day.
>
> **The 90% of agent work that is routine is a token debt. ORÁCULO pays it once.**

## The graduation cycle

```
 oraculo run backup -- <command>          (you route the task; same output)
      │ 1st run   observed
      │ 2nd run   observed
      │ 3rd run   ✔ same structure, clean → CANDIDATE          (0 tokens)
      ▼
 the oracle compiles it ONCE  ──►  guardian (3 layers)  ──►  SHADOW
      ▲                                                        │ runs BOTH ways,
      │ any failure: auto-degrade,                             │ promotes only on
      │ capture error+line+input,                              │ 100% output match
      │ recompile surgically, re-shadow                        ▼
      └────────────────────────────────────────────────  PROMOTED
                                            every next run: .py answers first
                                            0 tokens · ~9 ms · counter goes up
```

No step needs your attention. Detection is automatic (observation, not
requests), promotion needs 100% output coincidence, and a promoted script that
ever fails degrades back to the LLM **in the same invocation** — nothing
breaks, the failure is captured and cured. That harness is why it is safe to
use in production from day one.

## The numbers (measured, script in `scripts/bench.py`)

| What | Measured |
|---|---|
| Detection verdict over 10,000 runs | 1.4 ms |
| Detection verdict over 100,000 runs | 14.3 ms |
| Guardian full 3-layer pass (15 rules) | 0.4 ms |
| Compiled .py end-to-end (subprocess) | 9.4 ms |
| The same task through an LLM | seconds to minutes, plus tokens |

Token savings in `oraculo report` are always labeled as **estimates with the
method shown** (intercepted runs × estimated tokens per run). Honest numbers
or none.

## Honest comparison

| | Makes tools with LLM | Auto-detects by observation | Shadow before trusting | Auto-degrades on failure | Community pack |
|---|---|---|---|---|---|
| LATM (2023) | ✅ | ❌ on request | ❌ | ❌ | ❌ |
| ToolMaker (2025) | ✅ | ❌ on request | ❌ self-correction loop | ❌ | ❌ |
| Agent Workflow Memory (2024) | ❌ reinjects as context (still pays tokens) | ✅ | ❌ | ❌ | ❌ |
| Agent skills (Hermes/Claude) | ❌ text the LLM re-reads, paying every time | ❌ | ❌ | ❌ | ✅ hubs |
| **ORÁCULO** | ✅ | ✅ **by observation** | ✅ **100% match required** | ✅ **same invocation** | ✅ **la manada** |

The papers prove the economics work. Nobody had packaged it for an agent
people run every day — with automatic detection, a shadow period, automatic
degradation and a visible savings counter.

## Install

```bash
git clone https://github.com/nklabs-dev/oraculo && cd oraculo && ./install.sh
```

Zero mandatory configuration. Then route any repetitive task:

```bash
oraculo run mi-backup -- python3 backup.py --dest /srv/backups
oraculo status      # watch it graduate
oraculo report      # the morning report: intercepted / compiled / cured / saved
```

Works standalone; if `~/.hermes` exists it also installs the Hermes skill and
prints the `hermes cron create` line for the daily cycle.

## The guardian

Every generated script passes three layers before it may even enter shadow:
platform checks (`ast`, `compile`, `ruff` if present), the **ecosystem rule
pack** — the universal LLM code errors generic tooling does not know:
hallucinated imports, fake hook names, credential literals, junior vices
(`guardian_rules/`, 15 rules and growing) — and whatever code cannot decide is
marked and returned to the LLM with surgical context. The pack updates
hash-verified: `oraculo update-guardian`. One user discovers an error, everyone
gets the rule.

## La manada (the pack)

Most users run the same tools. A mundane task compiled by one user is
sanitized (paths → placeholders, zero credentials, publication aborts
otherwise), hashed, versioned, and matched **automatically** to other users
with the same tool config — where it re-validates in THEIR harness before
going active. One compiles, everyone runs. Off until you read the consent
text and opt in: `oraculo manada on`. Details: `herramientas/README.md`.

## The open book

`ORACULO.log` records every lifecycle event (detected / compiled / shadow /
promoted / failed / cured), triaged CRITICAL/MEDIUM/LOW, in your workdir, in
your git if you want (`oraculo log-sync` commits that one file and nothing
else). Scope is locked by design: only ORÁCULO's own cycle is recorded —
verifiable by reading `oraculo/log.py`.

---

*An agent that thinks the same thought twice learned nothing. ORÁCULO turns
repeated thought into code — and code works for free.*

## References

- Cai et al., **"Large Language Models as Tool Makers"** (LATM), 2023 — arXiv:2305.17126
- Wölflein et al., **ToolMaker**, 2025
- **"Agentic Compilation: Mitigating the LLM Rerun Crisis"**, 2026 — arXiv:2604.09718
- Zheng et al., **Agent Workflow Memory**, 2024
- Ocker et al., **Tulip Agent**, 2024

MIT © 2026 nklabs-dev · full reference: [DOCS.md](DOCS.md)
