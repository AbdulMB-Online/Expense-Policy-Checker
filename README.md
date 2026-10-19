# Expense Policy Checker

A command-line project for checking employee expenses against company policy.
Currently includes expense and policy loaders, a 30-record sample generator,
and JSON export. Policy evaluation is a separate component yet to be implemented.

## Quick start

Requires Python 3.11+. Run from the repository root:

```sh
python3 -m scripts.sample_data --force
python3 -m scripts.export_json --force
```

These commands regenerate the sample CSV in `data/expenses/` and export validated
records and row errors to `data/out/`. `--force` replaces existing files.
Policy files live in `data/policy/`.

See the [loader guide](docs/loader.md) for usage, input contracts, validation
behavior, JSON output, and sample scenarios.

## Tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
