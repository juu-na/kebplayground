"""Where the web layer keeps its state.

Two backends behind one interface: Firestore when deployed, memory for tests
and offline work. A user is stored as a flat document holding the same
encoded fields the CSV uses, plus the web-only name and contact, which never
enter the User dataclass.
"""

import os
from datetime import datetime, timezone

from .. import data
from ..models import User

USERS = "users"
RUNS = "runs"


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
        "created_at": datetime.now(timezone.utc).isoformat(),
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


class MemoryStore:
    """State held in the process. Used by the tests and offline dev."""

    def __init__(self) -> None:
        self._users: dict[str, dict[str, object]] = {}
        self._runs: list[dict[str, object]] = []

    def add_user(self, doc: dict[str, object]) -> None:
        self._users[str(doc["id"])] = doc

    def get_user(self, user_id: str) -> dict[str, object] | None:
        return self._users.get(user_id)

    def list_users(self) -> list[dict[str, object]]:
        return sorted(self._users.values(), key=lambda doc: str(doc["created_at"]))

    def save_run(self, result: dict[str, object]) -> None:
        self._runs.append(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
        )

    def latest_run(self) -> dict[str, object] | None:
        return self._runs[-1] if self._runs else None

    def reset(self) -> None:
        self._users.clear()
        self._runs.clear()


class FirestoreStore:
    """State held in Firestore, so it survives redeploys and scale to zero."""

    def __init__(self) -> None:
        # Imported here so the memory backend works without the package.
        from google.cloud import firestore

        self._client = firestore.Client()

    def add_user(self, doc: dict[str, object]) -> None:
        self._client.collection(USERS).document(str(doc["id"])).set(doc)

    def get_user(self, user_id: str) -> dict[str, object] | None:
        snapshot = self._client.collection(USERS).document(user_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_users(self) -> list[dict[str, object]]:
        docs = [snapshot.to_dict() for snapshot in self._client.collection(USERS).stream()]
        return sorted(docs, key=lambda doc: str(doc["created_at"]))

    def save_run(self, result: dict[str, object]) -> None:
        self._client.collection(RUNS).document().set(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
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

    def reset(self) -> None:
        for name in (USERS, RUNS):
            for snapshot in self._client.collection(name).stream():
                snapshot.reference.delete()


def make_store() -> MemoryStore | FirestoreStore:
    """Pick the backend from the STORE env var. Memory unless told otherwise."""
    if os.environ.get("STORE") == "firestore":
        return FirestoreStore()
    return MemoryStore()
