"""TEST-ONLY reference analyzer for the documented C subset.

This is a conventional, procedural implementation used only to produce
expected labels for evaluation.  It is never imported by the engine, the
helper, or the Vim plugin, and its output never enters inference.

Semantics (identical to docs/SEMANTICS.md):
  A "value node" is created by every definition (declaration with
  initialiser, parameter, bare declaration, assignment) and by every return
  statement.  A node depends on the definitions read in its initialiser or
  return expression.  Downstream relevance of a selected occurrence is the
  transitive closure along "depends on" edges from the definition that
  occurrence reads (or writes); upstream relevance is the same closure in
  the opposite direction.  Labels are placed on identifier tokens only.
"""

import re

TYPE_KW = {"int", "char", "long", "short", "float", "double", "unsigned",
           "void", "signed", "static", "const"}
KW = TYPE_KW | {"return", "if", "else", "while", "for", "do"}

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|==|!=|<=|>=|&&|\|\||"
                      r"[-+*/%=;,(){}\[\]<>!&|.]")


def strip_comments(src):
    """Blank out comments and string/char literals, preserving byte offsets."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                out[k] = " "
            i = j
        elif c in "\"'":
            q = c
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    j += 1
                    break
                j += 1
            for k in range(i, min(j, n)):
                out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def tokenize(src):
    blank = strip_comments(src)
    toks = []
    for m in TOKEN_RE.finditer(blank):
        toks.append(dict(text=m.group(0), start=m.start(), end=m.end()))
    return toks, blank


def is_ident(t):
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t["text"]))


def analyze(src, cursor, mode="downstream"):
    """Procedural reference with block merges and loop-carried dependence.

    Same semantics as the network: a phi node per slot written inside a block
    (entry version, exit version), and a loop header read depends on the body
    definition of the same slot.  Data flow only; control dependence is not
    modelled on either side.
    """
    toks, blank = tokenize(src)
    n = len(toks)

    def kind(i):
        if i >= n:
            return "EOF"
        t = toks[i]["text"]
        if t in KW:
            return t
        if is_ident(toks[i]):
            return "ID"
        if t.isdigit():
            return "NUM"
        return t

    nodes = []
    cur = {}
    ident_node = {}
    read_def = {}
    wstack = []

    def new_node(kindn, name, anchor, apply):
        nodes.append(dict(kind=kindn, name=name, anchor=anchor, apply=apply,
                          deps=set()))
        return len(nodes) - 1

    def mark_write(name):
        for s_ in wstack:
            s_.add(name)

    def expr_reads(i, stops):
        reads = []
        while i < n:
            k = kind(i)
            if k in stops or k == "EOF":
                break
            if k == "ID":
                nm = toks[i]["text"]
                if nm in cur:
                    read_def[i] = cur[nm]
                    reads.append(i)
            i += 1
        return reads, i

    def close_block(i, entry, is_loop=False, cond_reads=(), step_defs=()):
        wr = wstack.pop()
        for nm in sorted(wr):
            e = entry.get(nm)
            x = cur.get(nm)
            nd = new_node("def", nm, i - 1, i - 1)
            nodes[nd]["deps"] = {d for d in (e, x) if d is not None}
            cur[nm] = nd
            if is_loop:
                # the header test of this slot sees what the loop produced
                for r in cond_reads:
                    if toks[r]["text"] == nm and r in read_def:
                        nodes[read_def[r]]["deps"].add(nd)
                # a for step clause runs after the body of the same iteration
                for sd in step_defs:
                    if nodes[sd]["name"] == nm:
                        nodes[sd]["deps"].add(nd)
                        for r in cond_reads:
                            if toks[r]["text"] == nm and r in read_def:
                                nodes[read_def[r]]["deps"].add(sd)
        if wstack:
            wstack[-1] |= wr
        return i

    def block(i, entry, is_loop=False, cond_reads=(), step_defs=()):
        i += 1                                     # skip '{'
        wstack.append(set())
        while i < n and kind(i) != "}":
            i = stmt(i)
        if i < n:
            i += 1                                 # skip '}'
        return close_block(i, entry, is_loop, cond_reads, step_defs)

    def body(j, entry, is_loop=False, cond_reads=(), step_defs=()):
        """Braced block or single statement: both end in the same phi."""
        if j < n and kind(j) == "{":
            return block(j, entry, is_loop, cond_reads, step_defs)
        wstack.append(set())
        j = stmt(j)
        return close_block(j, entry, is_loop, cond_reads, step_defs)

    def cond(i):
        j = i + 1
        if j < n and kind(j) == "(":
            j += 1
        reads, j = expr_reads(j, (")", "}", ";"))
        if j < n and kind(j) == ")":
            j += 1
        return reads, j

    def for_step(j):
        """One step clause: i++, ++i, i += e, i = e, or anything readable."""
        defs = []
        while j < n and kind(j) != ")":
            kk = kind(j)
            if (kk == "ID" and kind(j + 1) in ("+", "-")
                    and kind(j + 2) in ("+", "-")):
                nm = toks[j]["text"]
                mark_write(nm)
                nd = new_node("def", nm, j, j)
                ident_node[j] = nd
                if nm in cur:
                    nodes[nd]["deps"].add(cur[nm])
                    read_def[j] = cur[nm]        # i++ also reads the old value
                cur[nm] = nd
                defs.append(nd)
                j += 3
            elif (kk == "ID" and kind(j + 1) in ("+", "-", "*", "/", "%")
                    and kind(j + 2) == "="):
                nm = toks[j]["text"]
                j0 = j
                mark_write(nm)
                nd = new_node("def", nm, j, j + 2)
                ident_node[j] = nd
                reads, j = expr_reads(j + 3, (")", ";", "}"))
                nodes[nd]["deps"] = {read_def[r] for r in reads
                                     if r in read_def}
                if nm in cur:
                    nodes[nd]["deps"].add(cur[nm])
                    read_def[j0] = cur[nm]       # target also consumes old value
                cur[nm] = nd
                defs.append(nd)
            elif kk == "ID" and kind(j + 1) == "=":
                nm = toks[j]["text"]
                j0 = j
                mark_write(nm)
                nd = new_node("def", nm, j, j + 1)
                ident_node[j] = nd
                reads, j = expr_reads(j + 2, (")", ";", "}"))
                nodes[nd]["deps"] = {read_def[r] for r in reads
                                     if r in read_def}
                if nm in cur:
                    read_def[j0] = cur[nm]
                cur[nm] = nd
                defs.append(nd)
            else:
                if kk == "ID" and toks[j]["text"] in cur:
                    read_def[j] = cur[toks[j]["text"]]
                j += 1
        return defs, j

    def for_stmt(i):
        j = i + 1
        if kind(j) == "(":
            j += 1
        if kind(j) == ";":
            j += 1                                 # empty init clause
        else:
            j = stmt(j)                            # init clause, eats its ';'
        reads, j = expr_reads(j, (";", ")", "}"))
        if kind(j) == ";":
            j += 1
        step_defs, j = for_step(j)
        if kind(j) == ")":
            j += 1
        return body(j, dict(cur), True, reads, step_defs)

    def stmt(i):
        k = kind(i)
        if k == "{":                               # bare compound statement
            return block(i, dict(cur))
        if k in TYPE_KW:
            i += 1
            while i < n:
                if kind(i) != "ID":
                    break
                nm = toks[i]["text"]
                anchor = i
                mark_write(nm)
                if kind(i + 1) == "=":
                    nd = new_node("def", nm, anchor, i + 1)
                    ident_node[anchor] = nd
                    reads, i = expr_reads(i + 2, (";", ",", "}"))
                    nodes[nd]["deps"] = {read_def[r] for r in reads
                                         if r in read_def}
                    cur[nm] = nd
                else:
                    nd = new_node("def", nm, anchor, anchor)
                    ident_node[anchor] = nd
                    cur[nm] = nd
                    i += 1
                if i < n and kind(i) == ",":
                    i += 1
                    continue
                break
            if i < n and kind(i) == ";":
                i += 1
            return i
        if k == "return":
            reads, j = expr_reads(i + 1, (";", "}"))
            nd = new_node("ret", None, i, i)
            nodes[nd]["deps"] = {read_def[r] for r in reads if r in read_def}
            if j < n and kind(j) == ";":
                j += 1
            return j
        if k == "if":
            reads, j = cond(i)
            entry = dict(cur)
            j = body(j, entry)
            if kind(j) == "else":
                j += 1
                if kind(j) == "if":
                    j = stmt(j)                    # chain, no extra scope
                else:
                    j = body(j, dict(cur))
            return j
        if k == "while":
            reads, j = cond(i)
            return body(j, dict(cur), True, reads)
        if k == "for":
            return for_stmt(i)
        if k == "do":
            j = body(i + 1, dict(cur))
            if kind(j) == "while":
                reads, j = cond(j)
                if kind(j) == ";":
                    j += 1
            return j
        if k == "ID" and kind(i + 1) in ("+", "-", "*", "/", "%") and \
                kind(i + 2) == "=":
            nm = toks[i]["text"]
            mark_write(nm)
            nd = new_node("def", nm, i, i + 2)
            ident_node[i] = nd
            old = cur.get(nm)
            reads, j = expr_reads(i + 3, (";", "}"))
            nodes[nd]["deps"] = {read_def[r] for r in reads if r in read_def}
            if old is not None:
                nodes[nd]["deps"].add(old)
            cur[nm] = nd
            if j < n and kind(j) == ";":
                j += 1
            return j
        if k == "ID" and kind(i + 1) == "=":
            nm = toks[i]["text"]
            mark_write(nm)
            nd = new_node("def", nm, i, i + 1)
            ident_node[i] = nd
            reads, j = expr_reads(i + 2, (";", "}"))
            nodes[nd]["deps"] = {read_def[r] for r in reads if r in read_def}
            cur[nm] = nd
            if j < n and kind(j) == ";":
                j += 1
            return j
        return i + 1

    # ---- top level: function definitions
    i = 0
    while i < n:
        if kind(i) in TYPE_KW and kind(i + 1) == "ID" and kind(i + 2) == "(":
            i += 3
            while i < n and kind(i) != ")":
                if kind(i) in TYPE_KW and kind(i + 1) == "ID":
                    nm = toks[i + 1]["text"]
                    nd = new_node("def", nm, i + 1, i + 1)
                    ident_node[i + 1] = nd
                    cur[nm] = nd
                    i += 2
                else:
                    i += 1
            if i < n:
                i += 1                             # ')'
            if i < n and kind(i) == "{":
                i = block(i, dict(cur))
            cur.clear()                            # params and locals go away
            continue
        i += 1

    # ---- selection
    sel_tok = None
    for t in range(n):
        if toks[t]["start"] <= cursor < toks[t]["end"]:
            sel_tok = t
            break
    value = None
    if sel_tok is not None:
        if sel_tok in ident_node:
            value = ident_node[sel_tok]
        elif sel_tok in read_def:
            value = read_def[sel_tok]

    hit = set()
    if value is not None:
        adj = {i2: set() for i2 in range(len(nodes))}
        radj = {i2: set() for i2 in range(len(nodes))}
        for i2, nd in enumerate(nodes):
            for d in nd["deps"]:
                adj[i2].add(d)
                radj[d].add(i2)
        frontier, seen = [value], {value}
        while frontier:
            v = frontier.pop()
            for w in (adj[v] if mode == "upstream" else radj[v]):
                if w not in seen:
                    seen.add(w)
                    frontier.append(w)
        for t in range(n):
            if not is_ident(toks[t]):
                continue
            if t in read_def and read_def[t] in seen:
                hit.add(t)
            if t in ident_node and ident_node[t] in seen:
                hit.add(t)
        if sel_tok is not None and is_ident(toks[sel_tok]):
            hit.add(sel_tok)

    labels = [0] * len(src)
    for t in range(n):
        if is_ident(toks[t]) and t in hit:
            for k2 in range(toks[t]["start"], toks[t]["end"]):
                labels[k2] = 1
    if sel_tok is not None and is_ident(toks[sel_tok]):
        for k2 in range(toks[sel_tok]["start"], toks[sel_tok]["end"]):
            labels[k2] = 2
    spans = [(toks[t]["start"], toks[t]["end"]) for t in range(n)
             if is_ident(toks[t])]
    return dict(labels=labels, spans=spans, selected_token=sel_tok,
                value=value, n_nodes=len(nodes))
