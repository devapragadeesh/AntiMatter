# Smart Compression Tool — Feature Roadmap (Phase 3 → 2 → 1 → 4)

## Context

Full-project audit reviewed; cleanup/hardening items deferred until closer to release (see bottom section). Four features to be implemented phase-by-phase in this order:

1. **Phase 3 (do first): UI overhaul** — current UI is minimal and has real layout/color bugs.
2. **Phase 2: Folder archiving** — compress/decompress whole folders like a .zip, not just single files.
3. **Phase 1: Windows Explorer right-click integration** — "Compress with Anti Matter" / "Extract" context menu entries, like WinRAR/7-Zip.
4. **Phase 4: Prediction system improvements** — tighten the ratio/size/confidence estimation accuracy.

Each phase below is self-contained enough to execute independently; later phases assume earlier ones are done (e.g. phase 2's folder support should also get the phase-3 UI treatment, and phase 1's context menu needs to invoke whatever folder-aware compression phase 2 produces).

---

## Phase 3 — UI overhaul (do first)

### Concrete bugs found in current code (not just "minimal", actually broken)

- **`ui/styles.py:15`** — the QSS string literally contains stray text `font-size: 13px;        ← move it here instead`. That arrow and comment text are inside the actual stylesheet string being passed to Qt, not a Python comment — this is leftover edit debris. Should just be `font-size: 13px;`.
- **Duplicate/dead methods in `ui/compress_screen.py`**: `_run_compression` (line 453) and `_start_compression` (line 696) are near-identical — the CTA button is wired to `_run_compression`, making `_start_compression` dead code that will drift out of sync if edited only once. Consolidate to one method.
- **Fragile manual layout-index reach-through**: `self.layout().itemAt(0).layout().itemAt(2).layout().addWidget(self._open_btn)` (`compress_screen.py:799`) blindly assumes the exact structure of nested layouts to inject the "open output folder" button. Any layout restructuring during the UI overhaul will silently break this. Give the results panel a proper named container widget with a stable reference instead.
- **No responsive/resize behavior** — panel stretch factors (5:4 split) are fixed; nothing suggests a minimum-width fallback (e.g. stacking panels vertically) if the window is resized small.
- **Emoji-as-icons throughout** (up-arrow, page, folder, gear, pencil, spinner, check, x, warning) — inconsistent rendering across Windows font/emoji-fallback configurations. Real icon assets (SVG via `QIcon`) would look far more polished and consistent.
- **Hardcoded inline `setStyleSheet(...)` calls scattered across widgets** (e.g. `compress_screen.py:44,48,63-66,76,92`) bypass the centralized QSS object-name system already established in `styles.py`.

### Recommended approach

1. **Fix the styles.py bug first** (5-minute fix, unblocks everything else): remove the stray text, re-verify the QSS parses cleanly (no Qt console warnings on startup).
2. **Establish a small icon set**: replace emoji glyphs with a consistent icon font or SVG icon set (e.g. via `qtawesome` package, or a handful of bundled SVGs loaded through `QIcon`). Biggest visible quality jump.
3. **Consolidate ad-hoc `setStyleSheet` calls into named QSS selectors** in `styles.py`, so all future color/spacing tweaks happen in one file.
4. **Add responsive behavior**: define a minimum width where the two-panel layout (`compress_screen.py:_build`) collapses to a single stacked column, and test resizing down to the `setMinimumSize(960, 680)` floor and below.
5. **Fix the dead-code/fragile-layout issues above** while touching this file anyway.
6. **Pass over `ui/decompress_screen.py`** (564 lines, mirrors compress_screen) applying the same fixes.
7. **Visual polish pass**: consistent spacing/padding scale (currently mixes 4/6/8/10/12/14/16/24px ad hoc), consistent corner radius (6px vs 8px used inconsistently), and a real color palette/contrast check.

### Verification
Run the app (`python main.py`) after each step, resize the window through several breakpoints, drag-drop a file, switch tabs, open Settings dialog, and confirm no visual clipping, no stray text/artifacts, and consistent icon rendering.

---

## Phase 2 — Folder / directory archiving

Currently **nothing in the codebase handles directories at all** — `compressor.py` calls `input_path.read_bytes()` directly (single file only), and `profiler.py`'s feature extraction assumes a single file's bytes. Folder support is a genuinely new capability, not an extension of existing logic.

### Design approach
1. **Bundle folder → single byte stream before compression.** Use Python's stdlib `tarfile` (in-memory or temp-file mode) to pack a folder's contents (preserving relative paths/structure) into one uncompressed tar stream, then run that stream through the existing profiler → selector → predictor → engine pipeline exactly like a single file. Reuses 100% of the existing smart-selection machinery.
   - Avoid `zipfile` for the packing step — tar-then-compress lets the existing engine choice (zstd/lzma/brotli/etc.) still apply, whereas zip's own per-entry DEFLATE would fight with the outer compressor. Keep the **output extension** user-facing as something like `.amz` so it doesn't read as a raw `.tar` internally, but structurally it's tar+chosen-engine.
2. **Profiling a folder**: sample from the packed stream the same way `profiler.py` already does for files >2MB (existing 512KB-window sampling logic, `profiler.py:36-37,212-242`) — reuses existing code path, no new profiling logic needed.
3. **Decompression**: reverse — decompress the stream, then `tarfile.extractall()` into the chosen output directory, recreating the original folder structure.
4. **UI changes**: `DropZone` (`ui/compress_screen.py:26`) currently only handles single dropped files (`urls[0]`) — extend `dropEvent`/`mousePressEvent` to accept a directory drop (`QFileDialog.getExistingDirectory` as an alternative browse mode) and detect `path.is_dir()` in `_on_file_dropped`. `FileCard.set_file` should show folder icon + total recursive size + file count instead of a single extension when a folder is staged.
5. **Progress/size caveats**: folder sizes could be much larger than typical single files tested against `benchmark.db` — check whether the benchmark corpus (`data/raw/`) includes any large aggregate/archive-like samples; if not, prediction confidence for folder-mode compression may run consistently "low," which is expected but should be communicated to the user rather than looking like a bug.

### Files to touch
- New: a small `archiver.py` (or extend `compressor.py`) with `pack_folder(path) -> tempfile path` and `unpack_folder(stream, dest)` using `tarfile`.
- `compressor.py`: branch at the top of the compress entry point — if `input_path.is_dir()`, pack first, then proceed with existing logic on the resulting tar stream.
- `ui/compress_screen.py` / `ui/decompress_screen.py`: drop-zone and file-card updates for directories.
- `ui/worker.py`: `ProfileWorker`/`CompressWorker` need the packing step to happen off the GUI thread too (it can be slow for large folders) — fold it into the existing worker's `run()`.

### Verification
Compress a folder with nested subfolders and mixed file types, confirm decompression restores the exact original structure (byte-for-byte on a few sample files), and confirm the prediction card shows sensible (if low-confidence) numbers rather than crashing.

---

## Phase 1 — Windows Explorer right-click ("Compress/Extract with Anti Matter")

OS-integration work, distinct from the Python app itself — writing Windows Registry entries (typically under `HKEY_CLASSES_ROOT\*\shell\...` and `HKEY_CLASSES_ROOT\Directory\shell\...` for folders) that call your packaged .exe with the clicked file/folder path as an argument.

### Design approach
1. **Requires the app to be packaged as a standalone .exe first** (e.g. via PyInstaller) since registry shell commands need a stable executable path. This is a hard dependency: confirm packaging strategy before starting this phase.
2. **Command-line entry point needed.** `compressor.py` already has a CLI (`argparse`-based) — extend it (or add a thin wrapper) so it accepts a mode like `--context-compress <path>` / `--context-extract <path>` that launches the GUI pre-populated with that file/folder staged (reusing `AppState`), rather than immediately running headless compression with default settings.
3. **Registry entries** (typically installed by the installer, e.g. Inno Setup/NSIS/WiX, not by the Python app itself at runtime):
   - `HKCR\*\shell\AntiMatterCompress\command` → `"<path to exe>" --context-compress "%1"` (applies to any file)
   - `HKCR\Directory\shell\AntiMatterCompress\command` → same, for right-click on folders (ties directly into phase 2's folder support)
   - `HKCR\.amz\shell\AntiMatterExtract\command` (or whatever your chosen output extension is) → `"<path to exe>" --context-extract "%1"`, so right-click on your own archive format offers extract directly.
   - Icons: `HKCR\...\command` entries can have a sibling default icon key for the context-menu icon.
4. **Installer integration**: since there's no installer yet, this phase likely needs an installer (Inno Setup is the common lightweight choice for PySide6 Windows apps) that both bundles the PyInstaller .exe and writes these registry keys on install / removes them on uninstall.

### Verification
After packaging + installing, right-click a file and a folder in Explorer, confirm the "Compress with Anti Matter" entry appears and launches the app with that item pre-staged; right-click a `.amz` file and confirm "Extract" works; uninstall and confirm registry entries are removed cleanly.

---

## Phase 4 — Prediction system improvements

Builds on the existing k-NN regression design (`selector.py`/`predictor.py` against `benchmark.db`'s ~11,934 rows) rather than replacing it — the architecture is sound, the issue is calibration and coverage.

1. **Calibrate confidence thresholds empirically.** `CONFIDENCE_DISTANCE_HIGH/MEDIUM` and `CONFIDENCE_VARIANCE_HIGH/MEDIUM` (`predictor.py:42-45`, values 0.25/0.50 and 0.50/1.00) are currently hand-guessed. Run `validator.py` (already brute-forces all 30 engine/level combos against real files and reports actual prediction error, `validator.py:434-492`) across a broad, representative set of real-world files, log `(avg_distance, ratio_variance, actual_error%)` triples, then pick thresholds that actually separate "low error" from "high error" cases in that data.
2. **Expand `benchmark.db` coverage.** Folder/archive-mode (phase 2) will introduce new content statistics (tar-packed multi-file streams) likely underrepresented in the current training chunks (`data/raw/{numeric,random,repetitive,structured,text}`). Consider adding a "packed/archive" category to the training pipeline (`chunker.py`/`pipeline.py`).
3. **Fix the memory-prediction blind spot.** `tracemalloc`-based memory measurement (used when populating `benchmark.db` via `runner.py`) only sees Python-level allocations, missing the actual C-extension buffers in `zstandard`/`brotli`/`lz4`. Switch to process RSS delta (e.g. `psutil.Process().memory_info().rss` before/after) in `runner.py`'s benchmark-generation path, then regenerate `benchmark.db`.
4. **Real percentile-based prediction range** instead of raw min/max of k=20 neighbors (`predictor.py:308-311`). Switch to 10th/90th percentile of neighbor ratios.
5. **Shared k-NN module.** De-duplicate the near-identical neighbor-search code between `selector.py` and `predictor.py` into one shared module — otherwise a tuning change applied to one file silently doesn't apply to the other.
6. **Post-compression accuracy tracking.** `compress_screen.py:_show_result` already computes `err = abs(pred_ratio - actual_ratio) / pred_ratio * 100` after every real compression (`compress_screen.py:759`) but only displays it — it's thrown away. Log these prediction-vs-actual deltas so real usage data accumulates over time.

### Verification
Before/after comparison using `validator.py` against a fixed test-file set: capture current prediction-rank and error-percentage stats, apply changes, re-run, and confirm the confidence labels correlate more tightly with actual error and that displayed ranges are less frequently blown out by outliers.

---

## Deferred: pre-release cleanup / hardening audit

The architecture is genuinely stronger than a typical "guess type → pick preset" tool: `profiler.py` extracts a 6-dimensional content-based feature vector (entropy, repetitiveness, numeric density, ASCII ratio, a cheap zlib-based compressibility hint, unique-byte ratio), and `selector.py`/`predictor.py` run k-NN regression against a `benchmark.db` of ~11,934 real measured compression runs to recommend an engine/level and predict ratio/speed/memory with a confidence label. This is closer to a lightweight ML recommender system than a static lookup table — the items below are about closing release-readiness gaps, deferred until closer to release.

### Release blockers
1. **No `requirements.txt`/`pyproject.toml`** — add one pinning `PySide6`, `zstandard`, `lz4`, `brotli`.
2. **`DB_PATH = Path("data/benchmark.db")` is relative to cwd** (`selector.py:38`, `ui/state.py:53`) — resolve relative to executable/script location instead.
3. **Unused `Tools/` folder** (gzip.exe, lz4.exe, zstd.exe, lzma.exe binaries, DLLs, headers) — nothing invokes them via subprocess. Remove or finish the native-binary path.
4. **No decompression integrity check** — add an optional SHA-256 verify step.
5. **Committed `__pycache__/` directories** — add to `.gitignore`.

### Estimation / recommendation quality
6. Confidence thresholds hand-guessed, not calibrated (see Phase 4 item 1).
7. Predicted range is min/max not percentile-based (see Phase 4 item 4).
8. Peak memory measured with `tracemalloc`, undercounts C-extension buffers (see Phase 4 item 3).
9. k-NN is brute-force O(n) linear scan — fine at ~12k rows, but `scipy.spatial.cKDTree` would help if the DB grows.
10. Duplicated k-NN/distance math between `selector.py`/`predictor.py` (see Phase 4 item 5).
11. Stale DB cache (`_DB_CACHE` in `selector.py`) has no invalidation hook when DB path setting changes.

### Robustness / error handling
12. Bare `RuntimeError`/`ValueError`/`FileNotFoundError` propagate through `ui/worker.py`'s generic exception handling, losing type info — worth typed exceptions.
13. `main_window.py`'s DB pre-warm thread swallows all exceptions silently — surface a status indicator instead.
14. Decompression engine detection is extension-only (`EXTENSION_ENGINE_MAP`) — add magic-byte sniffing fallback (zstd, gzip, xz all have magic numbers).

### Cleanup / polish
15. Duplicated `sys.path` bootstrap copy-pasted across `main.py`, `ui/worker.py`, `main_window.py` — centralize once.
16. `demo.py` is a stray undocumented script — remove or fold into an About dialog.
17. `Logs.docx` binary doc in repo root — move out of source control or convert to plain-text changelog.
18. Simulated progress bar (`ProgressTickerWorker`) — fine as-is, note why in a comment.
19. No automated tests — add a small pytest suite around `profiler.py`/`selector.py`/`predictor.py`.
