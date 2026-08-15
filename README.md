# kebplayground

Matches university students with each other, based on how well their
timetables, subjects, interests and languages line up.

A user picks a mode, meaning the kind of connection they are after, such as
a lunch mate, a study buddy, a friend group or a campus couple. The mode
decides which things count for more when working out a score. Three matching
algorithms are then run over those scores and compared against each other.

How the code is put together, and what each module does, is in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Status

Phase 1 is a set of empty functions.
Each one has a description of what goes in, what comes out, and what it has
to do. Every one of them raises `NotImplementedError` until it is written.

The tests in `tests/` describe what each function has to do once written.
They are the checklist for the work.

## Requirements

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
```

Creates the `.venv` directory and installs the dependencies listed in
`pyproject.toml`.

## Run

```bash
uv run python -m kebplayground.cli --mode NAME --algo NAME
```

This raises `NotImplementedError` for now, since `cli.py` has not been
written yet.

### Arguments:

| argument | what it does |
| --- | --- |
| `--input PATH` | a CSV of users. When left out, users are made up |
| `--count N` | how many users to make up, 100 by default |
| `--seed N` | the seed used when making up users, so a run can be repeated exactly |
| `--mode NAME` | the kind of connection, one of the modes in `scoring.WEIGHTS` |
| `--algo NAME` | `greedy`, `stable` or `cluster` |
| `--explain` | also ask the LLM to write the match messages |
| `--output PATH` | where to write the results as JSON |

`--explain` is the only part that calls out to an LLM. No provider has been
chosen yet, so the package to install and the API key to set are still open.

## Test

```bash
uv run python -m unittest discover -s tests -t .
```

Add `-v` to see the name of each test as it runs.

Nearly every test fails initially, and each failure names a function that
has not been written yet. Work down the file in the order it is written in,
which is the order the data moves through the modules.
