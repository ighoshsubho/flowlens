#!/bin/sh
# Reproducible end-to-end demo: engine labels, then the same analysis inside
# headless Vim, printing the properties Vim actually applied.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "### 1. neural engine, no editor"
python3 "$ROOT/scripts/demo.py"

echo
echo "### 2. same analysis inside Vim (headless), showing applied properties"
cat > /tmp/flowlens_show.c <<'CEOF'
int demo(int input, int ignored) {
    int x = input + 1;
    int saved = x;
    x = 0;
    int unrelated = ignored * 2;
    int result = saved * 3;
    return result;
}
CEOF

cat > /tmp/flowlens_show.vim <<VIMEOF
set nocompatible
set rtp+=$ROOT/vim
runtime! plugin/flowlens.vim
syntax off
edit /tmp/flowlens_show.c
call cursor(3, 17)
Flow downstream
let n = 0
while n < 600 && empty(flowlens#timing())
  sleep 5m
  let n += 1
endwhile
let out = []
call add(out, '  :Flow downstream   (cursor on the x in "int saved = x;")')
call add(out, '')
for l in range(1, line('$'))
  let txt = getline(l)
  let marks = []
  for p in prop_list(l)
    if p.type ==# 'FlowLensDim'
      continue
    endif
    let mark = p.type ==# 'FlowLensSelected' ? 'selected' : 'flow'
    call add(marks, printf('%s[%d..%d)=%s', mark, p.col - 1, p.col - 1 + p.length,
          \ strpart(txt, p.col - 1, p.length)))
  endfor
  call add(out, printf('  %-56s %s', txt, join(marks, ' ')))
endfor
let t = flowlens#timing()
call add(out, '')
call add(out, printf('  encode %.2f ms  infer %.2f ms  render %.2f ms  end-to-end %.2f ms  tokens %d  MACs %d',
      \ get(t,'encode_ms',0), get(t,'infer_ms',0), get(t,'render_ms',0),
      \ get(t,'end_to_end_ms',0), get(t,'tokens',0), get(t,'macs',0)))
Flow clear
call writefile(out, '/tmp/flowlens_show.txt')
qa!
VIMEOF

vim -Nu NONE -n -es -S /tmp/flowlens_show.vim >/dev/null 2>&1 || true
cat /tmp/flowlens_show.txt

echo
echo "### 3. the same command with the cursor on the return expression"
cat > /tmp/flowlens_show2.vim <<VIMEOF
set nocompatible
set rtp+=$ROOT/vim
runtime! plugin/flowlens.vim
syntax off
edit /tmp/flowlens_show.c
call cursor(7, 13)
Flow upstream
let n = 0
while n < 600 && empty(flowlens#timing())
  sleep 5m
  let n += 1
endwhile
let out = []
call add(out, '  :Flow upstream   (cursor on "result" in the return)')
call add(out, '')
for l in range(1, line('$'))
  let marks = []
  for p in prop_list(l)
    if p.type ==# 'FlowLensDim'
      continue
    endif
    call add(marks, printf('%s=%s', p.type ==# 'FlowLensSelected' ? 'selected' : 'flow',
          \ strpart(getline(l), p.col - 1, p.length)))
  endfor
  call add(out, printf('  %-46s %s', getline(l), join(marks, ' ')))
endfor
Flow clear
call writefile(out, '/tmp/flowlens_show2.txt')
qa!
VIMEOF

vim -Nu NONE -n -es -S /tmp/flowlens_show2.vim >/dev/null 2>&1 || true
cat /tmp/flowlens_show2.txt
