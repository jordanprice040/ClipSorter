# Valorant Clip Sorter

Local Windows Python tool with a small desktop interface and a command line. Only `.mp4` files are scanned (case insensitive); screenshots and other file types are ignored. Input and output folders can be anywhere accessible on your computer. All decoding and OCR run locally. Clips are never uploaded.

## Start

On a fresh checkout, install Python 3.13 and run these commands in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
.\launch.cmd
```

After setup, double-click **launch.cmd** to open the tool. Sample videos, the Python environment, and generated results are not included in the repository.

Choose your clips folder, output folder, and results/resume folder. Click **Preview / Resume**. Review `results.csv`, `validation.csv` for the supplied samples, and the timestamped images in `evidence`. **Copy from preview** preserves originals. **Move from preview** explicitly removes originals only after verifying a copied destination. Neither action runs automatically after preview.

Changing the folder fields does not analyze those folders. Always click **Preview / Resume** after changing them. Copy/Move stay disabled until the selected input, output, and subfolder setting match a completed preview. The status line identifies the saved preview; move confirmation shows both paths. For each separate clip collection, use a separate results/resume folder to keep its results and undo history together.

Keep the entire results folder: SQLite holds the resumable plan and operation state, while `undo.jsonl` is a readable undo journal. **Undo** removes unchanged copies or restores moved originals. It refuses changed destinations and occupied original paths. Empty category directories remain.

## Command line

From this folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe sorter.py preview --input "C:\path\to\clips" --output "C:\path\to\Sorted" --work "sort_results"
.\.venv\Scripts\python.exe sorter.py apply --work "sort_results" --mode copy
.\.venv\Scripts\python.exe sorter.py undo --work "sort_results"
```

For moving, explicitly use `--mode move`. Undo a copy before switching the same plan to move. Rerun the same command after an interruption. A completed preview is required before apply. `--recursive` includes subfolders; output and evidence directories are excluded. `--reanalyze` ignores cached analysis. `--skip-feed` skips the slower fallback evidence scan. The desktop interface leaves this optional, review-only feed scan **off by default**, which is recommended for large libraries. Preview can create evidence and result files, but never creates sorted video copies or moves originals.

## Large libraries and decoder errors

The batch size is not limited to a few hundred clips. Video decoding and OCR run in a persistent disposable worker. Every clip has a configurable total deadline, including hashing, OCR, and optional feed tracking: **120 seconds by default**. A timeout or native decoder crash puts the clip in Needs review, restarts the worker, and continues to the next clip. Decoder error spam cannot fill the interface; it shows bounded progress and concise per-clip failures. A deadline is a safety limit, not a runtime estimate or a diagnosis that a clip is corrupt.

The interface keeps at most 1,000 queued messages and about 1,500 visible log lines, and yields between display batches. Saved-preview checks run off the UI thread so a slow drive does not block that check. Stop cancels the current preview worker and preserves completed database results. On copy/move/undo, Stop takes effect between file operations so an in-progress operation can reach a safe state.

Each completed clip is committed immediately to SQLite. CSV snapshots update in batches (50 completed clips or about a minute between clips). Full JSON is streamed when preview finishes or stops cleanly, rather than rewriting all OCR results after every clip. Following a forced termination, SQLite is the source of truth; resume rebuilds the export files. Keep CSV closed in Excel when the final exports are written.

For the E-drive library, reopen the updated program, use the same folders, leave **Collect kill-feed evidence** off, and click Preview / Resume. Existing compatible results are reused. Turn on **Retry previous decoder errors / timeouts** to retry only failures; raise Seconds per clip limit if valid large/slow files reach the default. CLI equivalents are `--skip-feed --clip-timeout 120 --retry-errors`. If a file cannot even be hashed, it is recorded as Needs review and apply leaves its original in place; it is never moved without verification.

All supplied account aliases are built in. Override them for feed evidence with `--names "AccountOne" "AccountTwo"`. Combat-report counting does not depend on your displayed name. Hidden agent names are deliberately not treated as personal aliases.

## Decisions

Output categories are `0`, `1`, `2`, `3`, `4`, `5+`, `Needs review`, `Deathmatch`, `Range`, `Outside of match`, and `Short clips`.

1. Repeated ending HUD evidence determines range, deathmatch, or outside-of-match first. Earlier match content does not override that ending state. Inconsistent mode evidence goes to review.
2. A standard-match clip shorter than **20 seconds** goes directly to Short clips when a standard round timer is positively identified. Unknown or nonstandard clips do not enter this category merely because they are short.
3. Search backward from the ending, densely sampling its last two seconds, for the last shown combat report. Require two complete report frames with matching outgoing kill counts. Count exact left-side **KILLED** labels, exclude **ASSIST**, incoming **KILLED YOU**, killer banners, and damage totals. A visual outgoing highlight check guards against dropped kill/assist OCR labels. Evidence timestamps refer to seconds from the start of the clip.
4. Zero requires readable outgoing damage rows and visual confirmation that no unaccounted outgoing kill/assist highlights remain; missing OCR alone never establishes zero. Ambiguous reports go to review.
5. If no reliable report is found, track named outgoing kill-feed entries at two samples per second, deduplicate persistent entries, and save event timestamps and images. **Feed fallback remains review-only**: it cannot safely prove a complete final-round total from a partial recording, menus, resurrection, or a hidden player name. Candidate events are in `results.json`; these clips stay in Needs review.

The report search covers the last 30 seconds. Clips whose relevant report occurs earlier, non-English HUDs, unusual overlays/crops, HDR/color changes, other HUD versions, and unsupported modes may need review. Two OCR frames are a consistency check, not a calibrated confidence probability. Deathmatch recognition uses its top-bar score sequence/timer and respawn or multikill HUD text; it does not total deathmatch kills.

## Files and safety

- `results.csv`: source, category, kill count when established, duration, method, reason, evidence timestamps, evidence directory, and SHA-256.
- `results.json`: full OCR observations, report checks, and fallback feed events.
- `plan.json` / `state.sqlite3`: preview settings, completion marker, cached results, and operation recovery state.
- `undo.jsonl`: durable prepare, publish, completion, and undo events.
- `evidence`: timestamped screenshots for inspection.

Copies use temporary files, SHA-256 verification, and publication that refuses to overwrite a destination. Filename collisions get `(1)`, `(2)`, etc. File identity is recorded before publication to recover the interruption between a rename and the next database commit. Move deletes the source only after verified publication. Undo also verifies file content and refuses overwrites. One process can use a given results folder at a time. Preserve the journal/database and avoid changing files while applying or undoing. This is an undo facility, not a replacement for backups.

## Validation

The original 13 labeled samples were inspected before implementing file operations. A first prototype exposed a deathmatch misclassification and two conservative review results; the revised prototype matched all 13 labels. After adding the short and zero-kill clips and a visual check for dropped report labels, the final preview matched **15 of 15** supplied labels. All source checksums were verified unchanged. Labels are consumed only by `validate_samples.py`, never the visual classifier. See `VALIDATION.md` and `sort_results/validation.csv` for the per-clip results.

```powershell
.\.venv\Scripts\python.exe validate_samples.py sort_results/results.json
.\.venv\Scripts\python.exe -m unittest -v test_sorter test_recognition test_resilience
```

This is a small development set used to refine the rules, not an independent accuracy benchmark. Test another representative batch in preview mode before moving a larger library. Thirty-one tests passed: sixteen file-operation tests, four synthetic report-parser checks, and eleven worker/scaling/resume checks. These include protection against applying a preview for different folders, native worker crashes, timeouts, log floods, an 11,000-row streaming export, and retrying errors without reanalyzing successes. The 15 labeled samples also matched their labels through the isolated worker. Source-preservation checks refer to read-only validation, before any user-initiated moves. GUI responsiveness was tested with a simulated slow drive and 100,000 log messages. See `LARGE_LIBRARY_FIX.md` for the E-drive investigation and limits.

The unit tests run without sample clips. To repeat clip validation, provide your labeled videos in `sample_clips`, run a preview, then run `validate_samples.py`. The inspection and derived-fixture helper scripts also require these local sample videos.
