" Hands-free walkthrough for screen capture.  Each step waits for the previous
" analysis to land, then pauses so the result is readable on video.
"
"   sh scripts/demo_video.sh --scripted
"
" Steps: downstream on `mean` -> clear -> upstream on `result` -> :Flow marks
"        in a split -> :Flow info.
set nocompatible
let s:root = expand('<sfile>:p:h:h')
execute 'edit ' . s:root . '/examples/loop_kernel.c'
call cursor(7, 9)

function! s:settle(ms) abort
  " wait until the helper has answered, then hold the frame
  let i = 0
  while i < 400
    let t = get(b:, 'flowlens_timing', {})
    if type(t) == v:t_dict && !empty(t) && get(t, 'end_to_end_ms', 0) > 0
      break
    endif
    execute 'sleep 20m'
    let i += 1
  endwhile
  execute 'sleep ' . a:ms . 'm'
  redraw
endfunction

Flow downstream
call s:settle(2600)

Flow clear
call s:settle(900)

call cursor(21, 12)
Flow upstream
call s:settle(2600)

" show the receipt: exactly which spans are painted
Flow marks
call s:settle(3200)

" and the machine-readable subset/limits panel
Flow info
call s:settle(3200)

" leave it on the highlighted buffer, not the trace windows
Flow close
call cursor(7, 9)
Flow downstream
call s:settle(6000)
