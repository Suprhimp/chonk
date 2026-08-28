#!/usr/bin/env python3
"""UserPromptSubmit hook: when the live context gets big, propose wrapping up.

Works on both Claude Code and Codex CLI — the hook contract is nearly identical
(stdin JSON with transcript_path, ${CLAUDE_PLUGIN_ROOT} which Codex aliases to
${PLUGIN_ROOT}, and a hookSpecificOutput.additionalContext JSON reply both
harnesses inject). The differences current_context()/main() bridge: the
transcript format, and Codex's context window (which caps how large live
context can get, so the nudge threshold is held below it).

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
WINDOW_FRACTION = 0.75  # when the transcript reports the model's context window
                        # (Codex does; Claude Code doesn't), cap the nudge at this
                        # fraction of it. A 300K default sits ABOVE Codex's ~258K
                        # window — compaction holds live context under the window,
                        # so a fixed 300K would never fire. Measured over 413 local
                        # Codex sessions, live context topped out at 250K/258K; 0.75
                        # (~193K) fires with real runway left to wrap up.
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
    """(live_context_tokens, context_window) from one transcript line, or
    (0, None) if it isn't a usage record. Window is None when the transcript
    doesn't report it (Claude Code); Codex reports it per token_count event."""
    # Claude Code
    if d.get("type") == "assistant" and not d.get("isSidechain"):
        u = (d.get("message") or {}).get("usage") or {}
        return (((u.get("input_tokens") or 0)
                 + (u.get("cache_creation_input_tokens") or 0)
                 + (u.get("cache_read_input_tokens") or 0)), None)
    # Codex CLI — input_tokens already includes cached_input_tokens
    p = d.get("payload") or {}
    if p.get("type") == "token_count":
        info = p.get("info") or {}
        last = info.get("last_token_usage") or {}
        return (last.get("input_tokens") or 0, info.get("model_context_window"))
    return (0, None)


def current_context(path):
    """(prompt size, context window) of the most recent main-thread turn."""
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
        ctx, window = _line_context(d)
        if ctx:
            return ctx, window
    return 0, None


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
        tokens, window = current_context(path)
    except Exception:
        return

    # Where the transcript reports the model's context window, keep the nudge
    # below it: compaction holds live context under the window, so a threshold
    # at or above it (e.g. the 300K default vs Codex's ~258K) never fires.
    if window and nudge_at > window * WINDOW_FRACTION:
        nudge_at = int(window * WINDOW_FRACTION)

    if tokens < nudge_at:
        return

    band = (tokens - nudge_at) // rearm
    session = data.get("session_id") or os.path.basename(path)
    if already_nudged(session, band):
        return

    rung = CHART[min(band, len(CHART) - 1)]
    context = (
        f"[chonk] Context is ~{tokens // 1000}K tokens — {rung}. Every further "
        "turn re-reads all of it. Before answering, briefly PROPOSE that this "
        "may be a good point to wrap up and continue in a fresh session (offer "
        "a short handoff: current state + next steps). If they'd rather keep "
        "going, just continue."
    )
    # JSON hookSpecificOutput.additionalContext is the form both harnesses inject
    # reliably on UserPromptSubmit. Codex accepts plain stdout in its docs but
    # shipped Codex plugins use this JSON shape, so it's the safe common path.
    event = data.get("hook_event_name") or "UserPromptSubmit"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
