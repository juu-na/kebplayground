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
  -> llm.py         # write the message explaining the match (optional)
  -> output         # the list of matches, on screen and as JSON
```

`constraints.py` runs before `scoring.py` so that only the pairs that are allowed have to be scored. 

A banned pair cannot be matched whatever it
scores so working out its score is wasted.

Two tables are shared between the modules:
- `S`, the score for every pair
- `H`, whether the pair is allowed at all

## Phase 1

`models.py`: describes what a user looks like, covering features such as `id, major, faculty, year, age, MBTI, languages, gender, area, interests, preferences, modes, status`, etc.
- `modes` is the kinds of connection the user is open to, one or both of friendship and date. A pair is only considered when they share one
- `status` is where the user is up to. Only the waiting ones take part in a run
- `area` is the part of Auckland the user lives in, only ever read when somebody asked for the same area
- `preferences` is what the user is after in the other person, listed in `vocabulary.py`. Gender and age rule a pair out. The rest lift the measurement they speak for to full marks when the other person satisfies them, and change nothing when they do not, so asking for something can only ever help
- will not be modified once written and confirmed, since every other module imports it

`vocabulary.py`: the registered options a user can be described by, such as the faculties and the majors each one teaches, the languages, the interests and the areas.
- every other module reads its lists from here, so that made up users, the scores and the preferences all agree on the same values
- also says which keys a user may state as a preference, and which of them rule a pair out rather than only moving the score

`data.py`: reads users from a CSV file, and makes up a group of users for testing.
- makes up user data, for example 100 users with a sensible spread of values
- may also use the real details of the keb playground participants for a demo
- returns a list of `User` objects
- needed early, because everything else runs against that list

`features.py`: measures how alike two users are, one feature at a time.
- each measurement is a function that takes two users and returns a number from 0 to 1 (0% to 100%)
- features worth measuring include same (or similar) major, shared interests, languages, personality, how close in age and year they are, and, when asked for, living in the same area
- `view(a, b)` is how a sees b, which is not the same as how b sees a, because a's stated preferences lift the measurements they speak for
- only measures (makes no decisions) and does not know that matching exists
- returns the name of each measurement and its result

`constraints.py`: decides which pairs are not allowed to be matched at all.
- work out what rules out a pair, such as no shared free time, different modes or a self matching
- returns `H`, the table saying which pairs are allowed
- kept apart from scoring because these rules cannot be outweighed, a banned pair stays banned even at a score of 1.0

`scoring.py`: turns the measurements into one score, `S`.
- give each mode its own set of weights, so that friendship counts shared interests more heavily, while a date counts personality and age more heavily
- score both directions and keep the lower one, since a match one person is lukewarm about is a lukewarm match
- pick the best of the kinds of connection the two share, and return that alongside the score, because `llm.py` has to know which one it is writing about
- leave out anything below `MIN_MATCH_SCORE`. A few real matches are better than many average ones, and the two users keep waiting
- also work out how good a whole run was, one report per kind of connection, listing who is still waiting rather than counting them as failures

`matcher.py`: three ways of matching, all reading `S` and `H` only and knowing nothing about users.
1. greedy pairing. Take the best allowed pair still available, again and again. Nobody ends up wanting to swap, because both halves of a pair read the same score. It does not give the highest total, since taking the best pair can strand two people who each had a good second choice.
2. fairest pairing, then local search. Serve whoever is hardest to place first, then repeatedly apply whichever single swap raises the total most.
3. blossom, which is `networkx.max_weight_matching`. The highest total there is, by construction.

Measured over 30 runs of 60 made up users: at the `0.6` floor fairest and blossom tie on total and blossom is five times faster, and below the floor blossom wins outright. The three are compared by reading the pairs through `scripts/compare.py` rather than ranking a number, because blossom's win on total is a property of the algorithm rather than a finding.

Gale-Shapley was tried and dropped. It settles a disagreement between two sides' preference orders, and it was dropped when `S` gave both halves of a pair the same number. Directional scoring has since brought a real disagreement back, so it is worth another look, though one pool of students is the stable roommates problem rather than the two-sided one Gale-Shapley solves.

`llm.py`: asks an LLM to write the message shown to a matched pair.
- write a system prompt that asks for a match message giving a reason and a suggestion
- connect to the API
- send the system prompt along with the details of the match (both users, the kind of connection, the score and the feature measurements)
- check response quality and format
- output the message
- runs after matching, never affects who gets matched
- put it behind an `--explain` flag
- save the replies to JSON (a fallback), so a failed API call cannot break the live demo

`cli.py`: runs the whole application from the command line and reads the arguments.
- reading in the input file
- choosing the mode
- choosing the algorithm
- write the output (display the matching table, save as JSON for phase 2)

## Phase 2

Backend: a FastAPI app with two endpoints.
1. take in a user profile
2. send back a match
- wraps the same pipeline and adds no other feature to it

Frontend: a plain HTML page.
1. sign up form
2. match result
- no login for demo
