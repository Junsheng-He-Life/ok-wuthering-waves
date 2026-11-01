# Agent Instructions

## Python

- When running Python commands in this repository, use the local virtual environment if it exists.
- On Windows/PowerShell, prefer `.\.venv\Scripts\python.exe` when present.
- On POSIX shells, prefer `./.venv/bin/python` when present.
- Fall back to `python` only when no local `.venv` interpreter exists.
- Prefer invoking the interpreter directly, for example `.\.venv\Scripts\python.exe -m pytest`, instead of relying on shell activation.

## Combat extensibility

- Shared scheduling, action confirmation, bounded retry and recovery must work
  across characters and parties. Do not add fixes gated on a particular roster.
- Character modules supply mechanic-specific prerequisites, inputs and visual
  evidence (for example multi-stage skills, transformations and held attacks).
  Do not treat a cooldown transition as proof of every character's full combo.
- Team recommendations may rank eligible switch targets; they must not bypass
  action completion, character switch restrictions or health/resource guards.
- Test shared contracts independently of the current party. Report per-character
  and cross-party live validation separately; one successful party does not
  establish that all character mechanics have been adapted.

## Echo pipeline

- Read `docs/声骸轮刷.md` before running the new Boss/Tacet echo tasks.
- Use the desktop panel or `scripts/ultrawide_trial.py` with `--phase echo-catalog` / `--phase echo`
  with the adjacent `ok-script/.venv313/bin/python` and `PYTHONPATH=../ok-script:.`.
- Both modes default to claiming after verified victory within explicit limits.
  Reserve and solvent allowances default to zero; do not infer new authorization.
- Preserve the shared controller lock, activity ledger and pending-claim guards.
  A cleared absorb prompt is not a verified inventory increase.
