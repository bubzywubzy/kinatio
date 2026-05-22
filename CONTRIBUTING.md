# Contributing

Thanks for helping improve Kinatio.

## Before you start

- Read `README.md` for project scope and supported backends.
- Use `SECURITY.md` for vulnerabilities or sudo-related security concerns.
- Use `docs/README.md` for the full documentation map.
- Open or join an issue before making a large behavior or UX change so the implementation lands in the right shape.

## Development setup

```bash
./install.sh --dev
```

Manual fallback when `python3` is already `3.12+`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Local checks

Run the same checks expected in CI before opening a pull request:

```bash
./.venv/bin/ruff check kinatio tests
./.venv/bin/python3 -m pytest -q
```

## Implementation guidelines

- Keep the collector → domain model → runtime store → UI/CLI layering intact.
- Prefer small, focused pull requests over broad refactors.
- Add or update tests when changing scheduler, auth, execution, cache, or collector behavior.
- Document user-facing behavior changes in `README.md`, `QUICKSTART.md`, `docs/`, or `CHANGELOG.md` as appropriate.
- Keep longer release and reference material under `docs/`, with dated audits under `docs/audits/`.
- Preserve reduced-capability and deferred-collection messaging; Kinatio should fail closed, not optimistically.

## Pull request checklist

Before opening a PR, make sure you have:

- explained the problem and the chosen fix
- linked the relevant issue when one exists
- added or updated tests for changed behavior
- updated documentation for visible UX, CLI, or security behavior changes
- run lint and tests locally

## Code of conduct

Be respectful, keep feedback actionable, and assume good intent. Tiny jokes are welcome; drive-by hostility is not.
