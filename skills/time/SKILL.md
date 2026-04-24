---
name: time
description: Accurate time, date, duration, and stopwatch operations. USE THIS instead of guessing — Claude has no wall clock and makes calendar arithmetic mistakes (off-by-one on days, wrong weekday, leap years, DST, timezone conversion). Triggers include "what time is it", "what's today's date", "how long did X take", "how many days until/since Y", "what weekday was Z", "start/stop a timer", "what's N weeks from now".
---

# time skill

Deterministic answers for everything involving clocks, calendars, and stopwatches. Offloads all time reasoning to a stdlib-only Python CLI instead of guessing from session context.

## When to use

**Invoke this skill whenever an answer depends on a real wall-clock or calendar value.** Claude reliably drifts on:

- **Current date/time.** The system prompt may contain today's date, but not the current time-of-day, and the date can be stale in long-lived sessions.
- **Elapsed time of a process Claude started.** Claude has no stopwatch — if you started a build ten minutes ago, you have no idea how long it has run.
- **Calendar arithmetic.** Off-by-one on day counts, wrong weekday for a historical date, forgetting leap years, forgetting DST transitions, miscounting weeks-until.
- **Timezone conversion.** Local ↔ UTC ↔ named zones.

Concrete triggers — run this skill the moment you see any of:

- "What time is it?" / "What's today's date?"
- "How long did that take?" / "How much time has passed since ...?"
- "How many days until Friday / the release / my birthday?"
- "What day of the week was November 9, 1989?"
- "Start a timer" / "time this for me" / "stopwatch"
- "What's the date 3 weeks from now?" / "When is 90 days from today?"

**Do NOT** use this skill for things that are time-shaped but not wall-clock:
- Algorithm time-complexity
- Historical facts you already know ("the moon landing was in 1969")
- Idioms ("in the long run", "just a moment")

## Golden rule: bracket long processes with a timer

Whenever you're about to run a command that might take more than a few seconds — builds, tests, deploys, network fetches, data processing — **start a timer first and stop it after**. Otherwise you'll have no way to answer "how long did that take?" later.

```bash
python scripts/clock.py timer start build
npm run build       # or whatever the long thing is
python scripts/clock.py timer stop build
# → stopped build: 47.3s  (47s)
```

Timer state persists across invocations in `~/.claude/skills/time/state/timers.json`, so you can start a timer in one tool call and stop it in another.

## Commands

All commands: `python scripts/clock.py <subcommand>`.

| Command | Purpose |
|---|---|
| `now [--tz TZ] [--format FMT]` | Current date/time (default: local, ISO 8601). |
| `parse EXPR [--format FMT]` | Parse a timestamp expression → ISO (or custom format). |
| `diff T1 T2 [--json]` | Duration between two timestamps (`T2 - T1`). |
| `add TS DURATION [--format FMT]` | Timestamp + duration. |
| `sub TS DURATION [--format FMT]` | Timestamp − duration (use this instead of `add ... -7d`; argparse eats leading `-`). |
| `humanize SECONDS` | `4500` → `1h 15m`. |
| `weekday DATE` | Day of the week for a date. |
| `timer start NAME` | Start a named stopwatch. |
| `timer stop NAME` | Stop it, print elapsed. |
| `timer status [NAME]` | Elapsed so far (running or stopped). Without NAME: all timers. |
| `timer list` | Short one-line listing of all timers. |
| `timer clear [NAME] [--all]` | Clear a specific timer, all stopped ones (default), or all (`--all`). |

### Formats for `--format`

`iso` (default), `unix`, `human` (`YYYY-MM-DD HH:MM:SS TZ`), `date` (`YYYY-MM-DD`), `time` (`HH:MM:SS`), or any Python `strftime` string like `%A, %d %B %Y`.

### Duration syntax

`3d5h30m` style. Units: `y` (365d approximate), `w` (7d), `d`, `h`, `m`, `s`. Optional `+`/`-` prefix for sign. Examples:

```
45s        10m        2h30m      3d
2w         1y         -7d        1d12h
```

### Timestamp syntax (accepted by `parse`, `diff`, `add`, `weekday`)

- **ISO 8601:** `2026-04-24`, `2026-04-24T10:30`, `2026-04-24T10:30:00+02:00`, `2026-04-24T10:30:00Z`.
- **Unix epoch** (seconds or milliseconds): `1745481600`, `1745481600000`.
- **Keywords:** `now`, `today`, `yesterday`, `tomorrow`.

Naive timestamps (no offset) are interpreted as **local time**.

## Recipes

**Current UTC time:**
```bash
python scripts/clock.py now --tz UTC
```

**Today's date only:**
```bash
python scripts/clock.py now --format date
```

**Time a long process:**
```bash
python scripts/clock.py timer start deploy
./deploy.sh
python scripts/clock.py timer stop deploy
```

**Check elapsed on a still-running timer (without stopping):**
```bash
python scripts/clock.py timer status deploy
```

**Days between two dates:**
```bash
python scripts/clock.py diff 2024-01-15 2026-04-24
# → 70502400s  (816d)
```

**N weeks from today:**
```bash
python scripts/clock.py add now 3w --format date
```

**Weekday of a historical date:**
```bash
python scripts/clock.py weekday 1989-11-09
# → Thursday
```

**Humanize a raw seconds value from elsewhere:**
```bash
python scripts/clock.py humanize 5400
# → 1h 30m
```

**Custom strftime format:**
```bash
python scripts/clock.py now --format "%A, %d %B %Y"
# → Friday, 24 April 2026
```

## Windows path gotcha (Git-Bash / MSYS)

When invoking the script from Bash on Windows, **use forward slashes** for the path, not backslashes:

```bash
# ✓ works
python /c/Users/os/.claude/skills/time/scripts/clock.py now

# ✗ fails — Bash treats backslashes as escape characters and collapses
#   C:\Users\os\... into the nonsense path "Usersos.claudeskillstimescriptsclock.py"
python C:\Users\os\.claude\skills\time\scripts\clock.py now
```

Native `cmd.exe` / PowerShell accept backslashes fine; this is a Bash quirk. Rule of thumb: from any Unix-y shell on Windows, spell the path with `/`.

## Accuracy notes

- The script reads the **host machine's wall clock** — not Claude's session-frozen date. That's the entire point of this skill.
- **Named timezones** (e.g. `Europe/Berlin`) require `zoneinfo` (Python 3.9+). On Windows you may need `pip install tzdata`. `UTC` and local time always work without any install.
- The `y` duration unit is a **365-day approximation** — leap years and exact year arithmetic are not handled (the CLI is stdlib-only and deliberately doesn't depend on `dateutil`). For precise "N calendar years from date X" use the host's `date` command or a dedicated tool.
- DST transitions: `add` adds fixed seconds; it does **not** keep a wall-clock "same hour, N days later" invariant across DST boundaries. For DST-aware calendar math, prefer manipulating `datetime` directly with `zoneinfo`.

## Anti-patterns

- Do not invent a current time ("it's probably around 3pm") — run `now`.
- Do not estimate how long a command took ("that took roughly a minute") — wrap it with `timer start`/`stop`.
- Do not compute weekdays in your head for anything past the current week — run `weekday`.
- Do not convert "3 weeks from Tuesday" mentally — run `add`.
