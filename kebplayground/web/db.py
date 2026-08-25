"""Where the web layer keeps its state.

Two backends behind one interface: Firestore when deployed, memory for tests
and offline work. A user is stored as a flat document holding the same
encoded fields the CSV uses, plus the web-only name, contact and match_id,
which never enter the User dataclass.

Three collections. Users are the people. Matches are the pairs a run made,
and are what a participant's page reads. Runs hold the whole pipeline result
for the admin summary and the CSV export.

Everything that moves a user between statuses goes through this module, so
that the Firestore backend can do it in a transaction and the memory one
under a lock. Nothing above should read a status, change it and write it
back.
"""

import os
import threading
import uuid
from datetime import datetime, timezone

from .. import data
from ..models import User

USERS = "users"
RUNS = "runs"
MATCHES = "matches"
SETTINGS = "settings"

# The single settings document, and what it holds before anyone edits it.
SETTINGS_DOC = "app"
DEFAULT_SETTINGS: dict[str, object] = {"pool_size": 10}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_to_doc(user: User, name: str, contact: str) -> dict[str, object]:
    """Encode a user the same way the CSV does, with the web-only fields."""
    return {
        "id": user.id,
        "major": user.major,
        "faculty": user.faculty,
        "year": user.year,
        "age": user.age,
        "mbti": user.mbti,
        "languages": data.SEPARATOR.join(sorted(user.languages)),
        "gender": user.gender,
        "area": user.area,
        "interests": data.SEPARATOR.join(sorted(user.interests)),
        "mode": user.mode,
        "preferences": data._encode_preferences(user.preferences),
        "status": user.status,
        "name": name,
        "contact": contact,
        # The match this user is answering, if any. Cleared when the match is
        # turned down, so a user page never has to search the matches.
        "match_id": None,
        "created_at": now(),
    }


def doc_to_user(doc: dict[str, object]) -> User:
    return User(
        id=str(doc["id"]),
        major=str(doc["major"]),
        faculty=str(doc["faculty"]),
        year=int(doc["year"]),  # type: ignore[arg-type]
        age=int(doc["age"]),  # type: ignore[arg-type]
        mbti=str(doc["mbti"]),
        languages=data._parse_frozenset(str(doc["languages"])),
        gender=str(doc["gender"]),
        area=str(doc["area"]),
        interests=data._parse_frozenset(str(doc["interests"])),
        mode=data._parse_mode(str(doc["mode"])),
        preferences=data._decode_preferences(str(doc["preferences"])),
        status=str(doc.get("status") or "waiting"),
    )


def profile_fields(doc: dict[str, object]) -> dict[str, object]:
    """The part of a user document a profile edit is allowed to replace.

    Everything else, meaning status, match_id and created_at, belongs to the
    matching and has to survive an edit.
    """
    keep = {"status", "match_id", "created_at"}
    return {key: value for key, value in doc.items() if key not in keep}


def new_match(
    a: str, b: str, score: float, mode: str, suggestion: str, why: str,
    breakdown: dict[str, float], place: str,
) -> dict[str, object]:
    """One pair a run made, before either side has answered."""
    return {
        "a": a,
        "b": b,
        "score": score,
        "mode": mode,
        # One thing these two could go and do, from the model.
        "suggestion": suggestion,
        # What the two actually have in common, worked out without the model.
        # Written down at the time, so it still reads true after either of
        # them edits their profile.
        "why": why,
        "breakdown": breakdown,
        "place": place,
        # offered until both sides say yes, or either says no.
        "state": "offered",
        "a_response": None,
        "b_response": None,
        "created_at": now(),
    }


def _settled(match: dict[str, object]) -> str:
    """What a match's state becomes, given the answers so far."""
    answers = (match.get("a_response"), match.get("b_response"))
    if "declined" in answers:
        return "declined"
    if all(answer == "accepted" for answer in answers):
        return "accepted"
    return "offered"


class MemoryStore:
    """State held in the process. Used by the tests and offline dev.

    A lock stands in for Firestore's transactions. A run asks for several
    messages at once and signups arrive while a run is going, so the reads
    and writes that move people between statuses cannot be left open.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: dict[str, dict[str, object]] = {}
        self._runs: list[dict[str, object]] = []
        self._matches: dict[str, dict[str, object]] = {}
        self._settings: dict[str, object] = dict(DEFAULT_SETTINGS)

    # --- users ---

    def add_user(self, doc: dict[str, object]) -> None:
        with self._lock:
            self._users[str(doc["id"])] = dict(doc)

    def update_user(self, user_id: str, fields: dict[str, object]) -> None:
        with self._lock:
            doc = self._users.get(user_id)
            if doc is not None:
                doc.update(fields)

    def get_user(self, user_id: str) -> dict[str, object] | None:
        with self._lock:
            doc = self._users.get(user_id)
            return dict(doc) if doc else None

    def list_users(self) -> list[dict[str, object]]:
        with self._lock:
            docs = [dict(doc) for doc in self._users.values()]
        return sorted(docs, key=lambda doc: str(doc["created_at"]))

    def count_waiting(self) -> int:
        with self._lock:
            return sum(1 for doc in self._users.values() if doc.get("status") == "waiting")

    def set_status_if(self, user_id: str, expected: str, new: str) -> bool:
        """Move a user between statuses only if they are where we thought.

        Answers False when they are not, which is how pause finds out that a
        run claimed the user first.
        """
        with self._lock:
            doc = self._users.get(user_id)
            if doc is None or doc.get("status") != expected:
                return False
            doc["status"] = new
            return True

    def claim_waiting(self) -> list[dict[str, object]]:
        """Take everyone waiting into a run.

        Returns the documents as they were, still saying waiting, because
        that is what pipeline.run_matching filters on. Anybody signing up
        after this belongs to the next run.
        """
        with self._lock:
            claimed = []
            for doc in self._users.values():
                if doc.get("status") == "waiting":
                    claimed.append(dict(doc))
                    doc["status"] = "matching"
            return claimed

    def reclaim_matching(self) -> None:
        """Put anyone left mid-run back in the pool.

        Only called when no run is going, so anyone still saying matching is
        left over from a run that was cut off.
        """
        with self._lock:
            for doc in self._users.values():
                if doc.get("status") == "matching":
                    doc["status"] = "waiting"

    # --- matches ---

    def save_match(self, match: dict[str, object]) -> str:
        match_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._matches[match_id] = dict(match, id=match_id)
        return match_id

    def get_match(self, match_id: str) -> dict[str, object] | None:
        with self._lock:
            match = self._matches.get(match_id)
            return dict(match) if match else None

    def list_matches(self) -> list[dict[str, object]]:
        with self._lock:
            matches = [dict(match) for match in self._matches.values()]
        return sorted(matches, key=lambda match: str(match["created_at"]))

    def respond_to_match(self, match_id: str, user_id: str, response: str) -> str | None:
        """Record one side's answer and move both users accordingly.

        Returns the match's new state, or None when there is nothing to
        answer. Saying the same thing twice changes nothing.
        """
        with self._lock:
            match = self._matches.get(match_id)
            if match is None or match["state"] != "offered":
                return None
            side = "a_response" if match["a"] == user_id else (
                "b_response" if match["b"] == user_id else None
            )
            if side is None:
                return None

            match[side] = response
            state = _settled(match)
            match["state"] = state

            for uid in (str(match["a"]), str(match["b"])):
                doc = self._users.get(uid)
                if doc is None:
                    continue
                if state == "declined":
                    # Both go back in the pool. The refusal is remembered on
                    # the match, not on either person.
                    doc["status"] = "waiting"
                    doc["match_id"] = None
                elif state == "accepted":
                    doc["status"] = "accepted"
            return state

    # --- runs and settings ---

    def save_run(self, result: dict[str, object]) -> None:
        with self._lock:
            self._runs.append({"created_at": now(), "result": result})

    def latest_run(self) -> dict[str, object] | None:
        with self._lock:
            return dict(self._runs[-1]) if self._runs else None

    def get_settings(self) -> dict[str, object]:
        with self._lock:
            return dict(self._settings)

    def set_settings(self, fields: dict[str, object]) -> None:
        with self._lock:
            self._settings.update(fields)

    def reset(self) -> None:
        with self._lock:
            self._users.clear()
            self._runs.clear()
            self._matches.clear()
            self._settings = dict(DEFAULT_SETTINGS)


class FirestoreStore:
    """State held in Firestore, so it survives redeploys and scale to zero."""

    def __init__(self) -> None:
        # Imported here so the memory backend works without the package.
        from google.cloud import firestore

        self._client = firestore.Client()

    # --- users ---

    def add_user(self, doc: dict[str, object]) -> None:
        self._client.collection(USERS).document(str(doc["id"])).set(doc)

    def update_user(self, user_id: str, fields: dict[str, object]) -> None:
        self._client.collection(USERS).document(user_id).update(fields)

    def get_user(self, user_id: str) -> dict[str, object] | None:
        snapshot = self._client.collection(USERS).document(user_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_users(self) -> list[dict[str, object]]:
        docs = [snapshot.to_dict() for snapshot in self._client.collection(USERS).stream()]
        return sorted(docs, key=lambda doc: str(doc["created_at"]))

    def _with_status(self, status: str):
        return self._client.collection(USERS).where("status", "==", status)

    def count_waiting(self) -> int:
        return sum(1 for _ in self._with_status("waiting").stream())

    def set_status_if(self, user_id: str, expected: str, new: str) -> bool:
        from google.cloud import firestore

        reference = self._client.collection(USERS).document(user_id)

        @firestore.transactional
        def swap(transaction) -> bool:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists or snapshot.to_dict().get("status") != expected:
                return False
            transaction.update(reference, {"status": new})
            return True

        return swap(self._client.transaction())

    def claim_waiting(self) -> list[dict[str, object]]:
        from google.cloud import firestore

        query = self._with_status("waiting")

        @firestore.transactional
        def claim(transaction) -> list[dict[str, object]]:
            # Built inside the transaction: it can be retried, and anything
            # gathered on an earlier attempt would be stale.
            claimed = []
            references = []
            for snapshot in query.stream(transaction=transaction):
                claimed.append(snapshot.to_dict())
                references.append(snapshot.reference)
            # Every read has to come before every write in a transaction.
            for reference in references:
                transaction.update(reference, {"status": "matching"})
            return claimed

        return claim(self._client.transaction())

    def reclaim_matching(self) -> None:
        for snapshot in self._with_status("matching").stream():
            snapshot.reference.update({"status": "waiting"})

    # --- matches ---

    def save_match(self, match: dict[str, object]) -> str:
        reference = self._client.collection(MATCHES).document()
        reference.set(dict(match, id=reference.id))
        return reference.id

    def get_match(self, match_id: str) -> dict[str, object] | None:
        snapshot = self._client.collection(MATCHES).document(match_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_matches(self) -> list[dict[str, object]]:
        matches = [s.to_dict() for s in self._client.collection(MATCHES).stream()]
        return sorted(matches, key=lambda match: str(match["created_at"]))

    def respond_to_match(self, match_id: str, user_id: str, response: str) -> str | None:
        from google.cloud import firestore

        match_ref = self._client.collection(MATCHES).document(match_id)

        @firestore.transactional
        def answer(transaction) -> str | None:
            snapshot = match_ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            match = snapshot.to_dict()
            if match["state"] != "offered":
                return None
            side = "a_response" if match["a"] == user_id else (
                "b_response" if match["b"] == user_id else None
            )
            if side is None:
                return None

            match[side] = response
            state = _settled(match)

            user_refs = [
                self._client.collection(USERS).document(str(match[key]))
                for key in ("a", "b")
            ]
            transaction.update(match_ref, {side: response, "state": state})
            for reference in user_refs:
                if state == "declined":
                    transaction.update(reference, {"status": "waiting", "match_id": None})
                elif state == "accepted":
                    transaction.update(reference, {"status": "accepted"})
            return state

        return answer(self._client.transaction())

    # --- runs and settings ---

    def save_run(self, result: dict[str, object]) -> None:
        self._client.collection(RUNS).document().set(
            {"created_at": now(), "result": result}
        )

    def latest_run(self) -> dict[str, object] | None:
        from google.cloud import firestore

        found = (
            self._client.collection(RUNS)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        for snapshot in found:
            return snapshot.to_dict()
        return None

    def get_settings(self) -> dict[str, object]:
        snapshot = self._client.collection(SETTINGS).document(SETTINGS_DOC).get()
        if not snapshot.exists:
            return dict(DEFAULT_SETTINGS)
        return {**DEFAULT_SETTINGS, **snapshot.to_dict()}

    def set_settings(self, fields: dict[str, object]) -> None:
        self._client.collection(SETTINGS).document(SETTINGS_DOC).set(fields, merge=True)

    def reset(self) -> None:
        for name in (USERS, RUNS, MATCHES, SETTINGS):
            for snapshot in self._client.collection(name).stream():
                snapshot.reference.delete()


def make_store() -> MemoryStore | FirestoreStore:
    """Pick the backend from the STORE env var. Memory unless told otherwise."""
    if os.environ.get("STORE") == "firestore":
        return FirestoreStore()
    return MemoryStore()
