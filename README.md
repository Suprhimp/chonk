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

[chonk] This session is ~612K cumulative tokens — MEGACHONKER.

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

## The Chonk Chart

Each time the session grows past another band, chonk moves one rung up. This is how you tell the second nudge from the fourth without reading the number.

```
        350K                600K                850K                1.1M
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
| **First nudge at** | `350000` | Cumulative session tokens before chonk first speaks up |
| **Re-arm every** | `250000` | How much further growth before it speaks again |

The defaults sit at roughly the 99th percentile of a real 1,145-session sample (p90 83K, p95 133K, p99 314K, max 2.4M). That's deliberate: chonk should fire on the sessions that are genuinely out of hand, not the merely long ones.

**Your distribution is not mine.** If you work in short bursts you may never see a nudge; if you run overnight agent sessions you may want to lower it. Two numbers, one dialog.

The re-arm matters more than the first threshold. A session that hits 350K and gets nudged once will often run to 2M anyway — the reminders at 600K, 850K, and 1.1M are what actually curb it.

## How it works

A `UserPromptSubmit` hook runs before each of your messages, reads the session transcript, and adds up every block that costs text tokens: message text, tool call inputs, and tool result contents. In a coding session the tool blocks — file reads, greps, command output — are the overwhelming majority, so anything that counts only the prose you can see will undercount by an order of magnitude or more.

Image blocks are skipped on purpose. Base64 length has nothing to do with image token cost, and one screenshot would blow the estimate past every threshold at once.

If the total crosses a band that hasn't fired yet, chonk prints one line to stdout, which Claude Code injects as context for that turn. It records the band in a temp file so the same rung never fires twice, and sweeps its own stamps after a week.

Every failure path is silent. Bad JSON on stdin, missing transcript, unreadable file, unwritable temp dir — chonk returns quietly rather than interfering with your prompt.

## Limitations

Worth knowing before you rely on it:

- **It's an estimate.** `chars / 4` is a coarse proxy, and it runs low on CJK text. It's consistent enough to compare sessions against each other, which is all a threshold needs — but it isn't a token count.
- **It measures cumulative volume, not current context.** These differ. A session that reads one enormous file in five turns has a huge *context* but small *cumulative* total, and chonk won't fire. That's usually the right call — five expensive turns is a few dollars — but it does mean chonk is tuned for the marathon, not the sprint. (See the FAQ.)
- **It doesn't know about compaction.** Cumulative tokens only go up. After a compaction your live context drops but chonk's number doesn't.
- **It reads the whole transcript each time.** ~340ms on a 62MB file, imperceptible on normal ones. [Incremental reads are the obvious fix.](https://github.com/Suprhimp/chonk/issues)
- **The transcript format isn't a public API.** It can change. chonk fails silent if it does, but it may silently stop working.

## FAQ

### Doesn't Claude Code already handle this with auto-compaction?

Compaction keeps you *inside* the window — it summarizes so the session can continue. It's a survival mechanism, not a suggestion to stop. chonk answers a different question: not "can this continue?" but "should it?"

### How is this different from the token dashboards?

Tools like ccusage and the various transcript analyzers tell you where your tokens went, afterwards. Useful, and there are several good ones. chonk is the only one I know of that says something *during* the session, when you can still act on it.

### Why not read the exact context size from `usage`?

You can — every assistant turn in the transcript carries `input_tokens + cache_creation + cache_read`, which is the exact prompt size the API billed. It's precise, it's cheaper to compute, and it drops correctly after compaction.

It answers a different question, though. Live context tells you what the *next* turn will cost; cumulative volume tells you how much this session has already consumed. For "should I start fresh," the second one matched my spend distribution better — the sessions that dominated my bill were long marathons, not single turns with huge context. If you'd rather trigger on live context, it's a small change and a PR is welcome.

### Will it slow down my prompts?

By 30–340ms depending on transcript size, once per message. The slow end only shows up in the sessions chonk exists to catch.

### Does it send anything anywhere?

No. It reads one file on your disk and prints one line to stdout. There is no network code in it.

## Contributing

Issues and PRs welcome, especially:

- Incremental transcript reads (track a byte offset instead of re-reading)
- A `--calibrate` mode that reads your own sessions and suggests thresholds
- Live-context mode as an option alongside cumulative

## License

MIT

---

<p align="center">
  <sub>Built at <a href="https://planningo.io">Planningo</a> after a month of wondering where the tokens went.</sub>
</p>
