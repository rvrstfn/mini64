# Repository Guidelines

## Project Structure & Module Organization
- `mini64.py`: Main Pygame app and BASIC interpreter (single-file design).
- `README.md`: Usage, command reference, and example programs.
- `*.png`: UI screenshots and graphics assets.
- `*.bas`: User-saved programs (ignored by Git via `.gitignore`). Do not commit.

Keep changes focused in `mini64.py`. Discuss before introducing new modules or external deps.

## Build, Test, and Development Commands
- Create venv: `python -m venv .venv` then `source .venv/bin/activate` (Windows: `.venv\\Scripts\\Activate.ps1`).
- Install runtime deps: `pip install pygame-ce` (or `pip install pygame` if preferred).
- Run locally: `python mini64.py`.
- Lint (optional): `python -m pip install ruff` then `ruff check .`.

## Coding Style & Naming Conventions
- Python 3, PEP 8, 4-space indentation.
- Use `snake_case` for functions/variables, `CapWords` for classes, UPPER_CASE for constants.
- Keep functions small and cohesive; favor readability over cleverness.
- Preserve current UI/behavior; document any intentional behavior changes in PR.

## Testing Guidelines
- No formal test suite. Perform manual verification:
  - Launch app and switch modes (ESC). Run examples from `README.md`.
  - Verify `RUN`, `LIST`, `NEW`, `EDIT`, `SAVE "NAME"`, `LOAD "NAME"`, and turtle graphics (`FD`, `RT`, `CIRCLE`, etc.).
  - Confirm `.bas` files are created and listed by `DIR/FILES` and remain untracked by Git.
- If adding logic, consider small self-contained helper functions to ease manual testing.

## Commit & Pull Request Guidelines
- Commits: imperative mood, concise scope (e.g., `fix: correct NEXT handling`).
- PRs must include:
  - Summary of changes and rationale; affected commands/UI.
  - Repro steps and platform (OS, Python version); screenshots/gifs for UI changes.
  - Linked issue, if applicable.
- Keep diffs minimal; avoid unrelated refactors.

## Security & Configuration Tips
- GUI requires a display. For headless/CI runs: set `SDL_VIDEODRIVER=dummy` to initialize Pygame without a window.
- User program files (`*.bas`) may contain arbitrary content—treat as untrusted inputs; do not execute via `eval`.

