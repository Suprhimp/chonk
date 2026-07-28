#!/usr/bin/env python3
"""UserPromptSubmit hook: when a session gets chonky, propose wrapping up.

Estimates cumulative session size from the transcript and, past a threshold,
injects a one-line reminder telling the assistant to PROPOSE stopping here +
handing off. It only suggests — the user decides. Fires once per threshold band
so it doesn't nag.

What it counts: text blocks, tool_use inputs, and tool_result text. In a coding
session the tool blocks (file reads, greps, command output) are the bulk of the
tokens, so counting only assistant/user prose misses ~90%+ of a long session.
Image blocks are skipped (base64 would wildly overcount, and images are
tokenized by dimension rather than byte length).

Defaults are tuned to a real transcript distribution (n=1145 sessions, same
estimator): p90 83K, p95 133K, p99 314K, max 2.4M cumulative tokens. NUDGE_AT
sits near p99 so it fires on the top ~1% — genuinely long sessions, not
normal-large ones. Override both via /plugin config.
"""
import glob
import json
import os
import sys
import tempfile
import time

# Overridable from `/plugin config` — Claude Code exports every userConfig
# option to hook processes as CLAUDE_PLUGIN_OPTION_<KEY>.
NUDGE_AT = 350_000      # cumulative session tokens before the first nudge
REARM_EVERY = 250_000   # re-arm at 600K/850K/1.1M... — this is what curbs whales

# The Chonk Chart. Each re-arm band moves one rung up.
CHART = ["he chonky", "HEFTY CHONK", "MEGACHONKER", "OH LAWD HE COMIN"]


def option(key, fallback):
    """Read a user-configured integer, falling back to the built-in default."""
    raw = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key}")
    try:
        value = int(float(raw))
        return value if value > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def block_len(b):
    """chars of a content block that costs text tokens; images/thinking -> 0."""
    if not isinstance(b, dict):
        return 0
    t = b.get("type")
    if t == "text":
        return len(b["text"]) if isinstance(b.get("text"), str) else 0
    if t == "tool_use":
        try:
            return len(json.dumps(b.get("input", {}), ensure_ascii=False))
        except Exception:
            return 0
    if t == "tool_result":
        c = b.get("content")
        if isinstance(c, str):
            return len(c)
        if isinstance(c, list):
            return sum(block_len(x) for x in c)  # image blocks fall through to 0
        return 0
    # chonk: images excluded (base64 overcounts ~100x); if image-heavy sessions
    # need catching, add a per-image dimension-based token estimate.
    return 0


def session_tokens(path):
    """chars/4 proxy over every text-bearing block in the transcript."""
    chars = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                msg = json.loads(line).get("message", {})
            except Exception:
                continue
            content = msg.get("content")
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                chars += sum(block_len(b) for b in content)
    return chars // 4


def already_nudged(session, band):
    """True if this band was already announced. Records it if not."""
    tmp = tempfile.gettempdir()
    # Sweep our own stamps older than a week — sessions end without notice, so
    # clean up opportunistically instead of leaking one file per session.
    try:
        cutoff = time.time() - 7 * 86400
        for old in glob.glob(os.path.join(tmp, "chonk_*")):
            if os.path.getmtime(old) < cutoff:
                os.remove(old)
    except Exception:
        pass

    stamp = os.path.join(tmp, f"chonk_{session}")
    try:
        with open(stamp) as f:
            if int(f.read().strip()) >= band:
                return True
    except Exception:
        pass
    try:
        with open(stamp, "w") as f:
            f.write(str(band))
    except Exception:
        pass
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # never break prompt submission
    path = data.get("transcript_path")
    if not path or not os.path.exists(path):
        return

    nudge_at = option("NUDGE_AT", NUDGE_AT)
    rearm = option("REARM_EVERY", REARM_EVERY)

    try:
        tokens = session_tokens(path)
    except Exception:
        return
    if tokens < nudge_at:
        return

    band = (tokens - nudge_at) // rearm
    # The transcript filename is a per-session uuid — a stable key when
    # session_id is absent, so distinct sessions never share a stamp.
    session = data.get("session_id") or os.path.basename(path)
    if already_nudged(session, band):
        return

    rung = CHART[min(band, len(CHART) - 1)]
    print(
        f"[chonk] This session is ~{tokens // 1000}K cumulative tokens — {rung}. "
        "Before answering, briefly PROPOSE to the user that this may be a good "
        "point to wrap up and continue in a fresh session (offer a short "
        "handoff: current state + next steps). If they'd rather keep going, "
        "just continue."
    )


if __name__ == "__main__":
    main()
