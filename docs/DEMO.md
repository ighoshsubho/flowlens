# Recording a FlowLens demo

Everything below runs on this machine. ffmpeg 7.1.1 and `screencapture` are
installed; nothing else is needed.

## 1. Prepare the session

    sh scripts/demo_video.sh              # you drive the keystrokes
    sh scripts/demo_video.sh --scripted   # hands-free: runs the whole take

Interactive mode opens `examples/loop_kernel.c` in real Vim with the cursor
on `mean` (line 7, col 9) and `:Flow downstream` already applied. Scripted
mode walks downstream → clear → upstream → `:Flow marks` → `:Flow info` →
back to the highlighted buffer, with pauses long enough to read.

Both use `scripts/demo_vimrc`: no user config, `desert` colours, bigger
highlight groups (`FlowLensSelected` blue, `FlowLensRelevant` green,
`FlowLensDim` grey), and a statusline that shows mode + relevant-token count
+ anomaly count.

## 2. Record

Built-in, no install (records a selected region, saves a .mov):

    Cmd+Shift+5   →   "Record Selected Portion"   →   Record

Or from the terminal — the terminal app needs Screen Recording permission
(System Settings → Privacy & Security → Screen Recording), granted once:

    screencapture -v -V 40 -k /tmp/flowlens.mov

`-V 40` is a hard 40-second limit, so a take cannot run long. Press
Ctrl+C in the terminal to stop early.

## 3. Encode

MP4 for LinkedIn / a blog header:

    ffmpeg -i /tmp/flowlens.mov -vf "fps=24,scale=1280:-2:flags=lanczos" \
           -pix_fmt yuv420p -c:v libx264 -crf 20 -movflags +faststart \
           /tmp/flowlens_demo.mp4

GIF for a bearblog post (900 px wide, 12 fps, 128-colour palette):

    ffmpeg -i /tmp/flowlens.mov \
           -vf "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer" \
           /tmp/flowlens_demo.gif

Both commands are verified on this ffmpeg build (produced a 30 KB mp4 and a
306 KB gif from a test clip).

## 4. Shot list, with the numbers that should be on screen

| beat | keystroke | what the viewer should see |
|---|---|---|
| 1 | (already applied) | `mean` in blue, 15 green spans running through the loop body, `acc = floor` in the if-branch correctly *not* green, statusline `relevant 15 anomalies 0` |
| 2 | `:Flow clear` | all spans back to the dim colour |
| 3 | cursor on line 21 `result`, `:Flow upstream` | the chain back through `acc`, `mean`, `safe`, to the parameters |
| 4 | `:Flow marks` | the receipt: every painted span with line:col, so the pixels are auditable |
| 5 | `:Flow info` | supported subset, limits (2048 bytes, 512 tokens, …), and the measured timings |
| 6 | `:Flow stop` then open a pointer file | `anomalies 1` and the warning — the refusal to guess |

See `examples/loop_kernel.c` (in subset, 0 anomalies) and `examples/worker_snippet.c`
(real threaded code, anomalies reported) for beats 6.

## Honest framing for the voiceover

The claim to make is narrow and checkable: *per-byte relevance labels computed
from the source bytes by a frozen-weight network, no parser, no compiler, no
LLM, 0 anomalies on the supported subset*. The claim not to make: general C
dataflow. Pointers, aliasing, macros and control dependence are out of scope
and are reported as anomalies, not approximated.
