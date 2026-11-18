#!/bin/sh
# Run the checker over each example file and show the result.
# The flagged example fails on purpose, so each run is allowed to fail.
cd "$(dirname "$0")/.."
for f in examples/clean.css examples/flagged.css examples/edge.css; do
  echo "== $f =="
  python3 src/css_var_checker.py "$f" || true
  echo
done
echo "== examples/ : the whole folder =="
python3 src/css_var_checker.py examples/ || true
