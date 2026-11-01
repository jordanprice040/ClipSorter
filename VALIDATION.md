# Validation results

Final preview: **15/15 labeled clips classified correctly**, with no video copies or moves. All 15 SHA-256 checks match their recorded source hashes. Resume reused all 15 cached results.

| Clip | Expected | Result | Evidence seconds |
|---|---|---|---|
| 0kills_death_multiplerounds_noassists.mp4 | 0 | 0 | 180.015, 179.765, 179.465 |
| 1kill_death_multiplerounds_noassists.mp4 | 1 | 1 | 96.717, 96.467 |
| 1kill_death_oneround_1assist.mp4 | 1 | 1 | 50.982, 50.732 |
| 2kills_death_oneround_1assist.mp4 | 2 | 2 | 180.014, 179.764 |
| 2kills_nodeath_oneround_2assists.mp4 | 2 | 2 | 85.467, 85.217 |
| 2kills_nodeath_oneround_noassists.mp4 | 2 | 2 | 99.935, 99.685 |
| 3kills_death_oneround_noassists.mp4 | 3 | 3 | 104.233, 103.983 |
| 3kills_nodeath_multiplerounds_noassists.mp4 | 3 | 3 | 157.998, 157.748 |
| 4kills_nodeath_oneround_noassists.mp4 | 4 | 4 | 41.005, 40.755 |
| 5kills_nodeath_oneround_noassists.mp4 | 5+ | 5+ | 60.324, 60.074 |
| deathmatch.mp4 | Deathmatch | Deathmatch | 180.066, 178.266, 175.266 |
| notinmatch.mp4 | Outside of match | Outside of match | 54.614, 52.814, 49.814 |
| olderclipexample_3kills_death_multiplerounds_noassists.mp4 | 3 | 3 | 180.134, 179.884 |
| range.mp4 | Range | Range | 179.597, 177.797, 174.797 |
| sub20sec_doubleclip.mp4 | Short clips | Short clips | 10.434, 8.634, 5.634 |

The report-based cases cover 0, 1, 2, 3, 4 and 5 kills, assists, incoming damage, an older HUD, and multiple rounds. The final report consistently provided the relevant count in these samples.

Sixteen tests passed: twelve file-operation tests with disposable files and four synthetic report-parser checks. The derived 10-second fixture also classified as Short clips. GUI widget construction passed after configuring the installed Tcl/Tk library paths.

Limitations: this set was used for development, not held-out evaluation. Non-English or changed HUDs, clips without a recent complete report, and kill-feed-only totals remain uncertain. Feed fallback saves candidate event evidence for human review and never assigns an unproven exact round count. No supplied sample required fallback.

Detailed evidence and OCR are in sort_results/results.json; per-clip screenshots are in sort_results/evidence. CSV results are in sort_results/results.csv and sort_results/validation.csv. Original-preservation checks are in sort_results/source_audit.json.
