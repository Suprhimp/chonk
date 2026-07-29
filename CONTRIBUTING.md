# Contributing

Thanks for looking. chonk is small on purpose, so the most useful thing to know is what it's trying to be.

## What this is

One `UserPromptSubmit` hook that reads one number and prints at most one line. It does not analyze, dashboard, summarize, or store anything. There are already several good tools that tell you where your tokens went *afterwards* — chonk's whole reason to exist is saying something *during*, while you can still act on it.

Changes that keep it one file doing one thing are easy to merge. Changes that grow it into a usage analyzer are not, however well built.

## The one rule: measure, don't reason

This project shipped with a threshold that never fired, based on a metric that sounded right and wasn't. Cumulative session tokens covered 34% of spend; live context covers 80%. Nobody could have argued their way to that — it took counting.

So: **any change to what gets measured or where the threshold sits needs numbers from real transcripts.** Not a benchmark, not a synthetic session — your own `~/.claude/projects/**/*.jsonl`. Say how many sessions you looked at and what share of cost the change would catch. A PR that says "500K feels too high" gets a request for the number; a PR that says "across my 200 sessions 500K only catches 40% because I work in short bursts, here's the histogram" gets merged.

Sample size doesn't need to be large. It needs to be real.

## Working on it

```bash
git clone https://github.com/Suprhimp/chonk
claude --plugin-dir ./chonk        # loads it without installing
```

`/reload-plugins` picks up edits without restarting.

The hook reads JSON on stdin, so you can exercise it directly against a real transcript — no Claude Code in the loop:

```bash
echo '{"transcript_path":"'"$HOME"'/.claude/projects/<project>/<session>.jsonl","session_id":"test-1"}' \
  | python3 scripts/chonk.py
```

Run it twice with the same `session_id` — the second call should print nothing. That band-dedup is the thing most likely to break silently.

## Before opening a PR

- **It must fail silent.** Bad JSON on stdin, missing file, unreadable transcript, read-only temp dir — every one of those returns quietly. A hook that throws blocks the user's prompt, which is far worse than a missed nudge. Test with `''`, `'not json'`, `'{}'`, and a nonexistent path; all four should exit 0 with empty stderr.
- **Keep it dependency-free.** Standard library only, and it should run on whatever `python3` ships with macOS. No packaging, no venv.
- **Watch the read cost.** It runs before every prompt. The 2MB tail read keeps a 62MB transcript at ~35ms; anything that walks the whole file will be slowest exactly in the sessions chonk exists for.
- **Don't put anything long in the output.** Every character printed becomes context tokens on that turn. A token-thrift tool spending tokens to say so is a bad joke.
- **Run `claude plugin validate .`** if you touched the manifest or `hooks.json`.

## Things worth doing

- A `--calibrate` mode that reads your own sessions and suggests thresholds, so the defaults stop being one person's distribution
- A peak-context mode — right now a session that already hit 999K goes quiet after a compaction, because the reading is a live gauge rather than a high-water mark
- Counting sub-agent (`isSidechain`) turns toward the coordinator's total
- Windows: the temp-dir stamp path is untested there

## Bugs

Include your transcript size, what the hook printed (or didn't), and what `usage` actually said on the last assistant turn. That last number is the whole input, so a report with it in is usually a five-minute fix and one without it is guesswork.

Please don't paste raw transcripts — they contain your source code.
