"""The Phase 2 web app.

Wraps the pipeline for a live demo: participants sign in with their
university Google account, fill in a profile, an organiser triggers a run,
and each participant sees their match. The admin pages take a token from the
ADMIN_TOKEN env var instead, since an organiser is not a participant.

A participant is identified by the address in their session, which is also
the id the pipeline sees, so signing in again finds the same profile.

Most routes are plain def, never async def, so the blocking Gemini and store
calls run in the threadpool and polling keeps working while a run is in
flight. The two OAuth routes are async, because Authlib's calls out to
Google are.
"""

import csv
import io
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .. import data, vocabulary
from ..models import User
from . import auth, db, matchflow

# Local dev reads ADMIN_TOKEN and friends from .env. Deployed, the real
# environment is already set and load_dotenv finds nothing.
load_dotenv()

HERE = Path(__file__).parent

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-session-secret"),
    same_site="lax",
    https_only=os.environ.get("STORE") == "firestore",
)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

store = db.make_store()

# The order the modes are offered in, friendship first. Anything registered
# later and not named here comes after, so vocabulary stays the source.
MODE_ORDER = ("friendship", "date")


def _modes_in_order() -> list[str]:
    known = [mode for mode in MODE_ORDER if mode in vocabulary.MODES]
    return known + sorted(set(vocabulary.MODES) - set(known))


# What the signup form offers, sorted once. Majors are grouped by faculty so
# the template renders one optgroup per faculty.
OPTIONS = {
    "majors_by_faculty": {
        faculty: sorted(majors)
        for faculty, majors in sorted(vocabulary.MAJORS.items())
    },
    "years": sorted(vocabulary.YEARS),
    "mbtis": sorted(vocabulary.MBTIS),
    "genders": sorted(vocabulary.GENDERS),
    "areas": sorted(vocabulary.AREAS),
    "languages": sorted(vocabulary.LANGUAGES),
    "interests": sorted(vocabulary.INTERESTS),
    "modes": _modes_in_order(),
}


def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        request, template, context, status_code=status_code
    )


# --- signing in -------------------------------------------------------------


@app.get("/login")
async def login(request: Request):
    """Hand the browser over to Google.

    The domain is passed as a hint, so the account chooser shows university
    accounts first. It is only a hint, and the answer is checked again in
    the callback.
    """
    redirect = request.url_for("auth_callback")
    return await auth.oauth.google.authorize_redirect(
        request, str(redirect), hd=auth.allowed_domain()
    )


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    try:
        token = await auth.oauth.google.authorize_access_token(request)
    except Exception:
        # A cancelled sign in lands here too, so this is not only an error.
        return RedirectResponse("/?error=sign+in+did+not+finish", status_code=303)

    claims = token.get("userinfo") or {}
    email = str(claims.get("email") or "")
    verified = bool(claims.get("email_verified"))

    if not email or not verified or not auth.is_allowed(email):
        return render(
            request,
            "message.html",
            status_code=403,
            title="That account cannot be used",
            body=(
                f"Sign in with your @{auth.allowed_domain()} account. "
                "Personal Google accounts are not part of this demo."
            ),
        )

    auth.sign_in(request, email, str(claims.get("name") or ""))
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    auth.sign_out(request)
    return RedirectResponse("/", status_code=303)


# --- participant pages ------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, error: str = "", notice: str = ""):
    """The front door, which depends on how far along the visitor is.

    Not signed in, they get the sign in button. Signed in without a profile,
    the form. Otherwise their own home: the profile, and where their match
    is up to.
    """
    email = auth.signed_in_email(request)
    if email is None:
        return render(request, "login.html", domain=auth.allowed_domain(), error=error)

    doc = store.get_user(email)
    if doc is None:
        return render(
            request,
            "signup.html",
            options=OPTIONS,
            form={"name": auth.signed_in_name(request)},
            email=email,
            heading="Find your match",
            action="/signup",
            button="Sign up",
            error=None,
        )

    return render(request, "home.html", notice=notice, **_home_context(doc))


# What each measurement is called on the page, and the order they read in.
# Anything the pipeline measures but that is not named here is left off
# rather than shown by its internal name.
FEATURE_LABELS = {
    "interests": "Interests",
    "major": "Study",
    "languages": "Languages",
    "mbti": "Personality",
    "age": "Age",
    "year": "Year",
    "area": "Part of town",
}


def _bars(breakdown: dict[str, float]) -> list[dict[str, object]]:
    """The measurements worth drawing, strongest first."""
    scored = [
        {"label": FEATURE_LABELS[name], "percent": round(value * 100)}
        for name, value in breakdown.items()
        if name in FEATURE_LABELS and value > 0
    ]
    return sorted(scored, key=lambda bar: bar["percent"], reverse=True)


def _shared(doc: dict[str, object], partner: dict[str, object]) -> dict[str, object]:
    """What the two have in common, for the chips under the card.

    The study line is the closest thing they share and no more: the same
    major beats the same department, which beats the same faculty.
    """
    mine = db.doc_to_user(doc)
    theirs = db.doc_to_user(partner)

    study = None
    department = vocabulary.department_of(mine.major)
    if mine.major == theirs.major:
        study = mine.major
    elif department is not None and department == vocabulary.department_of(theirs.major):
        study = department
    elif mine.faculty == theirs.faculty:
        study = mine.faculty

    return {
        "study": study,
        "interests": sorted(mine.interests & theirs.interests),
        "languages": sorted(mine.languages & theirs.languages),
    }


# How few interests counts as few. Interests carry the most weight of any
# measurement, so somebody who listed a couple has the most to gain by
# listing more.
FEW_INTERESTS = 5


def _tips(doc: dict[str, object]) -> list[str]:
    """What this person could change to be easier to match.

    Only says a thing when it is true of them, so the list is empty for
    somebody who has already opened up as far as they can.
    """
    user = db.doc_to_user(doc)
    preferences = user.preferences
    tips = []

    if len(user.interests) < FEW_INTERESTS:
        tips.append(
            f"Add a few more interests. You have {len(user.interests)}, "
            "and interests count for more than anything else."
        )

    age = preferences.get("age")
    if isinstance(age, tuple):
        low, high = age
        tips.append(f"Widen your age range from {low} to {high} by a year either way.")

    genders = preferences.get("genders")
    if genders and len(genders) < len(vocabulary.GENDERS):  # type: ignore[arg-type]
        tips.append("Open up on who you are happy to be matched with.")

    if preferences.get(vocabulary.SAME_AREA_ONLY):
        tips.append("Turn off matching only within your part of Auckland.")

    return tips


def _last_run_for(user_id: str) -> dict[str, object] | None:
    """The last run this person took part in but came out of unmatched."""
    run = store.latest_run()
    if run is None:
        return None
    result = run["result"]
    if user_id not in result.get("waiting", []):  # type: ignore[union-attr]
        return None
    return {
        "floor": result.get("floor", 0.0),  # type: ignore[union-attr]
        "best": result.get("best", {}).get(user_id, 0.0),  # type: ignore[union-attr]
    }


def _home_context(doc: dict[str, object]) -> dict[str, object]:
    """Everything both the home page and its polled fragment need."""
    status = str(doc.get("status") or "waiting")
    match = None
    partner = None
    match_id = doc.get("match_id")
    if match_id:
        match = store.get_match(str(match_id))
    if match:
        other = match["b"] if match["a"] == doc["id"] else match["a"]
        partner = store.get_user(str(other))
    return {
        "doc": doc,
        "status": status,
        "match": match,
        "partner": partner,
        "bars": _bars(match["breakdown"]) if match else [],  # type: ignore[arg-type]
        "shared": _shared(doc, partner) if match and partner else {},
        "waiting_count": store.count_waiting(),
        "pool_size": matchflow.pool_size(store),
        # Set only when a run has already been through without finding them
        # anybody, which is the one case worth explaining.
        "missed": _last_run_for(str(doc["id"])) if status == "waiting" else None,
        "tips": _tips(doc) if status == "waiting" else [],
    }


def _parse_signup(
    email: str, form: dict[str, object], picked: dict[str, list[str]]
) -> tuple[User, str]:
    """Turn the submitted form into a User plus the display name.

    The address comes from the session rather than the form, so it is the one
    Google verified. It is also the user's id, which is what lets a second
    sign in find the same profile.

    Raises ValueError naming the first thing wrong, which the form shows.
    """
    name = str(form.get("name", "")).strip()
    if not name:
        raise ValueError("name is missing")

    def choice(field: str, registered: frozenset) -> str:
        value = str(form.get(field, "")).strip()
        if value not in {str(item) for item in registered}:
            raise ValueError(f"{field} is missing or not registered")
        return value

    def number(field: str, lowest: int, highest: int) -> int:
        raw = str(form.get(field, "")).strip()
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"{field} has to be a whole number") from None
        if not lowest <= value <= highest:
            raise ValueError(f"{field} has to sit between {lowest} and {highest}")
        return value

    major = choice("major", vocabulary.ALL_MAJORS)
    languages = frozenset(picked.get("languages", []))
    interests = frozenset(picked.get("interests", []))
    if not languages <= vocabulary.LANGUAGES:
        raise ValueError("languages named something not registered")
    if not interests <= vocabulary.INTERESTS:
        raise ValueError("interests named something not registered")

    # At least one gender has to be ticked. Ticking every one is how a user
    # says they do not mind, which reads more clearly than an empty answer.
    preferences: dict[str, object] = {}
    pref_genders = frozenset(picked.get("pref_genders", []))
    if not pref_genders:
        raise ValueError("pick at least one gender to be matched with")
    preferences["genders"] = pref_genders
    age_low = str(form.get("pref_age_min", "")).strip()
    age_high = str(form.get("pref_age_max", "")).strip()
    if age_low or age_high:
        if not (age_low and age_high):
            raise ValueError("age preference needs both the lowest and the highest")
        try:
            preferences["age"] = (int(age_low), int(age_high))
        except ValueError:
            raise ValueError("age preference takes two whole numbers") from None
    # The one soft preference the form asks for. Left out entirely when the
    # box is unticked, which is how the rest of the codebase says "no
    # preference".
    if str(form.get("same_area_only", "")).strip():
        preferences[vocabulary.SAME_AREA_ONLY] = True
    vocabulary.validate_preferences(preferences)

    user = User(
        id=email,
        major=major,
        faculty=vocabulary.faculty_of(major),
        year=number("year", min(vocabulary.YEARS), max(vocabulary.YEARS)),
        age=number("age", 16, 99),
        mbti=choice("mbti", vocabulary.MBTIS),
        languages=languages,
        gender=choice("gender", vocabulary.GENDERS),
        area=choice("area", vocabulary.AREAS),
        interests=interests,
        mode=choice("mode", vocabulary.MODES),
        preferences=preferences,
    )
    return user, name


@app.post("/signup")
def signup(
    request: Request,
    name: str = Form(""),
    major: str = Form(""),
    year: str = Form(""),
    age: str = Form(""),
    mbti: str = Form(""),
    gender: str = Form(""),
    area: str = Form(""),
    mode: str = Form(""),
    languages: list[str] = Form([]),
    interests: list[str] = Form([]),
    pref_genders: list[str] = Form([]),
    pref_age_min: str = Form(""),
    pref_age_max: str = Form(""),
    same_area_only: str = Form(""),
):
    email = auth.signed_in_email(request)
    if email is None:
        return RedirectResponse("/", status_code=303)

    form = {
        "name": name,
        "major": major,
        "year": year,
        "age": age,
        "mbti": mbti,
        "gender": gender,
        "area": area,
        "mode": mode,
        "pref_age_min": pref_age_min,
        "pref_age_max": pref_age_max,
        "same_area_only": same_area_only,
    }
    picked = {
        "languages": languages,
        "interests": interests,
        "pref_genders": pref_genders,
    }
    try:
        user, clean_name = _parse_signup(email, form, picked)
    except ValueError as error:
        return render(
            request,
            "signup.html",
            status_code=400,
            options=OPTIONS,
            form={**form, **picked},
            email=email,
            heading="Find your match",
            action="/signup",
            button="Sign up",
            error=str(error),
        )

    store.add_user(db.user_to_doc(user, clean_name, email))
    matchflow.maybe_trigger(store)
    return RedirectResponse("/", status_code=303)


@app.get("/me")
def me():
    """Kept so older links still land somewhere sensible."""
    return RedirectResponse("/", status_code=303)


@app.get("/me/status", response_class=HTMLResponse)
def me_status(request: Request):
    """The fragment the home page polls.

    Answers with the same state block the page was built with, so the phone
    picks up a match without the page reloading.
    """
    email = auth.signed_in_email(request)
    if email is None:
        return Response(headers={"HX-Redirect": "/"})
    doc = store.get_user(email)
    if doc is None:
        return Response(headers={"HX-Redirect": "/"})
    return render(request, "partials/status.html", **_home_context(doc))


# --- answering a match, and stepping out ---


def _signed_in_doc(request: Request) -> dict[str, object] | None:
    email = auth.signed_in_email(request)
    return store.get_user(email) if email else None


@app.post("/match/respond")
def respond(request: Request, answer: str = Form("")):
    doc = _signed_in_doc(request)
    if doc is None:
        return RedirectResponse("/", status_code=303)
    if answer not in ("accepted", "declined"):
        return RedirectResponse("/?error=unknown+answer", status_code=303)

    match_id = doc.get("match_id")
    if match_id:
        state = store.respond_to_match(str(match_id), str(doc["id"]), answer)
        if state == "declined":
            # Both are back in the pool, which may be enough for a round.
            matchflow.maybe_trigger(store)
    return RedirectResponse("/", status_code=303)


@app.post("/pause")
def pause(request: Request):
    doc = _signed_in_doc(request)
    if doc is None:
        return RedirectResponse("/", status_code=303)
    if store.set_status_if(str(doc["id"]), "waiting", "paused"):
        return RedirectResponse("/?notice=you+are+sitting+this+one+out", status_code=303)
    return RedirectResponse(
        "/?notice=too+late+to+pause%2C+a+round+is+going", status_code=303
    )


@app.post("/resume")
def resume(request: Request):
    doc = _signed_in_doc(request)
    if doc is None:
        return RedirectResponse("/", status_code=303)
    if store.set_status_if(str(doc["id"]), "paused", "waiting"):
        matchflow.maybe_trigger(store)
    return RedirectResponse("/", status_code=303)


# --- editing the profile ---


@app.get("/profile/edit", response_class=HTMLResponse)
def edit_form(request: Request):
    doc = _signed_in_doc(request)
    if doc is None:
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "signup.html",
        options=OPTIONS,
        form=_doc_to_form(doc),
        email=str(doc["contact"]),
        heading="Your profile",
        action="/profile/edit",
        button="Save",
        error=None,
    )


def _doc_to_form(doc: dict[str, object]) -> dict[str, object]:
    """Turn a stored user back into the shape the form template reads."""
    user = db.doc_to_user(doc)
    preferences = user.preferences
    age = preferences.get("age")
    return {
        "name": doc.get("name", ""),
        "major": user.major,
        "year": str(user.year),
        "age": str(user.age),
        "mbti": user.mbti,
        "gender": user.gender,
        "area": user.area,
        "mode": user.mode,
        "languages": sorted(user.languages),
        "interests": sorted(user.interests),
        "pref_genders": sorted(preferences.get("genders") or []),
        "pref_age_min": str(age[0]) if age else "",
        "pref_age_max": str(age[1]) if age else "",
        "same_area_only": "on" if preferences.get(vocabulary.SAME_AREA_ONLY) else "",
    }


@app.post("/profile/edit")
def edit(
    request: Request,
    name: str = Form(""),
    major: str = Form(""),
    year: str = Form(""),
    age: str = Form(""),
    mbti: str = Form(""),
    gender: str = Form(""),
    area: str = Form(""),
    mode: str = Form(""),
    languages: list[str] = Form([]),
    interests: list[str] = Form([]),
    pref_genders: list[str] = Form([]),
    pref_age_min: str = Form(""),
    pref_age_max: str = Form(""),
    same_area_only: str = Form(""),
):
    doc = _signed_in_doc(request)
    if doc is None:
        return RedirectResponse("/", status_code=303)
    email = str(doc["id"])

    form = {
        "name": name,
        "major": major,
        "year": year,
        "age": age,
        "mbti": mbti,
        "gender": gender,
        "area": area,
        "mode": mode,
        "pref_age_min": pref_age_min,
        "pref_age_max": pref_age_max,
        "same_area_only": same_area_only,
    }
    picked = {
        "languages": languages,
        "interests": interests,
        "pref_genders": pref_genders,
    }
    try:
        user, clean_name = _parse_signup(email, form, picked)
    except ValueError as error:
        return render(
            request,
            "signup.html",
            status_code=400,
            options=OPTIONS,
            form={**form, **picked},
            email=str(doc["contact"]),
            heading="Your profile",
            action="/profile/edit",
            button="Save",
            error=str(error),
        )

    # A merge, not a replace: status, match_id and created_at belong to the
    # matching and have to survive an edit. An edit while a match is on
    # offer changes nothing about that match, only the next round.
    fresh = db.user_to_doc(user, clean_name, str(doc["contact"]))
    store.update_user(email, db.profile_fields(fresh))
    return RedirectResponse("/?notice=profile+saved", status_code=303)


# --- admin ------------------------------------------------------------------


def _check_token(token: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or not secrets.compare_digest(token or "", expected):
        raise HTTPException(status_code=403, detail="wrong or missing token")


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, token: str = "", notice: str = ""):
    _check_token(token)
    users = store.list_users()
    counts: dict[str, int] = {}
    for doc in users:
        counts[str(doc["mode"])] = counts.get(str(doc["mode"]), 0) + 1
    run = store.latest_run()
    statuses: dict[str, int] = {}
    for doc in users:
        key = str(doc.get("status") or "waiting")
        statuses[key] = statuses.get(key, 0) + 1
    return render(
        request,
        "admin.html",
        token=token,
        notice=notice,
        total=len(users),
        counts=counts,
        statuses=statuses,
        waiting_count=store.count_waiting(),
        pool_size=matchflow.pool_size(store),
        run=run,
    )


@app.post("/admin/run")
def admin_run(token: str = Form("")):
    """Force a round on whoever is waiting, however few that is.

    Run here rather than on a thread, so the admin sees the outcome on the
    page they land on.
    """
    _check_token(token)
    if not matchflow.run_now(store):
        return RedirectResponse(
            f"/admin?token={token}&notice=a+run+is+already+going", status_code=303
        )
    return RedirectResponse(f"/admin?token={token}&notice=run+finished", status_code=303)


@app.post("/admin/settings")
def admin_settings(token: str = Form(""), pool_size: int = Form(10)):
    _check_token(token)
    if pool_size < 2:
        return RedirectResponse(
            f"/admin?token={token}&notice=pool+size+has+to+be+2+or+more", status_code=303
        )
    store.set_settings({"pool_size": pool_size})
    # A smaller pool may already be met by the people waiting.
    matchflow.maybe_trigger(store)
    return RedirectResponse(
        f"/admin?token={token}&notice=pool+size+is+now+{pool_size}", status_code=303
    )


@app.post("/admin/reset")
def admin_reset(token: str = Form("")):
    _check_token(token)
    store.reset()
    return RedirectResponse(f"/admin?token={token}&notice=cleared", status_code=303)


@app.post("/admin/seed")
def admin_seed(token: str = Form(""), count: int = Form(12)):
    _check_token(token)
    import dataclasses

    # Made up users are keyed by a made up address, the same way a real
    # signup is keyed by the one Google verified.
    users = data.generate_users(count)
    for i, user in enumerate(users, start=1):
        email = f"demo{i}@{auth.allowed_domain()}"
        made = dataclasses.replace(user, id=email)
        store.add_user(db.user_to_doc(made, f"Demo {i}", email))
    matchflow.maybe_trigger(store)
    return RedirectResponse(
        f"/admin?token={token}&notice=seeded+{count}", status_code=303
    )


@app.get("/admin/export.csv")
def export_users(token: str = ""):
    _check_token(token)
    out = io.StringIO()
    fields = data.WRITTEN_FIELDS + ["name", "contact", "created_at"]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for doc in store.list_users():
        writer.writerow(doc)
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@app.get("/admin/matches.csv")
def export_matches(token: str = ""):
    _check_token(token)
    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=["a", "a_name", "b", "b_name", "mode", "score", "why", "suggestion"]
    )
    writer.writeheader()
    # The reason for a pair is written down on the match rather than in the
    # run, so look it up by the pair.
    reasons = {
        (str(match["a"]), str(match["b"])): str(match.get("why") or "")
        for match in store.list_matches()
    }
    run = store.latest_run()
    if run is not None:
        for entry in run["result"]["matches"]:  # type: ignore[index]
            a = store.get_user(str(entry["a"])) or {}
            b = store.get_user(str(entry["b"])) or {}
            writer.writerow(
                {
                    "a": entry["a"],
                    "a_name": a.get("name", ""),
                    "b": entry["b"],
                    "b_name": b.get("name", ""),
                    "mode": entry["mode"],
                    "score": entry["score"],
                    "why": reasons.get((str(entry["a"]), str(entry["b"])), ""),
                    "suggestion": entry.get("suggestion", ""),
                }
            )
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=matches.csv"},
    )


# Not /healthz: Google's frontend answers that path itself on Cloud Run, so
# the request never reaches the app.
@app.get("/health")
def health():
    return {"ok": True}
