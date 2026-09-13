---
name: retro-lean
description: Working protocol for the retro-bonuses Family Market project (Python, Supabase, BigQuery, Excel parsing). Use for any task touching core/, sql/, tools/ or analysis/ - reading code, debugging scripts, editing logic, running reconciliations. Enforces symbol-level navigation, aggregate-first data inspection, and no full dumps of CSV or query output into the conversation.
---

# Retro project protocol

## Memory
CLAUDE.md holds durable rules only. Details live in docs/.
Open a docs/ file only when the task needs it, and say which one you opened.
If docs/ contradicts CLAUDE.md, CLAUDE.md wins - docs may be stale.

## Code navigation
Use Serena: find_symbol, find_referencing_symbols, get_symbols_overview.
Before changing any shared helper (sb_get, sb_post, load_env, apply_vat)
run find_referencing_symbols first and list call sites - these exist in
multiple copies with different behaviour.
Text search only for literal strings: table names, column names, env keys.
Never text-search a function or class name.
Trust Serena's reference list. Do not reopen listed files to confirm.

## Data output - the main cost here
Never pull a full CSV, query result or script log into the conversation.
For runs of calculate_retro / reconcile_facts / audit_facts_coverage /
probe_gap_docs / diagnose_retro: delegate to a subagent, ask back only for
row counts, totals, and the top 5 rows by absolute deviation.
CSV: header plus first 10 rows, then aggregate. Never read a CSV end to end.
BigQuery: never SELECT *. Aggregate in SQL (SUM, COUNT, GROUP BY supplier,
month). State the date window in every query.

## Domain guardrails
Before concluding money is lost, filter suppliers by retro_base_type.
payments and per_portion_sold suppliers do not respond to
incoming_transactions gaps. Skipping this roughly doubles any estimate.
Never compare against the current unclosed month.
Name resolution: EXACT or a human. No guessing, ever.
None and 0 are different states. Do not collapse them.
Parse Excel by header name only, never by column position.
Store-opening bonus columns are not retro and stay out of reconciliation.

## Edits
Minimal symbol-level edits. Never rewrite whole files.
Never reprint an edited file back to me. Report: file, symbol, one line.
More than 5 files touched - state the plan and wait for go-ahead.
No writes to the DB until output has been eyeballed on CSV.
Apply corrections via retro_adjustments, never by editing
retro_calculation_details directly.

## Output
No preamble, no restating the task. Numbers over narration.

## Handoff
On "wrap up": update session-notes.md - task state, decisions, files and
symbols touched, exact next step. Under 40 lines, overwrite stale entries.
Durable findings go to docs/, not to CLAUDE.md.
