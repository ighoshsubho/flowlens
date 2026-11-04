# FlowLens.vim

Neural information-flow highlighting for **Vim and Neovim**, computed from raw
C bytes by a recurrent network with hand-written weights.

Select an identifier occurrence, run `:Flow downstream`, and every value
derived from it lights up: definitions, copies, arithmetic consumers and the
return expression. `:Flow upstream` shows where the value came from.

```
int demo(int input, int ignored) {
    int {x} = input + 1;          <- the definition of the selected value
    int {saved} = [x];            <- [x] is the occurrence under the cursor
    x = 0;                        <- a new definition: untouched
    int unrelated = ignored * 2;  <- independent: untouched
    int {result} = {saved} * 3;
    return {result};              <- reaches the return expression
}
```

## The point

There is no C analyser in this repository's inference path. No clang, no
tree-sitter, no regex tokeniser, no symbol table, no AST, no dependency
walker, no LLM. The network reads bytes, classifies them, segments them,
recognises keywords by numeric spelling match, tracks definitions in an
external memory addressed by content, builds a value graph with matrix
algebra and takes a transitive closure with repeated matmul.

All of that behaviour lives in `weights/flowlens_weights.npz` (10,966
bytes, 305,894 numbers). That file was written by a deterministic
construction script with no gradient descent, no search and no pretrained
weights.

* Architecture and equations: `docs/ARCHITECTURE.md`
* Supported grammar and exact non-support: `docs/SEMANTICS.md`
* Measured results: `docs/RESULTS.md`

## Install (macOS)

Requirements: Vim 8.1+ with `+job`, `+channel`, `+textprop` (macOS system Vim
9.1 has all three) **or** Neovim 0.5+; Python 3 with numpy. Nothing else, and no
network access at any point.

```sh
cd /path/to/flowlens
./install.sh    # links into ~/.vim (Vim) and ~/.local/share/nvim/site (Neovim),
                # then self-tests every editor it finds
```

or manually, for either editor:

```sh
echo 'set rtp+=/path/to/flowlens/vim' >> ~/.vimrc        # Vim
echo 'set rtp+=/path/to/flowlens/vim' >> ~/.config/nvim/init.vim   # Neovim
python3 -c 'import numpy' || pip3 install numpy
```

One plugin, two rendering backends: Vim text properties
(`prop_type_add`/`prop_add`) and Neovim extmarks
(`nvim_buf_set_extmark`), with `job_start`+`ch_sendraw` on Vim and
`jobstart`+`chansend` on Neovim. The analysis engine and the frozen weights are
identical; `tests/vim/run.sh` runs the same nine checks against both editors.

`:Flow info` inside Vim shows the supported subset, the limits and the last
run's timings.

## If `:Flow` says "E492: Not an editor command"

Both editors are supported, so this now means the plugin is not in *that*
editor's runtimepath. Reasons, in order of likelihood:

```sh
type vim            # "vim is an alias for nvim" -> you are in Neovim
```

If `vim` is aliased to `nvim` (common on dev machines), then `vim file.c` opens
Neovim, which reads `~/.local/share/nvim/site`, not `~/.vim`. `./install.sh`
links both, but a session started before it ran will not have the command.
Either restart, or load it in place:

```vim
:set rtp+=~/flowlens/vim          " or wherever you cloned it
:runtime! plugin/flowlens.vim
:echo exists(':Flow')      " 2 = defined, 0 = not loaded
:scriptnames               " must list .../plugin/flowlens.vim
```

Other causes: the editor was started with `-u NONE` / `--clean` (skips the
runtimepath), `sudo vim` (different `$HOME`), or a plugin manager that resets
`runtimepath` — then use the explicit `set rtp+=` line above.

## Use

```
:Flow downstream    highlight what the occurrence under the cursor flows into
:Flow upstream      highlight what it was computed from
:Flow clear         remove highlights
:Flow inspect       scratch buffer with the network trace (tokens, slots,
                    value nodes, MACs, limits, cold start)
:Flow info          supported subset, limits and timings
:Flow marks         list exactly what is painted: selected / relevant / dim
:Flow close         close the FlowLens scratch window(s)
:Flow stop          close them, clear highlights and stop the helper process
```

`:Flow inspect` and `:Flow info` reuse a single scratch window, so running them
repeatedly does not stack splits. `:Flow stop` is the full reset; the next
`:Flow downstream` restarts the helper on demand.

Options (set in your vimrc before the plugin loads, or with `:let`):

```vim
let g:flowlens_root   = '/path/to/flowlens'   " if not auto-detected
let g:flowlens_python = 'python3'
let g:flowlens_dim    = 1                     " dim unrelated text
let g:flowlens_colors = {'selected': '...', 'relevant': '...', 'dim': '...'}
let g:flowlens_debug  = 0                     " 1 logs callbacks to /tmp
```

Highlight groups `FlowLensSelected`, `FlowLensRelevant`, `FlowLensDim` are
defined with `highlight default`, so any colorscheme can override them.

The helper is a persistent subprocess started on the first `:Flow` command.
Requests carry a monotonic id and the buffer's `changedtick`; responses whose
tick no longer matches the buffer are dropped, so a slow analysis can never
paint stale highlights. The buffer text is sent as it stands, including
unsaved edits.

## Results at a glance

Hardware: Apple M4, macOS 26.6.2, Python 3.9.6, numpy 2.0.2, Vim 9.1
(system build, no GUI). All numbers below are measured, not estimated.

| suite | cases | identifier slices exact | false pos | false neg |
|---|---|---|---|---|
| development (straight line) | 275 | 275/275 | 0 | 0 |
| development (loops, unbraced, do/while) | 16 programs, every cursor | 4,860/4,860 | 0 | 0 |
| curated held-out, frozen weights | 8 | 133/133 | 0 | 0 |
| randomised straight-line | 400 | 8,448/8,448 | 0 | 0 |
| randomised control flow, loops included | 9,584 case-modes | 371,572/371,572 | 0 | 0 |
| invariance (rename / reformat) | 240 checks | all | 0 | 0 |
| fresh held-out, frozen weights | 300 | 7,518/7,518 | 0 | 0 |
| fresh held-out loops, frozen weights | 258 case-modes | 3,494/3,494 | 0 | 0 |
| unsupported-construct detection | 11 flagged, 14 clean | — | — | — |

| source | bytes | tokens | encode | inference | Vim e2e |
|---|---|---|---|---|---|
| 10 stmt chain | 250 | 81 | 1.98 ms | 3.76 ms | 6.1 ms helper, 9.2 ms e2e |
| 25 stmt chain | 595 | 186 | 4.35 ms | 7.77 ms | 12.4 ms helper, 20.5 ms e2e |
| 43 stmt chain | 1010 | 312 | 7.27 ms | 12.26 ms | 20.1 ms helper, 34.8 ms e2e |
| 10 stmt loop body | 491 | 137 | 3.54 ms | 5.92 ms | 9.6 ms helper, 15.5 ms e2e |
| 35 stmt loop body | 1288 | 353 | 8.81 ms | 14.04 ms | 23.5 ms helper, 42.5 ms e2e |

Cold start (import + weights): 51.8 ms. Resident memory: 35.4 MB peak. The
helper process is started once, and repeated requests for the same text and
cursor are served from a cache, so moving the cursor without editing costs
only the render pass. Loop-heavy input is the slowest per byte because the
block stack adds per-token work at every `{`, `}` and `;`.

## Limits (stated, not hidden)

2048 bytes, 512 tokens, 16 identifier characters, 48 identifier slots, 192
value nodes, 8 nested blocks, 8 dataflow hops, 26 grammar states, 4 context
bits. Supported: scalar locals and parameters, declarations with and without
initialisation, assignments, compound assignment, arithmetic, `if`/`else`
(including `else if` chains), `while`, `for` (declaration or assignment
init, any step clause), `do`/`while`, and all of them braced **or** with a
single-statement body, plus bare `{ ... }` blocks.

Not modelled, and reported as anomalies rather than guessed: nested
single-statement bodies (dangling `else`), shadowing, `for`/`do` headers with
nested parentheses in the condition, pointers, arrays, structs, calls,
macros, casts, ternaries, and control dependence. Unsupported constructs are
*detected* by the network's own two-token-lookahead weights and reported, not
silently mis-analysed. This is a bounded-subset tool: it does not claim
general C dataflow.

## Reproduce

```sh
python3 build/construct_weights.py     # regenerate the frozen weights
python3 build/export_weights.py        # numeric JSON copy of every tensor
python3 tests/evaluate.py              # development + held-out suites
python3 tests/fuzz.py 200              # randomised conformance
python3 tests/fuzz2.py 40              # renaming / reformatting invariance
python3 tests/anomaly.py               # unsupported-construct detection
python3 tests/evaluate_loops.py        # loops / unbraced / do-while, every cursor
python3 tests/holdout_loops.py         # fresh loop cases, frozen weights
python3 tests/holdout_fresh.py         # fresh cases, frozen weights
python3 bench/bench.py                 # timings, memory, op counts
./tests/vim/run.sh                     # 9 headless Vim integration checks
./scripts/demo.sh                      # end-to-end demo incl. real Vim props
```

`tests/vim/run.sh` runs the same nine checks in every editor it finds (real
Vim and Neovim): correct label set, `:Flow clear`, upstream, stale-response
rejection after an edit, analysis of unsaved edits, one-selected-mark per
occurrence, and the `inspect` / `info` buffers.
