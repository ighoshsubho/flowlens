# FlowLens architecture

Raw C bytes + cursor + mode → a hand-built recurrent network → per-byte
relevance labels. This document states the equations and what every weight
block computes.

## 1. The boundary

At inference time the runtime does exactly this:

* encode bytes as one-hot rows (host encoding),
* multiply them by frozen tensors,
* take winner-take-all over linear maps to produce discrete states,
* read and write an external memory by one-hot addressing,
* build a value graph by matrix algebra over network-produced registers,
* take a transitive closure by repeated boolean matmul,
* emit labels.

There is no lexer, parser, symbol table, hash, regex, AST, or dependency
walker in `engine/`. The only C-shaped data in the system is the numeric
content of `weights/flowlens_weights.npz`: the keyword codewords and the
transition tables. Delete that file and the runtime cannot find a comment,
a keyword, or a statement boundary.

`tests/ref.py` is a conventional analyser. It exists only to produce
expected labels for evaluation and is never imported by the engine, the
helper, or the plugin.

## 2. Pipeline

Notation: `WTA(v) = onehot(argmax v)`; `⊗` is the outer product; `⊙` is
elementwise product; `[P]` is 1.0 when predicate `P` holds, else 0.0.

### Stage 1 — encoding, and why it is a weight block

```
C = X · W_byte_class        X ∈ {0,1}^{N×256},  C ∈ {0,1}^{N×27}
A = X · W_alpha             A ∈ {0,1}^{N×64}   (character code)
```

`W_byte_class` has exactly one 1 per row: it partitions the byte alphabet
into 27 classes (`ALPHA, DIGIT, US, SLASH, STAR, ...`). `W_alpha` maps a
byte to one of 64 code symbols (a-z, A-Z, 0-9, `_`). Both are ordinary
dense matrices, so the "host" contributes nothing but the one-hot of the
byte value.

### Stage 2 — comment/string automaton (a recurrent net over bytes)

```
b_t = h_{t-1} ⊗ c_t                        b_t ∈ R^{9·27}
h_t = WTA(W_lex · b_t)                     h_t ∈ {0,1}^9
```

Nine states: `CODE, CODE_SLASH, LINE, BLOCK, BLOCK_STAR, STRING,
STRING_ESC, CHAR, CHAR_ESC`.

Why a *linear* map can implement an arbitrary transition table exactly: the
outer product of two one-hots is itself a one-hot over the 243 basis
vectors `(state, class)`. Every basis vector is therefore an independent
column, and column `(s,c)` is set to `+2` in row `next(s,c)` and `-2`
elsewhere. `argmax` returns the designed next state with no approximation
and no ties. This is a lookup table written as weights — which is exactly
what a hand-set RNN is.

Comment openers are then removed from the token stream by a bilinear test:

```
opener_t = [ Σ_ij s_in[i] · W_opener[i,j] · s_out[j] > 0.5 ]
code_t   = [s_in ∈ code states] · (1 - [class ∈ {'"', '\'', '\\'}]) · (1 - opener_t)
```

### Stage 3 — tokeniser (network registers only)

```
idch_t   = code_t ∧ [c_t · v_idchar > 0.5]
start_t  = idch_t · (1 - idch_{t-1})                 (identifier starts)
numstart = dig_t · (1 - dig_{t-1}) · (1 - idch_{t-1})
tok_t    = code_t ∧ [c_t · v_punct > 0.5]            (punctuation token)
τ(t)     = running count of token starts             (token index register)
```

Every token keeps its byte span because the counters that produce the spans
are the same registers that index the token tensors.

### Stage 4 — spelling and identifier slots (content-addressed attention)

Each identifier writes its character codes into `S[τ, p, :]`, `p` being a
per-token character counter. `S ∈ {0,1}^{T×16×64}`. Length is encoded by
occupancy `o[t,p] = Σ_a S[t,p,a]`.

Exact spelling equality is an attention score computed with matmuls:

```
D_p[t,u]  = S[t,p,:] · S[u,p,:]                      (64-way dot product)
Z_p[t,u]  = (1 - o[t,p]) · (1 - o[u,p])              (both positions empty)
E[t,u]    = Π_p [D_p + Z_p > 0.5]                    (exact equality)
first[t]  = [ ¬∃u<t : E[t,u] ]                       (first occurrence)
canon     = E ⊙ first                                 (row → its canonical form)
rank      = cumsum(first)
σ(t)      = canon · rank                             (slot id, a matmul)
```

`E` is exact, not approximate: one-hot dot products are 1 exactly when two
positions carry the same symbol, the `Z` term makes trailing empty
positions compare equal, and the product over positions is a logical AND.
This is why `x`, `x1` and `xx` are three different slots while `y` and `y`
two statements apart are the same slot.

### Stage 5 — grammar automaton with definition memory

Twenty-six states (`TOP, TOP_IDENT, PARAM_*, STMT, DECL_NAME, AFTER_NAME,
AFTER_LHS, EXPR, RET_EXPR`, the condition states `IF_COND, IF_PEND,
ELSE_PEND, WHILE_COND, WHILE_PEND`, and the loop states `FOR_HEAD, FOR_COND,
FOR_STEP, FOR_STEP_IDENT, FOR_PEND, DO_PEND, DO_COND, DO_WHILE_COND,
DO_END`), eighteen token classes:

```
q_t = s_{t-1} ⊗ f_t ⊗ b_t   (7488 = 26 × 18 × 16 basis)
s_t = WTA(W_gsm · q_t)
out_t = W_out · q_t         (read / assign / declinit / declterm /
                             paramwrite / retend / barrier / anomaly /
                             compound / commit / open_* / close / stepinc)
```

`b_t` is a four-bit control context that the block stack exposes, kept as a
one-hot over sixteen combinations:

```
b_t = (depth = 0) + 2·(inside a for header) + 4·(closed do-block, before its
      while) + 8·(inside a for step clause)
```

The context bits are what keep the shared states honest: the first `;` of a
`for` header ends the init clause whichever state the init clause itself was
parsed in, and the `)` that ends a step clause ends an assignment written
inside it. Without them `for (i = 0; i < n; i = i + 1)` would need a separate
copy of every statement state.

`f_t` (token class) is assembled from the spelling tensors: keyword
recognition is

```
kw[t,k] = Π_p [ (S[t,p,:] · W_kw_code[k,p,:]) + (1-o[t,p])(1-o_kw[k,p]) > 0.5 ]
```

so `int` is a keyword because its *numeric spelling* matches a codeword,
not because anything compared strings.

**External working memory.** `R ∈ {0,1}^{48×96}`: row `s` holds a one-hot
of the definition currently visible in slot `s`.

```
read at token t:   ρ_t = R · σ(t)                    (content-addressed read)
write of def d:    R ← (1 - σ) ⊙ R + σ ⊗ e_d         (content-addressed write)
```

Writes are committed at the statement barrier, not at `=`, so
`m = m * 3` binds its right-hand `m` to the *previous* definition. That
single design decision is what makes copies and overwrites behave.

**Block stack.** For each open block (`DMAX = 8`) the runtime keeps an entry
snapshot of `R`, the set of slots written inside, the set of definitions
created inside, whether the body was braced, and for loops the definitions
read by the condition and the definitions created by the step clause. On the
closing token it emits one merge node per written slot:

```
merge_s = new_node;  deps(merge_s) = { R_entry[s], R[s] };  R[s] = merge_s

while/for:  E[header_read_def, body_def] = 1   same slot, body-written slots only
for:        E[step_def, body_def] = 1          the step follows the body
for:        E[header_read_def, step_def] = 1   the next test sees the step
```

The merge makes a conditional write non-destructive; the loop edges make the
header test depend on what the loop produced. Nothing counts iterations - it
is a may-flow fixpoint, absorbed by the same 8-hop closure. Loop edges are
restricted to slots the body writes, so a condition that merely *reads* a
parameter (a bound, a limit) does not get swept into the loop's cycle.

`do { ... } while (c)` needs no extra edge: its test is textually after the
merge, so the test's reads already bind the merge node.

**Single-statement bodies.** A pending-body state that sees anything other
than `{` opens a block with `braced = 0`; it closes at the `;` that ends the
statement, and emits the same merge. `else if` is a chain, not a block: the
`else` row is composed with the `STMT` row, so it enters `IF_COND` directly.
A block opened inside an unbraced body is reported as an anomaly, because
the dangling-`else` binding is then genuinely ambiguous for this automaton.

Compounding (`x += e`) is a read-modify-write: the new definition gets an
extra edge to the definition it replaced, taken from `R` before the write.

### Stage 6 — value graph and closure

A node is a definition (id 1..127) or a return sink (128..191). Definitions
include merge nodes emitted when a block closes.

```
A[u,v] = [∃ read r : apply(u) < r ∧ stmt(r) = stmt(u) ∧ ρ_r = e_v]
         ∨ self_dep(u,v)
```

built as tensors: `apply_oh · GTᵀ` gives "r later than the definition
point", `stmt_oh · stmt_ohᵀ` gives same-statement, and multiplying by the
read→definition one-hot matrix `ρ` produces the adjacency. And:

```
R = A ;  repeat 8: R ← R ∨ (R · R)          (transitive closure, boolean)
```

Downstream of a selected occurrence is the column of `R` for its value
node; upstream is the row. Labels are placed on identifier tokens whose
definition is in that set, plus the definition anchors themselves.

## 3. Weight blocks

| tensor | shape | what it computes |
|---|---|---|
| `W_byte_class` | 256×27 | byte → class one-hot |
| `W_alpha` | 256×64 | byte → character code |
| `W_kw_code` | 17×16×64 | keyword codewords; exact spelling match |
| `v_kw_len/type/ret/if/else/while/for/do` | 17 each | codeword length and keyword role |
| `W_lex` | 9×243 | comment/string automaton (9 states × 27 classes) |
| `W_opener` | 9×9 | "this byte opens a comment" |
| `v_lex_*` | 9 | code-state and comment-state selectors |
| `v_cls_*` | 27 | byte-class selectors (idchar, digit, punct, op, quote) |
| `W_tokF` | 27×18 | byte class → token class contribution |
| `W_gsm` | 26×7488 | grammar automaton over state ⊗ class ⊗ context bits |
| `v_out_*` | 7488 each | read / write / barrier / anomaly / compound / commit / stepinc decoders |
| `v_open_*` | 7488 each | which construct a `{` opens; `_u` variants open a one-statement body |
| `v_anom2` | 8424 | unsupported-construct detector over (state, class, next) |
| `GT` | 512×512 | the positional relation `i > j` |

## 4. Parameter accounting (measured, not promised)

| quantity | value |
|---|---|
| dense parameters | 681,281 |
| — of which the positional `GT` mask | 262,144 |
| — of which the grammar table `W_gsm` | 194,688 |
| — of which everything else | 224,449 |
| nonzero parameters | 334,056 (203,240 excluding `GT` and `W_gsm`) |
| serialized `.npz` | 18,580 bytes |
| exported JSON | 3.60 MB (3,604,134 bytes) |
| resident set, running | ~34 MB (interpreter + numpy) |
| operations, 1 KB source | see `docs/RESULTS.md` |

The grammar table is stored flat: every column carries one `+2` for the
target state and `-2` everywhere else, so winner-take-all needs no
threshold tuning. Most of its 194,688 entries are the `-2` padding, which
is why the serialized file is 18 KB rather than 2.7 MB of float32.

The mask dominates the dense count because it is a 512×512 relation stored
rather than computed; it compresses to almost nothing because it is
triangular. Reporting the split is the honest version of "parameter count".

## 5. Finite limits

| limit | value | why |
|---|---|---|
| source bytes | 2048 | bounds the byte recurrence |
| tokens | 512 | bounds the token tensors |
| identifier characters | 16 | spelling memory depth; longer names are not tracked and are flagged |
| identifier slots | 48 | distinct spellings per buffer |
| value nodes | 192 (127 definitions incl. merges + 65 return sinks) | graph size |
| block nesting | 8 | block stack depth, braced or single-statement |
| grammar states | 26 | statement + loop states; context bits are separate |
| context bits | 4 (16 combinations) | top level, for header, do-pending, for step |
| dataflow hops | 8 | closure iterations; longer chains saturate |

Nothing here claims unbounded C analysis.

## 6. What the recurrence buys, and what it costs

Three sweeps over the source: byte-level lexing, token-level grammar with
memory writes, then a graph closure. All source-dependent decisions
(content addressing, slot allocation, definition visibility, statement
grouping) are computed from byte values by the tensors above; the Python
around them only moves arrays.

Cost is linear in tokens for the automata and quadratic in identifiers for
the spelling attention and in nodes for the closure. Measured on an M4
Mac: 2.4 ms for 125 bytes, 16 ms for 1 KB (see `bench/results.json`).
The runtime is numpy on one core; nothing is GPU-accelerated, and small
parameter count does not by itself make inference fast — the per-timestep
Python dispatch is the actual cost.
