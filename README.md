# VidKit

Production-grade command-line video utility built on FFmpeg:

- **`vidkit clean`** — strip *all* metadata (EXIF/GPS, creation time, device info,
  encoder tags, chapters, custom tags) from video files **without re-encoding**.
  Every clean is verified afterwards with ffprobe; the job fails if any
  removable tag survives.
- **`vidkit split`** — split a long video into smaller ones by equal duration,
  by part count, or by explicit timestamp ranges — stream copy by default
  (fast, no quality loss), optional frame-accurate re-encode.
- **`vidkit probe`** — inspect duration, streams, and the full metadata
  inventory of a file.

Both `clean` and `split` support batch processing, parallel workers, dry runs,
JSON reports, and safe atomic output handling (interrupted jobs never leave
corrupt partial files in the output directory).

---

## Installation

### 1. Install FFmpeg (≥ 5.0)

VidKit shells out to `ffmpeg`/`ffprobe`; both must be installed and on `PATH`
(or pointed to via `VIDKIT_FFMPEG_PATH`).

| OS | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` (or `choco install ffmpeg`) |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |

### 2. Install VidKit

```bash
pip install .            # from a checkout
pip install -e ".[dev]"  # development install with test/lint tooling
```

Requires Python 3.11+.

---

## Usage

### Probe

```bash
vidkit probe movie.mp4            # human-readable tables
vidkit probe movie.mp4 --json     # machine-readable MediaInfo JSON
```

### Clean (metadata removal)

```bash
vidkit clean movie.mp4                          # -> ./vidkit_out/movie_clean.mp4
vidkit clean ./camera_roll/                     # batch: every video in the directory
vidkit clean "footage/**/*.mp4" --workers 4     # glob + parallel workers (max 8)
vidkit clean movie.mp4 --output-dir cleaned/ --overwrite
vidkit clean ./batch/ --report report.json      # write a JSON job report
vidkit clean movie.mp4 --dry-run                # print the exact ffmpeg command only
vidkit clean ./batch/ --quiet --json            # CI mode: no progress, JSON on stdout
```

Cleaning uses a **stream-copy remux** — no re-encoding, no quality change:

```
ffmpeg -i in.mp4 -map 0 -map_metadata -1 -map_chapters -1 -c copy \
       -fflags +bitexact -flags:v +bitexact -flags:a +bitexact out.mp4
```

After every clean, VidKit re-probes the output and **fails the job if any
metadata tag remains**. Purely structural container fields that a remux cannot
omit are allowed — and only with ffmpeg's neutral default values:

- format level: `major_brand`, `minor_version`, `compatible_brands`
  (the mp4 `ftyp` box — container identity, set by the muxer, never copied
  from your file's metadata)
- stream level: `handler_name` (only `VideoHandler`/`SoundHandler`/…),
  `vendor_id` (only `[0][0][0][0]`/`FFMP`), `language` (only `und`)

A leaked device string (e.g. `handler_name=Core Media Video` from an iPhone)
still fails verification.

### Split

```bash
vidkit split movie.mp4 --by-duration 10m               # equal 10-minute parts
vidkit split movie.mp4 --by-duration 1h30m             # duration suffixes: s / m / h
vidkit split movie.mp4 --by-count 4                    # 4 equal parts
vidkit split movie.mp4 --by-timestamps "00:00-05:30,05:30-12:00"
vidkit split movie.mp4 --by-count 3 --precise          # frame-accurate (re-encodes!)
vidkit split movie.mp4 --by-count 3 --dry-run          # show plan + commands only
```

Timestamps accept `HH:MM:SS`, `MM:SS`, `SS`, and duration expressions
(`90s`, `10m`, `1h30m`, `1h30m15s`). Ranges must not overlap and must fit
inside the video; gaps are allowed. Outputs are named
`movie_part01.mp4`, `movie_part02.mp4`, … in the output directory.

---

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Success (batch: no job **failed**; skipped inputs are tolerated) |
| 1 | Unexpected internal error |
| 2 | Usage error (bad flags/arguments) |
| 3 | ffmpeg/ffprobe not found, or version < 5.0 |
| 4 | Invalid input: missing, unreadable, or not a video container |
| 5 | Invalid split plan (bad duration/count, overlapping or out-of-range timestamps) |
| 6 | An ffmpeg invocation failed or timed out |
| 7 | Output already exists and `--overwrite` was not given |
| 8 | Post-clean verification found residual metadata |
| 10 | Batch finished, but one or more jobs failed |
| 130 | Interrupted (Ctrl-C); partial report was printed |

For a single input, the typed code (3–8) is surfaced directly; for batches,
individual failures are reported per-file and the run exits 10.

## Configuration

Precedence: **CLI flags > environment variables > `vidkit.toml` > defaults**.

| Env var | `vidkit.toml` key | Default | Meaning |
|---|---|---|---|
| `VIDKIT_FFMPEG_PATH` | `ffmpeg_path` | auto-detect on `PATH` | Path to `ffmpeg` (binary or its `bin/` directory) |
| `VIDKIT_FFPROBE_PATH` | `ffprobe_path` | auto-detect on `PATH` | Path to `ffprobe` |
| `VIDKIT_OUTPUT_DIR` | `output_dir` | `./vidkit_out` | Default output directory |
| `VIDKIT_WORKERS` | `workers` | CPU count | Parallel workers for batches (hard cap 8) |
| `VIDKIT_FFMPEG_TIMEOUT` | `ffmpeg_timeout` | `3600` | Per-invocation timeout in seconds |
| `VIDKIT_LOG_LEVEL` | `log_level` | `INFO` | `DEBUG` logs every ffmpeg argv |
| `VIDKIT_LOG_FORMAT` | `log_format` | `auto` | `console` (pretty), `json`, or `auto` (console on TTY, JSON otherwise) |

`vidkit.toml` is read from the current directory:

```toml
output_dir = "cleaned"
workers = 4
log_level = "DEBUG"
```

Logs go to stderr (structlog; pretty in dev, JSON in production/CI). Add
`--log-file vidkit.log` to any command to also write logs to a file, and
`--quiet` to silence progress/log output for CI.

## Troubleshooting

**Why aren't my split parts exactly the length I asked for?**
By default VidKit splits with stream copy (`-c copy`), which cannot cut
mid-GOP: every part must start on a *keyframe*, so cut points snap to the
nearest keyframe (typically within a second or two, but up to one full GOP on
footage with sparse keyframes). This is instant and lossless. If you need
frame-accurate cuts, use `--precise`, which re-encodes video with
`libx264 -crf 18 -preset medium` (visually lossless, but orders of magnitude
slower and the output is re-compressed).

**`ffmpeg was not found on PATH`**
Install FFmpeg (see table above) or set `VIDKIT_FFMPEG_PATH` /
`VIDKIT_FFPROBE_PATH` to the binary or its `bin/` directory. After a fresh
Windows install, open a new terminal so `PATH` changes apply.

**A file in my batch was "skipped"**
Skipped means ffprobe could not read it as a video (corrupt file, wrong
extension, audio-only, ...). The rest of the batch is unaffected; the reason
appears in the report (`--report report.json`) and the summary table.

**Verification failed after clean (exit 8)**
The output contained a tag VidKit refuses to whitelist. This is deliberately
strict — please report the container/tag combination. The temp output is
discarded, so nothing partially-cleaned is left in the output directory.

**Interrupted runs**
Ctrl-C stops the worker pool, kills in-flight ffmpeg processes, removes temp
files, prints a partial report, and exits 130. Because outputs are written to
temp names and renamed only on success, you will never find a truncated video
in the output directory.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .   # lint + formatting
mypy src/                               # strict type-checking
pytest --cov=vidkit --cov-fail-under=85 # tests (integration tests need ffmpeg)
```

Architecture: `src/vidkit/cli` is a thin Typer adapter; all domain logic lives
in `src/vidkit/core` (probe / cleaner / splitter services on top of a single
`FFmpeg` subprocess wrapper — the only module that spawns processes); Pydantic
models in `src/vidkit/models`; typed exceptions with exit codes in
`exceptions.py`. Segment planning is pure math, unit-tested without ffmpeg;
integration tests generate real fixtures with ffmpeg's `lavfi` test sources. 