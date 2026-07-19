#!/usr/bin/env bash
# ORÁCULO installer — by nklabs-dev. One command, zero mandatory configuration.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing ORÁCULO..."
if command -v pipx >/dev/null 2>&1; then
    pipx install "$AQUI" --force >/dev/null
elif pip install "$AQUI" >/dev/null 2>&1; then
    :
else
    pip install "$AQUI" --break-system-packages >/dev/null
fi

# Updatable copies of the standard + rule pack (update-guardian refreshes them)
mkdir -p "$HOME/.oraculo/guardian_rules"
cp "$AQUI/INGENIERO.md" "$HOME/.oraculo/INGENIERO.md"
cp "$AQUI/guardian_rules/reglas.json" "$HOME/.oraculo/guardian_rules/reglas.json"

# Hermes wiring — only if Hermes lives here, never touching anything existing
if [ -d "$HOME/.hermes" ]; then
    if [ ! -d "$HOME/.hermes/skills/oraculo" ]; then
        mkdir -p "$HOME/.hermes/skills/oraculo"
        cp "$AQUI/hermes/SKILL.md" "$HOME/.hermes/skills/oraculo/SKILL.md"
        echo "✅ Hermes skill installed: ~/.hermes/skills/oraculo/"
    else
        echo "ℹ️  Hermes skill already present — left untouched"
    fi
    mkdir -p "$HOME/.oraculo/bin"
    cp "$AQUI/hermes/oraculo_ciclo.sh" "$HOME/.oraculo/bin/oraculo_ciclo.sh"
    chmod +x "$HOME/.oraculo/bin/oraculo_ciclo.sh"
    if command -v hermes >/dev/null 2>&1; then
        echo ""
        echo "To schedule the daily cycle (detection + guardian refresh + log sync):"
        echo "  hermes cron create --name oraculo-ciclo --schedule '0 8 * * *' \\"
        echo "      --no-agent --script $HOME/.oraculo/bin/oraculo_ciclo.sh --deliver local"
        echo "  (check 'hermes cron create --help' for your version's exact flags;"
        echo "   set ORACULO_WORKDIR in the script if your project is not \$HOME)"
    fi
else
    echo "ℹ️  No ~/.hermes found — ORÁCULO works standalone; Hermes wiring skipped"
fi

echo ""
oraculo doctor --quick || true
echo ""
echo "── Scope notice ─────────────────────────────────────────────────────"
echo "ORACULO.log records ONLY ORÁCULO's own lifecycle (detection, compile,"
echo "shadow, promotion, failure, cure) for tasks YOU route through"
echo "'oraculo run'. Nothing else is observed. The log is public by design."
echo "── La manada ────────────────────────────────────────────────────────"
echo "Status: OFF until you read the consent text and opt in:"
echo "  oraculo manada on          # prints exactly what it does"
echo "  oraculo manada on --acepto # records your global consent"
echo "─────────────────────────────────────────────────────────────────────"
echo "✅ ORÁCULO active. Route a task:  oraculo run <name> -- <command...>"
