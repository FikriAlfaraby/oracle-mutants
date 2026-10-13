#!/bin/bash
# Run oracle-mutants over Terminal-Bench tasks, N at a time, with a time cap per task.
# Usage: PARALLEL=3 ./batch.sh task1 task2 ...
TB=${TB:-$HOME/Documents/Projects/_upstream/terminal-bench/tasks}
OUT=${OUT:-$PWD/runs/tb}
PARALLEL=${PARALLEL:-3}
mkdir -p "$OUT"
one() {
  t=$1
  echo "=== start $t $(date +%H:%M:%S)"
  timeout 2700 .venv/bin/oracle-mutants run "$TB/$t" --out "$OUT" --max-mutants 30 --workers 3 > "$OUT/$t.log" 2>&1
  echo "=== done $t exit=$? $(date +%H:%M:%S) :: $(tail -1 "$OUT/$t.log")"
}
export -f one; export TB OUT
printf "%s\n" "$@" | xargs -P "$PARALLEL" -I{} bash -c 'one {}'
