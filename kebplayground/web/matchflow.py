"""Running a round, and deciding when one should start.

A round claims everybody waiting, matches them, and turns each pair into a
match the two people can answer. Rounds start either because an organiser
pressed the button or because the pool reached the size the settings name.

Only one round runs at a time, which run_lock enforces. The service runs as
a single instance, so a lock in the process is enough.
"""

import os
import threading
from pathlib import Path

from .. import pipeline
from . import db

# Held for the whole of a round. Taken without blocking everywhere, since a
# second round starting while one is going is something to skip, not queue.
run_lock = threading.Lock()

# Where a pair is told to meet. Same faculty sends them to their own
# building; anywhere else meets at the landmark both sides know. A test
# checks every faculty is named here.
MEETING_PLACES = {
    "Faculty of Engineering and Design": "the Leech Building",
    "Business School": "the OGGB",
    "Auckland Law School": "the OGGB",
    "Faculty of Science": "the Science Centre",
    "Faculty of Arts and Education": "the Arts Building",
    "Faculty of Medical and Health Sciences": "the General Library",
}
DEFAULT_PLACE = "the General Library"

# Made up users answer their match on their own, so that a rehearsal with
# nobody else around still reaches the page that says where to meet.
SEED_MARK = "demo"


def place_for(faculty_a: str, faculty_b: str) -> str:
    if faculty_a == faculty_b:
        return MEETING_PLACES.get(faculty_a, DEFAULT_PLACE)
    return DEFAULT_PLACE


def pool_size(store) -> int:
    return int(store.get_settings().get("pool_size", 10))


def is_seeded(doc: dict[str, object]) -> bool:
    """Whether this is a made up user rather than somebody who signed in."""
    return str(doc.get("id", "")).startswith(SEED_MARK)


def _spawn(work) -> None:
    """Start a round off the request thread.

    Its own function so a test can run the round inline instead, which keeps
    the tests from depending on when a thread happens to finish.
    """
    threading.Thread(target=work, daemon=True).start()


def run_now(store) -> bool:
    """Do one round. Answers False when another one was already going."""
    if not run_lock.acquire(blocking=False):
        return False
    try:
        # Nothing is running, so anyone still marked as matching is left over
        # from a round that was cut off part way. Put them back in the pool.
        store.reclaim_matching()

        claimed = store.claim_waiting()
        if not claimed:
            return True

        users = [db.doc_to_user(doc) for doc in claimed]
        cache = Path(os.environ.get("LLM_CACHE_PATH", ".cache/llm.json"))
        result = pipeline.run_matching(users, explain=True, cache=cache)

        by_id = {str(doc["id"]): doc for doc in claimed}
        matched: set[str] = set()

        for entry in result["matches"]:  # type: ignore[index]
            a, b = str(entry["a"]), str(entry["b"])
            match = db.new_match(
                a=a,
                b=b,
                score=float(entry["score"]),  # type: ignore[arg-type]
                mode=str(entry["mode"]),
                message=str(entry.get("message") or ""),
                breakdown=entry.get("breakdown") or {},  # type: ignore[arg-type]
                place=place_for(
                    str(by_id[a]["faculty"]), str(by_id[b]["faculty"])
                ),
            )
            match_id = store.save_match(match)
            for uid in (a, b):
                store.update_user(uid, {"status": "offered", "match_id": match_id})
                matched.add(uid)
            for uid in (a, b):
                if is_seeded(by_id[uid]):
                    store.respond_to_match(match_id, uid, "accepted")

        left_over = [uid for uid in by_id if uid not in matched]
        for uid in left_over:
            store.update_user(uid, {"status": "waiting", "match_id": None})

        store.save_run(result)
    finally:
        run_lock.release()

    # Somebody may have signed up while the round was going, and their signup
    # found the lock held. Only start again for a genuinely new face: running
    # the same leftovers again would give the same answer forever.
    if _has_new_waiter(store, set(left_over)):
        maybe_trigger(store)
    return True


def _has_new_waiter(store, left_over: set[str]) -> bool:
    waiting = {
        str(doc["id"]) for doc in store.list_users() if doc.get("status") == "waiting"
    }
    return bool(waiting - left_over)


def maybe_trigger(store) -> None:
    """Start a round if the pool is big enough and nothing is running."""
    if run_lock.locked():
        return
    if store.count_waiting() < pool_size(store):
        return
    _spawn(lambda: run_now(store))
