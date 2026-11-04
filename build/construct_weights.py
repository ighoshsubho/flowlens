"""FlowLens weight construction.

Every tensor below is derived analytically from the design in
docs/ARCHITECTURE.md.  There is no gradient descent, no search, no fitting:
each block is written by a closed-form rule and the numeric result is saved
to weights/flowlens_weights.npz.

This script never reads a program being analysed.  The only C knowledge in
it is the grammar it encodes: the keyword codebook and the lexer/parser
transition tables.  Those are design constants, identical for every input.

Run:  python3 build/construct_weights.py
"""

import json
import os
import numpy as np

F = np.float32
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "weights", "flowlens_weights.npz")

# ---------------------------------------------------------------------------
# Finite limits (documented, enforced by the runtime)
# ---------------------------------------------------------------------------
L = dict(
    NMAXB=2048,   # source bytes
    TMAX=512,     # tokens
    P=16,         # identifier characters retained
    A=64,         # alphabet size for the character code
    S=48,         # identifier slots (distinct spellings tracked)
    NODES=192,    # value nodes: 127 definitions (incl. merges) + 65 returns
    KCLOSURE=8,   # dataflow chain depth
    DMAX=8,       # nested control-flow blocks
    NC=27,        # byte classes
    NL=9,         # lexer states
    NS=26,        # grammar states (17 statement + 9 loop)
    NF=18,        # token classes
    NKW=17,       # keyword codebook entries
    NC2=169,      # 13*13 lookahead class pairs
)

# ---------------------------------------------------------------------------
# Block 1: byte -> class one-hot.  W_byte_class is 256 x 26.
# Class is a partition of the byte alphabet: exactly one 1 per row.
# ---------------------------------------------------------------------------
CLASS_NAMES = [
    "SPACE", "NL", "ALPHA", "DIGIT", "US", "QUOTE", "SQUOTE", "BACKSLASH",
    "SLASH", "STAR", "LBRACE", "RBRACE", "LPAREN", "RPAREN", "SEMI", "COMMA",
    "EQ", "PLUS", "MINUS", "LT", "GT", "BANG", "AMP", "BAR", "DOT", "OTHER", "PCT",
 ]
CL = {n: i for i, n in enumerate(CLASS_NAMES)}

_SINGLE = {
    ord(" "): "SPACE", 9: "SPACE", 13: "SPACE",
    10: "NL",
    ord("_"): "US", ord('"'): "QUOTE", ord("'"): "SQUOTE",
    ord("\\"): "BACKSLASH", ord("/"): "SLASH", ord("*"): "STAR",
    ord("{"): "LBRACE", ord("}"): "RBRACE", ord("("): "LPAREN",
    ord(")"): "RPAREN", ord(";"): "SEMI", ord(","): "COMMA",
    ord("="): "EQ", ord("+"): "PLUS", ord("-"): "MINUS", ord("<"): "LT",
    ord(">"): "GT", ord("!"): "BANG", ord("&"): "AMP", ord("|"): "BAR",
    ord("."): "DOT", ord("%"): "PCT",
}


def class_of(b):
    if b in _SINGLE:
        return CL[_SINGLE[b]]
    c = chr(b)
    if c.isalpha() and b < 128:
        return CL["ALPHA"]
    if c.isdigit() and b < 128:
        return CL["DIGIT"]
    return CL["OTHER"]


W_byte_class = np.zeros((256, L["NC"]), dtype=F)
for b in range(256):
    W_byte_class[b, class_of(b)] = 1.0

# ---------------------------------------------------------------------------
# Block 2: byte -> character code one-hot, 256 x 64.
# Alphabet: a-z (0..25), A-Z (26..51), 0-9 (52..61), '_' (62).  63 unused.
# Non-identifier bytes map to the all-zero row (no code emitted).
# ---------------------------------------------------------------------------
W_alpha = np.zeros((256, L["A"]), dtype=F)
for b in range(256):
    c = chr(b)
    if b >= 128:
        continue
    if "a" <= c <= "z":
        W_alpha[b, ord(c) - ord("a")] = 1.0
    elif "A" <= c <= "Z":
        W_alpha[b, 26 + ord(c) - ord("A")] = 1.0
    elif "0" <= c <= "9":
        W_alpha[b, 52 + ord(c) - ord("0")] = 1.0
    elif c == "_":
        W_alpha[b, 62] = 1.0


def alpha_code(s):
    v = np.zeros((L["P"], L["A"]), dtype=F)
    for i, ch in enumerate(s[: L["P"]]):
        v[i, int(np.argmax(W_alpha[ord(ch)]))] = 1.0
    return v


# ---------------------------------------------------------------------------
# Block 3: keyword codebook, 12 x 16 x 64 (+ length / role vectors).
# Keyword recognition is exact spelling equality against these codewords,
# computed as AND over positions of a 64-way dot product.  No string compare
# happens in the runtime.
# ---------------------------------------------------------------------------
KEYWORDS = ["int", "char", "long", "short", "float", "double", "unsigned",
            "void", "signed", "return", "static", "const",
            "if", "else", "while", "for", "do"]
KW_TYPE = [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0]
KW_RET = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
KW_IF = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]
KW_ELSE = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]
KW_WHILE = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0]
KW_FOR = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]
KW_DO = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]

W_kw_code = np.zeros((L["NKW"], L["P"], L["A"]), dtype=F)
v_kw_len = np.zeros(L["NKW"], dtype=F)
for i, kw in enumerate(KEYWORDS):
    W_kw_code[i] = alpha_code(kw)
    v_kw_len[i] = len(kw)
v_kw_type = np.array(KW_TYPE, dtype=F)
v_kw_ret = np.array(KW_RET, dtype=F)
v_kw_if = np.array(KW_IF, dtype=F)
v_kw_else = np.array(KW_ELSE, dtype=F)
v_kw_while = np.array(KW_WHILE, dtype=F)
v_kw_for = np.array(KW_FOR, dtype=F)
v_kw_do = np.array(KW_DO, dtype=F)

# ---------------------------------------------------------------------------
# Block 4: lexer state machine, 9 x (9*26) = 9 x 234.
#
# States: 0 CODE, 1 CODE_SLASH, 2 LINE_COMMENT, 3 BLOCK_COMMENT,
#         4 BLOCK_STAR, 5 STRING, 6 STRING_ESC, 7 CHAR, 8 CHAR_ESC
#
# The next state is argmax over W_lex @ (state (x) class).  Each column of
# W_lex is the derived rule for one (state, class) pair: +2 on the target
# state, -2 elsewhere.  Because the outer product is a one-hot over the 234
# basis vectors, a linear map can realise any transition table exactly.
# ---------------------------------------------------------------------------
LEX_NAMES = ["CODE", "CODE_SLASH", "LINE", "BLOCK", "BLOCK_STAR",
             "STRING", "STRING_ESC", "CHAR", "CHAR_ESC"]
LX = {n: i for i, n in enumerate(LEX_NAMES)}


def lex_next(s, c):
    n = CLASS_NAMES[c]
    if s == LX["CODE"]:
        if n == "SLASH":
            return LX["CODE_SLASH"]
        if n == "QUOTE":
            return LX["STRING"]
        if n == "SQUOTE":
            return LX["CHAR"]
        return LX["CODE"]
    if s == LX["CODE_SLASH"]:
        if n == "SLASH":
            return LX["LINE"]
        if n == "STAR":
            return LX["BLOCK"]
        if n == "QUOTE":
            return LX["STRING"]
        if n == "SQUOTE":
            return LX["CHAR"]
        return LX["CODE"]
    if s == LX["LINE"]:
        return LX["CODE"] if n == "NL" else LX["LINE"]
    if s == LX["BLOCK"]:
        if n == "STAR":
            return LX["BLOCK_STAR"]
        return LX["BLOCK"]
    if s == LX["BLOCK_STAR"]:
        if n == "SLASH":
            return LX["CODE"]
        if n == "STAR":
            return LX["BLOCK_STAR"]
        return LX["BLOCK"]
    if s == LX["STRING"]:
        if n == "BACKSLASH":
            return LX["STRING_ESC"]
        if n == "QUOTE":
            return LX["CODE"]
        return LX["STRING"]
    if s == LX["STRING_ESC"]:
        return LX["STRING"]
    if s == LX["CHAR"]:
        if n == "BACKSLASH":
            return LX["CHAR_ESC"]
        if n == "SQUOTE":
            return LX["CODE"]
        return LX["CHAR"]
    if s == LX["CHAR_ESC"]:
        return LX["CHAR"]
    raise AssertionError


W_lex = np.zeros((L["NL"], L["NL"] * L["NC"]), dtype=F)
for s in range(L["NL"]):
    for c in range(L["NC"]):
        t = lex_next(s, c)
        col = s * L["NC"] + c
        W_lex[:, col] = -2.0
        W_lex[t, col] = 2.0

# Vectors selecting lexer states that are "source code" (not comment/string).
v_lex_code = np.zeros(L["NL"], dtype=F)
v_lex_code[LX["CODE"]] = 1.0
v_lex_code[LX["CODE_SLASH"]] = 1.0
# opener: bytes that *start* a comment.  opener = s_in^T W_opener s_out,
# so comment delimiters never become tokens.
W_opener = np.zeros((L["NL"], L["NL"]), dtype=F)
W_opener[LX["CODE"], LX["CODE_SLASH"]] = 1.0
W_opener[LX["CODE_SLASH"], LX["LINE"]] = 1.0
W_opener[LX["CODE_SLASH"], LX["BLOCK"]] = 1.0

v_lex_commentish = np.zeros(L["NL"], dtype=F)
for n in ("LINE", "BLOCK", "BLOCK_STAR"):
    v_lex_commentish[LX[n]] = 1.0

# ---------------------------------------------------------------------------
# Block 5: byte-class feature vectors (all 26-wide selectors).
# Everything downstream asks questions by matmul, not by index arithmetic.
# ---------------------------------------------------------------------------
def sel(names):
    v = np.zeros(L["NC"], dtype=F)
    for n in names:
        v[CL[n]] = 1.0
    return v


v_cls_idchar = sel(["ALPHA", "DIGIT", "US"])
v_cls_alpha = sel(["ALPHA"])
v_cls_digit = sel(["DIGIT"])
v_cls_us = sel(["US"])
v_cls_quote = sel(["QUOTE", "SQUOTE", "BACKSLASH"])
# punctuation bytes that form single-byte tokens
v_cls_punct = sel(["SLASH", "STAR", "LBRACE", "RBRACE", "LPAREN", "RPAREN",
                   "SEMI", "COMMA", "EQ", "PLUS", "MINUS", "LT", "GT",
                   "BANG", "AMP", "BAR", "PCT", "OTHER", "DOT"])
v_cls_op = sel(["SLASH", "STAR", "PLUS", "MINUS", "LT", "GT", "BANG",
                "AMP", "BAR", "PCT"])

# token-class contribution matrix: byte class -> token class index (26 x 13).
# Only the punctuation classes carry a direct contribution; identifier,
# keyword and number classes are assembled from the token-level predicates.
W_tokF = np.zeros((L["NC"], L["NF"]), dtype=F)
for n, i in (("EQ", 9), ("SEMI", 10), ("LBRACE", 11), ("RBRACE", 12),
             ("LPAREN", 13), ("RPAREN", 14), ("COMMA", 15), ("DOT", 17),
             ("OTHER", 17)):
    W_tokF[CL[n], i] = 1.0
for n in ("SLASH", "STAR", "PLUS", "MINUS", "LT", "GT", "BANG", "AMP",
          "BAR", "PCT"):
    W_tokF[CL[n], 16] = 1.0

# ---------------------------------------------------------------------------
# Block 6: grammar state machine.
# The state register is the product (statement state x 3 context bits), so one
# table lookup sees both the automaton state and the control context that the
# block stack exposes.  Context bits: 1=at top level, 2=inside a for header,
# 4=closed do-block awaiting its while.
# ---------------------------------------------------------------------------
GS_NAMES = ["TOP", "TOP_IDENT", "PARAM_TYPE", "PARAM_NAME", "PARAM_AFTER",
            "PARAM_END", "STMT", "DECL_NAME", "AFTER_NAME", "AFTER_LHS",
            "EXPR", "RET_EXPR",
            # control flow (v2): braced if / else / while
            "IF_COND", "IF_PEND", "ELSE_PEND", "WHILE_COND", "WHILE_PEND",
            # control flow (v3): for / do-while, braced or single-statement
            "FOR_HEAD", "FOR_COND", "FOR_STEP", "FOR_STEP_IDENT", "FOR_PEND",
            "DO_PEND", "DO_COND", "DO_WHILE_COND", "DO_END"]
NBIT = 16                    # 2^4 context-bit combinations
GS = {n: i for i, n in enumerate(GS_NAMES)}
FC_NAMES = ["IDENT", "TYPEKW", "RETKW", "IFKW", "ELSEKW", "WHILEKW", "FORKW",
            "DOKW", "NUM", "EQ", "SEMI", "LBRACE", "RBRACE", "LPAREN",
            "RPAREN", "COMMA", "OP", "OTHER"]
FC = {n: i for i, n in enumerate(FC_NAMES)}

# state indices, kept next to the names they mirror (used only for reading)
_ST, _DN, _AN, _AL, _EX, _RE = 6, 7, 8, 9, 10, 11
_IFC, _IFP, _ELP, _WHC, _WHP = 12, 13, 14, 15, 16
_FHD, _FCN, _FST, _FSI, _FPN = 17, 18, 19, 20, 21
_DPN, _DCD, _DWC, _DEN = 22, 23, 24, 25

# (state, class) -> next state, for code inside a function body.
TRANS = {}
for st in GS_NAMES:
    for cl in FC_NAMES:
        TRANS[(st, cl)] = st
TRANS.update({
    ("TOP", "TYPEKW"): "TOP_IDENT", ("TOP", "LBRACE"): "STMT",
    ("TOP_IDENT", "LPAREN"): "PARAM_TYPE",
    ("PARAM_TYPE", "RPAREN"): "PARAM_END",
    ("PARAM_TYPE", "TYPEKW"): "PARAM_NAME",
    ("PARAM_NAME", "IDENT"): "PARAM_AFTER",
    ("PARAM_AFTER", "COMMA"): "PARAM_TYPE",
    ("PARAM_AFTER", "RPAREN"): "PARAM_END",
    ("PARAM_END", "LBRACE"): "STMT",
    ("STMT", "TYPEKW"): "DECL_NAME",
    ("STMT", "RETKW"): "RET_EXPR",
    ("STMT", "IFKW"): "IF_COND",
    ("STMT", "ELSEKW"): "ELSE_PEND",
    ("STMT", "WHILEKW"): "WHILE_COND",
    ("STMT", "FORKW"): "FOR_HEAD",
    ("STMT", "DOKW"): "DO_PEND",
    ("STMT", "IDENT"): "AFTER_LHS",
    ("DECL_NAME", "IDENT"): "AFTER_NAME",
    ("AFTER_NAME", "EQ"): "EXPR",
    ("AFTER_NAME", "COMMA"): "DECL_NAME",
    ("AFTER_NAME", "SEMI"): "STMT",
    ("AFTER_LHS", "EQ"): "EXPR",
    ("EXPR", "SEMI"): "STMT",
    ("EXPR", "COMMA"): "DECL_NAME",
    ("RET_EXPR", "SEMI"): "STMT",
    # conditions read in their own state, so the closing ')' is unambiguous
    ("IF_COND", "RPAREN"): "IF_PEND",
    ("WHILE_COND", "RPAREN"): "WHILE_PEND",
    ("IF_PEND", "LBRACE"): "STMT",
    ("ELSE_PEND", "LBRACE"): "STMT",
    ("WHILE_PEND", "LBRACE"): "STMT",
    # ---- for header: init ; cond ; step ----
    ("FOR_HEAD", "LPAREN"): "FOR_HEAD",
    ("FOR_HEAD", "TYPEKW"): "DECL_NAME",
    ("FOR_HEAD", "IDENT"): "AFTER_LHS",
    ("FOR_HEAD", "SEMI"): "FOR_COND",
    ("FOR_COND", "SEMI"): "FOR_STEP",
    ("FOR_COND", "RPAREN"): "FOR_PEND",
    ("FOR_STEP", "IDENT"): "FOR_STEP_IDENT",
    ("FOR_STEP", "RPAREN"): "FOR_PEND",
    # the identifier that opens a step clause may be a postfix increment
    # ('i++') or the target of an assignment ('i = ...', 'i += ...')
    ("FOR_STEP_IDENT", "OP"): "AFTER_LHS",
    ("FOR_STEP_IDENT", "EQ"): "EXPR",
    ("FOR_STEP_IDENT", "RPAREN"): "FOR_PEND",
    ("AFTER_LHS", "RPAREN"): "FOR_PEND",
    ("FOR_PEND", "LBRACE"): "STMT",
    # ---- do / while ----
    ("DO_PEND", "LBRACE"): "STMT",
    ("DO_COND", "WHILEKW"): "DO_WHILE_COND",
    ("DO_WHILE_COND", "RPAREN"): "DO_END",
    ("DO_END", "SEMI"): "STMT",
})
# A pending-body state that sees anything but '{' has a single-statement
# body: the body's first token is consumed as if it started a statement, so
# the row is the composition of the STMT row.
for _p in ("IF_PEND", "ELSE_PEND", "WHILE_PEND", "FOR_PEND", "DO_PEND"):
    for _cl in FC_NAMES:
        if _cl != "LBRACE":
            TRANS[(_p, _cl)] = TRANS[("STMT", _cl)]
# Outside any block the closing brace ends the function, and a type keyword
# starts the next one.  The extra "at top level" bit comes from the block
# stack the network maintains, so this stays a table lookup.
TOP1 = {}
for cl in FC_NAMES:
    TOP1[("RBRACE", cl)] = "TOP"
TOP1[("STMT", "TYPEKW")] = "TOP_IDENT"
TOP1[("STMT", "RBRACE")] = "TOP"
TOP1[("EXPR", "RBRACE")] = "TOP"
TOP1[("RET_EXPR", "RBRACE")] = "TOP"


def gsm_next(st, cl, bits):
    top, infor, dop = bits & 1, (bits >> 1) & 1, (bits >> 2) & 1
    instep = (bits >> 3) & 1
    # the ')' that ends a step clause also ends an assignment inside it
    if instep and cl == "RPAREN" and st in ("EXPR", "AFTER_LHS",
                                            "FOR_STEP_IDENT", "FOR_STEP"):
        return "FOR_PEND"
    # whatever follows a closed do-block is its trailing while
    if dop:
        return "DO_WHILE_COND" if cl == "WHILEKW" else "DO_COND"
    # first ';' of a for header ends the init clause, whichever state the
    # init clause itself was parsed in
    if infor and cl == "SEMI":
        return "FOR_COND"
    if top:
        return TOP1.get((st, cl), TRANS[(st, cl)])
    return TRANS[(st, cl)]


# basis: state (x) class (x) context bits
W_gsm = np.zeros((L["NS"], L["NS"] * L["NF"] * NBIT), dtype=F)
_ok = set()
for si, st in enumerate(GS_NAMES):
    for ci, cl in enumerate(FC_NAMES):
        for bits in range(NBIT):
            t = GS[gsm_next(st, cl, bits)]
            col = (si * L["NF"] + ci) * NBIT + bits
            W_gsm[:, col] = -2.0
            W_gsm[t, col] = 2.0
            _ok.add((st, cl))
assert len(_ok) == L["NS"] * L["NF"]


def out_vec(pairs, bits=None):
    v = np.zeros(L["NS"] * L["NF"] * NBIT, dtype=F)
    allowed = range(NBIT) if bits is None else bits
    for s_, c_ in pairs:
        for b in allowed:
            v[(GS[s_] * L["NF"] + FC[c_]) * NBIT + b] = 1.0
    return v


ALL = GS_NAMES
v_out_read = out_vec([("EXPR", "IDENT"), ("RET_EXPR", "IDENT"),
                      ("IF_COND", "IDENT"), ("WHILE_COND", "IDENT"),
                      ("FOR_COND", "IDENT"), ("FOR_STEP", "IDENT"),
                      ("DO_WHILE_COND", "IDENT")])
v_out_assign = out_vec([("AFTER_LHS", "EQ"), ("FOR_STEP_IDENT", "EQ")])
v_out_declinit = out_vec([("AFTER_NAME", "EQ")])
v_out_declterm = out_vec([("AFTER_NAME", "SEMI")])
v_out_paramwrite = out_vec([("PARAM_NAME", "IDENT")])
v_out_retend = out_vec([("RET_EXPR", "SEMI")])
v_out_barrier = out_vec([(s_, c_) for s_ in ALL
                         for c_ in ("SEMI", "LBRACE", "RBRACE")])
v_out_commit = out_vec([(s_, c_) for s_ in ALL
                        for c_ in ("SEMI", "LBRACE", "RBRACE", "COMMA")]
                       + [("FOR_STEP", "RPAREN"), ("EXPR", "RPAREN"),
                          ("AFTER_LHS", "RPAREN")])
v_out_compound = out_vec([("AFTER_LHS", "OP"), ("FOR_STEP_IDENT", "OP")])
v_out_stepinc = out_vec([("FOR_STEP_IDENT", "OP")])

# block structure: which construct a '{' opens
v_open_if = out_vec([("IF_PEND", "LBRACE")])
v_open_else = out_vec([("ELSE_PEND", "LBRACE")])
v_open_while = out_vec([("WHILE_PEND", "LBRACE")])
v_open_for = out_vec([("FOR_PEND", "LBRACE")])
v_open_do = out_vec([("DO_PEND", "LBRACE")])
v_open_plain = out_vec([("STMT", "LBRACE"), ("PARAM_END", "LBRACE")])
# the same constructs with a single-statement body: the block opens implicitly
# at the body's first token.  'else if' is a chain, not a nested block.
v_open_if_u = out_vec([("IF_PEND", c) for c in FC_NAMES if c != "LBRACE"])
v_open_else_u = out_vec([("ELSE_PEND", c) for c in FC_NAMES
                         if c not in ("LBRACE", "IFKW")])
v_open_while_u = out_vec([("WHILE_PEND", c) for c in FC_NAMES if c != "LBRACE"])
v_open_for_u = out_vec([("FOR_PEND", c) for c in FC_NAMES if c != "LBRACE"])
v_open_do_u = out_vec([("DO_PEND", c) for c in FC_NAMES if c != "LBRACE"])
v_out_close = out_vec([(s_, "RBRACE") for s_ in ALL])

# unsupported-construct detector, one token
v_out_anomaly = out_vec(
    [(s_, "OTHER") for s_ in ALL]
    + [("EXPR", "EQ"), ("RET_EXPR", "EQ"), ("STMT", "NUM"), ("STMT", "OP")]
    + [("DO_COND", c) for c in FC_NAMES if c != "WHILEKW"])

# ---------------------------------------------------------------------------
# Block 7b: two-token-lookahead anomaly decoder.
# ---------------------------------------------------------------------------
ANOM2 = [
    ("STMT", "IDENT", "LPAREN"),      # call statement
    ("STMT", "LPAREN", "IDENT"),
    ("EXPR", "IDENT", "LPAREN"),      # call in an expression
    ("RET_EXPR", "IDENT", "LPAREN"),
    ("TOP_IDENT", "OP", "IDENT"),     # pointer return type
    ("DECL_NAME", "OP", "IDENT"),     # pointer declarator
    ("PARAM_NAME", "OP", "IDENT"),    # pointer parameter
    ("AFTER_LHS", "IDENT", "IDENT"),  # struct / typedef
    ("AFTER_LHS", "LBRACE", None),    # else { / struct body
    ("DECL_NAME", "LBRACE", None),
    ("EXPR", "TYPEKW", "RPAREN"),     # cast
]
v_anom2 = np.zeros(L["NS"] * L["NF"] * L["NF"], dtype=F)
for s_, c_, nx in ANOM2:
    base = GS[s_] * L["NF"] * L["NF"] + FC[c_] * L["NF"]
    if nx is None:
        v_anom2[base:base + L["NF"]] = 1.0
    else:
        v_anom2[base + FC[nx]] = 1.0

# ---------------------------------------------------------------------------
# Block 8: positional mask.  GT[t1,t2] = 1 iff t1 > t2.  A tensor, not code:
# it is the "later than" relation over token positions that the dependency
# builder needs.
# ---------------------------------------------------------------------------
GT = np.zeros((L["TMAX"], L["TMAX"]), dtype=F)
for i in range(L["TMAX"]):
    GT[i, :i] = 1.0

P = dict(
    W_byte_class=W_byte_class, W_alpha=W_alpha,
    W_kw_code=W_kw_code, v_kw_len=v_kw_len,
    v_kw_type=v_kw_type, v_kw_ret=v_kw_ret,
    v_kw_if=v_kw_if, v_kw_else=v_kw_else, v_kw_while=v_kw_while,
    v_kw_for=v_kw_for, v_kw_do=v_kw_do,
    W_lex=W_lex, W_opener=W_opener,
    v_lex_code=v_lex_code, v_lex_commentish=v_lex_commentish,
    v_cls_idchar=v_cls_idchar, v_cls_alpha=v_cls_alpha,
    v_cls_digit=v_cls_digit, v_cls_us=v_cls_us, v_cls_quote=v_cls_quote,
    v_cls_punct=v_cls_punct, v_cls_op=v_cls_op,
    W_tokF=W_tokF, W_gsm=W_gsm, v_anom2=v_anom2,
    v_out_compound=v_out_compound,
    v_out_read=v_out_read, v_out_assign=v_out_assign,
    v_out_declinit=v_out_declinit, v_out_declterm=v_out_declterm,
    v_out_paramwrite=v_out_paramwrite, v_out_retend=v_out_retend,
    v_out_barrier=v_out_barrier, v_out_commit=v_out_commit,
    v_open_if=v_open_if, v_open_else=v_open_else,
    v_open_while=v_open_while, v_open_plain=v_open_plain,
    v_open_for=v_open_for, v_open_do=v_open_do,
    v_open_if_u=v_open_if_u, v_open_else_u=v_open_else_u,
    v_open_while_u=v_open_while_u, v_open_for_u=v_open_for_u,
    v_open_do_u=v_open_do_u,
    v_out_stepinc=v_out_stepinc,
    v_out_close=v_out_close,
    v_out_anomaly=v_out_anomaly,
    GT=GT,
)

# ---------------------------------------------------------------------------
# Save + report
# ---------------------------------------------------------------------------
os.makedirs(os.path.dirname(OUT), exist_ok=True)
np.savez_compressed(OUT, **P)

dense = 0
nz = 0
for k, v in P.items():
    dense += v.size
    nz += int((v != 0).sum())

manifest = {
    "limits": L,
    "tensors": {k: {"shape": list(v.shape), "dense": int(v.size),
                    "nonzero": int((v != 0).sum()),
                    "bytes_f32": int(v.size * 4)} for k, v in P.items()},
    "dense_params": int(dense),
    "nonzero_params": int(nz),
    "serialized_bytes": int(os.path.getsize(OUT)),
    "grammar_states": GS_NAMES,
    "token_classes": FC_NAMES,
    "blocks": {
        "W_byte_class": "byte -> 26-way class one-hot (encoding layer)",
        "W_alpha": "byte -> 64-way character code (spelling alphabet)",
        "W_kw_code": "12 keyword codewords; exact spelling match by dot+AND",
        "W_lex": "9x234 lexer transition table (comment/string automaton)",
        "W_gsm": "grammar transition table over (state x class x context bits)",
        "v_anom2": "2028-wide two-token-lookahead unsupported-construct detector",
        "v_out_*": "decoder vectors: read/write/barrier/anomaly pulses",
        "GT": "positional greater-than mask",
    },
}
with open(os.path.join(ROOT, "weights", "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)

print("wrote", OUT, os.path.getsize(OUT), "bytes")
print("dense params:", dense, "nonzero:", nz)
for k, v in P.items():
    print(f"  {k:18s} {str(v.shape):16s} dense={v.size:7d} nz={(v!=0).sum():7d}")
