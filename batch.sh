#!/bin/bash
# Run oracle-mutants over Terminal-Bench tasks, N at a time, with a time cap per task.
# Usage: PARALLEL=3 ./batch.sh task1 task2 ...
TB=${TB:-$HOME/Documents/Projects/_upstream/terminal-bench/tasks}
OUT=${OUT:-$PWD/runs/tb}
PARALLEL=${PARALLEL:-3}
MAX_MUTANTS=${MAX_MUTANTS:-30}
MAX_FILES=${MAX_FILES:-6}
TASK_TIMEOUT=${TASK_TIMEOUT:-2700}
mkdir -p "$OUT"
one() {
  t=$1
  echo "=== start $t $(date +%H:%M:%S)"
  timeout "$TASK_TIMEOUT" .venv/bin/oracle-mutants run "$TB/$t" --out "$OUT" --max-mutants "$MAX_MUTANTS" --max-files "$MAX_FILES" --workers 3 > "$OUT/$t.log" 2>&1
  echo "=== done $t exit=$? $(date +%H:%M:%S) :: $(tail -1 "$OUT/$t.log")"
}
export -f one; export TB OUT MAX_MUTANTS MAX_FILES TASK_TIMEOUT
printf "%s\n" "$@" | xargs -P "$PARALLEL" -I{} bash -c 'one {}'
