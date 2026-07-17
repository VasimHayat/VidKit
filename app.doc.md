# VidKit — Application Guide

Everything you need to install, start, and use VidKit from scratch.

VidKit is a command-line tool with two jobs:

1. **Clean** — remove *all* metadata from video files (GPS location, creation
   time, camera/phone info, titles, encoder tags, chapters) **without
   re-encoding**, so quality is untouched and it takes seconds, not hours.
2. **Split** — cut a long video into smaller ones: equal-length parts, N equal
   parts, or exact timestamp ranges.

---

## 1. Requirements

| Requirement | Version | Check with |
|---|---|---|
| Python | 3.11 or newer | `python --version` |
| FFmpeg + FFprobe | 5.0 or newer | `ffmpeg -version` |

### Installing FFmpeg

| OS | Command |
|---|---|
| **Windows** | `winget install Gyan.FFmpeg` (or `choco install ffmpeg`) |
| **macOS** | `brew install ffmpeg` |
| **Ubuntu/Debian** | `sudo apt install ffmpeg` |
| **Fedora** | `sudo dnf install ffmpeg` |

> **Windows note:** after installing with winget, **open a new terminal** —
> the PATH change does not apply to terminals that were already open.
> If VidKit still can't find ffmpeg, point it there directly:
>
> ```powershell
> $env:VIDKIT_FFMPEG_PATH  = "C:\path\to\ffmpeg\bin"
> $env:VIDKIT_FFPROBE_PATH = "C:\path\to\ffmpeg\bin"
> ```
>
> (The variable accepts either the `.exe` itself or its `bin` folder.
> On this machine the winget install lives under
> `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_...\ffmpeg-8.1.2-full_build\bin`.)

---

## 2. Starting the app (installation)

From the project folder (`py-video-tool`):

### Windows (PowerShell)

```powershell
# one-time setup: create a virtual environment and install VidKit into it
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .

# run it
.\.venv\Scripts\vidkit.exe --version
```

To use plain `vidkit` (without the full path), activate the venv first:

```powershell
.\.venv\Scripts\Activate.ps1
vidkit --version
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .

vidkit --version
```

### Developer install (tests + linters included)

```bash
pip install -e ".[dev]"
```

You should see `vidkit 1.0.0`. Running `vidkit` with no arguments prints the
help screen. Every command below assumes the venv is activated (or prefix with
`.\.venv\Scripts\vidkit.exe` on Windows).

---

## 3. The three commands

### 3.1 `vidkit probe` — see what's inside a file

Shows duration, streams (video/audio codecs), and **every metadata tag** in
the file — run this first to see what `clean` will remove.

```bash
vidkit probe movie.mp4          # human-readable tables
vidkit probe movie.mp4 --json   # machine-readable JSON
```

Example output includes a "Metadata inventory" table like:

```
| Location       | Key           | Value                       |
|----------------|---------------|-----------------------------|
| format         | title         | Family vacation             |
| format         | location      | +37.7749-122.4194/          |  <- GPS!
| format         | creation_time | 2024-06-15T10:30:00.000000Z |
| stream:0:video | handler_name  | Core Media Video            |  <- iPhone
```

### 3.2 `vidkit clean` — remove all metadata

```bash
# one file -> ./vidkit_out/movie_clean.mp4
vidkit clean movie.mp4

# choose the output folder
vidkit clean movie.mp4 --output-dir cleaned/

# a whole folder of videos (batch)
vidkit clean ./camera_roll/

# a glob pattern, processed with 4 parallel workers
vidkit clean "footage/**/*.mp4" --workers 4

# preview the exact ffmpeg command without running anything
vidkit clean movie.mp4 --dry-run

# replace outputs that already exist
vidkit clean movie.mp4 --overwrite

# write a JSON report of what happened to every file
vidkit clean ./camera_roll/ --report report.json

# CI / scripting mode: no progress bars, JSON result on stdout
vidkit clean ./camera_roll/ --quiet --json
```

What it does:

- Copies the video/audio streams bit-for-bit (**no re-encode, no quality
  loss**) into a new file with `-map_metadata -1 -map_chapters -1 -c copy`
  plus bitexact flags so ffmpeg doesn't add its own encoder tag.
- **Verifies the result with ffprobe** and fails the job if any real tag
  survived. (Three structural container fields — `major_brand`,
  `minor_version`, `compatible_brands` — always remain; they identify the mp4
  file type and contain no personal data.)
- Never touches your original file. Output is named `<name>_clean.<ext>`.
- Writes to a temp file and renames it only on success — an interrupted run
  never leaves a half-written video in the output folder.
- In a batch, corrupt or non-video files are **skipped** and reported; they
  never crash the run.

### 3.3 `vidkit split` — cut a video into parts

Pick **exactly one** mode:

```bash
# equal segments of a given length (suffixes: s, m, h — combinable)
vidkit split movie.mp4 --by-duration 10m
vidkit split movie.mp4 --by-duration 90s
vidkit split movie.mp4 --by-duration 1h30m

# N equal parts
vidkit split movie.mp4 --by-count 4

# exact ranges (start-end, comma separated; gaps allowed, overlaps rejected)
vidkit split movie.mp4 --by-timestamps "00:00-05:30,05:30-12:00"
```

Timestamps accept `HH:MM:SS`, `MM:SS`, plain seconds, or duration expressions
(`90s`, `2m30s`). Outputs are numbered `movie_part01.mp4`, `movie_part02.mp4`, …

Useful flags (same as clean): `--output-dir`, `--dry-run`, `--overwrite`,
`--report`, `--quiet`, `--json`.

**Fast vs exact cuts:**

| Mode | Speed | Accuracy | Quality |
|---|---|---|---|
| default (stream copy) | instant | cut snaps to the nearest keyframe (usually within ~1–2 s) | lossless |
| `--precise` | slow (re-encodes) | frame-accurate | visually lossless (libx264 CRF 18) |

```bash
vidkit split movie.mp4 --by-count 3 --precise
```

Use the default unless the exact frame of the cut matters.

---

## 4. A complete example session

```powershell
PS> vidkit probe vacation.mp4
# ...shows GPS location, phone model, creation date...

PS> vidkit clean vacation.mp4 --output-dir cleaned
# cleaning vacation.mp4 ━━━━━━━━━━━━ 1/1
# 1 succeeded · 0 failed · 0 skipped

PS> vidkit probe cleaned\vacation_clean.mp4
# Metadata inventory: only major_brand / minor_version / compatible_brands

PS> vidkit split cleaned\vacation_clean.mp4 --by-count 3 --output-dir parts
# splitting vacation_clean.mp4 ━━━━━━━━━━━━ 3/3

PS> dir parts
# vacation_clean_part01.mp4  vacation_clean_part02.mp4  vacation_clean_part03.mp4
```

---

## 5. Common options (all commands)

| Flag | Meaning |
|---|---|
| `--output-dir`, `-o` | Where outputs go (default `./vidkit_out`) |
| `--overwrite` | Allow replacing existing output files |
| `--dry-run` | Print the plan / exact ffmpeg commands, execute nothing |
| `--report FILE` | Write a JSON job report (per-file status, timings, outputs) |
| `--quiet`, `-q` | No progress bars/logs — for scripts and CI |
| `--json` | Print the result as JSON on stdout |
| `--log-file FILE` | Also write structured JSON logs to a file |
| `--log-level LEVEL` | `DEBUG` shows every ffmpeg command line |
| `--workers`, `-w` | (clean only) parallel workers for batches, max 8 |

Press **Ctrl-C** at any time: in-flight ffmpeg processes are killed, temp
files are removed, a partial report is printed, and the exit code is 130.

---

## 6. Configuration (optional)

Priority: **command-line flags > environment variables > `vidkit.toml` > defaults**.

Environment variables (prefix `VIDKIT_`):

```powershell
$env:VIDKIT_OUTPUT_DIR = "D:\cleaned"     # default output folder
$env:VIDKIT_WORKERS = "4"                 # batch parallelism (cap 8)
$env:VIDKIT_FFMPEG_TIMEOUT = "7200"       # per-ffmpeg-call timeout, seconds
$env:VIDKIT_LOG_LEVEL = "DEBUG"
$env:VIDKIT_LOG_FORMAT = "json"           # console | json | auto
$env:VIDKIT_FFMPEG_PATH = "C:\ffmpeg\bin" # if ffmpeg isn't on PATH
```

Or put a `vidkit.toml` in the folder you run VidKit from:

```toml
output_dir = "cleaned"
workers = 4
log_level = "INFO"
```

---

## 7. Exit codes (for scripts)

| Code | Meaning |
|---:|---|
| 0 | Success (batch: nothing *failed*; skipped files are tolerated) |
| 1 | Unexpected internal error |
| 2 | Usage error — bad flags or arguments |
| 3 | ffmpeg/ffprobe missing, or older than 5.0 |
| 4 | Input missing, unreadable, or not a video |
| 5 | Bad split plan (invalid duration/count, overlapping/out-of-range ranges) |
| 6 | An ffmpeg run failed or timed out |
| 7 | Output exists and `--overwrite` not given |
| 8 | Metadata still present after clean (verification failed) |
| 10 | Batch finished but some jobs failed |
| 130 | Interrupted with Ctrl-C |

---

## 8. Troubleshooting

**"ffmpeg was not found on PATH" (exit 3)**
Install FFmpeg (section 1) or set `VIDKIT_FFMPEG_PATH`. On Windows, open a
*new* terminal after installing.

**"output already exists" (exit 7)**
VidKit never overwrites anything by default. Add `--overwrite` or choose
another `--output-dir`.

**Split parts aren't exactly the requested length**
Normal in default mode: stream copy can only cut on keyframes. Use
`--precise` if the exact cut point matters (much slower, re-encodes).

**A file was "skipped" in a batch**
ffprobe couldn't read it as video (corrupt, wrong extension, audio-only).
The rest of the batch continues; the reason is in the summary table and in
`--report report.json`.

**Where did my outputs go?**
Default is `./vidkit_out` relative to the folder you ran the command from.
The report table and the JSON report list every output path in full.

**I want to see exactly what VidKit runs**
Add `--dry-run` (prints commands, executes nothing) or `--log-level DEBUG`
(logs every ffmpeg command line as it runs).

---

## 9. For developers

```bash
pip install -e ".[dev]"                  # install with test/lint tooling
ruff check . && ruff format --check .    # lint + formatting
mypy src/                                # strict type checking
pytest --cov=vidkit --cov-fail-under=85  # 171 tests; integration needs ffmpeg
```

Layout: `src/vidkit/cli` (Typer/Rich adapter) → `src/vidkit/core` (probe,
cleaner, splitter services; `ffmpeg.py` is the only module that spawns
subprocesses) → `src/vidkit/models` (Pydantic). Typed exceptions in
`exceptions.py` map 1:1 to the exit-code table above. CI (GitHub Actions)
runs ruff → mypy → pytest with the 85% coverage gate on Python 3.11–3.13.
