# FlowLens results

All numbers below were produced on this machine by the commands shown.
Nothing here is estimated.

Environment: Apple M4, macOS 26.6.2 (25G83), arm64, Python 3.9.6,
numpy 2.0.2 (Apple Accelerate BLAS), Vim 9.1 system build ("Normal version
without GUI", `+job +channel +textprop`), Neovim 0.11.2 (extmark backend),
single core, no GPU, no network. The macOS/Vim integration was exercised
directly, not simulated: `tests/vim/run.sh` drives both editors headlessly.

## Correctness

Expected labels come from `tests/ref.py` (test-only, never in the inference
path). Metrics are per identifier slice: a slice counts as exact only when
every byte in it matches. Byte accuracy is reported separately because it is
dominated by unlabelled bytes.

| suite | case-modes | slices exact | positive slices | FP | FN |
|---|---|---|---|---|---|
| development, straight line (`evaluate.py`) | — | 373/373 | 157/157 | 0 | 0 |
| development, loops + unbraced + do/while (`evaluate_loops.py`) | 2,592 | 4,860/4,860 | — | 0 | 0 |
| curated held-out, frozen weights | — | 133/133 | 129/129 | 0 | 0 |
| randomised straight line (`fuzz.py`) | 400 | 8,448/8,448 | 1,711/1,711 | 0 | 0 |
| randomised control flow incl. loops (`fuzz_cf.py 200`) | 9,584 | 371,572/371,572 | — | 0 | 0 |
| renaming + reformatting invariance (`fuzz2.py`) | 240 checks | all | — | 0 | 0 |
| fresh held-out (`holdout_fresh.py`) | 300 | 7,518/7,518 | 1,519/1,519 | 0 | 0 |
| fresh held-out loops (`holdout_loops.py`) | 258 | 3,494/3,494 | — | 0 | 0 |
| editor integration (`tests/vim/run.sh`) | 12 checks × 2 editors | identical label sets in Vim 9.1 and Neovim 0.11.2 | — | 0 | 0 |

False positives and false negatives are reported separately and both are
zero on every suite above. The randomised suites generate identifier names,
chain depths, statement orders, comments, literals, loop shapes, body
bracing and formatting procedurally, so the model is not being scored on the
names in the examples.

`evaluate_loops.py` and `holdout_loops.py` select *every* identifier
occurrence in turn, in both modes, which is what catches the occurrence-level
mistakes that a single cursor per program hides. `holdout_loops.py` was
written after the v3 weights were frozen and shares no program, name or
formatting with the development set.

Unsupported-construct detection (`tests/anomaly.py`): 11/11 unsupported
programs flagged (nested single-statement body, shadowing, nested-paren
condition, pointer parameter, pointer local, function call, `struct`, cast,
array, ternary, stray `else`), and 14/14 supported programs clean (basic
flow, unbraced `if`, `else if` chain, unbraced `while`, `do`/`while`, `for`
with `i++`, `for` unbraced, bare block, nested braced blocks, `op=`, `%`,
parentheses, comments). The detector is an 8,424-wide weight block over
`(state, class, next-class)`.

Invariance is measured, not asserted: for each program the suite renames
every identifier through a random bijection, reformats whitespace, and
compares the label sequence over identifier tokens. All 240 comparisons
match.

## Performance

Measured by `bench/bench.py` (12 runs per size, median).

| source | bytes | tokens | encode | inference | total (helper) | MACs | tensor ops |
|---|---|---|---|---|---|---|---|
| 4 stmt chain | 125 | 39 | 1.07 ms | 2.11 ms | 3.22 ms | 76.8 M | 805 |
| 10 stmt chain | 251 | 81 | 1.98 ms | 3.76 ms | 5.81 ms | 100.4 M | 1,495 |
| 25 stmt chain | 596 | 186 | 4.35 ms | 7.77 ms | 12.25 ms | 168.7 M | 3,310 |
| 35 stmt chain | 826 | 256 | 5.93 ms | 10.13 ms | 16.28 ms | 221.3 M | 4,520 |
| 43 stmt chain | 1010 | 312 | 7.27 ms | 12.26 ms | 19.79 ms | 267.4 M | 5,488 |
| 4 stmt for body | 316 | 90 | 2.37 ms | 4.23 ms | 6.69 ms | 110.0 M | 1,770 |
| 10 stmt for body | 491 | 137 | 3.54 ms | 5.92 ms | 9.61 ms | 139.6 M | 2,641 |
| 20 stmt for body | 832 | 230 | 5.83 ms | 9.55 ms | 15.61 ms | 205.1 M | 4,350 |
| 35 stmt for body | 1288 | 353 | 8.81 ms | 14.04 ms | 23.32 ms | 305.5 M | 6,624 |

Vim, headless, end-to-end from `:Flow downstream` to properties applied:

| buffer | bytes | tokens | e2e | helper round trip | render | properties |
|---|---|---|---|---|---|---|
| 10 stmt chain (cold) | 250 | 81 | 59.1 ms | 6.1 ms | 2.3 ms | 67 |
| 25 stmt chain | 595 | 186 | 20.5 ms | 12.4 ms | 6.8 ms | 157 |
| 43 stmt chain | 1009 | 312 | 34.8 ms | 20.1 ms | 14.4 ms | 265 |
| 10 stmt for body | 490 | 137 | 15.5 ms | 9.6 ms | 4.1 ms | 108 |
| 35 stmt for body | 1287 | 353 | 42.5 ms | 23.5 ms | 17.5 ms | 293 |

* Cold start (interpreter + weights + first analysis): 51.8 ms. The first
  Vim request pays it once, when the helper process starts.
* Resident memory: 35.4 MB peak for the whole process.
* The headless end-to-end column includes the test script's blocking wait
  (`sleep 2m` polling), which is why it exceeds helper + render. In an
  interactive Vim the channel callback runs as soon as the loop is idle.
* Repeat requests for the same text, cursor and mode are served from the
  helper's cache, so moving the cursor without editing costs only the render
  pass.
* Loop-heavy input costs about 30% more per token than a straight-line
  chain of the same size: the block stack does per-token work at every `{`,
  `}`, `;` and at every pending-body decision.

Cost model, from the runner: the byte and token recurrences are linear in
tokens but pay Python dispatch per timestep (~13 µs/token), which is what
dominates at these sizes; the spelling attention is quadratic in identifier
tokens; the closure is 8 × 192³ boolean MACs, ~56 M, now the largest fixed
term after the grammar table.

Optimisation done during development, driven by these measurements:
restricting the spelling attention to identifier rows (gather by a
network-computed mask), slicing every token tensor to the live token count,
scatter-adding per-token class counts instead of an outer product per byte,
and switching the MAC counter to count real output terms (the earlier counter
over-reported vector products by their output dimension).

## Weight revisions driven by failures

The weights were revised on development cases, and every revision has a named
failing example. This is the actual log, in order. Entries 1–8 are v1/v2;
entries 9–15 are the v3 loop work.

| # | failure observed | cause | revision |
|---|---|---|---|
| 1 | downstream labels stopped at the selected token | dependency edges computed "read earlier than definition" (`GT` used untransposed) | use `GTᵀ` in the edge builder |
| 2 | `saved` and `x` shared a memory slot | slot taken from the running first-occurrence *count* | added the `canon` attention retrieving the rank at the token's canonical first occurrence |
| 3 | `m = m * 3` bound its right-hand `m` to the *new* definition | write committed at `=` | commit at the statement barrier |
| 4 | selecting a function name produced no highlight | selected mark emitted only when a value node existed | always mark the selected occurrence |
| 5 | `//` inside a body produced anomaly false alarms | comment openers tokenised as operators | added `W_opener` |
| 6 | `a % 3` lost an operand silently | `%` had no byte class | added the `PCT` class |
| 7 | `int *p` parameter not flagged | rule keyed on the wrong state | corrected the rule |
| 8 | `if (x) {...}` analysed with no warning | one-token anomaly block too weak | added the two-token-lookahead block |
| 9 | `if (c) { x = 1; } return x;` lost the branch value | conditional write overwrote the single definition register | block stack + merge node per written slot |
| 10 | `while (c) { s = 5; } return s;` missed the loop's write | no loop-carried edge | merge + same-slot edge from header read to body definition |
| 11 | `for (i = 0; i < n; i++)` — selecting `n` downstream lit up `i` and `s` | suppressing the header's statement boundary put the init definition in the same statement as the condition, so the edge builder made `i = 0` depend on `n` | header keeps three statement ids; loop edges are explicit, not statement-derived |
| 12 | `for (...; i = i + 1)` treated the *right-hand* `i` as the assignment target | `FOR_STEP` self-looped on an identifier, so `=` was never seen | added `FOR_STEP_IDENT`; a step-clause context bit routes the closing `)` |
| 13 | selecting `i` in `i++` resolved to the *init* value | the step definition was created but never anchored to its token | anchor + role set on the step definition |
| 14 | `for (...) s = s + i;` missing the body read of `i` | the unbraced body shared a statement id with the step clause, so the step definition absorbed the body's reads | an implicitly opened body starts its own statement |
| 15 | after a `for` header, the *next* assignment gained a spurious self-edge | `i++` set the compound flag and nothing cleared it (no commit token at `)`) | `)`, and `)` in `EXPR`/`AFTER_LHS`, added to the commit decode |
| 16 | selecting a parameter used only as a loop bound revealed the whole loop body | loop-carried edges attached to every header-read slot | restricted to slots the body actually writes |

Revision 16 is the difference between "the loop touches this value" and
"this value feeds the loop": a bound is read by the test but never written by
the body, so it cannot be loop-carried. Getting that wrong is what made
`select n` highlight `i` and `s`.

The bare-block disagreement found by the v3 suite is worth recording
separately: `tests/ref.py` did not open a block for a bare `{ ... }`, so the
reference and the network disagreed on a construct v2 already claimed. The
network was right; the reference was wrong. It has been wrong five times
across this project (also: `if`/`else`/`while` missing from its keyword set
in two separate places, a comma-swallowing expression reader, and treating
`i++` as a definition only). That asymmetry is exactly why the reference is
test-only and never an inference input.

## What is still wrong

* **Nested single-statement bodies and shadowing are not modelled.** They are
  detected and reported, not analysed. Exact failing examples and mechanisms
  are in `docs/SEMANTICS.md`.
* **Pointers, arrays, structs, unions, calls, macros, casts and ternaries are
  not modelled** — detected and reported.
* **Control dependence is not modelled.** Selecting a condition reveals
  nothing about the statements it guards; only data flow is labelled. This is
  a semantic choice, not a bug, and it is stated in `:Flow info`.
* **`for` and `do` headers with nested parentheses in the condition** are
  flagged: the first `)` closes the condition.
* **Identifiers longer than 16 characters are not tracked** (reported).
* **Chains longer than 8 hops saturate** (the closure has 8 iterations).
* **192 value nodes** per buffer (127 definitions including merges + 65
  return sinks).
* **Only identifier tokens are labelled.** Operators and literals on a flow
  path are not marked.
* **No scope awareness**: two `x` in different blocks are one slot.
* The `*p` dereference case cannot be distinguished from multiplication
  without types, so it is not flagged in expression position.
* The grammar table is 194,688 dense parameters, 79% of all parameters,
  because it stores the full `(state × class × context)` product. It
  compresses to 18 KB total file size but it is not a small model in the
  usual sense, and inference time is dominated by Python dispatch anyway.
