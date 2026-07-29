```
          /\_/\
      ┌──( -.- )──┐
     /(           )\
    |(             )|
     \(___________)/
      └───────────┘
       c h o n k
```

# chonk

> *"…wait, where did all my tokens go?"*
> Into this conversation. They're still going.

[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757)](#install)
[![MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**chonk** is a [Claude Code](https://code.claude.com) plugin that notices when your session has gotten heavy and asks whether you'd like to wrap up and continue in a fresh one — with a handoff written for you.

Claude Code will happily let a single session run for 98 hours. It auto-compacts so you never hit a wall, and it shows a context meter you can glance at. What it never does is *say something*. So you keep going, and every turn quietly re-reads everything that came before it.

```
> add a loading state to the upload button

[chonk] Context is ~612K tokens — MEGACHONKER.

Before I do that — this session has gotten pretty large, and every turn
from here re-reads all of it. Want to wrap up and start fresh?

  Where we are:  upload flow is done through the S3 presign step;
                 retry logic is stubbed in uploader.ts:88
  Next up:       loading state on the button, then the retry backoff

Or say the word and I'll just keep going.
```

It **suggests**. It never blocks, never ends your session, never edits anything. If you say keep going, it keeps going.

## Why this exists

I pulled a month of my own Claude Code transcripts — 40,009 requests across 311 sessions — and priced every one of them at public API rates. Then I looked at where the money went:

| | |
|---|---|
| Sessions with 300+ requests | **74.6%** of all cost — 36 of 311 sessions |
| Sessions with 600+ requests | **43.3%** of all cost — **13 sessions** |
| Requests with 400K+ token prompts | **59%** of all cost |

Thirteen sessions. Out of three hundred and eleven.

Cost per request is **linear in context size** — there is no knee, no cliff, no threshold where things suddenly get expensive:

| prompt size | cost / request |
|---|---|
| under 50K | $0.07 |
| 100–200K | $0.14 |
| 300–400K | $0.31 |
| 800K+ | **$0.74** |

### What to measure

The obvious thing to count is how much the session has produced. That turns out to be the wrong number. Cost comes from *re-reading* the same history every turn, not from generating new text — so a session can sit at 999K context for 800 turns while its cumulative output barely moves.

Measured across the same 342 sessions, by what share of total spend each trigger would catch:

| threshold | cumulative session tokens | live context |
|---|---|---|
| 350K | 10 sessions · **34%** of spend | 76 sessions · 89% |
| 500K | 2 sessions · 15% | 48 sessions · **80%** |

Four of the eight most expensive sessions filled the window to ~999K while never crossing 350K cumulative. chonk reads live context for exactly this reason.

Which means there's exactly one lever: **notice sooner, start a new session.** Not a smarter cache, not a cheaper model — just don't carry 800K tokens of history into a question that needed 20K.

The catch is that starting over feels expensive, because you have to rebuild the context in your head. So chonk writes the handoff for you. That's the actual product; the threshold detection is just the trigger.

## Install

```
/plugin marketplace add Suprhimp/chonk
/plugin install chonk@chonk
```

Or try it without installing:

```bash
git clone https://github.com/Suprhimp/chonk
claude --plugin-dir ./chonk
```

Requires `python3` (already on macOS and most Linux). No dependencies, no network calls, no telemetry — it reads one local file and prints one line.

Not using plugins? Drop `scripts/chonk.py` anywhere and register it in `~/.claude/settings.json` — user scope, so it covers every project and worktree at once:

```json
{ "hooks": { "UserPromptSubmit": [{ "hooks": [
  { "type": "command", "command": "python3 \"$HOME/.claude/hooks/chonk.py\"", "timeout": 10 }
]}]}}
```

Project-scoped `.claude/settings.json` only covers that one checkout, which is an easy way to install a guardrail that never fires.

## The Chonk Chart

Each time the session grows past another band, chonk moves one rung up. This is how you tell the second nudge from the fourth without reading the number.

```
        500K                700K                900K                1.1M
                                                                  /\_/\
  ┌───────────┐       ┌───────────┐           /\_/\              ( -.- )
  │           │       │   /\_/\   │       ┌──( -.- )──┐       ┌─(       )─┐
  │   /\_/\   │       │  ( -.- )  │       │ (       ) │      /(           )\
  │  ( o.o )  │       │ (       ) │      /(           )\    |(             )|
  │  (_____)  │       │(_________)│      \(___________)/     \(___________)/
  └───────────┘       └───────────┘       └───────────┘       └───────────┘
     he chonky          HEFTY CHONK         MEGACHONKER       OH LAWD HE COMIN
```

The box doesn't get bigger. That's the whole problem — the context window is fixed and the conversation isn't.

## Configuration

Run `/plugin config chonk`, or leave it alone — the defaults are measured, not guessed.

| option | default | what it does |
|---|---|---|
| **First nudge at** | `500000` | Live context tokens before chonk first speaks up |
| **Re-arm every** | `200000` | How much further growth before it speaks again |

500K is about half the 1M window, and the point where the nudge covers ~80% of spend in the sample above. Simulated over 48 days of real sessions it fires about twice a day across ~7 concurrent sessions — roughly one session in three.

Drop it to 400K to cover 89% instead of 80%, at ~3 nudges/day. Raise it to 700K for ~1/day and 64% coverage.

**Your distribution is not mine.** If you work in short bursts you may never see a nudge; if you run overnight agent sessions you may want it lower. Two numbers, one dialog.

The re-arm matters more than the first threshold. A session nudged once at 500K will often run to the wall anyway — the reminders at 700K and 900K are what actually curb it.

## How it works

A `UserPromptSubmit` hook runs before each of your messages and reads one number out of the session transcript: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` from the most recent assistant turn. That is the exact prompt size the API billed for that request.

Reading the billed number instead of estimating gets several things for free. Tool results, images, the system prompt, and tool schemas are all counted, because the API counted them. It needs no tokenizer and is not thrown off by CJK text. And it *drops* after a compaction, so a compacted session goes quiet again instead of staying flagged forever.

It reads only the last 2MB of the file — transcripts reach 60MB and the newest record is at the end. If the value crosses a band that hasn't fired yet, chonk prints one line to stdout, which Claude Code injects as context for that turn. It records the band in a temp file so the same rung never fires twice, and sweeps its own stamps after a week.

Every failure path is silent. Bad JSON on stdin, missing transcript, unreadable file, unwritable temp dir — chonk returns quietly rather than interfering with your prompt.

## Limitations

Worth knowing before you rely on it:

- **It reports the last turn, not the peak.** If a session's final request happened to be small — right after a compaction, say — chonk stays quiet even though the session hit 999K earlier. It's a live gauge, not a high-water mark.
- **It says nothing about how long you've been at it.** A session can burn real money in twenty turns at 900K without ever being *long*. Context size is the better proxy for cost, but it isn't a proxy for fatigue.
- **Sub-agent turns are skipped** (`isSidechain`), so a coordinator that delegates heavily reads lower than the work it's actually driving.
- **The 2MB tail is a heuristic.** A single turn larger than that would be missed. None have been observed; raise `TAIL_BYTES` if yours are.
- **The transcript format isn't a public API.** It can change. chonk fails silent if it does, but it may silently stop working.

## FAQ

### Doesn't Claude Code already handle this with auto-compaction?

Compaction keeps you *inside* the window — it summarizes so the session can continue. It's a survival mechanism, not a suggestion to stop. chonk answers a different question: not "can this continue?" but "should it?"

### How is this different from the token dashboards?

Tools like ccusage and the various transcript analyzers tell you where your tokens went, afterwards. Useful, and there are several good ones. chonk is the only one I know of that says something *during* the session, when you can still act on it.

### Why live context instead of cumulative session tokens?

chonk started out counting cumulative tokens — everything the session had produced. It seemed like the better proxy for "this has gone on too long," and it was calibrated carefully against a real distribution.

It caught 34% of spend. Live context at 500K catches 80%.

The reason is that cost doesn't come from producing text, it comes from re-reading it. A session parked at 999K context for 800 turns generates very little *new* content while quietly costing $0.74 a request. Four of my eight most expensive sessions looked unremarkable by cumulative tokens and had completely filled the window.

If you want the old behavior, `git log` has it — but the numbers argue against it.

### Will it slow down my prompts?

About 35–40ms, once per message, flat — it reads a 2MB tail rather than the whole file, so a 62MB transcript costs the same as a small one.

### Does it send anything anywhere?

No. It reads one file on your disk and prints one line to stdout. There is no network code in it.

## Contributing

Issues and PRs welcome, especially:

- A `--calibrate` mode that reads your own sessions and suggests thresholds
- A peak-context mode, so a session that has already been at 999K stays flagged after a compaction
- Counting sub-agent (`isSidechain`) turns toward the coordinator's total

## License

MIT

---

<p align="center">
  <sub>Built at <a href="https://planningo.io">Planningo</a> after a month of wondering where the tokens went.</sub>
</p>
