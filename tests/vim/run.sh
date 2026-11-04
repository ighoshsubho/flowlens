#!/bin/sh
# Editor integration tests for FlowLens: runs the same suite in real Vim and,
# if present, in Neovim.
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

cat > /tmp/flowlens_demo.c <<'CEOF'
int demo(int input, int ignored) {
    int x = input + 1;
    int saved = x;
    x = 0;
    int unrelated = ignored * 2;
    int result = saved * 3;
    return result;
}
CEOF

for EDITOR in vim nvim; do
  command -v "$EDITOR" >/dev/null 2>&1 || { echo "== $EDITOR not installed, skipped"; continue; }
  echo "== $EDITOR"
  cat > /tmp/flowlens_tests.vim <<VIMEOF
set nocompatible
set rtp+=$ROOT/vim
runtime! plugin/flowlens.vim
syntax off
source $ROOT/tests/vim/test_plugin.vim
VIMEOF

  rm -f /tmp/flowlens_editor_tests.json
  if [ "$EDITOR" = "nvim" ]; then
    nvim --headless -u NONE -S /tmp/flowlens_tests.vim >/dev/null 2>&1 || true
  else
    vim -Nu NONE -n -es -S /tmp/flowlens_tests.vim >/dev/null 2>&1 || true
  fi

  if [ ! -f /tmp/flowlens_editor_tests.json ]; then
    echo "  FAILED: no report produced by $EDITOR"
    continue
  fi
  cp /tmp/flowlens_editor_tests.json "/tmp/flowlens_report_$EDITOR.json"
  python3 - "$EDITOR" <<'PYEOF'
import json, sys
ed = sys.argv[1]
d = json.load(open('/tmp/flowlens_report_%s.json' % ed))
bad = 0
for c in d['checks']:
    print(('  ok   ' if c['ok'] else '  FAIL ') + c['check'] + '  ' + c['detail'][:100])
    bad += 0 if c['ok'] else 1
print('  %d/%d checks passed in %s\n' % (len(d['checks']) - bad, len(d['checks']), d['editor']))
sys.exit(1 if bad else 0)
PYEOF
done
