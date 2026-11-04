#!/bin/sh
# FlowLens installer: real Vim and/or Neovim (no sudo, no network).
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
echo "FlowLens root: $ROOT"

echo "-> checking python3 + numpy"
command -v python3 >/dev/null || { echo "   ERROR: python3 not found"; exit 1; }
python3 -c 'import numpy' 2>/dev/null || {
  echo "   ERROR: numpy missing. Install it with: python3 -m pip install numpy"
  exit 1; }
python3 -c 'import numpy,sys;print("   python",sys.version.split()[0],"numpy",numpy.__version__)'

echo "-> checking editors"
HAVE_VIM=0
HAVE_NVIM=0
if command -v vim >/dev/null 2>&1; then
  if vim --version 2>/dev/null | head -1 | grep -qi NVIM; then
    echo "   'vim' resolves to Neovim (shell alias) - use 'command vim' for real Vim"
  else
    ok=1
    for f in job channel textprop; do
      vim --version | grep -q "+$f" || ok=0
    done
    if [ "$ok" = "1" ]; then
      HAVE_VIM=1
      echo "   vim: $(vim --version | head -1)"
    else
      echo "   vim: lacks +job/+channel/+textprop, skipped"
    fi
  fi
fi
if command -v nvim >/dev/null 2>&1; then
  HAVE_NVIM=1
  echo "   nvim: $(nvim --version | head -1)"
fi
[ "$HAVE_VIM" = "1" ] || [ "$HAVE_NVIM" = "1" ] || {
  echo "   ERROR: need Vim 8.1+ (+job +channel +textprop) or Neovim 0.5+"; exit 1; }

echo "-> weights"
[ -f "$ROOT/weights/flowlens_weights.npz" ] || {
  python3 "$ROOT/build/construct_weights.py" | head -2; }
echo "   $(wc -c < "$ROOT/weights/flowlens_weights.npz" | tr -d ' ') bytes"

echo "-> installing editor files"
mkdir -p "$HOME/.vim/plugin" "$HOME/.vim/autoload"
ln -sf "$ROOT/vim/plugin/flowlens.vim" "$HOME/.vim/plugin/flowlens.vim"
ln -sf "$ROOT/vim/autoload/flowlens.vim" "$HOME/.vim/autoload/flowlens.vim"
echo "   vim:  ~/.vim/{plugin,autoload}/flowlens.vim"
NVIM_SITE="${XDG_DATA_HOME:-$HOME/.local/share}/nvim/site"
mkdir -p "$NVIM_SITE/plugin" "$NVIM_SITE/autoload"
ln -sf "$ROOT/vim/plugin/flowlens.vim" "$NVIM_SITE/plugin/flowlens.vim"
ln -sf "$ROOT/vim/autoload/flowlens.vim" "$NVIM_SITE/autoload/flowlens.vim"
echo "   nvim: $NVIM_SITE/{plugin,autoload}/flowlens.vim"
echo "   (custom runtimepath: add set rtp+=$ROOT/vim)"

echo "-> helper self-test"
printf '%s\n' '{"id":1,"tick":1,"text":"int f(int a){int b=a+1;return b;}\n","cursor":19,"mode":"downstream"}' \
 | python3 -u "$ROOT/engine/helper.py" | tail -1 | python3 -c \
 'import json,sys; r=json.load(sys.stdin); print("   ok" if r.get("ok") else "   FAILED", r.get("ranges"), r.get("error",""))'

echo "-> editor self-tests"
cat > /tmp/flowlens_st.c <<'CEOF'
int demo(int input, int ignored) {
    int x = input + 1;
    int saved = x;
    return saved;
}
CEOF
sed "s|__ROOT__|$ROOT|" <<'VIMEOF' > /tmp/flowlens_st.vim
set nocompatible
set rtp+=__ROOT__/vim
runtime! plugin/flowlens.vim
syntax off
edit /tmp/flowlens_st.c
call cursor(3, 17)
Flow downstream
let n = 0
while n < 600 && empty(flowlens#timing())
  sleep 10m
  let n += 1
endwhile
let t = flowlens#timing()
let marks = flowlens#marks(bufnr('%'))
let sel = filter(copy(marks), 'v:val.group ==# "FlowLensSelected"')
call writefile([json_encode({'editor': has('nvim') ? 'neovim' : 'vim',
      \ 'ok': !empty(t), 'labels': len(marks), 'selected': len(sel),
      \ 'render_ms': get(t, 'render_ms', -1),
      \ 'e2e_ms': get(t, 'end_to_end_ms', -1)})], '/tmp/flowlens_st.json')
qa!
VIMEOF
rm -f /tmp/flowlens_st.json
if [ "$HAVE_VIM" = "1" ]; then
  vim -Nu NONE -n -es -S /tmp/flowlens_st.vim >/dev/null 2>&1 || true
  [ -f /tmp/flowlens_st.json ] && { printf '   vim:  '; cat /tmp/flowlens_st.json; echo; } \
    || echo "   vim:  self-test produced no output"
  rm -f /tmp/flowlens_st.json
fi
if [ "$HAVE_NVIM" = "1" ]; then
  nvim --headless -u NONE -S /tmp/flowlens_st.vim >/dev/null 2>&1 || true
  [ -f /tmp/flowlens_st.json ] && { printf '   nvim: '; cat /tmp/flowlens_st.json; echo; } \
    || echo "   nvim: self-test produced no output"
  rm -f /tmp/flowlens_st.json
fi

echo
echo "Done. Open a .c file, put the cursor on an identifier, run :Flow downstream"
echo "Inside the editor, :Flow info shows the supported subset and timings."
