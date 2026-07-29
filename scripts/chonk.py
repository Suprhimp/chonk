#!/usr/bin/env python3
"""UserPromptSubmit hook: when the live context gets big, propose wrapping up.

Reads the exact prompt size from the last assistant turn's `usage` record
(input + cache_creation + cache_read) — what the API actually billed for that
request. That counts tool results, images, the system prompt and tool schemas,
and it *drops* after a compaction, none of which a character count can see.

Why live context and not cumulative session tokens: cost is driven by re-reading
the same history every turn, not by how much new text was produced. Measured
over 342 local sessions, a 500K live-context threshold covers ~80% of spend;
a 350K cumulative-token threshold covered ~34%.

Suggests only — never blocks. Fires once per band so it doesn't nag.
Override both thresholds from /plugin config.
"""
import glob
import json
import os
import sys
import tempfile
import time

NUDGE_AT = 500_000      # live context tokens before the first nudge (~half the 1M window)
REARM_EVERY = 200_000   # re-arm at 700K / 900K — catches the same sessions as 150K
                        # with ~25 fewer repeat nudges over a 48-day sample
TAIL_BYTES = 2_000_000  # transcripts reach 60MB+; only the tail holds the newest usage

CHART = ["he chonky", "HEFTY CHONK", "MEGACHONKER", "OH LAWD HE COMIN"]


def option(key, fallback):
    """Read a /plugin config value; Claude Code exports each userConfig option
    to hook processes as CLAUDE_PLUGIN_OPTION_<KEY>."""
    try:
        v = int(float(os.environ[f"CLAUDE_PLUGIN_OPTION_{key}"]))
        return v if v > 0 else fallback
    except (KeyError, TypeError, ValueError):
        return fallback


def current_context(path):
    """Exact prompt size of the most recent main-thread assistant turn."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read()
    if size > TAIL_BYTES:
        chunk = chunk.split(b"\n", 1)[-1]      # drop the partial first line

    for line in reversed(chunk.splitlines()):
        if b'"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        u = (d.get("message") or {}).get("usage") or {}
        ctx = ((u.get("input_tokens") or 0)
               + (u.get("cache_creation_input_tokens") or 0)
               + (u.get("cache_read_input_tokens") or 0))
        if ctx:
            return ctx
    return 0


def already_nudged(session, band):
    """True if this band was already announced. Records it if not."""
    tmp = tempfile.gettempdir()
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
        tokens = current_context(path)
    except Exception:
        return
    if tokens < nudge_at:
        return

    band = (tokens - nudge_at) // rearm
    session = data.get("session_id") or os.path.basename(path)
    if already_nudged(session, band):
        return

    rung = CHART[min(band, len(CHART) - 1)]
    print(
        f"[chonk] Context is ~{tokens // 1000}K tokens — {rung}. Every further "
        "turn re-reads all of it. Before answering, briefly PROPOSE that this "
        "may be a good point to wrap up and continue in a fresh session (offer "
        "a short handoff: current state + next steps). If they'd rather keep "
        "going, just continue."
    )


if __name__ == "__main__":
    main()
