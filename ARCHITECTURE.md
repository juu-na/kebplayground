# Architecture

This document explains how the project is put together and what each module is responsible for.
Setup and run instructions are in the [README](README.md).

## Pipeline

```
cli.py
  -> data.py        # read in users, or make them up
  -> constraints.py # mark the pairs that are not allowed, building H
  -> features.py    # measure each allowed pair on each thing being compared
  -> scoring.py     # turn those measurements into one score per pair, building S
  -> matcher.py     # decide who is matched with who
  -> llm.py         # suggest something the pair could go and do (optional)
  -> output         # the list of matches, on screen and as JSON
```

`constraints.py` runs before `scoring.py` so that only the pairs that are allowed have to be scored. 

A banned pair cannot be matched whatever it
scores so working out its score is wasted.

Two tables are shared between the modules:
- `S`, the score for every pair
- `H`, whether the pair is allowed at all

## Phase 1

`models.py`: describes what a user looks like, covering features such as `id, major, faculty, year, age, MBTI, languages, gender, area, interests, preferences, mode, status`, etc.
- `mode` is the one kind of connection the user is after, friendship or date. A pair needs both to want the same one. One value, since a date user states a gender preference and two modes would need two
- `status` is where the user is up to. Only the waiting ones take part in a run
- `area` is the part of Auckland the user lives in, only ever read when somebody asked for the same area
- `preferences` is what the user is after in the other person, listed in `vocabulary.py`. Gender and age rule a pair out. The rest lift the measurement they speak for to full marks when the other person satisfies them, and change nothing when they do not, so asking for something can only ever help. The form asks both of every user, and stores "I do not mind" by leaving the key out
- kept stable, since every other module imports it

`vocabulary.py`: the registered options a user can be described by, such as the faculties and the majors each one teaches, the languages, the interests and the areas.
- every other module reads its lists from here, so that made up users, the scores and the preferences all agree on the same values
- also says which keys a user may state as a preference, and which of them rule a pair out. The rest only move the score
- `DEPARTMENTS` groups the majors of a faculty, the middle step in `major_similarity`. Only Engineering is split so far

`data.py`: reads users from a CSV file, and makes up a group of users for testing.
- makes up user data, for example 100 users with a sensible spread of values
- a `Cohort` narrows or weights those draws, so a run can be shaped like a particular group. Left out, the spread is even
- returns a list of `User` objects
- needed early, because everything else runs against that list

`features.py`: measures how alike two users are, one feature at a time.
- each measurement is a function that takes two users and returns a number from 0 to 1 (0% to 100%)
- features worth measuring include same (or similar) major, shared interests, languages, personality, how close in age and year they are, and, when asked for, living in the same area
- `major_similarity` runs faculty, then department, then major, splitting 1.0 as 0.6, 0.2 and 0.2. The department step separates two majors inside one faculty
- `view(a, b)` is how a sees b, which is not the same as how b sees a, because a's stated preferences lift the measurements they speak for
- only measures (makes no decisions) and does not know that matching exists
- returns the name of each measurement and its result

`constraints.py`: decides which pairs are not allowed to be matched at all.
- work out what rules out a pair, such as different modes, a gender or age preference either user stated or a self matching
- returns `H`, the table saying which pairs are allowed
- kept apart from scoring because these rules cannot be outweighed, a banned pair stays banned even at a score of 1.0

`scoring.py`: turns the measurements into one score, `S`.
- give each mode its own set of weights, so that friendship counts shared interests more heavily, while a date counts personality and age more heavily
- score both directions and keep the lower one, since a match one person is lukewarm about is a lukewarm match
- return the mode alongside the score, because `llm.py` has to know which one it is writing about
- leave out anything below `MIN_MATCH_SCORE`. A few real matches are better than many average ones, and the two users keep waiting
- also work out how good a whole run was, one report per kind of connection, and list who is still waiting for the next run

`matcher.py`: three ways of matching, all reading `S` and `H` only and knowing nothing about users.
1. greedy pairing. Take the best allowed pair still available, again and again. Nobody ends up wanting to swap, because both halves of a pair read the same score. It does not give the highest total, since taking the best pair can strand two people who each had a good second choice.
2. fairest pairing, then local search. Serve whoever is hardest to place first, then repeatedly apply whichever single swap raises the total most.
3. blossom, which is `networkx.max_weight_matching`. The highest total by construction.

Measured over 30 runs of 60 made up users at the `0.6` floor: blossom 6.68 over 10.1 pairs, fairest 6.60 over 10.0 and four times slower, greedy 6.10 over 9.1 and fastest. `scripts/compare.py` prints the three match lists side by side, since blossom's win on total follows from the algorithm.

Gale-Shapley was tried and dropped. It settles a disagreement between two sides' preference orders, and it was dropped when `S` gave both halves of a pair the same number. Directional scoring has since brought a real disagreement back, so it is worth another look, though one pool of students is the stable roommates problem, and Gale-Shapley solves the two-sided one.

`llm.py`: writes the two things a matched pair are shown.

Why they were matched is worked out in code, by `why()`, which names the shared major, interests and languages. It reads the two users, so it can be specific in a way the measurements alone cannot, and it never invents anything.

What they could do about it is asked of the model, by `suggest()`. That is the part code is bad at: one activity that suits these two in particular, drawing on the whole of both profiles rather than only their overlap.
- the system prompt holds the rules a suggestion has to meet: public, near the city campus, free or nearly, no alcohol, and suitable for two people who have not met
- the prompt sends both profiles in full, plus what they already have in common spelled out
- `verify` turns down an empty or over-long reply, and one naming something the rules ruled out. It cannot tell whether a suggestion is a good idea, only whether it broke a rule in a way the words give away
- a turned down or failed reply falls back to `plain_suggestion`, so a live demo never shows nothing
- runs after matching, never affects who gets matched
- behind the `--explain` flag on the command line
- replies are saved to JSON, so a repeat run costs nothing and a failed call cannot break the demo

`cli.py`: runs the whole application from the command line and reads the arguments.
- reading in the input file
- setting the count, the seed and the minimum score
- write the output (display the matching table, save as JSON for phase 2)
- no flag for the mode or the algorithm. The mode is in the profile, the algorithm is fixed

`scripts/`: two scripts, run as `python -m scripts.<name>` since the package is not installed.
- `compare.py` prints what each of the three algorithms did with the same users
- `keb_demo.py` runs one narrow cohort and sweeps the floor, so `MIN_MATCH_SCORE` can be picked from numbers

## Phase 2

Backend: a FastAPI app with two endpoints.
1. take in a user profile
2. send back a match
- wraps the same pipeline and adds no other feature to it

Frontend: a plain HTML page.
1. sign up form
2. match result
- no login for demo

## Future work

Every similarity in `features.py` comes from a hardcoded table. Each table is a manual judgement, and each needs an edit when the vocabulary changes.

The plan is to replace them with vector distance. An embedding model gives every word a position in a few hundred dimensions, where a shorter distance means a closer meaning. Every vocabulary entry gets a vector, and a pair is measured by the distance between them.

The model is pretrained, so it works on the first run.

Things to consider:
- vectors are computed once and cached, so matching stays as a lookup and is reproducible
- distance needs mapping onto the 0.0 to 1.0 range the other measurements use
- the model knows general English words, so UoA usage may need finetuning