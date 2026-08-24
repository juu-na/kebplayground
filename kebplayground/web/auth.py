"""Signing in with a university Google account.

Google is asked for the account, and the answer is checked here rather than
trusted from the browser. Only an address on the allowed domain gets a
session, so a personal account cannot sign in by editing the request.
"""

import os

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Request

# Read before the client is registered below, which happens while this module
# is being imported. app.py loads the same file, but only after importing
# this one, which would be too late for the client id.
load_dotenv()

# Which addresses may sign in. An env var rather than a constant, so the door
# can be widened at deploy time without a code change.
DOMAIN_VAR = "ALLOWED_EMAIL_DOMAIN"
DEFAULT_DOMAIN = "aucklanduni.ac.nz"

# Where the signed in address and name are kept between requests. The session
# is a cookie signed with SESSION_SECRET, so the browser cannot edit it.
EMAIL_KEY = "email"
NAME_KEY = "google_name"

DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url=DISCOVERY,
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    client_kwargs={"scope": "openid email profile"},
)


def allowed_domain() -> str:
    return os.environ.get(DOMAIN_VAR) or DEFAULT_DOMAIN


def is_allowed(email: str) -> bool:
    """Whether an address may sign in.

    The domain is compared in lower case, and only after the last @, so an
    address like "someone@evil.com@example.org" cannot slip through.
    """
    domain = allowed_domain().lower()
    if not domain:
        return True
    return email.strip().lower().endswith("@" + domain)


def signed_in_email(request: Request) -> str | None:
    """The address of whoever is signed in, or None."""
    email = request.session.get(EMAIL_KEY)
    return str(email) if email else None


def signed_in_name(request: Request) -> str:
    return str(request.session.get(NAME_KEY) or "")


def sign_in(request: Request, email: str, name: str) -> None:
    request.session[EMAIL_KEY] = email.strip().lower()
    request.session[NAME_KEY] = name


def sign_out(request: Request) -> None:
    request.session.clear()
