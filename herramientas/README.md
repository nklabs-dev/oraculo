# herramientas/ — la manada (the pack)

**One user compiles, everyone runs.** Most Hermes users run the same common
tools (Graphify, Obsidian, ChromaDB, git, gateway/Telegram) with small config
variations. Every mundane task of those tools is compiled ONCE by whoever hits
it first — and matched, downloaded and re-validated automatically by everyone
else. Fully functional from day one.

## How a shared .py lives

1. **Born normal.** It graduates in its author's ORÁCULO the standard way:
   observed → detected → compiled → guardian → shadow to 100% → promoted →
   real production use.
2. **Published because the tool is common.** `oraculo manada publicar <task>`
   auto-sanitizes it (personal paths → placeholders, ZERO credentials — the
   publication aborts if any credential pattern is found), hashes it, and
   writes `herramientas/<tool>/v<N>/` with the config profile it was born in.
3. **Versions come from variation, not choice.** A different config produces
   the next version; the old one stays — they cover different territory.
4. **Matching is automatic and surgical.** A receiving ORÁCULO (with the
   manada consent ON) downloads ONLY the versions whose profile matches the
   tools THIS user actually runs — never this whole directory. The repo is
   the library; each user takes their two books.
5. **Re-validated at destination.** A downloaded .py always enters the
   receiver's own harness (short local shadow) before it is active. Any
   failure self-degrades and is logged. Tested in YOUR house before it runs
   YOUR house.

## Security = ORÁCULO's own chain

Guardian (3 layers) + shadow at origin + sha256 per version (what you install
is byte-for-byte what was published) + local harness at destination + the
public triaged log. Versions flagged `marcada` by log triage are never offered.

## State of the catalog

The catalog (`index.json`) starts empty at launch. The **guardian rule pack**
(`../guardian_rules/`, distributed hash-verified via `oraculo update-guardian`)
is the first shared content of the pack — the .py that makes every other .py
reliable. Activation is per-user and consent-first: `oraculo manada on`.
