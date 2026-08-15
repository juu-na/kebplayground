# kebplayground

## Phase 1 Architecture
models.py: define User model (e.g. id, major, degree, year, age, MBTI, languages, gender, proximity, timetable, interests, preferences, mode)
- mode is the type of relationship the user wants e.g. lunch mate, study buddy, long term friend group, campus couple, etc.
- proximity is the distance from residental address to city campus

data.py: load users from csv, generate sample user group
- produce synthetic user data, e.g. 100 users with realistic distribution
- optionally get keb playground participants' user data for demo

features.py: define matching algorithm
- each feature is a function that takes two users and returns a decimal between 0 to 1 (e.g. 1 is 100%, 0.5 is 50%, 0 is 0%)
- consider user data such as feature overlap, similarity in major, interests, etc.

constraints.py: define base filters for incompatible match
- consider what makes a match incompatible e.g. timetable conflict, different user mode, self pairing

scoring.py: combine features into a score S
- define a weight vector per mode e.g. lunch mate weights timetable compatibility more than other features, study buddy weights major and degree more
- also define evaluation metrics e.g. matching window that can be adjusted later

matcher.py: implement three matching algorithms
1. greedy max weight pairing
2. gale shapely stable matching using score ordered preference list
3. bottom up clustering - merge two closest groups until a stopping condition e.g. size cap of n users per friend group
- then compare 1 and 2 to find the better algorithm
- 3 is a separate one for friend group mode

llm.py: LLM wrapper to generate match message
- draft a system prompt, to generate a match message with reason + recommendation
- connect to LLM call API
- send match data to LLM + system prompt
- get response and verify content
- output match message

cli.py: command line wrapper with agrument parsing
- input file loading
- mode selection
- algo selection
- feature entry
- output path (JSON for phase 2 UI + matching table)

## Phase 2 
Backend: FastAPI app with endpoints
1. accept user profile
2. return match

Frontend: Static HTML page
1. user sign up form
2. match result display
- for demo purposes, no auth

