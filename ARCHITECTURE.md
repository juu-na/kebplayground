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

`models.py`: describes what a user looks like, covering features such as `id, major, faculty, year, age, MBTI, languages, gender, area, timetable, interests, preferences, mode`, etc.
- `mode` is the kind of connection the user is after, one of lunch mate, study buddy, friend group, besties or campus couple
- `area` is the part of Auckland the user lives in, read only to work out whether two users live in the same one
- `preferences` is what the user will accept in the other person, listed in `vocabulary.py`, where gender and age rule a pair out and the rest only move the score
- `timetable` is a typical week of free and busy slots, so shared free time can be worked out
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
- features worth measuring include shared free time, same (or similar) major, shared interests, languages and how close in age they are
- only measures (makes no decisions) and does not know that matching exists
- returns the name of each measurement and its result

`constraints.py`: decides which pairs are not allowed to be matched at all.
- work out what rules out a pair, such as no shared free time, different modes or a self matching
- returns `H`, the table saying which pairs are allowed
- kept apart from scoring because these rules cannot be outweighed, a banned pair stays banned even at a score of 1.0

`scoring.py`: turns the measurements into one score, `S`.
- give each mode its own set of weights, so that lunch mate counts shared free time more heavily, while study buddy counts major and faculty more heavily
- return both the final score and the separate measurements behind it, because `llm.py` needs those measurements to explain a match
- also work out how good a whole run was, using the average score, the score of the worst off user and how many users were left unmatched

`matcher.py`: three ways of matching.
1. greedy pairing. Take the best allowed pair still available, again and again. Nobody ends up wanting to swap, because both halves of a pair read the same score, so the best pair left has to be taken or those two would rather have each other. It does not give the highest total score, since taking the best pair can strand two people who each had a good second choice.
2. fairest pairing. Work out each free user's best remaining partner and serve whoever is hardest to place first. Most pairs are banned by the time `constraints.py` has run, so this spends the few allowed partners on the people who have no others, and leaves fewer users out. The average score comes out lower in exchange.
3. building groups from the bottom up. Start with everyone alone, then join the two closest groups until a stopping point is reached, such as a limit of n users per friend group. When judging a join, use the worst pair in the group rather than the average, so nobody ends up in a group with someone they do not get on with.

- 1 and 2 are then compared, to see which works better. They want different things, so which is better depends on whether a run is judged on its average score or on how many people it left out
- 3 is separate, and is used for friend group mode
- all three read `S` and `H` only, and know nothing about users

Gale-Shapley was tried and dropped. It settles a disagreement between two sides' preference orders, and `S` gives both halves of a pair the same number, so there is no disagreement to settle and any correct stable matching is the one greedy already returns.

`llm.py`: asks an LLM to write the message shown to a matched pair.
- write a system prompt that asks for a match message giving a reason and a suggestion
- connect to the API
- send the system prompt along with the details of the match (both users, matching score and feature measurements)
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
