# Frozen weights

| file | what it is |
|---|---|
| `flowlens_weights.npz` | the tensors the runtime loads (10,966 bytes, 305,894 numbers) |
| `flowlens_weights.json` | the same numbers as JSON, with shape and equation per tensor |
| `manifest.json` | shapes, dense/nonzero counts, serialized size, block descriptions |

Both are produced by `build/construct_weights.py` (deterministic, no gradient
descent, no search, no pretrained values) and `build/export_weights.py`.

Blocks:

```
W_byte_class  256x27   byte -> class one-hot
W_alpha       256x64   byte -> character code
W_kw_code     12x16x64 keyword codewords (exact spelling match)
W_lex         9x243    comment/string automaton
W_opener      9x9      "this byte opens a comment"
W_tokF        27x13    byte class -> token class contribution
W_gsm         26x7488  grammar automaton
v_out_*       156      read / write / barrier / anomaly / compound decoders
v_anom2       2028     (state, class, next class) unsupported-construct detector
GT            512x512  positional relation i > j
```

`GT` is 262,144 of the 305,894 dense values; it is a stored relation, not a
learned one, and it is reported separately in docs/ARCHITECTURE.md.

Regenerate:

```sh
python3 build/construct_weights.py
python3 build/export_weights.py
```
