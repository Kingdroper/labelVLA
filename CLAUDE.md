# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Use `uv` for all Python invocations, and `make` for project workflows.

- `make setup` — create the `uv` venv and install dev dependencies (`uv sync`).
- `make test` — run the full pytest suite under a headless Qt (`QT_QPA_PLATFORM=offscreen`, `pytest-xdist --numprocesses=auto`). Override args via `PYTEST_ARGS`, e.g. `PYTEST_ARGS="-k smoke_test -x" make test`.
- `QT_QPA_PLATFORM=offscreen uv run pytest -v tests/unit/shape_test.py::test_name` — run one test (tests will hang without `offscreen` when no display is available).
- `make coverage` — tests with coverage report against the `labelme` package.
- `make lint` — runs `ruff format --check`, `ruff check`, `ty check`, `taplo fmt --check`, `mdformat --check`, `yamlfix --check`, and `typos`. Each of these has a corresponding auto-fix step in `make format` (except `ty` and `typos`, which are check-only).
- `make format` — auto-fix formatting and lint issues.
- `make check` — `make lint` plus `make check_translate` (ensures translation files are regenerated and contain no `type="unfinished"` entries).
- `make update_translate` — regenerate `labelme/translate/*.ts` and `*.qm`. Requires `pylupdate5` 5.15.x and `lrelease` on `PATH` (Ubuntu: `apt install qttools5-dev`). Any user-facing string change must be followed by this; CI will fail otherwise.
- `uv run labelme …` — launch the app from a dev checkout.

## High-level architecture

Labelme is a PyQt5 desktop image-annotation app. Annotations are read/written as JSON label files and the app can delegate segmentation/detection to ONNX models via the `osam` package.

### Entry point and app lifecycle

- `labelme/__main__.py:main` — CLI entry (`[project.scripts] labelme`). It parses args (most have `default=argparse.SUPPRESS` so only user-provided flags override config), configures `loguru` to also write a rotating log under `~/.cache/labelme/labelme.log` (Windows: `%LOCALAPPDATA%\labelme`), installs a Qt-aware `sys.excepthook`, loads the Qt translator for the system locale, forces the `Fusion` style + light palette, and constructs `MainWindow`.
- `labelme/__init__.py` imports `onnxruntime` **before** PyQt5 — this ordering is load-bearing on Windows (issue #1564); do not move it.

### Configuration flow

- Defaults: `labelme/config/default_config.yaml` (single source of truth for available keys).
- `labelme/config/__init__.py:load_config` merges: defaults → `~/.labelmerc` (user file, created on first run with commented examples) → CLI overrides. `_update_dict` rejects unknown keys, and `_validate_config_item` enforces allowed values (`validate_label`, `shape_color`, `labels` uniqueness).
- `_migrate_config_from_file` transparently rewrites legacy keys (`store_data` → `with_image_data`, `SegmentAnything (...)` → `Sam (...)`, old `*_polygon` shortcut names → `*_shape`, etc.). When renaming config keys, add a migration here so existing user configs keep working.

### Core domain objects

- `labelme/_label_file.py` — `LabelFile` (load/save `.json`) plus the `ShapeDict` `TypedDict` (`label`, `points`, `shape_type`, `flags`, `description`, `group_id`, `mask`, `other_data`). Handles base64-encoded `imageData`, TIFF via `tifffile`, Windows path normalization, and `imagePath` relative to the JSON.
- `labelme/shape.py` — `Shape` is the in-memory geometry used by the canvas. It mirrors `ShapeDict` fields but also owns Qt drawing state (colors, vertex highlight, fill, etc.) and geometry helpers (mask <-> polygon via `skimage.measure`). Class-level `line_color` / `fill_color` / etc. are shared defaults; per-instance overrides are per-shape.
- `labelme/app.py` — `MainWindow` (~2.6k lines) wires everything together: menus, tool bar, docks (flags / labels / shape list / file list), status bar, and all actions. Most user-facing logic (open/save, create/edit shape, AI prompting, zoom, navigation) lives here. `_ZoomMode` and the `_AI_CREATE_MODES` / `_AI_MODELS_WITHOUT_POINT_SUPPORT` constants are defined at the top.

### Widgets (`labelme/widgets/`)

- `canvas.py` — `Canvas` (~1.3k lines): the drawing surface. Owns paint loop, hit-testing, create/edit/move modes, AI prompt points, and emits signals back to `MainWindow`.
- `label_list_widget.py`, `unique_label_qlist_widget.py`, `label_dialog.py` — the three views over labels: per-shape list (right dock), unique-label palette, and the create/edit dialog.
- `_ai_assisted_annotation_widget.py`, `_ai_text_to_annotation_widget.py` — AI inference UIs (point/box → polygon, and text → boxes). They call into `labelme/_automation/`.
- `download.py` — `download_ai_model` uses `osam` to fetch model weights with progress + cancel.
- `brightness_contrast_dialog.py`, `zoom_widget.py`, `tool_bar.py`, `_status.py`, `_info_button.py`, `file_dialog_preview.py` — supporting UI.

### AI automation (`labelme/_automation/`)

- `_osam_session.py` — `OsamSession` wraps an `osam.types.Model`, lazily loads weights on first use, and keeps a small LRU (`collections.deque`) of image embeddings keyed by image id so successive prompts on the same image are fast. `run(...)` dispatches on whether you pass `points`/`point_labels` or `texts`.
- `bbox_from_text.py`, `polygon_from_mask.py` — text → bbox prompt and mask → polygon post-processing used by the AI widgets.

### Translations (`labelme/translate/`)

- `.ts` are source files (xml); `.qm` are compiled binaries loaded at runtime by `QtCore.QTranslator`. Both are checked in and CI enforces they are in sync (`make check_translate`). After changing any translatable string (`self.tr("...")`), run `make update_translate` and commit both files. Never hand-edit `.qm`.

### Tests

- `tests/unit/` — fast, mostly import-level checks (`shape_test.py`, `config_test.py`, `_label_file_test.py`, `utils/`, `widgets/`).
- `tests/e2e/` — GUI tests using `pytest-qt` (`qt_api = "pyqt5"`). `conftest.py` provides a `data_path` fixture that copies `tests/data/` into `tmp_path` and synthesizes an `annotated_nested` variant where the JSON `imagePath` points to a sibling directory. The `--pause` option (plus the `close_or_pause` helper) leaves the window open for manual inspection when debugging a single test.
- Tests assume `QT_QPA_PLATFORM=offscreen` on headless machines; `make test` sets it for you.

## Packaging & distribution

- Version is derived from git tags via `hatch-vcs` (see `pyproject.toml`); `labelme/__init__.py` resolves it from installed metadata.
- Standalone executables are built with PyInstaller; see the recipe in `README.md`. The build currently pins `numpy<2.0` (issue #1532) and bundles `osam` model assets plus `labelme/{config,icons,translate}`.

## Project rules (from `.claude/CLAUDE.md`)

- Use `uv` to run Python commands (e.g. `uv run python`, `uv run pytest`).
- Use `make test` to run tests.
- Use `make update_translate` after changing user-facing strings.
- Use `make lint` to check formatting and `make format` to auto-fix.
