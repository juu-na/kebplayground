# kebplayground

## Pipeline

```
cli.py
  -> data.py        load or generate users
  -> features.py    measure each pair on each dimension
  -> scoring.py     combine features into one score per pair
  -> constraints.py mark forbidden pairs
  -> matcher.py     decide who matches who
  -> llm.py         explain the match (optional)
  -> output         match table + JSON
```

There are two shared tables: 
- S, the score for every pair
- H, whether the pair is allowed at all

## Phase 1 Architecture

models.py: define User model (e.g. id, major, degree, year, age, MBTI, languages, gender, proximity, timetable, interests, preferences, mode)
- mode is the type of relationship the user wants e.g. lunch mate, study buddy, long term friend group, campus couple, etc.
- proximity is the distance from residental address to city campus
- timetable is a weekly grid of free/busy slots so overlap can be computed
- written first and frozen, since every other module imports it

data.py: load users from csv, generate sample user group
- produce synthetic user data, e.g. 100 users with realistic distribution
- optionally get keb playground participants’ user data for demo
- returns a list of User objects, needed early since everything else runs against it

features.py: define pairwise similarity features
- each feature is a function that takes two users and returns a decimal between 0 to 1 (e.g. 1 is 100%, 0.5 is 50%, 0 is 0%)
- consider user data such as timetable overlap, similarity in major, interests, languages, proximity, etc.
- pure measurement only, no decisions, doesn’t know matching exists
- returns a dict of feature name to value

constraints.py: define base filters for incompatible match
- consider what makes a match incompatible e.g. timetable conflict, different user mode, self pairing
- returns H, the allowed/not allowed table
- separate from scoring because these are absolute, a forbidden pair stays forbidden even at score 1.0

scoring.py: combine features into a score S
- define a weight vector per mode e.g. lunch mate weights timetable compatibility more than other features, study buddy weights major and degree more
- return both the combined score and the per feature breakdown, since llm.py needs the breakdown to explain a match
- also define evaluation metrics e.g. average match score, score for the worst off user, number of users left unmatched. these are what let us compare algorithms rather than just run them

matcher.py: implement three matching algorithms
1. greedy max weight pairing, repeatedly take the best remaining allowed pair, maximises total score
2. gale shapely stable matching using score ordered preference list, lower total but no two people would both rather swap into each other
3. bottom up clustering, merge two closest groups until a stopping condition e.g. size cap of n users per friend group. use complete link, meaning add whoever maximises the minimum score against existing members, so nobody ends up grouped with someone they don’t fit
- then compare 1 and 2 to find the better algorithm
- 3 is a separate one for friend group mode
- consumes S and H only, knows nothing about users

llm.py: LLM wrapper to generate match message
- draft a system prompt, to generate a match message with reason + recommendation
- connect to LLM call API
- send match data (both users, score, feature breakdown) + system prompt
- get response and verify content
- output match message
- runs after matching, never before. the LLM explains a decision already made, it never influences the match, or results stop being reproducible
- put it behind an –explain flag and cache output to JSON, so a failed API call can’t break the live demo

cli.py: command line wrapper with agrument parsing
- input file loading
- mode selection
- algo selection
- output path (JSON for phase 2 UI + matching table)

## Phase 2

Backend: FastAPI app with endpoints
1. accept user profile
2. return match
- wraps the same pipeline, adds nothing to it

Frontend: Static HTML page
1. user sign up form
2. match result display
- for demo purposes, no auth