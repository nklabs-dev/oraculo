#!/usr/bin/env bash
# oraculo-ciclo — daily no-agent cron body for Hermes. $0 tokens.
# Runs detection + cure + guardian refresh + log sync. Prints [SILENT] when green.
set -euo pipefail
cd "${ORACULO_WORKDIR:-$HOME}"
exec oraculo ciclo
