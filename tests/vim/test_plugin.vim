" FlowLens editor integration tests.  Runs unchanged in Vim and Neovim.
" Requires flowlens#marks(), which both backends implement.

let s:report = []

function! s:wait(bnr, ms) abort
  let n = 0
  call setbufvar(a:bnr, 'flowlens_timing', {})
  while n < a:ms
    sleep 5m
    let n += 5
    if !empty(getbufvar(a:bnr, 'flowlens_timing'))
      return 1
    endif
  endwhile
  return 0
endfunction

" backend-agnostic view of what is painted: ['S:text', 'R:text', ...]
function! s:props(bnr) abort
  let out = []
  let lines = getbufline(a:bnr, 1, '$')
  for m in flowlens#marks(a:bnr)
    if m.group ==# 'FlowLensDim'
      continue
    endif
    let txt = strpart(get(lines, m.line - 1, ''), m.col, m.len)
    call add(out, (m.group ==# 'FlowLensSelected' ? 'S:' : 'R:') . txt)
  endfor
  return out
endfunction

function! s:scratchwins() abort
  let n = 0
  for info in getwininfo()
    if !empty(getbufvar(info.bufnr, 'flowlens_scratch'))
      let n += 1
    endif
  endfor
  return n
endfunction

function! s:check(name, ok, detail) abort
  call add(s:report, {'check': a:name, 'ok': a:ok ? 1 : 0, 'detail': a:detail})
endfunction

" ---- 1. downstream on the canonical example
edit /tmp/flowlens_demo.c
call cursor(3, 17)
Flow downstream
let ok = s:wait(bufnr('%'), 4000)
let got = s:props(bufnr('%'))
call s:check('downstream-runs', ok, string(got))
call s:check('downstream-labels',
      \ got == ['R:x', 'R:saved', 'S:x', 'R:result', 'R:saved', 'R:result'],
      \ string(got))

" ---- 2. clear removes everything
Flow clear
call s:check('clear', empty(s:props(bufnr('%'))), string(s:props(bufnr('%')))) 

" ---- 3. upstream
call cursor(7, 13)
Flow upstream
let ok = s:wait(bufnr('%'), 4000)
let got = s:props(bufnr('%'))
call s:check('upstream-labels',
      \ index(got, 'S:result') >= 0 && index(got, 'R:saved') >= 0
      \ && index(got, 'R:x') >= 0 && index(got, 'R:input') >= 0, string(got))
Flow clear

" ---- 4. stale response is dropped: request, then edit before it lands
call cursor(3, 17)
Flow downstream
call setline(1, getline(1) . ' ')
let immediate = len(s:props(bufnr('%')))
sleep 250m
let later = len(s:props(bufnr('%')))
call s:check('stale-rejected', immediate == 0 && later == 0,
      \ 'immediate=' . immediate . ' later=' . later)

" ---- 5. unsaved edits are analysed (no file write)
edit! /tmp/flowlens_demo.c
call append(3, '    int extra = saved + 7;')
call cursor(4, 17)
Flow downstream
let ok = s:wait(bufnr('%'), 4000)
let got = s:props(bufnr('%'))
call s:check('unsaved-edits', index(got, 'R:extra') >= 0, string(got))
Flow clear

" ---- 6. every identifier occurrence of one program, both modes:
" exactly one selected mark, and it is the word under the cursor.
let KW = ["int", "char", "long", "short", "float", "double", "unsigned", "void", "signed", "static", "const", "return"]
edit! /tmp/flowlens_demo.c
let bad = []
let seen = 0
for l in range(1, line("$"))
  let txt = getline(l)
  let i = 0
  let n = strlen(txt)
  while i < n
    if txt[i] =~# "[A-Za-z_]" && (i == 0 || txt[i - 1] !~# "[A-Za-z0-9_]")
      let w = matchstr(strpart(txt, i), "^[A-Za-z0-9_]*")
      if index(KW, w) < 0
        for mode in ["downstream", "upstream"]
          call cursor(l, i + 1)
          execute "Flow " . mode
          call s:wait(bufnr("%"), 4000)
          let marks = s:props(bufnr("%"))
          let sel = filter(copy(marks), "v:val =~# '^S:'")
          let seen += 1
          if len(sel) != 1 || sel[0] !=# ("S:" . w)
            call add(bad, printf("%d:%d %s %s -> %s", l, i + 1, mode, w, string(marks)))
          endif
        endfor
      endif
      let i += strlen(w)
      continue
    endif
    let i += 1
  endwhile
endfor
call s:check("every-occurrence-selected", empty(bad), printf("checked=%d bad=%s", seen, string(bad[0:2])))
Flow clear

" ---- 7. inspect opens a trace buffer
edit! /tmp/flowlens_demo.c
call cursor(3, 17)
Flow inspect
let ok = s:wait(bufnr('%'), 4000)
sleep 50m
let found = 0
for b in range(1, bufnr('$'))
  if bufexists(b) && getbufvar(b, '&filetype') ==# 'flowlensinspect'
    let found = len(getbufline(b, 1, '$'))
  endif
endfor
call s:check('inspect-buffer', found > 4, string(found))
Flow clear

" ---- 8. info shows the subset and the backend
Flow info
let ln = 0
let backend = ''
for b in range(1, bufnr('$'))
  if bufexists(b) && getbufvar(b, '&filetype') ==# 'flowlensinfo'
    let ln = len(getbufline(b, 1, '$'))
    let backend = getbufline(b, 4)[0]
  endif
endfor
call s:check('info-buffer', ln > 8, string(ln) . ' ' . backend)

" ---- 9/10. inspect reuses one scratch window; close removes it
edit! /tmp/flowlens_demo.c
let cb = bufnr('%')
call cursor(3, 17)
Flow inspect
call s:wait(cb, 4000)
Flow inspect
call s:wait(cb, 4000)
let n = s:scratchwins()
call s:check('inspect-single-window', n == 1, 'windows=' . n)
Flow close
let n2 = s:scratchwins()
call s:check('close-scratch', n2 == 0, 'windows=' . n2)

" ---- 11. stop kills the helper; the next request restarts it
Flow downstream
call s:wait(cb, 4000)
Flow stop
let after = len(s:props(cb))
Flow downstream
let ok = s:wait(cb, 4000)
call s:check('stop-then-restart', after == 0 && ok && !empty(s:props(cb)),
      \ 'after_stop=' . after . ' after_restart=' . len(s:props(cb)))
Flow clear

" ---- 12. bare :Flow lists the commands
Flow
let hln = 0
let husage = 0
for b in range(1, bufnr('$'))
  if bufexists(b) && getbufvar(b, '&filetype') ==# 'flowlenshelp'
    let hln = len(getbufline(b, 1, '$'))
    let husage = match(getbufline(b, 1, '$'), 'USAGE') >= 0 ? 1 : 0
  endif
endfor
call s:check('help-buffer', hln > 8 && husage, 'lines=' . hln . ' usage=' . husage)
Flow close

" ---- 13. a range selects which occurrence is analysed
edit! /tmp/flowlens_demo.c
let cb = bufnr('%')
call cursor(3, 17)
3,3Flow downstream
let ok = s:wait(cb, 4000)
let got = s:props(cb)
call s:check('range-selects-occurrence', ok && !empty(got), string(got))
Flow clear

call writefile([json_encode({'editor': has('nvim') ? 'neovim' : 'vim',
      \ 'checks': s:report})], '/tmp/flowlens_editor_tests.json')
qa!
