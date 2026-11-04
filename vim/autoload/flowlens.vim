" FlowLens autoload: request lifecycle, staleness rejection, rendering.
" One code path; two rendering backends (Vim text properties, Neovim extmarks).

let s:nvim = has('nvim')
let s:job = v:null
let s:next_id = 0
let s:req = {}
let s:timing = {}
let s:acc = ''
let s:cold_ms = 0.0
let s:stats = {}
let g:flowlens_debug = get(g:, 'flowlens_debug', 0)

if s:nvim
  let s:ns = nvim_create_namespace('flowlens')
else
  let s:ns = -1
endif

function! s:dbg(msg) abort
  if g:flowlens_debug
    call writefile([strftime('%H:%M:%S') . ' ' . a:msg],
          \ '/tmp/flowlens_plugin.log', 'a')
  endif
endfunction

function! flowlens#complete(arglead, cmdline, cursorpos) abort
  return filter(['downstream', 'upstream', 'clear', 'inspect', 'info',
        \ 'marks', 'close', 'stop', 'help'], 'stridx(v:val, a:arglead) == 0')
endfunction

function! flowlens#command(arg, ...) abort
  let l1 = a:0 >= 3 ? a:1 : 0
  let l2 = a:0 >= 3 ? a:2 : 0
  let ranged = a:0 >= 3 ? a:3 : 0
  let a = tolower(a:arg)
  if a ==# '' || a ==# 'help'
    call flowlens#help()
  elseif a ==# 'clear'
    call flowlens#clear()
  elseif a ==# 'close'
    call flowlens#close()
  elseif a ==# 'stop'
    call flowlens#stop()
  elseif a ==# 'marks'
    call flowlens#marks_report()
  elseif a ==# 'inspect'
    call flowlens#run('downstream', 1, l1, l2, ranged)
  elseif a ==# 'info'
    call flowlens#info()
  elseif a ==# 'downstream' || a ==# 'upstream'
    call flowlens#run(a, 0, l1, l2, ranged)
  else
    echohl ErrorMsg
    echomsg 'FlowLens: unknown mode "' . a:arg
          \ . '" — try :Flow for the command list'
    echohl None
  endif
endfunction

" ---------------------------------------------------------------- process
function! s:alive() abort
  if s:job is v:null
    return 0
  endif
  if s:nvim
    return jobwait([s:job], 0)[0] == -1
  endif
  return job_status(s:job) ==# 'run'
endfunction

function! s:ensure() abort
  if s:alive()
    return 1
  endif
  let helper = g:flowlens_root . '/engine/helper.py'
  if !filereadable(helper)
    echohl ErrorMsg
    echomsg 'FlowLens: helper not found at ' . helper
          \ . ' (set g:flowlens_root to the FlowLens checkout)'
    echohl None
    return 0
  endif
  let cmd = [g:flowlens_python, '-u', helper]
  if s:nvim
    let s:acc = ''
    let s:job = jobstart(cmd, {'stdout_buffered': 0,
          \ 'on_stdout': function('s:nvim_out'),
          \ 'on_stderr': function('s:nvim_err')})
    if s:job <= 0
      echohl ErrorMsg
      echomsg 'FlowLens: could not start helper (' . string(cmd) . ')'
      echohl None
      let s:job = v:null
      return 0
    endif
    return 1
  endif
  let s:job = job_start(cmd, {'in_mode': 'nl', 'out_mode': 'nl',
        \ 'err_io': 'null', 'stoponexit': 'kill',
        \ 'out_cb': function('s:on_out')})
  if job_status(s:job) !=# 'run'
    echohl ErrorMsg
    echomsg 'FlowLens: could not start helper (' . string(cmd) . ')'
    echohl None
    let s:job = v:null
    return 0
  endif
  return 1
endfunction

function! s:nvim_err(job, data, event) abort
  call s:dbg('stderr: ' . join(a:data, ' '))
endfunction

" Neovim delivers chunks, not lines: reassemble before parsing.
function! s:nvim_out(job, data, event) abort
  let s:acc .= join(a:data, "\n")
  while stridx(s:acc, "\n") >= 0
    let i = stridx(s:acc, "\n")
    let line = strpart(s:acc, 0, i)
    let s:acc = strpart(s:acc, i + 1)
    if !empty(line)
      call s:on_out(a:job, line)
    endif
  endwhile
endfunction

function! s:send(payload) abort
  if s:nvim
    call chansend(s:job, a:payload . "\n")
  else
    call ch_sendraw(s:job, a:payload . "\n")
  endif
endfunction

function! flowlens#on_wipe(bufnr) abort
  if has_key(s:req, a:bufnr)
    call remove(s:req, a:bufnr)
  endif
endfunction

" ---------------------------------------------------------------- request
function! s:line_offsets(lines) abort
  let offs = [0]
  let acc = 0
  for l in a:lines
    let acc += strlen(l) + 1
    call add(offs, acc)
  endfor
  return offs
endfunction

" A range (visual selection, or :N,M Flow) only decides *which* occurrence is
" analysed: FlowLens labels one occurrence at a time.  The cursor position
" inside the range wins, which is what a visual selection means in Vim (the
" cursor stays on the selected text).  If the cursor is outside the range, the
" first non-blank character of the range is used.
function! s:range_cursor(l1, l2) abort
  let offs = s:line_offsets(getline(1, '$'))
  let pos = getcurpos()
  if pos[1] >= a:l1 && pos[1] <= a:l2
    return offs[pos[1] - 1] + (pos[2] - 1)
  endif
  let col = match(getline(a:l1), '\S')
  return offs[a:l1 - 1] + (col >= 0 ? col : 0)
endfunction

function! flowlens#run(mode, inspect, ...) abort
  if !s:ensure()
    return
  endif
  let bufnr = bufnr('%')
  let lines = getline(1, '$')
  let text = join(lines, "\n")
  let offs = s:line_offsets(lines)
  if a:0 >= 3 && a:3 != 0
    let cursor = s:range_cursor(a:1, a:2)
  else
    let pos = getcurpos()
    let cursor = offs[pos[1] - 1] + (pos[2] - 1)
  endif
  let s:next_id += 1
  let tick = b:changedtick
  let req = {'id': s:next_id, 'tick': tick, 'text': text, 'cursor': cursor,
        \ 'mode': a:mode, 'inspect': a:inspect ? v:true : v:false}
  let s:req[bufnr] = {'id': s:next_id, 'tick': tick, 'mode': a:mode,
        \ 'inspect': a:inspect, 't0': reltime()}
  let b:flowlens_mode = a:mode
  call s:send(json_encode(req))
endfunction

function! s:on_out(ch, msg) abort
  call s:dbg('out: ' . strpart(a:msg, 0, 100))
  try
    let r = json_decode(a:msg)
  catch
    return
  endtry
  if type(r) != v:t_dict
    return
  endif
  if has_key(r, 'hello')
    let s:cold_ms = get(r, 'cold_ms', 0.0)
    let s:stats = get(r, 'stats', {})
    return
  endif
  if !has_key(r, 'id')
    return
  endif
  let bufnr = -1
  for [bnr, q] in items(s:req)
    if q.id == r.id
      let bufnr = str2nr(bnr)
      break
    endif
  endfor
  if bufnr < 0 || !bufexists(bufnr)
    return
  endif
  let q = s:req[bufnr]
  " reject stale responses: the buffer changed since the request went out
  if getbufvar(bufnr, 'changedtick') != q.tick
    call s:dbg('stale: ' . getbufvar(bufnr, 'changedtick') . ' vs ' . q.tick)
    return
  endif
  if !get(r, 'ok', 0)
    echohl WarningMsg
    echomsg 'FlowLens: ' . get(r, 'error', 'failure')
    echohl None
    return
  endif
  call remove(s:req, bufnr)
  let stats = get(r, 'stats', {})
  if q.inspect
    call s:open_inspect(r, bufnr)
  endif
  let render_ms = s:render(bufnr, get(r, 'ranges', []))
  let timings = get(r, 'timings', {})
  let s:timing = {
        \ 'encode_ms': get(timings, 'encode_ms', 0.0),
        \ 'infer_ms': get(timings, 'infer_ms', 0.0),
        \ 'helper_ms': get(timings, 'total_ms', 0.0),
        \ 'render_ms': render_ms,
        \ 'end_to_end_ms': reltimefloat(reltime(q.t0)) * 1000.0,
        \ 'tokens': get(stats, 'tokens', 0),
        \ 'anomalies': get(stats, 'anomalies', 0),
        \ 'relevant_tokens': get(stats, 'relevant_tokens', 0),
        \ 'macs': get(stats, 'macs', 0),
        \ 'op_count': get(stats, 'op_count', 0),
        \ 'editor': s:nvim ? 'neovim' : 'vim',
        \ 'mode': q.mode,
        \ }
  call setbufvar(bufnr, 'flowlens_timing', s:timing)
  if get(stats, 'anomalies', 0) > 0
    echohl WarningMsg
    echomsg printf('FlowLens: %d token(s) outside the supported subset - '
          \ . 'highlights may be incomplete', stats.anomalies)
    echohl None
  endif
  if get(stats, 'selected_value', 0) == 0
    echomsg 'FlowLens: selected occurrence carries no value'
          \ . ' (function name, type keyword or unsupported position)'
  endif
endfunction

" ---------------------------------------------------------------- render
function! s:painter(bufnr) abort
  if s:nvim
    return
  endif
  let names = ['FlowLensSelected', 'FlowLensRelevant', 'FlowLensDim']
  for name in names
    if empty(prop_type_get(name, {'bufnr': a:bufnr}))
      call prop_type_add(name, {'bufnr': a:bufnr, 'highlight': name, 'priority': 20})
    endif
  endfor
endfunction

function! s:clear_marks(bufnr) abort
  if s:nvim
    call nvim_buf_clear_namespace(a:bufnr, s:ns, 0, -1)
  else
    for name in ['FlowLensSelected', 'FlowLensRelevant', 'FlowLensDim']
      call prop_remove({'type': name, 'bufnr': a:bufnr, 'all': 1})
    endfor
  endif
endfunction

function! s:paint(bufnr, lnum, col0, len, kind) abort
  if a:len <= 0
    return
  endif
  let group = a:kind ==# 'selected' ? 'FlowLensSelected'
        \ : a:kind ==# 'relevant' ? 'FlowLensRelevant' : 'FlowLensDim'
  if s:nvim
    call nvim_buf_set_extmark(a:bufnr, s:ns, a:lnum - 1, a:col0,
          \ {'end_col': a:col0 + a:len, 'hl_group': group, 'priority': 20})
  else
    call prop_add(a:lnum, a:col0 + 1,
          \ {'length': a:len, 'type': group, 'bufnr': a:bufnr})
  endif
endfunction

function! flowlens#clear() abort
  let s:req = {}
  call s:clear_marks(bufnr('%'))
  unlet! b:flowlens_mode
  echomsg 'FlowLens: cleared'
endfunction

" Apply byte ranges.  Labels are only coalesced into display runs here; no
" range is ever invented.
function! s:render(bufnr, ranges) abort
  if !bufloaded(a:bufnr) || a:bufnr != bufnr('%')
    return 0.0
  endif
  let t0 = reltime()
  call s:painter(a:bufnr)
  call s:clear_marks(a:bufnr)
  let lines = getline(1, '$')
  let offs = s:line_offsets(lines)
  let nlines = len(lines)
  for [s, e, lab] in a:ranges
    let kind = lab == 2 ? 'selected' : 'relevant'
    let ln = 0
    while ln < nlines && offs[ln + 1] <= s
      let ln += 1
    endwhile
    let cur = s
    while cur < e && ln < nlines
      let cstart = offs[ln]
      let cend = offs[ln] + strlen(lines[ln])
      let seg_s = cur
      let seg_e = min([e, cend])
      if seg_e > seg_s
        call s:paint(a:bufnr, ln + 1, seg_s - cstart, seg_e - seg_s, kind)
      endif
      let cur = cend + 1
      let ln += 1
    endwhile
  endfor
  if g:flowlens_dim
    let flat = join(lines, "\n")
    let n = strlen(flat)
    let covered = repeat([0], n + 1)
    for [s, e, lab] in a:ranges
      let i = s
      while i < e
        let covered[i] = 1
        let i += 1
      endwhile
    endfor
    let i = 0
    while i < n
      if covered[i] || flat[i] =~# '\s'
        let i += 1
        continue
      endif
      let j = i
      while j < n && !covered[j] && flat[j] !~# '\s'
        let j += 1
      endwhile
      let ln = 0
      while ln < nlines && offs[ln + 1] <= i
        let ln += 1
      endwhile
      if ln < nlines
        let cstart = offs[ln]
        let cend = offs[ln] + strlen(lines[ln])
        if i < cend
          call s:paint(a:bufnr, ln + 1, i - cstart,
                \ min([j, cend]) - i, 'dim')
        endif
      endif
      let i = j
    endwhile
  endif
  redraw
  return reltimefloat(reltime(t0)) * 1000.0
endfunction

" Backend-agnostic dump of what is painted in a buffer (used by the tests).
function! flowlens#marks(bufnr) abort
  let out = []
  if !bufexists(a:bufnr)
    return out
  endif
  if s:nvim
    let raw = nvim_buf_get_extmarks(a:bufnr, s:ns, 0, -1, {'details': 1})
    for m in raw
      let row = m[1]
      let col = m[2]
      let det = m[3]
      let endc = get(det, 'end_col', col + 1)
      call add(out, {'line': row + 1, 'col': col, 'len': endc - col,
            \ 'group': get(det, 'hl_group', '')})
    endfor
  else
    for l in range(1, getbufinfo(a:bufnr)[0].linecount)
      for p in prop_list(l, {'bufnr': a:bufnr})
        call add(out, {'line': l, 'col': p.col - 1, 'len': p.length,
              \ 'group': p.type})
      endfor
    endfor
  endif
  return out
endfunction

" Print exactly what FlowLens painted, so a highlight can never be a mystery.
function! flowlens#marks_report() abort
  let bnr = bufnr('%')
  let lines = getline(1, '$')
  let marks = flowlens#marks(bnr)
  let sel = []
  let rel = []
  let dim = 0
  for m in marks
    let txt = strpart(get(lines, m.line - 1, ''), m.col, m.len)
    if m.group ==# 'FlowLensSelected'
      call add(sel, printf('%4d:%-3d %s', m.line, m.col + 1, txt))
    elseif m.group ==# 'FlowLensRelevant'
      call add(rel, printf('%4d:%-3d %s', m.line, m.col + 1, txt))
    else
      let dim += 1
    endif
  endfor
  let out = ['FlowLens marks in this buffer', '']
  call add(out, 'selected (bg blue): ' . len(sel))
  call extend(out, map(copy(sel), '"    " . v:val'))
  call add(out, '')
  call add(out, 'relevant (bg green): ' . len(rel))
  call extend(out, map(copy(rel), '"    " . v:val'))
  call add(out, '')
  call add(out, 'dim runs (grey fg): ' . dim
        \ . '   [disable with: let g:flowlens_dim = 0]')
  call add(out, '')
  call add(out, 'Only identifier tokens are ever selected or relevant.')
  call add(out, 'Type keywords (int/char/...), operators, literals and comments')
  call add(out, 'are never painted unless a dim run covers them.')
  call s:scratch(out, 'flowlensmarks')
endfunction

" ---------------------------------------------------------------- inspect
function! s:open_inspect(r, bufnr) abort
  let insp = get(a:r, 'inspect', {})
  let lim = get(insp, 'limits', {})
  let lines = []
  call add(lines, 'FlowLens inspect - ' . get(insp, 'tokens', 0) . ' tokens, '
        \ . get(insp, 'n_def', 0) . ' definitions, '
        \ . get(insp, 'n_ret', 0) . ' return sinks')
  call add(lines, 'selected token #' . get(insp, 'selected_token', -1)
        \ . ' -> value node #' . get(insp, 'selected_value', -1))
  call add(lines, 'anomalies: ' . get(insp, 'anomalies', 0)
        \ . '   MACs: ' . get(insp, 'macs', 0)
        \ . '   tensor ops: ' . get(insp, 'op_count', 0))
  call add(lines, 'limits: '
        \ . join(map(items(lim), 'v:val[0]."=".v:val[1]'), ' '))
  call add(lines, '')
  call add(lines, 'token  span         role  slot  text')
  let src = join(getline(1, '$'), "\n")
  for sp in get(insp, 'spans', [])
    call add(lines, printf('%5d  [%4d,%4d)  %s   %3d   %s', sp.tok, sp.start,
          \ sp.end, sp.role == 1 ? 'read' : sp.role == 2 ? 'def ' : '    ',
          \ sp.slot, strpart(src, sp.start, sp.end - sp.start)))
  endfor
  call add(lines, '')
  call add(lines, 'role: 1=read 2=definition anchor; slot = identifier memory slot')
  call s:scratch(lines, 'flowlensinspect')
endfunction

function! s:scratch(lines, ft) abort
  let win = 0
  for w in range(1, winnr('$'))
    if !empty(getbufvar(winbufnr(w), 'flowlens_scratch'))
      let win = w
      break
    endif
  endfor
  if win > 0
    execute win . 'wincmd w'
  else
    belowright new
  endif
  setlocal buftype=nofile bufhidden=wipe noswapfile nobuflisted
  setlocal modifiable
  silent %delete _
  call setline(1, a:lines)
  setlocal nomodifiable
  let &l:filetype = a:ft
  let b:flowlens_scratch = 1
endfunction

" Close every FlowLens scratch window (the :Flow inspect / :Flow info splits).
function! flowlens#close() abort
  let ids = []
  for info in getwininfo()
    if !empty(getbufvar(info.bufnr, 'flowlens_scratch'))
      call add(ids, info.winid)
    endif
  endfor
  let n = 0
  for id in ids
    if winnr('$') <= 1
      break
    endif
    call win_gotoid(id)
    close
    let n += 1
  endfor
  echomsg 'FlowLens: closed ' . n . ' scratch window(s)'
  return n
endfunction

" Stop everything: scratch windows, highlights and the helper process.
function! flowlens#stop() abort
  call flowlens#close()
  call s:clear_marks(bufnr('%'))
  unlet! b:flowlens_mode
  if s:alive()
    if s:nvim
      call jobstop(s:job)
    else
      call job_stop(s:job, 'kill')
    endif
  endif
  let s:job = v:null
  let s:req = {}
  echomsg 'FlowLens: highlights cleared, helper stopped'
endfunction

" ---------------------------------------------------------------- help
function! flowlens#help() abort
  let lines = [
        \ 'FlowLens - neural information flow from raw C bytes',
        \ '',
        \ 'USAGE',
        \ '  :Flow downstream      what the occurrence under the cursor feeds',
        \ '  :Flow upstream        what that occurrence was built from',
        \ '  :Flow clear           remove every FlowLens highlight',
        \ '  :Flow marks           list every painted span (line:col, group, text)',
        \ '  :Flow inspect         scratch buffer with the per-token trace',
        \ '  :Flow info            supported subset, limits, measured timings',
        \ '  :Flow close           close the scratch window, keep highlights',
        \ '  :Flow stop            close, clear, stop the helper',
        \ '  :Flow                 this list (also  :Flow help)',
        \ '',
        \ 'WHICH OCCURRENCE',
        \ '  Put the cursor on an identifier and run downstream or upstream.',
        \ '  On a definition you get everything derived from that value; on a',
        \ '  read you get what the value it consumed flows into.  Selecting an',
        \ '  identifier and running :Flow is occurrence-level: the later',
        \ '  "x = 0" is a different occurrence from "int x = ...".',
        \ '',
        \ 'VISUAL SELECTION',
        \ '  Select a line or a word, press : then type  Flow downstream',
        \ "  (Vim inserts '<,'> for you).  The occurrence analysed is the",
        \ '  first identifier inside the selection.',
        \ '',
        \ '  Tab completion works:  :Flow <Tab>',
        \ '',
        \ 'OPTIONS  (set before the plugin loads, or with :let)',
        \ '  g:flowlens_dim     0 to leave unrelated text at normal colour',
        \ '  g:flowlens_root    path to this checkout',
        \ '  g:flowlens_python  interpreter with numpy',
        \ '  g:flowlens_colors  override the three highlight groups',
        \ '',
        \ 'Printed spans use FlowLensSelected / FlowLensRelevant / FlowLensDim;',
        \ 'restyle them with :highlight if the defaults are hard to see.',
        \ ]
  call s:scratch(lines, 'flowlenshelp')
endfunction

" ---------------------------------------------------------------- info
function! flowlens#info() abort
  let t = get(b:, 'flowlens_timing', s:timing)
  let lines = [
        \ 'FlowLens - neural information flow from raw C bytes',
        \ '',
        \ 'Editor backend: ' . (s:nvim ? 'Neovim extmarks' : 'Vim text properties'),
        \ '',
        \ 'Supported subset (anything else is reported as an anomaly):',
        \ '  one or more functions: TYPE NAME(params) { statements }',
        \ '  parameters and locals of type int/char/long/short/float/double',
        \ '  declarations with and without initialisation',
        \ '  assignment, including x = x + 1 style self-reference',
        \ '  expressions over identifiers and integer literals with + - * / % ( )',
        \ '  if / else, while, for and do-while, braced or single-statement,',
        \ '    with a merge node at every block exit and loop-carried edges',
        \ '  return expressions; // and /* */ comments; string and char literals',
        \ 'Not modelled (flagged): pointers, arrays, structs, calls, macros,',
        \ '  casts, ternaries, shadowing, nested single-statement bodies,',
        \ '  and control dependence (implicit flow)',
        \ '',
        \ 'Limits: 2048 bytes, 512 tokens, 16 identifier chars, 48 slots,',
        \ '        192 value nodes, 8 nested blocks, 8 hops.',
        \ '',
        \ 'Weights: ' . get(s:stats, 'params_dense', 0) . ' dense params, '
        \ . 'cold start ' . printf('%.1f', s:cold_ms) . ' ms',
        \ '',
        \ 'Last run: ' . (empty(t) ? 'none' :
        \ printf('%s  encode %.2f ms  infer %.2f ms  render %.2f ms  e2e %.2f ms  tokens %d  MACs %d',
        \ get(t, 'mode', '?'), get(t, 'encode_ms', 0.0), get(t, 'infer_ms', 0.0),
        \ get(t, 'render_ms', 0.0), get(t, 'end_to_end_ms', 0.0),
        \ get(t, 'tokens', 0), get(t, 'macs', 0))),
        \ '',
        \ 'This is a bounded-subset analysis, not verified general C dataflow.',
        \ ]
  call s:scratch(lines, 'flowlensinfo')
endfunction

function! flowlens#timing() abort
  return get(b:, 'flowlens_timing', {})
endfunction
