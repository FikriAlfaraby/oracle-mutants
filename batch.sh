#!/bin/bash
# Run oracle-mutants over a list of Terminal-Bench tasks, one at a time, with a time cap per task.
TB=${TB:-$HOME/Documents/Projects/_upstream/terminal-bench/tasks}
OUT=${OUT:-runs/tb}
mkdir -p "$OUT"
for t in "$@"; do
  echo "=== $t $(date +%H:%M:%S)"
  timeout 2400 .venv/bin/oracle-mutants run "$TB/$t" --out "$OUT" --max-mutants 30 --workers 4 > "$OUT/$t.log" 2>&1
  echo "exit $? $(tail -1 "$OUT/$t.log")"
done
