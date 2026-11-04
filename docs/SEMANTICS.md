# FlowLens semantics and supported subset

## What a highlight means

A *value node* is created by:

* every parameter,
* every declaration with an initialiser,
* every declaration without an initialiser,
* every assignment (including `op=`),
* every `return` statement (a sink node).

Node `u` depends on node `v` when `v` is the definition read by an
identifier in `u`'s initialiser or return expression. `x = x + 1` depends
on the previous `x`, and `x = 0` depends on nothing.

When a braced block closes, every slot written inside it gets a **merge
node** whose parents are the version from before the block and the version
after it. That is what stops a conditional write from destroying a flow:
in `int s = a; if (c) { s = 5; } return s;` the return reads the merge, so
it still depends on `a` (the block may not be taken).

A `while` block additionally gets a **loop-carried edge**: a definition
read by the header test depends on the body definition of the *same slot*,
so upstream from the returned value reaches the loop body and downstream
from a body read reaches the return. Iteration counts are not represented;
this is a may-flow fixpoint, not a simulation.

Given the occurrence under the cursor:

* **downstream** labels every identifier token whose definition is in the
  forward closure of the selected value, plus the definition anchors on
  that path.
* **upstream** labels every identifier token whose definition is in the
  backward closure of the selected value, plus those anchors.

Only identifier tokens are labelled. Types, keywords, operators and
literals are not labelled, and the selected occurrence is always marked —
even when it carries no value (a function name, for instance), because the
cursor mark is not a claim about flow.

## Supported grammar

```
program   := function+
function  := type IDENT '(' params? ')' block
params    := type IDENT (',' type IDENT)*
block     := '{' stmt* '}'
stmt      := type declarator (',' declarator)* ';'
           | IDENT '=' expr ';'
           | IDENT ('+'|'-'|'*'|'/'|'%') '=' expr ';'
           | 'return' expr? ';'
           | ';'
declarator:= IDENT ('=' expr)?
expr      := term (('+'|'-'|'*'|'/'|'%'|'<'|'>'|'&'|'|') term)*
term      := IDENT | INT | '(' expr ')'
type      := int | char | long | short | float | double | unsigned | void
             | signed | static | const
```

Comments (`//`, `/* */`), string literals and character literals are
lexed and ignored. Whitespace is irrelevant. Identifiers up to 16
characters are tracked; longer names are not tracked and are reported as
anomalies.

Anything else in the text is reported through the anomaly counter in
`:Flow inspect`. An anomaly count above zero means the labels may be
incomplete — the plugin says so in the status line.

## Precise non-support

| construct | status | mechanism |
|---|---|---|
| comment / string / char literal | supported | lexer automaton |
| declaration, assignment, `op=`, multiple declarators | supported | grammar automaton + memory |
| arithmetic over locals and literals | supported | expression reads |
| multiple functions | supported | `TOP` state re-entry |
| parameters | supported | `PARAM_*` states |
| `if` / `else`, braced or single-statement | supported | block stack, merge node per written slot |
| `else if` chains | supported | `ELSE_PEND` composed with the statement row; no extra scope |
| `while`, braced or single-statement | supported | merge node + loop-carried edge (same slot) |
| `for (init; cond; step)`, braced or single-statement | supported | dedicated header states; step clause becomes a definition |
| `+`/`-` postfix `i++`, `++i` in a for step | supported | step-clause definition, self-dependent on the previous value |
| `do { } while (c)` | supported | merge at `}`; the test is after the merge, so it binds it |
| bare compound statement `{ ... }` | supported | plain block, merge at `}` |
| control dependence / implicit flow | **not modelled** | selecting a condition reveals nothing about the body it guards; only data flow is labelled |
| nested single-statement body (`if (a) if (b) x = 1; else ...`) | **not modelled** | flagged: the dangling-`else` binding is ambiguous for a one-token-lookahead automaton |
| shadowing / redeclaration in an inner scope | **not modelled** | flagged: one slot per spelling, so an inner declaration rebinds the outer name |
| nested parentheses in a condition | **not modelled** | the first `)` closes the condition; flagged |
| pointers `*p`, `&x` | **not modelled** (deref is ambiguous with multiplication) | flagged for `int *p`; `*p` in an expression is indistinguishable from `a * b` without types |
| arrays, structs, unions, typedef | **not modelled** | flagged |
| function calls, external functions | **not modelled** | flagged |
| macros / preprocessor | **not modelled** | `#` is an `OTHER` token  flagged |
| casts | **not modelled** | flagged |
| ternary `?:` | **not modelled** | flagged |
| aliasing through pointers/references | **not modelled** | no address-taken analysis exists at all |
| scopes / shadowing | **not modelled** | one slot per spelling for the whole buffer; a redeclaration rebinds the slot |

### Exact failing example: a nested single-statement body

```
int f(int a, int b){
 int s = 1;
 if (a) if (b) s = 2; else s = 3;
 return s;
}
```

Selecting `s` inside `s = 2` and asking for upstream flow labels **nothing**
(`relevant_tokens = 0`, `anomalies = 2`). Mechanism: `if (a)` opens a
one-statement body at the inner `if`; that inner `if` tries to open a second
one-statement body, which the block opener reports as an anomaly, and the
automaton's `ELSE_PEND` then binds the `else` to the outer `if`. The
definition created in the inner body never reaches the merge for `s`, so the
merge keeps only the entry value. The repair is a statement-boundary stack
that remembers which `if` owns a pending `else`; the current build takes the
other path — it requires braces there and warns.

### Exact failing example: shadowing

```
int f(int a){
 int b = 1;
 { int b = 2; int c = b; }
 return b;
}
```

Anomalies = 1. The inner `b` shares the slot of the outer `b`, so selecting
the outer `b` at the return also reveals the inner `b` and `c`. Fixing this
needs a slot key of spelling × scope, changing the content-addressed memory
from 48 slots to 48 × 8.

### A branch, for contrast (supported since v2)

```
int f(int c, int a) {
    int b = a + 1;
    if (c) { b = 7; }
    return b;
}
```

Selecting `a` downstream gives `a`, `b` in `b = a + 1`, and `b` in the
return. The conditional write is non-destructive because the merge node for
`b` depends on both the entry definition and the body definition. This is
the case v1 could not do; it is the reason merge nodes exist.

## Evaluation semantics

`tests/ref.py` implements the same semantics conventionally, and is used
only to produce expected labels. Metrics are reported per identifier
slice, because byte accuracy is dominated by unlabelled bytes: a model
that predicts "irrelevant" everywhere would score in the high nineties on
bytes and near zero on positive slices.

Reported separately: false positives, false negatives, exact-slice
accuracy over all identifier slices, and exact-slice accuracy over slices
that contain at least one relevant byte.
