#!/usr/bin/env python3
"""Self-check for chonk.py: dual-format parsing, window cap, JSON output.
Run: python3 scripts/test_chonk.py   (no deps, asserts only)."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chonk


def _codex(ic, win=258400):
    return json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "last_token_usage": {"input_tokens": ic, "cached_input_tokens": max(0, ic - 1000)},
        "model_context_window": win}}})


def _claude(ic, sidechain=False):
    return json.dumps({"type": "assistant", "isSidechain": sidechain,
                       "message": {"usage": {"input_tokens": ic}}})


def _write(*lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines) + "\n")
    f.close()
    return f.name


def _run(path, tmpdir=None):
    env = dict(os.environ, TMPDIR=tmpdir or tempfile.mkdtemp())
    r = subprocess.run([sys.executable, os.path.join(HERE, "chonk.py")],
                       input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                         "session_id": os.path.basename(path),
                                         "transcript_path": path}),
                       env=env, capture_output=True, text=True)
    return r.stdout.strip()


def _fired(out):
    if not out:
        return False
    d = json.loads(out)  # output must be valid JSON
    hso = d["hookSpecificOutput"]
    return hso["hookEventName"] == "UserPromptSubmit" and "chonk" in hso["additionalContext"]


# --- parser: both formats, window surfaced only for Codex ---
assert chonk.current_context(_write(_claude(1_000))) == (1_000, None)
p = _write(_claude(400_000), _claude(9, sidechain=True))  # sidechain ignored
assert chonk.current_context(p) == (400_000, None)
assert chonk.current_context(_write(_codex(94_055))) == (94_055, 258_400)

# --- window cap: 300K default is unreachable on Codex's ~258K window, so it fires ---
assert _fired(_run(_write(_codex(240_000))))           # 240K > cap(193.8K) → fires
assert not _fired(_run(_write(_codex(150_000))))       # below cap → silent
assert not _fired(_run(_write(_codex(240_000, win=353_400))))  # reachable 300K stays → silent
os.environ["CHONK_NUDGE_AT"] = "220000"
assert not _fired(_run(_write(_codex(200_000))))       # reachable override stays 220K
del os.environ["CHONK_NUDGE_AT"]

# --- Claude path unchanged: no window, plain 300K default ---
assert not _fired(_run(_write(_claude(250_000))))
assert _fired(_run(_write(_claude(320_000))))

# --- once per band (same TMPDIR so the dedupe stamp persists) ---
p = _write(_codex(240_000))
td = tempfile.mkdtemp()
assert _fired(_run(p, td)) and not _run(p, td)         # second call silent

print("ALL CHECKS PASSED")
