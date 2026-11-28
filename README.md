# Valorant Clip Sorter

A local Windows tool that sorts a folder of Valorant `.mp4` clips by how many kills each one shows. It reads the end-of-round combat report with OCR, decides a category (0 to 5+ kills, Deathmatch, Range, Outside of match, Short clips, or Needs review), saves timestamped evidence images for every decision, and then copies or moves the files only after you review the preview. It is built to be conservative: when the evidence is ambiguous, the clip goes to Needs review instead of a guess, and every file operation is verified and can be undone.

All decoding and OCR run locally. Clips are never uploaded.

## What it does

- **Classifies clips from the HUD.** Detects the game mode from repeated end-of-clip HUD evidence, then searches backward from the end for the last combat report and counts outgoing **KILLED** labels (excluding assists, "KILLED YOU" and damage rows). Two matching report frames are required. Zero kills needs positive visual confirmation, not just missing OCR text.
- **Falls back safely.** If no reliable report is found, it tracks named kill-feed entries and saves the events, but those clips stay in Needs review.
- **Handles large libraries.** Decoding and OCR run in a disposable worker process with a per-clip deadline (120 s by default). A timeout or native decoder crash marks that clip for review, restarts the worker and moves on. Results are committed to SQLite per clip, so an interrupted run resumes where it stopped.
- **Safe file operations.** Preview never touches your videos. Copy uses temp files, SHA-256 verification and no-overwrite publishing; Move deletes an original only after a verified copy. Undo verifies content and refuses to overwrite.
- **Desktop GUI and CLI.** A tkinter interface with bounded logging that stays responsive, plus a `preview` / `apply` / `undo` command line.

## Tech stack

Python 3.13, OpenCV, RapidOCR (ONNX Runtime), NumPy, Pillow, tkinter, SQLite, `unittest`.

## How to run

On a fresh checkout, install Python 3.13, then in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
.\launch.cmd
```

After setup, double-click `launch.cmd` to open the GUI. Pick your clips folder, output folder and a results folder, then click **Preview / Resume**. Review `results.csv` and the images in `evidence/`, then choose **Copy from preview** or **Move from preview**.

Command line:

```powershell
.\.venv\Scripts\python.exe sorter.py preview --input "C:\path\to\clips" --output "C:\path\to\Sorted" --work "sort_results"
.\.venv\Scripts\python.exe sorter.py apply --work "sort_results" --mode copy
.\.venv\Scripts\python.exe sorter.py undo --work "sort_results"
```

Useful flags: `--mode move`, `--recursive`, `--reanalyze`, `--skip-feed` (skip the slower kill-feed fallback, recommended for large libraries), `--clip-timeout 120`, `--retry-errors`, and `--names "AccountOne" "AccountTwo"` to set the account names used for kill-feed evidence.

Sample videos, the Python environment and generated results are not included in the repo.

## Output files

| File | Contents |
|---|---|
| `results.csv` | Category, kill count, duration, method, reason, evidence timestamps, SHA-256 per clip |
| `results.json` | Full OCR observations, report checks, fallback feed events |
| `plan.json`, `state.sqlite3` | Preview settings, cached results, operation recovery state |
| `undo.jsonl` | Durable journal of copy/move/undo events |
| `evidence/` | Timestamped screenshots behind each decision |

## Testing and validation

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_sorter test_recognition test_resilience
```

The unit tests run without sample clips: 31 tests covering file operations, a synthetic report parser, worker crashes, timeouts, log floods, resume, an 11,000-row streaming export, and retrying only failed clips. On my labeled development set, the final preview matched all 15 of 15 labels (`validate_samples.py`, details in [VALIDATION.md](VALIDATION.md)). That set was used to refine the rules, so it is a sanity check, not an independent accuracy benchmark. [LARGE_LIBRARY_FIX.md](LARGE_LIBRARY_FIX.md) covers the scaling work.

## Known limits

The report search covers the last 30 seconds of a clip. Non-English HUDs, unusual overlays or crops, HDR or color changes, other HUD versions and unsupported modes may land in Needs review. Deathmatch is recognized but its kills are not counted.
