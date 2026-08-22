# kebplayground

Matches university students with each other, based on how well their
subjects, interests, languages and personalities line up.

A user signs up once, says whether they are open to friendship or a date or
both, and says what they are after in the other person. That choice decides
which things count for more when working out a score, and a stated preference
lifts whatever it speaks for. A pair is scored from both sides and keeps the
lower of the two, so a match one person is lukewarm about is a lukewarm match.

Anything below the minimum score is not offered at all. Somebody nobody suits
yet keeps waiting for the next run, because a few real matches are better than
many average ones.

How the code is put together, and what each module does, is in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Status

Phase 1 is written and runs end to end.

The tests in `tests/` describe what each module promises the others.
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

`--explain` calls Gemini, which needs a key of your own:

```bash
cp .env.example .env
```

Then put your key in `.env` against `GEMINI_API_KEY`. `.env` is gitignored,
so the key never leaves your machine. Everything apart from `--explain` runs
without one.

## Run

```bash
uv run python -m kebplayground.cli
```

Every module is written, so this runs the whole pipeline and prints the
matches, then the people still waiting for one.

A user says in their profile which kinds of connection they are open to, so
there is no flag for it. A run covers everybody who is waiting.

### Arguments:

| argument | what it does |
| --- | --- |
| `--input PATH` | a CSV of users. When left out, users are made up |
| `--count N` | how many users to make up, 100 by default |
| `--seed N` | the seed used when making up users, so a run can be repeated exactly |
| `--min-score N` | the lowest score worth offering, `0.6` by default |
| `--explain` | also ask the LLM to write the match messages |
| `--cache PATH` | where the LLM answers are kept between runs, `.cache/llm.json` by default |
| `--output PATH` | where to write the results as JSON |

`--explain` is the only part that calls out to an LLM. Without a key it
falls back to a plain message built from the measurements, so a run always
finishes.

Answers are kept in `.cache/llm.json` and reused, so asking for the same
match twice only costs one call.

## Test

```bash
uv run python -m unittest discover -s tests -t .
```

Add `-v` to see the name of each test as it runs.

Every failure names a function that has not been written yet. Work down the
file in the order it is written in, which is the order the data moves through
the modules.
