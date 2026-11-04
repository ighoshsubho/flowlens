#!/bin/sh
# Prepare a recordable FlowLens session in real Vim.
#
#   sh scripts/demo_video.sh                 # open the demo, highlights on
#   sh scripts/demo_video.sh --scripted      # hands-free walkthrough (~35 s)
#   sh scripts/demo_video.sh --scripted --record
#                                            # walkthrough + screen capture +
#                                            # encode mp4 and gif
#
# --record captures the SCREEN (not one window).  Set FLOWLENS_REGION to a
# rectangle to limit it:  FLOWLENS_REGION="0,0,1280,760"
# Screen Recording permission is required once for the terminal app.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VIM=${FLOWLENS_VIM:-}
if [ -z "$VIM" ]; then
  if [ -x /usr/bin/vim ] && /usr/bin/vim --version 2>/dev/null | head -1 | grep -qv NVIM; then
    VIM=/usr/bin/vim
  else
    VIM=$(command -v vim)
  fi
fi

SCRIPTED=0
RECORD=0
for a in "$@"; do
  case "$a" in
    --scripted) SCRIPTED=1 ;;
    --record)   RECORD=1 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

EXTRA=""
if [ "$SCRIPTED" = 1 ]; then
  EXTRA="-S $ROOT/scripts/demo_walkthrough.vim"
fi

echo "using $VIM ($("$VIM" --version | head -1))"
echo "buffer: examples/loop_kernel.c   cursor: line 7 col 9 ('mean')"

if [ "$RECORD" = 0 ]; then
  [ "$SCRIPTED" = 1 ] && echo "walkthrough: ~35 s, Vim stays open afterwards"
  echo "record it with Cmd+Shift+5, or rerun with --record"
  # shellcheck disable=SC2086
  exec "$VIM" -Nu "$ROOT/scripts/demo_vimrc" -n $EXTRA \
       -c 'call cursor(7, 9)' -c 'Flow downstream' \
       "$ROOT/examples/loop_kernel.c"
fi

# ---- record mode -----------------------------------------------------------
MOV=${FLOWLENS_OUT:-/tmp/flowlens_demo.mov}
MP4=${MOV%.mov}.mp4
GIF=${MOV%.mov}.gif
rm -f "$MOV" "$MP4" "$GIF"
set -- -v -V 55 -k
if [ -n "${FLOWLENS_REGION:-}" ]; then
  set -- "$@" -R "$FLOWLENS_REGION"
  echo "capture: region $FLOWLENS_REGION -> $MOV"
else
  echo "capture: full screen (set FLOWLENS_REGION=\"x,y,w,h\" to limit) -> $MOV"
fi
echo "grant Screen Recording permission if macOS asks; Ctrl+C to abort"
screencapture "$@" "$MOV" &
SC=$!

# the scripted take quits itself; an interactive take ends when you :q
QA=""
if [ "$SCRIPTED" = 1 ]; then QA="-c qa!"; fi
"$VIM" -Nu "$ROOT/scripts/demo_vimrc" -n $EXTRA -c 'call cursor(7, 9)' \
       -c 'Flow downstream' $QA "$ROOT/examples/loop_kernel.c" || true
wait $SC || true

if [ ! -s "$MOV" ]; then
  echo "capture failed — no file written. Check Screen Recording permission." >&2
  exit 1
fi

ffmpeg -v error -i "$MOV" -vf "fps=24,scale=1280:-2:flags=lanczos" \
       -pix_fmt yuv420p -c:v libx264 -crf 20 -movflags +faststart "$MP4" -y
ffmpeg -v error -i "$MOV" \
       -vf "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer" \
       "$GIF" -y
echo
echo "raw   $MOV  $(wc -c < "$MOV" | tr -d ' ') bytes"
echo "mp4   $MP4  $(wc -c < "$MP4" | tr -d ' ') bytes"
echo "gif   $GIF  $(wc -c < "$GIF" | tr -d ' ') bytes"
