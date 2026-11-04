"""FlowLens neural engine.

Architecture: a two-sweep hard-state recurrent network with an external
identifier memory, followed by a value-graph built by tensor algebra and a
transitive closure by repeated matmul.

    bytes -> [encoding layer]            W_byte_class, W_alpha
          -> [lexer RNN, 9 states]       W_lex
          -> [tokeniser counters]        (network registers)
          -> [spelling attention]        exact identifier equality
          -> [grammar RNN, 12 states]    W_gsm  -> def/read events
          -> [value graph]               tensor algebra over registers
          -> [closure]                   repeated boolean matmul
          -> per-byte labels

Nothing in this file inspects C text.  Every predicate is a matmul with a
tensor from the frozen weight file; every state is a one-hot produced by
winner-take-all over a linear map.  The only C-shaped data in the system is
inside weights/flowlens_weights.npz.
"""

import json
import os
import time

import numpy as np

from . import ops
from .ops import Ctx, F

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEIGHTS = os.path.join(ROOT, "weights", "flowlens_weights.npz")
MANIFEST = os.path.join(ROOT, "weights", "manifest.json")

# value-node id partition: 1..63 definitions, 64..95 return sinks
DEF_BASE = 1
RET_BASE = 128


class Unsupported(Exception):
    pass


class FlowLens:
    def __init__(self, weights_path=WEIGHTS):
        z = np.load(weights_path)
        self.w = {k: z[k].astype(F) for k in z.files}
        with open(MANIFEST) as f:
            self.manifest = json.load(f)
        self.L = self.manifest["limits"]
        w = self.w
        # wiring (architecture, not knowledge): stack the decoder vectors
        self.W_out = np.stack([
            w["v_out_read"], w["v_out_assign"], w["v_out_declinit"],
            w["v_out_declterm"], w["v_out_paramwrite"], w["v_out_retend"],
            w["v_out_barrier"], w["v_out_anomaly"], w["v_out_compound"],
            w["v_out_commit"], w["v_open_if"], w["v_open_else"],
            w["v_open_while"], w["v_open_plain"], w["v_out_close"],
            w["v_open_for"], w["v_open_do"], w["v_open_if_u"],
            w["v_open_else_u"], w["v_open_while_u"], w["v_open_for_u"],
            w["v_open_do_u"], w["v_out_stepinc"],
        ])
        self.GS = {n: i for i, n in enumerate(self.manifest["grammar_states"])}
        self.FC = {n: i for i, n in enumerate(self.manifest["token_classes"])}
        self.idx = dict(read=0, assign=1, declinit=2, declterm=3,
                        paramwrite=4, retend=5, barrier=6, anomaly=7,
                        compound=8, commit=9, open_if=10, open_else=11,
                        open_while=12, open_plain=13, close=14,
                        open_for=15, open_do=16, open_if_u=17,
                        open_else_u=18, open_while_u=19, open_for_u=20,
                        open_do_u=21, stepinc=22)
        self.KIND = dict(none=0, plain=1, if_=2, else_=3, while_=4,
                         for_=5, do_=6)
        self._gsname = self.manifest["grammar_states"]
        self._fcname = {i: n for n, i in self.FC.items()}
        self._stats = dict(params_dense=self.manifest["dense_params"],
                           params_nonzero=self.manifest["nonzero_params"],
                           weights_bytes=self.manifest["serialized_bytes"])

    # ------------------------------------------------------------------
    # stage 0+1: bytes -> class, character code, lexer states
    # ------------------------------------------------------------------
    def _lex(self, ctx, B):
        """B: (N,256) byte one-hot.  Returns class probs C (N,26),
        lexer state before/after each byte, and the character code."""
        w = self.w
        C = ops.mm(ctx, B, w["W_byte_class"])          # (N,26) one-hot
        A = ops.mm(ctx, B, w["W_alpha"])               # (N,64)
        N = B.shape[0]
        NL = self.L["NL"]
        s_in = np.zeros((N, NL), dtype=F)
        s_out = np.zeros((N, NL), dtype=F)
        h = ops.onehot(0, NL)                          # CODE
        for t in range(N):
            s_in[t] = h
            basis = ops.outer(ctx, h, C[t]).reshape(-1)  # (NL*26,)
            h = ops.wta(ctx, ops.mm(ctx, w["W_lex"], basis))
            s_out[t] = h
        return C, A, s_in, s_out

    # ------------------------------------------------------------------
    # stage 2+3: tokenisation, spelling, keyword match, slot assignment
    # ------------------------------------------------------------------
    def _tokens(self, ctx, C, A, s_in, s_out):
        w, L = self.w, self.L
        N = C.shape[0]
        TMAX, P, S = L["TMAX"], L["P"], L["S"]

        in_code = ops.thresh(ctx, ops.mm(ctx, s_in, w["v_lex_code"]))
        is_delim = ops.thresh(ctx, ops.mm(ctx, C, w["v_cls_quote"]))
        # a byte that opens a comment is not a token: opener = s_in W s_out
        opener = ops.thresh(
            ctx, (ops.mm(ctx, s_in, w["W_opener"]) * s_out).sum(axis=1))
        code_b = ops.mul(ctx, ops.mul(ctx, in_code, 1.0 - is_delim),
                         1.0 - opener)                          # (N,)
        idch = ops.mul(ctx, code_b,
                       ops.thresh(ctx, ops.mm(ctx, C, w["v_cls_idchar"])))
        dig = ops.mul(ctx, code_b,
                      ops.thresh(ctx, ops.mm(ctx, C, w["v_cls_digit"])))
        punct = ops.mul(ctx, code_b,
                        ops.thresh(ctx, ops.mm(ctx, C, w["v_cls_punct"])))

        prev_id = np.concatenate([[0.0], idch[:-1]]).astype(F)
        prev_dig = np.concatenate([[0.0], dig[:-1]]).astype(F)
        ident_start = ops.mul(ctx, idch, 1.0 - prev_id)
        num_start = ops.mul(ctx, ops.mul(ctx, dig, 1.0 - prev_dig),
                            1.0 - prev_id)
        tok_start = np.clip(ident_start + num_start + punct, 0, 1).astype(F)

        tokb = np.clip(idch + dig + punct, 0, 1)   # byte belongs to a token
        tok = np.zeros(N, dtype=np.int32)       # 1-based token index, 0 none
        tok_start_b = {}
        cpos = np.zeros(N, dtype=np.int32)
        nt = 0
        cc = 0
        for t in range(N):
            if tok_start[t] > 0.5:
                nt += 1
                if nt > TMAX:
                    raise Unsupported(f"token limit {TMAX} exceeded")
                tok_start_b[nt] = t
                cc = 0
            if tokb[t] > 0.5:
                tok[t] = nt
            if idch[t] > 0.5:
                cpos[t] = cc
                cc += 1
        if nt == 0:
            raise Unsupported("no tokens")
        T = nt

        # token span / spelling / class counts
        start_byte = np.full(T + 1, -1, dtype=np.int32)
        end_byte = np.zeros(T + 1, dtype=np.int32)
        for k, v in tok_start_b.items():
            start_byte[k] = v
        for t in range(N):
            if tok[t] > 0:
                end_byte[tok[t]] = t + 1

        spell = np.zeros((TMAX, P, L["A"]), dtype=F)
        counts = np.zeros((TMAX, L["NC"]), dtype=F)
        startcls = np.zeros((TMAX, L["NC"]), dtype=F)
        trunc = np.zeros(TMAX, dtype=F)
        live = np.flatnonzero(tok > 0)
        np.add.at(counts, tok[live] - 1, C[live])   # scatter-add over tokens
        ctx.ops += 1
        ctx.elem += live.size * L["NC"]
        for t in live:
            k = tok[t]
            if idch[t] > 0.5:
                p = cpos[t]
                if p < P:
                    spell[k - 1, p, :] = A[t]
                else:
                    trunc[k - 1] = 1.0
        for k in range(1, T + 1):
            startcls[k - 1] = C[start_byte[k]]

        # work on the live token rows only; TMAX is an upper bound, not a cost
        spell = spell[:T]
        startcls = startcls[:T]
        trunc = trunc[:T]
        occ = spell.sum(axis=2)                                 # (T,P)

        # keyword match: AND over positions of an exact 64-way dot product
        dot = np.einsum("tpa,kpa->tkp", spell, w["W_kw_code"])
        kwocc = w["W_kw_code"].sum(axis=2)                      # (K,P)
        both0 = (1.0 - occ)[:, None, :] * (1.0 - kwocc)[None, :, :]
        kw = np.prod(ops.add(ctx, dot, both0), axis=2)          # (T,K)
        kw = ops.thresh(ctx, kw, 0.5)

        is_alpha_start = ops.thresh(
            ctx, ops.mm(ctx, startcls, w["v_cls_alpha"] + w["v_cls_us"]))
        is_ident = ops.mul(ctx, is_alpha_start, 1.0 - trunc)
        is_kw_type = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_type"]))
        is_kw_ret = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_ret"]))
        is_kw_if = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_if"]))
        is_kw_else = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_else"]))
        is_kw_while = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_while"]))
        is_kw_for = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_for"]))
        is_kw_do = ops.thresh(ctx, ops.mm(ctx, kw, w["v_kw_do"]))
        is_kw = np.clip(is_kw_type + is_kw_ret + is_kw_if + is_kw_else
                        + is_kw_while + is_kw_for + is_kw_do, 0, 1).astype(F)
        is_num = ops.thresh(ctx, ops.mm(ctx, startcls, w["v_cls_digit"]))

        # token class one-hot (T,13)
        cls = startcls @ w["W_tokF"]
        cls[:, 0] = is_ident * (1.0 - is_kw)
        cls[:, 1] = is_kw_type * is_ident
        cls[:, 2] = is_kw_ret * is_ident
        cls[:, 3] = is_kw_if * is_ident
        cls[:, 4] = is_kw_else * is_ident
        cls[:, 5] = is_kw_while * is_ident
        cls[:, 6] = is_kw_for * is_ident
        cls[:, 7] = is_kw_do * is_ident
        cls[:, 8] = is_num
        cls[:, 17] = np.clip(1.0 - cls[:, :17].sum(axis=1), 0, 1)
        ctx.ops += 1

        # ---- spelling attention -> identifier slots -------------------
        # Attention runs over the identifier rows only (a gather by a
        # network-computed mask): cost is O(M^2) in identifier tokens.
        rows = np.flatnonzero(is_ident > 0.5)
        M = rows.size
        ssp = spell[rows]
        socc = occ[rows]
        eq = np.ones((M, M), dtype=F)
        for p in range(P):
            d = ops.mm(ctx, ssp[:, p, :], ssp[:, p, :].T)
            d = ops.add(ctx, d, ops.outer(ctx, 1.0 - socc[:, p],
                                          1.0 - socc[:, p]))
            eq = ops.mul(ctx, eq, ops.thresh(ctx, d))
        earlier = ops.mul(ctx, eq, w["GT"][:M, :M])              # u < t
        has_prev = ops.thresh(ctx, earlier.sum(axis=1), 0.5)
        first = 1.0 - has_prev
        rank = np.cumsum(first).astype(F)          # 1-based order of first use
        # retrieve the rank of a token's canonical first occurrence: a
        # content-addressed lookup, computed as one matmul over the
        # equal-and-first indicator rows.
        canon = ops.mul(ctx, eq, first[None, :])
        slot_id = ops.mm(ctx, canon, rank[:, None]).reshape(-1)
        slot_id = np.where(slot_id <= S - 1, slot_id, 0.0).astype(F)
        slot_oh = np.zeros((T, S), dtype=F)
        for k, t in enumerate(rows):                            # index encode
            slot_oh[t, int(slot_id[k])] = 1.0

        return dict(T=T, tok=tok, start_byte=start_byte, end_byte=end_byte,
                    spell=spell, occ=occ, cls=cls, kw=kw, slot_oh=slot_oh,
                    is_ident=is_ident, in_code=code_b, trunc=trunc)

    # ------------------------------------------------------------------
    # stage 4: grammar RNN with definition memory
    # ------------------------------------------------------------------
    def _grammar(self, ctx, tk):
        """Token-level recurrent scan with definition memory and block stack.

        Per token the state is a one-hot grammar state plus a block stack held
        in memory: for each open block an entry snapshot of the definition
        memory, the set of slots written inside it, the definitions created
        inside it, and (for loops) the definitions read by the header.
        Closing a block emits a merge (phi) definition per written slot, which
        is what makes a conditional write non-destructive.
        """
        w, L = self.w, self.L
        T, S, NODES = tk["T"], L["S"], L["NODES"]
        NS, NF = L["NS"], L["NF"]
        DMAX = L["DMAX"]
        cls = tk["cls"]
        K = self.KIND
        I = self.idx

        s = ops.onehot(0, NS)
        CD = np.zeros((S, NODES), dtype=F)
        entry = np.zeros((DMAX + 1, S, NODES), dtype=F)
        dirty = np.zeros((DMAX + 1, S), dtype=F)
        bodyd = np.zeros((DMAX + 1, NODES), dtype=F)
        hdr = np.zeros((DMAX + 1, NODES), dtype=F)
        stepd = np.zeros((DMAX + 1, NODES), dtype=F)
        braced = np.zeros(DMAX + 1, dtype=np.int32)
        kind = np.zeros(DMAX + 1, dtype=np.int32)
        def_decl = np.zeros(NODES, dtype=bool)
        def_depth = np.zeros(NODES, dtype=np.int32)
        depth = 0
        infor = 0.0
        dop = 0.0
        instep = 0.0
        pend_hdr = np.zeros(NODES, dtype=F)
        pend_step = np.zeros(NODES, dtype=F)
        extra = np.zeros((NODES, NODES), dtype=F)

        last_tok = -1
        last_slot = np.zeros(S, dtype=F)
        stmt = 0
        ndef = 0
        nret = 0
        read_mask = np.zeros(T, dtype=F)
        read_slot = np.zeros((T, S), dtype=F)
        read_def = np.zeros((T, NODES), dtype=F)
        def_slot = np.zeros((NODES, S), dtype=F)
        def_anchor = np.full(NODES, -1, dtype=np.int32)
        def_apply = np.full(NODES, -1, dtype=np.int32)
        def_stmt = np.zeros(NODES, dtype=F)
        ret_apply = np.full(NODES, -1, dtype=np.int32)
        ret_stmt = np.zeros(NODES, dtype=F)
        anchor_of = np.full(T, -1, dtype=np.int32)
        stmt_at = np.zeros(T, dtype=F)
        tok_role = np.zeros(T, dtype=np.int32)
        tok_slot = np.zeros(T, dtype=np.int32)
        anomalies = 0
        compound_pending = False
        pending = None
        last_closed = K["none"]
        self_dep = np.zeros((NODES, NODES), dtype=F)

        def new_def(anchor, apply_t, slot_v, stmt_v, decl=False):
            nonlocal ndef, anomalies
            ndef += 1
            d = ndef
            if d >= RET_BASE:
                raise Unsupported("definition limit exceeded")
            def_slot[d] = slot_v
            def_anchor[d] = anchor
            def_apply[d] = apply_t
            def_stmt[d] = stmt_v
            def_decl[d] = decl
            def_depth[d] = depth
            sl = int(np.argmax(slot_v))
            prev = int(np.argmax(CD[sl])) if CD[sl].sum() > 0.5 else 0
            if decl and prev > 0 and def_decl[prev] and def_depth[prev] != depth:
                anomalies += 1           # declared name shadows a live one
            dirty[depth, sl] = 1.0
            bodyd[depth, d] = 1.0
            return d

        def open_block(k, hdr_vec=None, is_braced=True):
            nonlocal depth, anomalies, last_closed, pend_step, stmt
            if k == K["else_"] and last_closed != K["if_"]:
                anomalies += 1          # 'else' with no preceding 'if'
            if depth > 0 and braced[depth] == 0:
                anomalies += 1          # block nested inside a one-statement body
            if not is_braced:
                stmt += 1               # the body is a statement of its own
            last_closed = K["none"]
            depth += 1
            if depth > DMAX:
                raise Unsupported("block nesting limit %d exceeded" % DMAX)
            entry[depth] = CD
            dirty[depth] = 0.0
            bodyd[depth] = 0.0
            stepd[depth] = pend_step
            pend_step = np.zeros(NODES, dtype=F)
            hdr[depth] = hdr_vec if hdr_vec is not None else np.zeros(NODES, dtype=F)
            braced[depth] = 1 if is_braced else 0
            kind[depth] = k

        def close_block(t):
            nonlocal depth, CD, extra, last_closed, dop
            k = int(kind[depth])
            last_closed = k
            for sl in np.flatnonzero(dirty[depth] > 0.5):
                d = new_def(t, t, ops.onehot(int(sl), S), stmt)
                # merge: the value after the block may be the entry value
                # (block not taken) or the value written inside it
                extra[d] = np.clip(entry[depth][int(sl)] + CD[int(sl)], 0, 1)
                CD = ops.row_scatter(ctx, CD, ops.onehot(int(sl), S),
                                     ops.onehot(d, NODES))
                bodyd[depth, d] = 1.0
            if k in (K["while_"], K["for_"]):
                # loop-carried dependence, restricted to the slots the body
                # writes: the header test of that slot at the next iteration
                # sees the value the loop produced for it
                same_slot = ops.mm(ctx, def_slot, def_slot.T)
                written = ops.mm(ctx, def_slot,
                                 np.asarray(dirty[depth]).reshape(-1, 1).astype(F))
                carried = ops.mul(ctx, same_slot, written)
                extra = np.clip(extra + ops.mul(
                    ctx, ops.outer(ctx, hdr[depth], bodyd[depth]), carried),
                    0, 1)
                if k == K["for_"]:
                    # the step clause of the next iteration follows this body
                    extra = np.clip(extra + ops.mul(
                        ctx, ops.outer(ctx, stepd[depth], bodyd[depth]),
                        carried), 0, 1)
                    extra = np.clip(extra + ops.mul(
                        ctx, ops.outer(ctx, hdr[depth], stepd[depth]),
                        carried), 0, 1)
            elif k == K["do_"]:
                dop = 1.0               # the trailing 'while' comes next
            dirty[depth - 1] = np.clip(dirty[depth - 1] + dirty[depth], 0, 1)
            bodyd[depth - 1] = np.clip(bodyd[depth - 1] + bodyd[depth], 0, 1)
            kind[depth] = K["none"]
            depth -= 1
            if depth == 0:
                # a function body ended: its parameters and locals go out of
                # scope, so a later function cannot bind them by spelling
                CD = np.zeros((S, NODES), dtype=F)

        nxt = np.zeros_like(cls)
        nxt[:-1] = cls[1:]
        NBIT = 16

        for t in range(T):
            c = cls[t]
            stmt_at[t] = stmt
            top = 1.0 if depth == 0 else 0.0
            b_oh = np.zeros(NBIT, dtype=F)
            b_oh[int(top + 2.0 * infor + 4.0 * dop + 8.0 * instep)] = 1.0
            s0_ = s
            sc = ops.outer(ctx, s, c).reshape(-1)
            basis = ops.outer(ctx, sc, b_oh).reshape(-1)
            f = ops.mm(ctx, self.W_out, basis).reshape(-1)
            a2 = ops.mm(ctx, self.w["v_anom2"][None, :],
                        ops.outer(ctx, sc, nxt[t]).reshape(-1))[0]
            if f[I["anomaly"]] > 0.5 or a2 > 0.5:
                anomalies += 1
            if f[I["compound"]] > 0.5:
                compound_pending = True

            if f[I["read"]] > 0.5:               # read
                rd = ops.row_gather(ctx, CD, tk["slot_oh"][t])
                read_mask[t] = 1.0
                read_slot[t] = tk["slot_oh"][t]
                read_def[t] = rd
                tok_role[t] = 1
                tok_slot[t] = int(np.argmax(tk["slot_oh"][t]))
                if (s[self.GS["WHILE_COND"]] > 0.5
                        or s[self.GS["FOR_COND"]] > 0.5):
                    pend_hdr = np.clip(pend_hdr + rd, 0, 1)

            if f[I["assign"]] > 0.5 or f[I["declinit"]] > 0.5:
                if last_tok >= 0:
                    d = new_def(last_tok, t, last_slot, stmt,
                                decl=f[I["declinit"]] > 0.5)
                    pending = (last_slot, d)
                    anchor_of[last_tok] = d
                    tok_role[last_tok] = 2
                    tok_slot[last_tok] = int(np.argmax(last_slot))
                    if compound_pending and f[I["assign"]] > 0.5:
                        extra[d] = ops.row_gather(ctx, CD, last_slot)
                    compound_pending = False
            elif f[I["paramwrite"]] > 0.5:       # parameter
                d = new_def(t, t, tk["slot_oh"][t], stmt, decl=True)
                anchor_of[t] = d
                tok_role[t] = 2
                tok_slot[t] = int(np.argmax(tk["slot_oh"][t]))
                CD = ops.row_scatter(ctx, CD, tk["slot_oh"][t],
                                     ops.onehot(d, NODES))
            elif f[I["declterm"]] > 0.5:         # declaration without init
                if last_tok >= 0:
                    d = new_def(last_tok, t, last_slot, stmt, decl=True)
                    pending = (last_slot, d)
                    anchor_of[last_tok] = d
                    tok_role[last_tok] = 2
                    tok_slot[last_tok] = int(np.argmax(last_slot))

            if f[I["stepinc"]] > 0.5 and last_tok >= 0:   # ++/-- in the step
                d = new_def(last_tok, t, last_slot, stmt)
                anchor_of[last_tok] = d
                tok_role[last_tok] = 2
                tok_slot[last_tok] = int(np.argmax(last_slot))
                extra[d] = ops.row_gather(ctx, CD, last_slot)
                CD = ops.row_scatter(ctx, CD, last_slot, ops.onehot(d, NODES))
                pend_step = np.clip(pend_step + ops.onehot(d, NODES), 0, 1)

            if f[I["retend"]] > 0.5:             # return sink
                nret += 1
                nid = RET_BASE + nret - 1
                if nid >= NODES:
                    raise Unsupported("return-node limit exceeded")
                ret_apply[nid] = t
                ret_stmt[nid] = stmt

            if f[I["commit"]] > 0.5:              # commit point
                compound_pending = False
                if pending is not None:
                    CD = ops.row_scatter(ctx, CD, pending[0],
                                         ops.onehot(pending[1], NODES))
                    pending = None
            if f[I["open_if"]] > 0.5:
                open_block(K["if_"])
            elif f[I["open_else"]] > 0.5:
                open_block(K["else_"])
            elif f[I["open_while"]] > 0.5:
                open_block(K["while_"], pend_hdr)
                pend_hdr = np.zeros(NODES, dtype=F)
            elif f[I["open_plain"]] > 0.5:
                open_block(K["plain"])
            elif f[I["open_for"]] > 0.5:
                open_block(K["for_"], pend_hdr)
                pend_hdr = np.zeros(NODES, dtype=F)
            elif f[I["open_do"]] > 0.5:
                open_block(K["do_"])
            elif f[I["open_if_u"]] > 0.5:         # single-statement bodies
                open_block(K["if_"], is_braced=False)
            elif f[I["open_else_u"]] > 0.5:
                open_block(K["else_"], is_braced=False)
            elif f[I["open_while_u"]] > 0.5:
                open_block(K["while_"], pend_hdr, is_braced=False)
                pend_hdr = np.zeros(NODES, dtype=F)
            elif f[I["open_for_u"]] > 0.5:
                open_block(K["for_"], pend_hdr, is_braced=False)
                pend_hdr = np.zeros(NODES, dtype=F)
            elif f[I["open_do_u"]] > 0.5:
                open_block(K["do_"], is_braced=False)

            if f[I["close"]] > 0.5 and depth > 0:  # closing brace
                close_block(t)
            # a ';' that is a clause separator of a for header does not end
            # a one-statement body
            hdr_sep = infor > 0.5 or s[self.GS["FOR_COND"]] > 0.5
            if (depth > 0 and braced[depth] == 0 and f[I["barrier"]] > 0.5
                    and not hdr_sep):
                close_block(t)
            if f[I["barrier"]] > 0.5:
                stmt += 1

            if c[0] > 0.5:                       # IDENT
                last_tok = t
                last_slot = tk["slot_oh"][t]

            s = ops.wta(ctx, ops.mm(ctx, w["W_gsm"], basis))
            ns = int(np.argmax(s))
            if ns == self.GS["FOR_HEAD"]:
                infor = 1.0
                pend_step = np.zeros(NODES, dtype=F)
            elif ns in (self.GS["FOR_COND"], self.GS["FOR_PEND"]):
                infor = 0.0
            if ns in (self.GS["FOR_STEP"], self.GS["FOR_STEP_IDENT"]):
                instep = 1.0
            elif ns == self.GS["FOR_PEND"]:
                instep = 0.0
            if ns == self.GS["DO_WHILE_COND"]:
                dop = 0.0
            if os.environ.get("FL_DEBUG"):
                print("t=%3d %-8s in=%-12s out=%-14s d=%d for=%d do=%d "
                      "step=%d f7=%d a2=%d anom=%d" % (
                          t, self._fcname.get(int(np.argmax(c)), "?"),
                          self._gsname[int(np.argmax(s0_))],
                          self._gsname[ns], depth, infor, dop, instep,
                          f[7] > 0.5, a2 > 0.5, anomalies))

        return dict(read_mask=read_mask, read_slot=read_slot,
                    read_def=read_def, def_slot=def_slot,
                    def_anchor=def_anchor, def_apply=def_apply,
                    def_stmt=def_stmt, ret_apply=ret_apply,
                    ret_stmt=ret_stmt, anchor_of=anchor_of,
                    read_def_idx=np.array(
                        [int(np.argmax(read_def[t])) for t in range(T)],
                        dtype=np.int32),
                    n_def=ndef, n_ret=nret, anomalies=anomalies,
                    tok_role=tok_role, tok_slot=tok_slot,
                    stmt_of_tok=stmt_at, self_dep=self_dep,
                    extra_edge=extra)

    # ------------------------------------------------------------------
    # stage 5: value graph + closure
    # ------------------------------------------------------------------
    def _graph(self, ctx, tk, gr):
        w, L = self.w, self.L
        T, NODES = tk["T"], L["NODES"]
        stmt_oh_tok = np.zeros((T, T + 2), dtype=F)     # stmt id one-hots
        stmt_ids = self._stmt_ids(gr, T)
        for t in range(T):
            stmt_oh_tok[t, min(int(stmt_ids[t]), T + 1)] = 1.0

        nodes = np.arange(NODES)
        valid = np.zeros(NODES, dtype=F)
        apply_tok = np.full(NODES, 0, dtype=np.int32)
        node_stmt = np.zeros(NODES, dtype=F)
        for d in range(DEF_BASE, NODES):
            if gr["def_apply"][d] >= 0:
                valid[d] = 1.0
                apply_tok[d] = gr["def_apply"][d]
                node_stmt[d] = gr["def_stmt"][d]
            if gr["ret_apply"][d] >= 0:
                valid[d] = 1.0
                apply_tok[d] = gr["ret_apply"][d]
                node_stmt[d] = gr["ret_stmt"][d]

        apply_oh = np.zeros((NODES, T), dtype=F)
        for d in range(NODES):
            if valid[d] > 0.5:
                apply_oh[d, apply_tok[d]] = 1.0
        node_stmt_oh = np.zeros((NODES, T + 2), dtype=F)
        for d in range(NODES):
            if valid[d] > 0.5:
                node_stmt_oh[d, min(int(node_stmt[d]), T + 1)] = 1.0

        # "read token later than the definition point": GT[j,i] = 1 iff j > i,
        # so the definition row times GT^T selects tokens i > apply.
        after = ops.mm(ctx, apply_oh, w["GT"][:T, :T].T)       # (NODES,T)
        same_stmt = ops.mm(ctx, node_stmt_oh, stmt_oh_tok.T)   # (NODES,T)
        cand = ops.mul(ctx, ops.mul(ctx, after, same_stmt),
                       gr["read_mask"][None, :])
        cand = ops.mul(ctx, cand, valid[:, None])
        rd_oh = np.zeros((T, NODES), dtype=F)                  # read->def
        for t in range(T):
            rd_oh[t, int(gr["read_def_idx"][t])] = 1.0
        edge = ops.mm(ctx, cand, rd_oh)                        # (NODES,NODES)
        edge = np.clip(edge + gr["self_dep"] + gr["extra_edge"], 0, 1).astype(F)
        np.fill_diagonal(edge, 0.0)
        return edge, valid, stmt_ids

    @staticmethod
    def _stmt_ids(gr, T):
        """Statement register values per token (decoded for tensor indexing)."""
        return gr["stmt_of_tok"]

    # ------------------------------------------------------------------
    # stage 6: labels for the selected occurrence
    # ------------------------------------------------------------------
    def analyze(self, src, cursor, mode="downstream"):
        with np.errstate(all="ignore"):
            return self._analyze(src, cursor, mode)

    def _analyze(self, src, cursor, mode="downstream"):
        ctx = Ctx()
        if isinstance(src, str):
            src = src.encode()
        N = len(src)
        if N == 0:
            raise Unsupported("empty buffer")
        if N > self.L["NMAXB"]:
            raise Unsupported(
                f"source exceeds {self.L['NMAXB']} byte limit")
        B = np.zeros((N, 256), dtype=F)
        B[np.arange(N), np.frombuffer(src, dtype=np.uint8)] = 1.0
        t0 = time.perf_counter()
        C, A, s_in, s_out = self._lex(ctx, B)
        tk = self._tokens(ctx, C, A, s_in, s_out)
        t1 = time.perf_counter()
        gr = self._grammar(ctx, tk)
        edge, valid, stmt_ids = self._graph(ctx, tk, gr)
        R = ops.reach(ctx, edge, self.L["KCLOSURE"])
        t2 = time.perf_counter()

        T = tk["T"]
        sel = self._select(tk, cursor)
        value = self._value_of(gr, tk, sel)
        labels = np.zeros(N, dtype=np.int8)
        node_set = np.zeros(self.L["NODES"], dtype=F)
        ntok = 0
        if value > 0:
            if mode == "upstream":
                node_set = np.clip(R[value] + ops.onehot(value, self.L["NODES"]),
                                   0, 1)
            else:
                node_set = np.clip(R[:, value] +
                                   ops.onehot(value, self.L["NODES"]), 0, 1)
            hit = np.zeros(T, dtype=bool)
            for t in range(T):
                if mode == "upstream":
                    rd = gr["read_def_idx"][t]
                    if gr["read_mask"][t] > 0.5 and rd > 0 and node_set[rd] > 0.5:
                        hit[t] = True
                else:
                    rd = gr["read_def_idx"][t]
                    if gr["read_mask"][t] > 0.5 and rd > 0 and node_set[rd] > 0.5:
                        hit[t] = True
                a = gr["anchor_of"][t]
                if a > 0 and node_set[a] > 0.5:
                    hit[t] = True
            if sel >= 0:
                hit[sel] = True
            for t in range(T):
                if hit[t] and tk["cls"][t, 0] > 0.5:
                    s0 = tk["start_byte"][t + 1]
                    e0 = tk["end_byte"][t + 1]
                    labels[s0:e0] = 1
                    ntok += 1
        # the selected occurrence is always marked, even when it carries no
        # value (e.g. a function name): the cursor highlight is not a claim
        # about flow.
        if sel >= 0 and tk["cls"][sel, 0] > 0.5:
            labels[tk["start_byte"][sel + 1]:tk["end_byte"][sel + 1]] = 2

        out = dict(
            labels=labels.tolist(),
            selected_token=int(sel),
            selected_value=int(value),
            mode=mode,
            tokens=tk["T"],
            anomalies=int(gr["anomalies"]),
            n_def=int(gr["n_def"]),
            n_ret=int(gr["n_ret"]),
            relevant_tokens=int(ntok),
            macs=int(ctx.macs), elem_ops=int(ctx.elem), op_count=int(ctx.ops),
            encode_ms=(t1 - t0) * 1000.0, infer_ms=(t2 - t1) * 1000.0,
            spans=self._spans(tk, gr, labels),
        )
        return out

    @staticmethod
    def _select(tk, cursor):
        T = tk["T"]
        for t in range(T):
            s0 = tk["start_byte"][t + 1]
            e0 = tk["end_byte"][t + 1]
            if s0 <= cursor < e0:
                return t
        # nearest previous token
        best = -1
        for t in range(T):
            if tk["start_byte"][t + 1] <= cursor:
                best = t
        return best

    @staticmethod
    def _value_of(gr, tk, sel):
        if sel < 0:
            return 0
        if gr["anchor_of"][sel] > 0:
            return int(gr["anchor_of"][sel])
        if gr["read_mask"][sel] > 0.5:
            return int(gr["read_def_idx"][sel])
        return 0

    @staticmethod
    def _spans(tk, gr, labels):
        out = []
        for t in range(tk["T"]):
            s0 = int(tk["start_byte"][t + 1])
            e0 = int(tk["end_byte"][t + 1])
            if e0 <= s0:
                continue
            lab = int(labels[s0]) if e0 > s0 else 0
            out.append(dict(tok=t, start=s0, end=e0, label=lab,
                            role=int(gr["tok_role"][t]),
                            slot=int(gr["tok_slot"][t])))
        return out

    def stats(self):
        return dict(self._stats)
