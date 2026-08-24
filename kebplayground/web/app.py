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
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .. import data, pipeline, vocabulary
from ..models import User
from . import auth, db

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

# Held while a match run is going, so two organisers cannot start one each.
run_lock = threading.Lock()

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
def home(request: Request, error: str = ""):
    """The front door, which depends on how far along the visitor is.

    Not signed in, they get the sign in button. Signed in with a profile
    already saved, they go to their own page. Otherwise they get the form.
    """
    email = auth.signed_in_email(request)
    if email is None:
        return render(request, "login.html", domain=auth.allowed_domain(), error=error)
    if store.get_user(email) is not None:
        return RedirectResponse("/me", status_code=303)
    return render(
        request,
        "signup.html",
        options=OPTIONS,
        form={"name": auth.signed_in_name(request)},
        email=email,
        error=None,
    )


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
            error=str(error),
        )

    store.add_user(db.user_to_doc(user, clean_name, email))
    return RedirectResponse("/me", status_code=303)


def _match_for(user_id: str) -> tuple[dict[str, object] | None, bool]:
    """Return (the match entry for this user, whether any run exists)."""
    run = store.latest_run()
    if run is None:
        return None, False
    result = run["result"]
    for entry in result["matches"]:  # type: ignore[index]
        if user_id in (entry["a"], entry["b"]):
            return entry, True
    return None, True


@app.get("/me", response_class=HTMLResponse)
def me(request: Request):
    email = auth.signed_in_email(request)
    if email is None:
        return RedirectResponse("/", status_code=303)
    doc = store.get_user(email)
    if doc is None:
        # Signed in but no profile yet, so back to the form.
        return RedirectResponse("/", status_code=303)

    entry, has_run = _match_for(email)
    if entry is None:
        return render(request, "waiting.html", has_run=has_run)
    partner_id = entry["b"] if entry["a"] == email else entry["a"]
    partner = store.get_user(str(partner_id)) or {}
    return render(
        request,
        "result.html",
        name=doc["name"],
        partner_name=partner.get("name", partner_id),
        partner_contact=partner.get("contact", ""),
        mode=entry["mode"],
        score=entry["score"],
        message=entry.get("message"),
    )


@app.get("/me/status", response_class=HTMLResponse)
def me_status(request: Request):
    email = auth.signed_in_email(request)
    if email is None:
        return Response(headers={"HX-Redirect": "/"})
    entry, has_run = _match_for(email)
    if entry is not None:
        # htmx follows this header, landing the phone on the result page.
        return Response(headers={"HX-Redirect": "/me"})
    return render(request, "partials/status.html", has_run=has_run)


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
    return render(
        request,
        "admin.html",
        token=token,
        notice=notice,
        total=len(users),
        counts=counts,
        run=run,
    )


@app.post("/admin/run")
def admin_run(token: str = Form("")):
    _check_token(token)
    if not run_lock.acquire(blocking=False):
        return RedirectResponse(
            f"/admin?token={token}&notice=a+run+is+already+going", status_code=303
        )
    try:
        users = [db.doc_to_user(doc) for doc in store.list_users()]
        cache = Path(os.environ.get("LLM_CACHE_PATH", ".cache/llm.json"))
        result = pipeline.run_matching(users, explain=True, cache=cache)
        store.save_run(result)
    finally:
        run_lock.release()
    return RedirectResponse(f"/admin?token={token}&notice=run+finished", status_code=303)


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
        out, fieldnames=["a", "a_name", "b", "b_name", "mode", "score", "message"]
    )
    writer.writeheader()
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
                    "message": entry.get("message", ""),
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
