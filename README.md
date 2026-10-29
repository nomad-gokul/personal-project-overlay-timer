# Study Timer ⏱️

A tiny, always-on-top **see-through stopwatch** for Windows that sits in a corner of your screen while you study, so you always know how long you've been at it, without covering the page you're reading.

I built it for myself to track daily study time during placement prep.

## Features
- **Transparent overlay**: only the digits are visible, no window or background
- **Always on top**: stays visible over the browser, PDFs, IDEs, etc.
- **Readable anywhere**: digits have a dark outline, so they show on light and dark pages
- **Drag to place** or **snap to any corner** (stays clear of the taskbar); position is remembered
- **Break tracking**: pausing starts a break, resuming ends it
- **CSV log for analysis**: every study block and break is saved automatically to a CSV
- **Daily summary**: today's study/break totals and a 7-day view, right from the timer
- Adjustable **opacity** and **size**
- Single Python file, **no dependencies** (just the standard library + Tkinter)

## Usage
1. Install [Python 3](https://www.python.org/downloads/) (Tkinter is included).
2. Download `study_timer.pyw` and double-click it.

| Action | What it does |
|---|---|
| Double-click digits | Start / pause (white = studying, amber = on a break) |
| Drag digits | Move the timer |
| Right-click digits | Menu: today's totals, reset, open CSV log, last 7 days, snap to corner, opacity, size, exit |

**Start with Windows:** press `Win + R`, type `shell:startup`, and put a shortcut to `study_timer.pyw` in that folder.

## Study log (CSV)
Every study block and break is appended to `study_log.csv` in your user folder (`C:\Users\<you>\study_log.csv`). Open it from the right-click menu → **Open study log (CSV)**.

```csv
date,start_time,end_time,type,duration_minutes
2026-10-29,09:00:12,09:52:40,study,52.47
2026-10-29,09:52:40,10:03:05,break,10.42
2026-10-29,10:03:05,11:01:30,study,58.42
```

- A **break** is the time between pausing and resuming. If you pause and then quit, that pause is not counted as a break.
- Blocks shorter than 5 seconds (accidental clicks) are ignored.
- If the laptop shuts down or the app crashes mid-study, the block is still logged up to the last autosave (every 30 s).
- If the CSV is open in Excel (Windows locks it), new rows are queued and written as soon as the file is free.

Quick analysis with pandas:
```python
import pandas as pd
df = pd.read_csv("study_log.csv", parse_dates=["date"])
print(df.pivot_table(index="date", columns="type", values="duration_minutes", aggfunc="sum"))
```

Settings and daily totals are stored in `~/.study_timer.json`.

## How it works
- `overrideredirect` + `-topmost` give a borderless window that floats above everything.
- `-transparentcolor` turns the background colour fully transparent (Windows), and `-alpha` controls overall opacity.
- Durations use `time.monotonic()` so they aren't affected by system clock changes; the open block is checkpointed every 30 s for crash recovery.
- The Win32 `SystemParametersInfo` work area is used to snap to corners without overlapping the taskbar, and DPI awareness keeps the text sharp on high-res screens.

## License
MIT
