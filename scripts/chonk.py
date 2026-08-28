#!/usr/bin/env python3
"""UserPromptSubmit hook: when the live context gets big, propose wrapping up.

Works on both Claude Code and Codex CLI — the hook contract is nearly identical
(stdin JSON with transcript_path, ${CLAUDE_PLUGIN_ROOT} which Codex aliases to
${PLUGIN_ROOT}, stdout text injected as context). The only real difference is
the transcript format, and current_context() reads both.

Reads the exact prompt size from the last turn's usage record — what the API
actually billed for that request. On Claude Code that's the assistant turn's
`usage` (input + cache_creation + cache_read); on Codex it's the last
`token_count` event's `info.last_token_usage.input_tokens` (which already
folds cached tokens in). That counts tool results, images, the system prompt
and tool schemas, and it *drops* after a compaction — none of which a
character count can see.

Why live context and not cumulative session tokens: cost is driven by re-reading
the same history every turn, not by how much new text was produced. Measured
over 342 local sessions, a 350K cumulative-token threshold covered ~34% of spend
while live context caught the sessions that actually ran the window to the wall.

Suggests only — never blocks. Fires once per band so it doesn't nag.
Override both thresholds from /plugin config.
"""
import glob
import json
import os
import sys
import tempfile
import time

NUDGE_AT = 300_000      # live context tokens before the first nudge.
                        # Was 500K, which assumed spend concentrates in a few
                        # window-filling sessions. On a parallel workload — many
                        # sessions at once, each moderate — it doesn't: over a
                        # 41h/32-session sample, 500K covered 6.8% of spend and
                        # 300K covered 34.4%. Low enough to catch the mid-range
                        # where the money actually is, high enough that only
                        # 1 session in 4 ever hears it.
REARM_EVERY = 200_000   # re-arm at 500K / 700K / 900K — catches the same sessions
                        # as 150K with ~25 fewer repeat nudges over a 48-day sample
TAIL_BYTES = 2_000_000  # transcripts reach 60MB+; only the tail holds the newest usage

CHART = ["he chonky", "HEFTY CHONK", "MEGACHONKER", "OH LAWD HE COMIN"]


def option(key, fallback):
    """Read a config override. Claude Code exports each userConfig option to
    hook processes as CLAUDE_PLUGIN_OPTION_<KEY>; Codex has no such mechanism,
    so CHONK_<KEY> works as a plain env override on either harness."""
    for var in (f"CLAUDE_PLUGIN_OPTION_{key}", f"CHONK_{key}"):
        try:
            v = int(float(os.environ[var]))
            if v > 0:
                return v
        except (KeyError, TypeError, ValueError):
            continue
    return fallback


def _line_context(d):
    """Live context tokens from one transcript line, or 0 if it isn't a usage
    record. Handles Claude Code (assistant/message.usage) and Codex
    (event_msg/token_count/info.last_token_usage)."""
    # Claude Code
    if d.get("type") == "assistant" and not d.get("isSidechain"):
        u = (d.get("message") or {}).get("usage") or {}
        return ((u.get("input_tokens") or 0)
                + (u.get("cache_creation_input_tokens") or 0)
                + (u.get("cache_read_input_tokens") or 0))
    # Codex CLI — input_tokens already includes cached_input_tokens
    p = d.get("payload") or {}
    if p.get("type") == "token_count":
        last = (p.get("info") or {}).get("last_token_usage") or {}
        return last.get("input_tokens") or 0
    return 0


def current_context(path):
    """Exact prompt size of the most recent main-thread turn."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read()
    if size > TAIL_BYTES:
        chunk = chunk.split(b"\n", 1)[-1]      # drop the partial first line

    for line in reversed(chunk.splitlines()):
        if b"usage" not in line:               # matches "usage" and *_token_usage
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        ctx = _line_context(d)
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
