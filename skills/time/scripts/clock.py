#!/usr/bin/env python3
"""clock — time, date, duration, and named-stopwatch CLI.

Stdlib only. Python 3.8+. Uses zoneinfo (3.9+) for named timezones; on Windows
this may require `pip install tzdata`. UTC and local timezone always work.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python < 3.9
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception  # type: ignore


DEFAULT_STORE = Path.home() / ".claude" / "skills" / "time" / "state" / "timers.json"


# ---------- now / timezone ----------

def _local_tz():
    """Return the current local tzinfo.

    We snapshot it via `datetime.now().astimezone().tzinfo` (which only invokes
    the OS's localtime for the *current* time — that call is safe) and reuse it
    for any historical date. Calling `.astimezone()` with no argument on a
    naive datetime before 1970 fails on Windows with OSError EINVAL because
    the underlying C `_localtime64_s` rejects negative epochs. Passing an
    explicit tzinfo (via `.astimezone(tz)` or `.replace(tzinfo=tz)`) avoids it.
    """
    return datetime.now().astimezone().tzinfo


def _now(tz: str | None = None) -> datetime:
    if tz is None:
        return datetime.now(_local_tz())
    if tz.upper() == "UTC":
        return datetime.now(timezone.utc)
    if ZoneInfo is None:
        sys.exit(
            "zoneinfo not available. Use --tz UTC, omit --tz for local, "
            "or upgrade to Python 3.9+."
        )
    try:
        zi = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        sys.exit(
            f"unknown timezone: {tz!r}. On Windows you may need: pip install tzdata"
        )
    return datetime.now(zi)


# ---------- timestamp parsing ----------

_EPOCH_RE = re.compile(r"-?\d{10,13}(\.\d+)?")


def _parse_ts(s: str) -> datetime:
    """Parse a timestamp string into an aware datetime.

    Accepts ISO 8601, unix epoch (sec or ms), and the keywords
    now / today / yesterday / tomorrow. Naive ISO is treated as local.
    """
    s = s.strip()
    low = s.lower()

    if low == "now":
        return _now()
    midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    if low == "today":
        return midnight
    if low == "yesterday":
        return midnight - timedelta(days=1)
    if low == "tomorrow":
        return midnight + timedelta(days=1)

    if _EPOCH_RE.fullmatch(s):
        n = float(s)
        if abs(n) > 1e12:  # milliseconds
            n /= 1000
        return datetime.fromtimestamp(n, timezone.utc).astimezone(_local_tz())

    # Accept trailing 'Z' on Python versions that don't (pre-3.11).
    s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError as e:
        sys.exit(f"cannot parse timestamp: {s!r} ({e})")
    if dt.tzinfo is None:
        # Treat naive ISO as local time. Use .replace (not .astimezone with no
        # argument) so pre-1970 dates work on Windows — see _local_tz().
        dt = dt.replace(tzinfo=_local_tz())
    return dt


# ---------- duration parsing & humanizing ----------

_DUR_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(y|w|d|h|m|s)", re.IGNORECASE)
_DUR_UNIT_SECONDS = {
    "y": 365 * 86400,  # approximate
    "w": 7 * 86400,
    "d": 86400,
    "h": 3600,
    "m": 60,
    "s": 1,
}


def _parse_duration(s: str) -> float:
    """Parse '3d5h30m' or '-2w' into seconds. Negative prefix flips sign."""
    raw = s.strip()
    neg = raw.startswith("-")
    if neg or raw.startswith("+"):
        raw = raw[1:]
    parts = _DUR_PART.findall(raw)
    if not parts:
        sys.exit(f"cannot parse duration: {s!r}")
    total = 0.0
    reconstructed = ""
    for num, unit in parts:
        total += float(num) * _DUR_UNIT_SECONDS[unit.lower()]
        reconstructed += f"{num}{unit}"
    # ensure we consumed the whole string (ignoring whitespace and case)
    if reconstructed.lower().replace(" ", "") != raw.lower().replace(" ", ""):
        sys.exit(f"cannot parse duration: {s!r} (stray characters)")
    return -total if neg else total


def _humanize(seconds: float) -> str:
    s = int(round(abs(seconds)))
    sign = "-" if seconds < 0 else ""
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return sign + " ".join(parts)


# ---------- formatting ----------

def _fmt(dt: datetime, fmt: str) -> str:
    if fmt == "iso":
        return dt.isoformat()
    if fmt == "unix":
        return str(int(dt.timestamp()))
    if fmt == "human":
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    if fmt == "date":
        return dt.strftime("%Y-%m-%d")
    if fmt == "time":
        return dt.strftime("%H:%M:%S")
    # treat as a custom strftime format
    return dt.strftime(fmt)


# ---------- commands: now / parse / diff / add / humanize / weekday ----------

def cmd_now(args):
    print(_fmt(_now(args.tz), args.format))


def cmd_parse(args):
    print(_fmt(_parse_ts(args.expr), args.format))


def cmd_diff(args):
    a = _parse_ts(args.t1)
    b = _parse_ts(args.t2)
    sec = (b - a).total_seconds()
    if args.json:
        print(json.dumps({
            "from": a.isoformat(),
            "to": b.isoformat(),
            "seconds": sec,
            "humanized": _humanize(sec),
        }))
    else:
        print(f"{sec:.0f}s  ({_humanize(sec)})")


def cmd_add(args):
    ts = _parse_ts(args.ts)
    delta = timedelta(seconds=_parse_duration(args.duration))
    print(_fmt(ts + delta, args.format))


def cmd_sub(args):
    ts = _parse_ts(args.ts)
    delta = timedelta(seconds=_parse_duration(args.duration))
    print(_fmt(ts - delta, args.format))


def cmd_humanize(args):
    print(_humanize(args.seconds))


def cmd_weekday(args):
    print(_parse_ts(args.date).strftime("%A"))


# ---------- commands: timer ----------

def _load_timers(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"timer state corrupt ({path}): {e}")


def _save_timers(path: str, timers: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(timers, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_timer(name: str, t: dict, short: bool = False) -> None:
    if t.get("stop") is not None:
        elapsed = float(t.get("elapsed_s") or 0)
        if short:
            print(f"{name:20}  STOPPED  {_humanize(elapsed)}")
        else:
            print(f"{name}  STOPPED")
            print(f"  started: {t['start']}")
            print(f"  stopped: {t['stop']}")
            print(f"  elapsed: {_humanize(elapsed)}  ({elapsed:.1f}s)")
    else:
        start = datetime.fromisoformat(t["start"])
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        if short:
            print(f"{name:20}  RUNNING  {_humanize(elapsed)}")
        else:
            print(f"{name}  RUNNING")
            print(f"  started: {t['start']}")
            print(f"  elapsed: {_humanize(elapsed)}  ({elapsed:.1f}s)")


def cmd_timer(args):
    timers = _load_timers(args.store)

    if args.action in ("start", "stop") and not args.name:
        sys.exit(f"timer {args.action} requires a NAME")

    if args.action == "start":
        existing = timers.get(args.name)
        if existing and existing.get("stop") is None:
            sys.exit(
                f"timer {args.name!r} is already running (since {existing['start']}). "
                "Stop it first or pick a different name."
            )
        now_iso = _utc_now_iso()
        timers[args.name] = {"start": now_iso, "stop": None, "elapsed_s": None}
        _save_timers(args.store, timers)
        print(f"started {args.name} at {now_iso}")
        return

    if args.action == "stop":
        t = timers.get(args.name)
        if t is None:
            sys.exit(f"no timer named {args.name!r}")
        if t.get("stop") is not None:
            print(
                f"timer {args.name!r} already stopped "
                f"(elapsed {_humanize(t['elapsed_s'])})",
                file=sys.stderr,
            )
            sys.exit(1)
        start = datetime.fromisoformat(t["start"])
        stop_dt = datetime.now(timezone.utc)
        elapsed = (stop_dt - start).total_seconds()
        t["stop"] = stop_dt.isoformat()
        t["elapsed_s"] = elapsed
        _save_timers(args.store, timers)
        print(f"stopped {args.name}: {elapsed:.1f}s  ({_humanize(elapsed)})")
        return

    if args.action == "status":
        if args.name:
            t = timers.get(args.name)
            if t is None:
                sys.exit(f"no timer named {args.name!r}")
            _print_timer(args.name, t)
            return
        if not timers:
            print("(no timers)")
            return
        for name, t in timers.items():
            _print_timer(name, t, short=True)
        return

    if args.action == "list":
        if not timers:
            print("(no timers)")
            return
        for name, t in timers.items():
            _print_timer(name, t, short=True)
        return

    if args.action == "clear":
        if args.all:
            n = len(timers)
            _save_timers(args.store, {})
            print(f"cleared {n} timer(s)")
            return
        if args.name:
            if args.name not in timers:
                sys.exit(f"no timer named {args.name!r}")
            del timers[args.name]
            _save_timers(args.store, timers)
            print(f"cleared timer {args.name!r}")
            return
        # default: clear only stopped timers
        stopped = [n for n, t in timers.items() if t.get("stop") is not None]
        for n in stopped:
            del timers[n]
        _save_timers(args.store, timers)
        print(f"cleared {len(stopped)} stopped timer(s)")


# ---------- entrypoint ----------

def build_parser():
    p = argparse.ArgumentParser(
        prog="clock",
        description="Time, date, duration, and named-stopwatch CLI (stdlib only).",
    )
    p.add_argument(
        "--store",
        default=str(DEFAULT_STORE),
        help=f"timer state file (default: {DEFAULT_STORE})",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("now", help="current date/time")
    s.add_argument("--tz", help="timezone (UTC, Europe/Berlin, ...); default local")
    s.add_argument(
        "--format",
        default="iso",
        help="iso | unix | human | date | time | <strftime-string>",
    )
    s.set_defaults(func=cmd_now)

    s = sub.add_parser("parse", help="parse a timestamp expression to ISO")
    s.add_argument("expr")
    s.add_argument("--format", default="iso")
    s.set_defaults(func=cmd_parse)

    s = sub.add_parser("diff", help="duration between two timestamps (t2 - t1)")
    s.add_argument("t1")
    s.add_argument("t2")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("add", help="TIMESTAMP + DURATION (e.g. 'add now 3d')")
    s.add_argument("ts")
    s.add_argument("duration")
    s.add_argument("--format", default="iso")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("sub", help="TIMESTAMP - DURATION (e.g. 'sub now 7d')")
    s.add_argument("ts")
    s.add_argument("duration")
    s.add_argument("--format", default="iso")
    s.set_defaults(func=cmd_sub)

    s = sub.add_parser("humanize", help="seconds -> '1h 15m'")
    s.add_argument("seconds", type=float)
    s.set_defaults(func=cmd_humanize)

    s = sub.add_parser("weekday", help="day of the week for a date")
    s.add_argument("date")
    s.set_defaults(func=cmd_weekday)

    s = sub.add_parser("timer", help="named stopwatch with persistent state")
    s.add_argument(
        "action", choices=["start", "stop", "status", "list", "clear"]
    )
    s.add_argument("name", nargs="?")
    s.add_argument(
        "--all",
        action="store_true",
        help="with 'clear': remove all timers instead of just stopped ones",
    )
    s.set_defaults(func=cmd_timer)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
