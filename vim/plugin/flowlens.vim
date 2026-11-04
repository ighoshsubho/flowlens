" FlowLens.vim - neural information-flow highlighting.
"
" Works in Vim 8.1+ (+job +channel +textprop) and in Neovim 0.5+ (extmarks +
" jobstart/chansend).  Only the editor glue differs; the analysis is the same
" Python engine and the same frozen weights.
"
" Commands:
"   :Flow downstream   information derived from the occurrence under the cursor
"   :Flow upstream     the values that occurrence depends on
"   :Flow clear        remove all FlowLens highlights
"   :Flow inspect      open a scratch buffer with the network trace
"   :Flow info         supported subset, limits and measured timings
"   :Flow marks        exactly what is painted right now
"   :Flow close        close the scratch window(s)
"   :Flow stop         close them, clear marks, stop the helper

if exists('g:loaded_flowlens')
  finish
endif
let g:loaded_flowlens = 1

let s:nvim = has('nvim')
let s:ok = s:nvim ? has('nvim-0.5') : (has('job') && has('channel') && has('textprop'))

if !s:ok
  " Explain the failure instead of letting :Flow be an unknown command.
  function! s:unsupported(arg) abort
    echohl WarningMsg
    echomsg 'FlowLens needs Vim 8.1+ with +textprop/+job/+channel, '
          \ . 'or Neovim 0.5+.'
    echohl None
  endfunction
  command! -nargs=* Flow call s:unsupported(<q-args>)
  finish
endif

" repo root: this file lives in <root>/vim/plugin/
let s:root = fnamemodify(resolve(expand('<sfile>:p')), ':h:h:h')

if !exists('g:flowlens_python')
  let g:flowlens_python = 'python3'
endif
if !exists('g:flowlens_root')
  let g:flowlens_root = s:root
endif
if !exists('g:flowlens_dim')
  let g:flowlens_dim = 1
endif
if !exists('g:flowlens_colors')
  let g:flowlens_colors = {}
endif

command! -nargs=* -range -complete=customlist,flowlens#complete Flow
      \ call flowlens#command(<q-args>, <line1>, <line2>, <range>)

augroup flowlens
  autocmd!
  autocmd BufWipeout * call flowlens#on_wipe(str2nr(expand('<abuf>')))
augroup END

highlight default FlowLensSelected ctermbg=24 ctermfg=231 guibg=#1f6feb
      \ guifg=#ffffff gui=bold
highlight default FlowLensRelevant ctermbg=22 ctermfg=231 guibg=#2ea043
      \ guifg=#ffffff
highlight default FlowLensDim ctermfg=242 guifg=#6e7681
