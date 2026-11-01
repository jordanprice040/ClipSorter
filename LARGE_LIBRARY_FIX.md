# Large-library reliability fix

The failed E-drive preview had saved two results from 10,869 MP4 files. The program therefore stalled very early, rather than after loading thousands of OCR results. The screenshot showed FFmpeg/H.264 decoder warnings. The exact original decoder failure was not reproduced on the sampled clips, so this investigation does not diagnose a failing disk or declare those videos corrupt.

Code review found three independent reliability problems:

- The Tk poll callback drained an unbounded log queue completely and rendered every line individually. A continuous native decoder-error stream could monopolize the UI and grow memory indefinitely.
- Decoding and OCR had no per-clip timeout or process isolation. One pathological clip could hold up the rest of the library, and stopping the controller could leave work unfinished.
- Every completed clip rewrote the entire growing JSON and CSV, including all previous OCR observations. This made large batches do unnecessary repeated work and use increasingly large temporary Python objects. Idle preview checks also touched the selected drive on the UI thread.

The fix bounds queued and visible log output, batches UI updates, moves saved-plan checks to a background thread, isolates decoding/OCR in a reusable disposable worker, limits each clip's runtime, and stops that worker cooperatively. Crashes/timeouts become Needs review and the next clip gets a fresh worker. Native decoder spam is suppressed; structured per-clip failures remain visible and are saved in results. Every result is still committed to SQLite immediately. CSV checkpoints are batched and JSON is streamed on completion or a clean stop. Apply also streams result rows.

The desktop interface defaults the optional kill-feed evidence scan off. This scan was only collecting review evidence, not automatically assigning uncertain kill counts, and could do hundreds of extra seeks/OCR calls per clip. It can still be enabled explicitly. The per-clip deadline defaults to 120 seconds and can be raised. Cached decode errors/timeouts can be retried independently. Files that cannot be hashed remain in place when applying; no unverifiable source is moved.

Validation performed:

- All 31 unit/integration-style tests passed. The scaling test streamed 11,000 synthetic result rows; the flood test queued 100,000 messages. Worker tests covered timeout, native-style abrupt process exit, decoder error, stderr flood, cancellation, and continuing to the following clip. Preview tests covered safe interruption/resume and selectively retrying failures.
- The live Tk event-loop stress check handled 100,000 queued messages and a simulated one-second drive lookup, maintaining event-loop heartbeat gaps under 15 milliseconds on this machine.
- The first four E-drive clips completed in approximately 8.4, 7.0, 7.2, and 3.9 seconds with optional feed evidence off. Their outcomes were two Needs review, one 4-kill report, and one Short clips. The same sampled video decoded from both E: and a byte-for-byte C: copy; 37 sampled seeks on each returned frames successfully.
- The original 15 labeled samples still matched all 15 labels through the worker.
- A real invalid MP4 was recorded as Needs review, and the following valid fixture completed normally. A separate real stop/resume check stopped the worker in about 0.05 seconds, retained an incomplete-preview marker, and resumed successfully. These timings are observations, not guarantees for every machine or storage device.

All investigation outputs were saved under the tool's local `.tmp` directory. No E-drive source clips or existing E-drive results were modified. The entire 10,869-clip library was **not** analyzed as part of this validation.

To retry: close the old window, reopen `launch.cmd`, select the same E-drive input/output/results folders, leave Collect kill-feed evidence unchecked, and choose Preview / Resume. Enable Retry previous decoder errors / timeouts if you want to retry previously recorded failures. Completed compatible results are retained. Do not delete the results database or undo journal.
