" Headless Vim measurement: end-to-end latency from :Flow to properties
" applied, plus the render time the plugin itself reports.
let s:root = expand('<sfile>:p:h:h')
let s:res = []
let s:files = ['bench_chain_10.c', 'bench_chain_25.c', 'bench_chain_43.c', 'bench_loop_10.c', 'bench_loop_35.c']

call prop_type_add('probe', {'highlight': 'FlowLensRelevant'})

function! s:wait(bufnr, maxticks) abort
  let i = 0
  while i < a:maxticks
    sleep 2m
    let t = getbufvar(a:bufnr, 'flowlens_timing')
    if type(t) == v:t_dict && !empty(t) && get(t, 'end_to_end_ms', 0) > 0
      return get(t, 'end_to_end_ms', 0)
    endif
    let i += 1
  endwhile
  return -1
endfunction

for f in s:files
  execute 'edit ' . s:root . '/bench/corpus/' . f
  call cursor(2, 9)
  call setbufvar(bufnr('%'), 'flowlens_timing', {})
  let req_t = reltime()
  Flow downstream
  let got = s:wait(bufnr('%'), 500)
  let wall = reltimefloat(reltime(req_t)) * 1000.0
  let t = getbufvar(bufnr('%'), 'flowlens_timing')
  let nprops = 0
  for l in range(1, line('$'))
    let nprops += len(prop_list(l))
  endfor
  call add(s:res, {'file': f, 'lines': line('$'), 'bytes': line2byte(line('$')),
        \ 'e2e_ms': got, 'wall_ms': wall,
        \ 'render_ms': get(t, 'render_ms', 0.0),
        \ 'encode_ms': get(t, 'encode_ms', 0.0),
        \ 'infer_ms': get(t, 'infer_ms', 0.0),
        \ 'helper_ms': get(t, 'helper_ms', 0.0),
        \ 'props': nprops, 'tokens': get(t, 'tokens', 0)})
  Flow clear
endfor

call writefile([json_encode({'runs': s:res})], '/tmp/flowlens_vim_bench.json')
qa!
