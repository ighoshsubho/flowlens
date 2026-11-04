# Spike 001: retarget to assembly instead of C?

**Question.** Could FlowLens analyse compiler output (assembly/IR) instead of C
source, and map results back to the source line?

**Approach.** Compiled `demo.c` (pointers, a struct, an array, a loop, a call,
a macro — all things the C-side network cannot model) with `clang -S -g` at
`-O0` and `-O2`, then measured the shape of the input the network would see.
The compiler is used here **only to produce a measurement artefact**; nothing
in this spike is part of the inference path.

## Measured (Apple M4, clang 21, arm64)

| | source | asm -O0 | asm -O2 |
|---|---|---|---|
| lines | 44 | 931 (100 instructions, rest directives/DWARF) | 666 (14 instructions) |
| distinct mnemonics | — | 20 | 11 |
| registers touched | — | 12 (of 31) | 7 |
| basic blocks (branch targets) | — | 4 | 0 |
| `.loc` directives | — | 63 | 4 |
| source lines still mapped | 44 | 23 | 3 |
| instructions per source line | — | median 3, max 12 | 5 |

Load/store share of instructions at `-O0`: 40 of 100 (`ldr` 23, `str` 17).

## What this says

**In favour**

* The vocabulary collapses: 20 mnemonics here, ~100 for all of arm64, against a
  full C grammar with types, scopes, declarators and preprocessor.
* The register file is finite and small (12 used, 31 maximum) — it fits the
  48-slot memory model directly, with no scope or shadowing problem.
* Control flow is explicit: labels and conditional branches are exactly the
  block structure the v2 merge machinery already consumes. No unbraced bodies,
  no `for`-header ambiguity.
* Types, structs, arrays and macros all flatten into loads and stores at
  offsets, so the "unsupported syntax" list largely evaporates.

**Against**

* **It breaks the project's boundary.** `clang -S` is Clang in front of the
  network, which is the single thing the brief forbids.
* **Map-back is only honest at `-O0`.** At `-O2` the demo was constant-folded
  to 14 instructions and 3 mapped source lines; inlining deletes whole
  functions. Highlighting a source column then claims a correspondence that no
  longer exists.
* **`-O0` output is spill soup.** 40% of instructions are loads and stores to
  the stack, so a tracked value hops between slots constantly; the register
  graph is wide and shallow rather than the clean chain you get in source.
* **Aliasing gets worse, not better.** `mov (%rax), %rbx` says nothing about
  what `rax` points at. C at least names the variable; assembly only names the
  address register. This is the same analysis problem with less information.
* 89% of `.s` lines are directives and DWARF data, so a tokenizer must strip
  them — and the line/column map lives in that DWARF anyway.

## Verdict: PARTIAL

Viable as a **retarget** (a network whose input language *is* assembly, opened
directly, no compiler at inference). Not viable as a **front-end** under the
current rules, and lossy as a map-back strategy above `-O0`.

## Recommendation

If pursued, build it as a new weight set with assembly as the native input
language:

* ~25 grammar states, ~40 token classes (mnemonics + operand forms + labels)
* register file as 32 slots replacing the 48 identifier slots
* branch targets as block boundaries (merge nodes already exist)
* back-edges give loops for free (`b` to an earlier label)
* optional: read `.loc` to render source spans — a table lookup in the render
  layer, not source analysis

Estimated effort: 2-3 days, mostly vocabulary construction, reusing the v2
block machinery. It would cover essentially all C *as compiled*, including
pointers and structs at the syntax level, while alias resolution remains
unsolved exactly as it is for C.
