---
name: oraculo
description: Route repetitive tasks through ORÁCULO so they graduate into free .py scripts; always check oraculo status before solving an already-compiled task with the LLM
---

# ORÁCULO — the agent that compiles itself

This machine runs ORÁCULO: every task it sees repeated with the same structure
gets compiled ONCE into a tested .py and never costs tokens again. Your job as
the agent is to feed it and to respect its promotions.

## The two rules

1. **Route repetitive work through the wrapper.** Any command you (or a cron
   script) run more than once with the same shape should go through:

       terminal(command="oraculo run <task-name> -- <command...>", timeout=120)

   Same behavior, same output — plus observation. After 3 identical-structure
   clean runs the task becomes a compilation candidate automatically.

2. **Never re-solve with the LLM what is already compiled.** Before doing a
   task that smells routine, check:

       terminal(command="oraculo status", timeout=15)

   If the task appears as `promovida`, run it through `oraculo run` — the .py
   answers in milliseconds for 0 tokens. If it appears `degradada`, the system
   is already curing it; just use the normal path this once.

## Useful commands

- `oraculo candidates` — what is ready to compile
- `oraculo compile <task>` — compile one candidate (respects the token budget)
- `oraculo report` — what was intercepted/compiled/cured and the estimated saving
- `oraculo doctor` — verify the install and this integration

## Fulfilling a manual compilation request

If `.oraculo/requests/<task>.md` exists, ORÁCULO is asking for a script.
Read the request (it contains the full spec, real examples and the INGENIERO.md
standard), write the script to a file, then:

    terminal(command="oraculo compile <task> --desde <file.py>", timeout=60)

The guardian and the shadow period take it from there — do not skip them.
