#!/bin/bash
set -euo pipefail
python3 - <<'PY'
import json, re, collections
words = re.findall(r"[a-z]+", open("/app/input.txt").read().lower())
json.dump(dict(sorted(collections.Counter(words).items())), open("/app/counts.json", "w"), indent=2)
PY
