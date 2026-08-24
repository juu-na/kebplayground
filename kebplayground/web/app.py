"""The Phase 2 web app.

Wraps the pipeline for a live demo: participants sign up, an organiser
triggers a run, participants see their match. No login; the admin pages take
a token from the ADMIN_TOKEN env var.

Every route is a plain def, never async def, so the blocking Gemini and
store calls run in the threadpool and polling keeps working while a run is
in flight.
"""

import csv
import io
import os
import re
import secrets
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import data, pipeline, vocabulary
from ..models import User
from . import db

# Local dev reads ADMIN_TOKEN and friends from .env. Deployed, the real
# environment is already set and load_dotenv finds nothing.
load_dotenv()

HERE = Path(__file__).parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

store = db.make_store()

# Held while a match run is going, so two organisers cannot start one each.
run_lock = threading.Lock()

# The order the modes are offered in, friendship first. Anything registered
# later and not named here comes after, so vocabulary stays the source.
MODE_ORDER = ("friendship", "date")

# What a contact has to look like. Deliberately loose: one @, a dot after it,
# no spaces. Anything tighter turns down addresses that work.
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


# --- participant pages ------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def signup_form(request: Request):
    return render(request, "signup.html", options=OPTIONS, form={}, error=None)


def _parse_signup(form: dict[str, object], picked: dict[str, list[str]]) -> tuple[User, str, str]:
    """Turn the submitted form into a User plus the web-only fields.

    Raises ValueError naming the first thing wrong, which the form shows.
    """
    name = str(form.get("name", "")).strip()
    contact = str(form.get("contact", "")).strip()
    if not name:
        raise ValueError("name is missing")
    if not EMAIL.match(contact):
        raise ValueError("email does not look like an address")

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
        id=uuid.uuid4().hex[:12],
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
    return user, name, contact


@app.post("/signup")
def signup(
    request: Request,
    name: str = Form(""),
    contact: str = Form(""),
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
    form = {
        "name": name,
        "contact": contact,
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
        user, clean_name, clean_contact = _parse_signup(form, picked)
    except ValueError as error:
        return render(
            request,
            "signup.html",
            status_code=400,
            options=OPTIONS,
            form={**form, **picked},
            error=str(error),
        )

    store.add_user(db.user_to_doc(user, clean_name, clean_contact))
    response = RedirectResponse(f"/me/{user.id}", status_code=303)
    # A fallback for a lost tab: /me with no id reads this cookie.
    response.set_cookie("kb_user", user.id, max_age=60 * 60 * 24 * 7)
    return response


@app.get("/me", response_class=HTMLResponse)
def me_from_cookie(request: Request):
    user_id = request.cookies.get("kb_user")
    if user_id and store.get_user(user_id):
        return RedirectResponse(f"/me/{user_id}", status_code=303)
    return RedirectResponse("/", status_code=303)


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


@app.get("/me/{user_id}", response_class=HTMLResponse)
def me(request: Request, user_id: str):
    doc = store.get_user(user_id)
    if doc is None:
        return render(request, "message.html", status_code=404,
                      title="Not found", body="That link does not point at a signup.")
    entry, has_run = _match_for(user_id)
    if entry is None:
        return render(request, "waiting.html", user_id=user_id, has_run=has_run)
    partner_id = entry["b"] if entry["a"] == user_id else entry["a"]
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


@app.get("/me/{user_id}/status", response_class=HTMLResponse)
def me_status(request: Request, user_id: str):
    entry, has_run = _match_for(user_id)
    if entry is not None:
        # htmx follows this header, landing the phone on the result page.
        return Response(headers={"HX-Redirect": f"/me/{user_id}"})
    return render(request, "partials/status.html", user_id=user_id, has_run=has_run)


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

    users = data.generate_users(count)
    for i, user in enumerate(users, start=1):
        made = dataclasses.replace(user, id=uuid.uuid4().hex[:12])
        store.add_user(db.user_to_doc(made, f"Demo {i}", f"demo{i}@example.com"))
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
