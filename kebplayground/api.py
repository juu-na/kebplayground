"""HTTP layer over the matching engine.

This is the "Phase 2 API" cli.py's docstring already talks about: every
endpoint here calls the same functions the command line uses (data,
constraints, scoring, matcher) rather than reimplementing any of it. The
only thing this module adds is a single in-memory profile to run those
functions against — see state.py for why.

Run it with: uv run uvicorn kebplayground.api:app --reload
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import constraints, data, matcher, scoring, vocabulary
from .models import User, pair_key
from .state import store

app = FastAPI(title="kiWe API")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

DEFAULT_COUNT = 60
DEFAULT_SEED = 1
FLOOR = scoring.MIN_MATCH_SCORE


# ---------------------------------------------------------------- vocabulary

@app.get("/api/vocabulary")
def vocabulary_endpoint():
    """Every registered value a form on the frontend needs to offer.

    Nothing here is made up for the UI — it is read straight out of
    vocabulary.py, the same module data.py and constraints.py read.
    """
    return {
        "majors_by_faculty": {
            faculty: sorted(majors) for faculty, majors in vocabulary.MAJORS.items()
        },
        "faculties": sorted(vocabulary.FACULTIES),
        "years": sorted(vocabulary.YEARS),
        "mbtis": sorted(vocabulary.MBTIS),
        "genders": sorted(vocabulary.GENDERS),
        "areas": sorted(vocabulary.AREAS),
        "languages": sorted(vocabulary.LANGUAGES),
        "interests": sorted(vocabulary.INTERESTS),
        "modes": sorted(vocabulary.MODES),
    }


# --------------------------------------------------------------------- "you"

class SignupBody(BaseModel):
    major: str
    faculty: str
    year: int
    age: int
    mbti: str
    languages: list[str] = []
    gender: str
    area: str
    interests: list[str] = []
    mode: str


class PreferencesBody(BaseModel):
    genders: list[str] | None = None
    age_min: int | None = None
    age_max: int | None = None
    majors: list[str] | None = None
    faculties: list[str] | None = None
    years: list[int] | None = None
    mbti: list[str] | None = None
    languages: list[str] | None = None
    interests: list[str] | None = None
    same_area_only: bool | None = None


class SettingsBody(BaseModel):
    show_scores: bool | None = None
    paused: bool | None = None


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "major": user.major,
        "faculty": user.faculty,
        "year": user.year,
        "age": user.age,
        "mbti": user.mbti,
        "languages": sorted(user.languages),
        "gender": user.gender,
        "area": user.area,
        "interests": sorted(user.interests),
        "mode": user.mode,
        "preferences": {
            key: (sorted(value) if isinstance(value, frozenset) else value)
            for key, value in user.preferences.items()
        },
    }


@app.get("/api/me")
def me():
    return {
        "profile": _serialize_user(store.profile),
        "signed_up": store.signed_up,
        "settings": store.settings,
    }


@app.post("/api/signup")
def signup(body: SignupBody):
    if body.faculty not in vocabulary.MAJORS:
        raise HTTPException(400, f"unknown faculty: {body.faculty}")
    if body.major not in vocabulary.MAJORS[body.faculty]:
        raise HTTPException(400, f"{body.major} is not taught in {body.faculty}")
    if body.mode not in vocabulary.MODES:
        raise HTTPException(400, f"unknown mode: {body.mode}")

    store.replace_profile(
        major=body.major,
        faculty=body.faculty,
        year=body.year,
        age=body.age,
        mbti=body.mbti,
        languages=frozenset(body.languages),
        gender=body.gender,
        area=body.area,
        interests=frozenset(body.interests),
        mode=body.mode,
        preferences={},
    )
    return {"profile": _serialize_user(store.profile)}


@app.post("/api/preferences")
def set_preferences(body: PreferencesBody):
    preferences: dict[str, object] = {}
    if body.genders:
        preferences["genders"] = frozenset(body.genders)
    if body.age_min is not None and body.age_max is not None:
        preferences["age"] = (body.age_min, body.age_max)
    if body.majors:
        preferences["majors"] = frozenset(body.majors)
    if body.faculties:
        preferences["faculties"] = frozenset(body.faculties)
    if body.years:
        preferences["years"] = frozenset(body.years)
    if body.mbti:
        preferences["mbti"] = frozenset(body.mbti)
    if body.languages:
        preferences["languages"] = frozenset(body.languages)
    if body.interests:
        preferences["interests"] = frozenset(body.interests)
    if body.same_area_only:
        preferences["same_area_only"] = True

    try:
        vocabulary.validate_preferences(preferences)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    store.replace_profile(preferences=preferences)
    return {"profile": _serialize_user(store.profile)}


@app.patch("/api/settings")
def update_settings(body: SettingsBody):
    if body.show_scores is not None:
        store.settings["show_scores"] = body.show_scores
    if body.paused is not None:
        if body.paused != store.settings["paused"]:
            store.reset_run()
        store.settings["paused"] = body.paused
    return {"settings": store.settings}


# ------------------------------------------------------------------- running

def _compute_run(count: int, seed: int) -> dict:
    """Score and match one run: the made up cohort, plus "you" if not paused.

    Cached so /api/feed, /api/profile and /api/waiting all read the same
    cohort instead of each generating a fresh, disagreeing one.
    """
    cached = store.run_cache
    if cached and cached["count"] == count and cached["seed"] == seed:
        return cached

    cohort = [u for u in data.generate_users(count, seed) if u.id != store.profile.id]
    users = cohort if store.settings["paused"] else cohort + [store.profile]

    allowed = constraints.build_allow_table(users)
    # floor 0.0 keeps every allowed pair's score, not just the ones offered,
    # so /api/waiting can show how close "you" got even when nothing clears
    # the real floor.
    all_scores, modes, allowed = scoring.build_score_table(users, allowed, 0.0)
    live_scores = {pair: score for pair, score in all_scores.items() if score >= FLOOR}

    matches = matcher.ALGORITHMS["blossom"](live_scores, allowed)
    matched_ids = {uid for pair in matches for uid in pair}
    waiting = sorted(u.id for u in users if u.id not in matched_ids)

    run = {
        "count": count,
        "seed": seed,
        "users_by_id": {u.id: u for u in users},
        "all_scores": all_scores,
        "live_scores": live_scores,
        "modes": modes,
        "allowed": allowed,
        "matches": matches,
        "waiting": waiting,
    }
    store.run_cache = run
    return run


def _partner_of(run: dict, user_id: str) -> str | None:
    for a, b in run["matches"]:
        if a == user_id:
            return b
        if b == user_id:
            return a
    return None


def _why(you: User, other: User, mode: str) -> str:
    """A one-line reason, built from the same breakdown llm.explain reads."""
    _, _, breakdown = scoring.score_pair(you, other)
    weights = scoring.WEIGHTS[mode]
    reasons = []

    same_department = vocabulary.department_of(you.major) is not None and (
        vocabulary.department_of(you.major) == vocabulary.department_of(other.major)
    )
    if you.major == other.major:
        reasons.append("the same major")
    elif same_department:
        reasons.append("the same department")

    shared_interests = sorted(you.interests & other.interests)
    if shared_interests:
        reasons.append(f"{len(shared_interests)} shared interests")

    shared_langs = sorted(you.languages & other.languages)
    if shared_langs:
        reasons.append(f"you both speak {', '.join(shared_langs)}")

    if breakdown.get("mbti", 0) >= 0.8:
        reasons.append("compatible MBTI")

    if not reasons:
        top = max(breakdown, key=lambda k: breakdown[k] * weights.get(k, 0))
        reasons.append(f"a strong {top} match")

    headline = reasons[0][0].upper() + reasons[0][1:]
    tail = reasons[1:]
    if len(tail) > 1:
        rest = ", ".join(tail[:-1]) + " and " + tail[-1]
    else:
        rest = " and ".join(tail)
    return f"{headline}{', ' + rest if rest else ''}."


def _card(you: User, other: User, run: dict) -> dict:
    key = pair_key(you.id, other.id)
    score = run["all_scores"].get(key, 0.0)
    shared = sorted(you.interests & other.interests)
    also = sorted(other.interests - you.interests)
    department = vocabulary.department_of(other.major)
    return {
        "id": other.id,
        "name": other.id.replace("user_", "User "),
        "study": other.major,
        "faculty": other.faculty,
        "department": department,
        "same_department": department is not None and department == vocabulary.department_of(you.major),
        "year": other.year,
        "age": other.age,
        "mbti": other.mbti,
        "area": other.area,
        "score": round(score, 2),
        "ringPct": f"{round(score * 100)}%",
        "shared": shared,
        "other": also[:6],
        "languages": sorted(other.languages),
        "sharedLanguages": sorted(you.languages & other.languages),
        "mode": run["modes"].get(key, other.mode),
        "note": _why(you, other, run["modes"].get(key, other.mode)),
    }


@app.get("/api/feed")
def feed(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED):
    if store.settings["paused"]:
        return {"paused": True, "cards": []}

    run = _compute_run(count, seed)
    you = store.profile
    partner_id = _partner_of(run, you.id)

    cards = []
    if partner_id and partner_id not in store.passed:
        cards.append(_card(you, run["users_by_id"][partner_id], run))

    return {
        "paused": False,
        "mode": you.mode,
        "cards": cards,
        "remaining": len(cards),
        "matched": partner_id is not None,
    }


@app.get("/api/profile/{other_id}")
def profile(other_id: str, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED):
    run = _compute_run(count, seed)
    other = run["users_by_id"].get(other_id)
    if other is None:
        raise HTTPException(404, f"no such person in this run: {other_id}")
    return _card(store.profile, other, run)


@app.post("/api/feed/{other_id}/like")
def like(other_id: str, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED):
    run = _compute_run(count, seed)
    other = run["users_by_id"].get(other_id)
    if other is None:
        raise HTTPException(404, f"no such person in this run: {other_id}")

    card = _card(store.profile, other, run)
    store.history.insert(
        0,
        {
            "id": other.id,
            "name": card["name"],
            "study": card["study"],
            "score": card["score"],
            "status": "Liked",
            "run_seed": seed,
        },
    )
    return card


@app.post("/api/feed/{other_id}/pass")
def pass_on(other_id: str, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED):
    run = _compute_run(count, seed)
    other = run["users_by_id"].get(other_id)
    if other is None:
        raise HTTPException(404, f"no such person in this run: {other_id}")

    store.passed.add(other_id)
    store.history.insert(
        0,
        {
            "id": other.id,
            "name": other.id.replace("user_", "User "),
            "study": other.major,
            "score": round(
                run["all_scores"].get(pair_key(store.profile.id, other_id), 0.0), 2
            ),
            "status": "Passed",
            "run_seed": seed,
        },
    )
    return {"ok": True}


@app.get("/api/waiting")
def waiting(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED):
    run = _compute_run(count, seed)
    you = store.profile

    if _partner_of(run, you.id) is not None:
        return {"matched": True}

    your_scores = {
        pair: score for pair, score in run["all_scores"].items() if you.id in pair
    }
    best_score = round(max(your_scores.values()), 2) if your_scores else 0.0

    tips = []
    if len(you.interests) < 5:
        tips.append(
            "Add a few more interests — sharing is the single biggest part of your score."
        )
    if you.preferences.get("same_area_only"):
        tips.append('Turn off "same area only" to see all of Auckland.')
    age_pref = you.preferences.get("age")
    if age_pref and age_pref[1] - age_pref[0] < 6:
        low, high = age_pref
        tips.append(f"Widen your age range from {low}–{high} to {max(18, low - 1)}–{high + 2}.")
    if not tips:
        tips.append("Nobody in this run's cohort cleared the floor with you — try again on the next run.")

    return {
        "matched": False,
        "waiting": run["waiting"],
        "best_score": best_score,
        "floor": FLOOR,
        "tips": tips[:3],
    }


@app.get("/api/history")
def history():
    return {"history": store.history}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
