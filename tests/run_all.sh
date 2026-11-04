#!/bin/sh
# FlowLens: run every check.  Default is the fast set (~20 s); --full adds the
# randomised suites at the sizes quoted in docs/RESULTS.md (~2 min).
#
#   sh tests/run_all.sh            fast
#   sh tests/run_all.sh --full     everything
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
MODE=${1:-quick}
case "$MODE" in
  --full) FUZZ=200; FUZZ2=80; HOLDOUT=300; CF=200 ;;
  *)      FUZZ=40;  FUZZ2=20; HOLDOUT=40;  CF=12 ;;
esac
fail=0
run() {
  name=$1; shift
  printf '%-22s ' "$name"
  out=$("$@" 2>&1)
  if [ $? -ne 0 ]; then
    echo "FAIL"
    echo "$out" | tail -12 | sed 's/^/    /'
    fail=$((fail + 1))
  else
    echo "$out" | tail -1 | sed 's/^ *//'
  fi
}

echo "== weights are a pure function of the construction script =="
before=$(shasum -a 256 weights/flowlens_weights.npz 2>/dev/null | cut -d' ' -f1)
python3 build/construct_weights.py >/dev/null 2>&1
after=$(shasum -a 256 weights/flowlens_weights.npz | cut -d' ' -f1)
if [ "$before" = "$after" ]; then
  echo "  deterministic: yes   $after"
else
  echo "  deterministic: NO    $before -> $after"
  fail=$((fail + 1))
fi

echo
echo "== correctness against the test-only reference =="
run "development"            python3 tests/evaluate.py
run "loops+unbraced"         python3 tests/evaluate_loops.py
run "held-out (frozen)"      python3 tests/holdout_fresh.py "$HOLDOUT"
run "held-out loops"         python3 tests/holdout_loops.py
run "fuzz straight-line"     python3 tests/fuzz.py "$FUZZ"
run "fuzz control flow"      python3 tests/fuzz_cf.py "$CF"
run "fuzz invariance"        python3 tests/fuzz2.py "$FUZZ2"
run "unsupported detection"  python3 tests/anomaly.py

echo
echo "== editors (real Vim 9.1 and Neovim, headless) =="
printf '%-22s ' "vim + neovim"
ed=$(sh tests/vim/run.sh 2>&1); edrc=$?
v=$(echo "$ed" | grep -c "checks passed in vim")
n=$(echo "$ed" | grep -c "checks passed in neovim")
if [ "$edrc" -eq 0 ] && [ "$v" -eq 1 ] && [ "$n" -eq 1 ]; then
  echo "$(echo "$ed" | grep "in vim" | tail -1 | sed 's/^ *//') / $(echo "$ed" | grep "in neovim" | tail -1 | sed 's/^ *//')"
else
  echo "FAIL"
  echo "$ed" | tail -10 | sed 's/^/    /'
  fail=$((fail + 1))
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "ALL CHECKS PASSED ($MODE)"
else
  echo "$fail CHECK(S) FAILED ($MODE)"
fi
exit $((fail > 0))
