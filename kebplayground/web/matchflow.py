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

# Roughly where each spot sits on a line across the campuses, running from
# the law end through the middle of the city campus and out to Grafton. The
# numbers only mean distance relative to each other, so that a pair from two
# faculties can be sent somewhere between the two.
PLACES = {
    "the Davis Library": 0,
    "the Arts Building": 2,
    "the OGGB": 3,
    "the General Library": 3,
    "Kate Edger": 3,
    "the Leech study space": 4,
    "Hiwa Recreation Centre": 4,
    "the Science Centre": 5,
    "the Grafton campus": 8,
}

# The spots that are nobody's home faculty. A pair from two faculties is
# sent to one of these where there is a choice, so that neither of them is
# the one made to travel to the other's building.
NEUTRAL = frozenset({"the General Library", "Kate Edger", "Hiwa Recreation Centre"})

# Where a faculty meets its own. A test checks every faculty is named here.
MEETING_PLACES = {
    "Auckland Law School": "the Davis Library",
    "Faculty of Arts and Education": "the Arts Building",
    "Business School": "the OGGB",
    "Faculty of Engineering and Design": "the Leech study space",
    "Faculty of Science": "the Science Centre",
    "Faculty of Medical and Health Sciences": "the Grafton campus",
}
DEFAULT_PLACE = "the General Library"

# Which spot wins a tie is decided by where it appears above, so the answer
# is the same every time rather than depending on how a dict happens to
# iterate.
_ORDER = {name: index for index, name in enumerate(PLACES)}

# Made up users answer their match on their own, so that a rehearsal with
# nobody else around still reaches the page that says where to meet.
SEED_MARK = "demo"


def place_for(faculty_a: str, faculty_b: str) -> str:
    """Where to send a pair.

    Two people from the same faculty meet at their own building. Otherwise
    aim for the halfway point between the two buildings, preferring a spot
    that belongs to neither of them when several are equally close.
    """
    home_a = MEETING_PLACES.get(faculty_a, DEFAULT_PLACE)
    home_b = MEETING_PLACES.get(faculty_b, DEFAULT_PLACE)
    if faculty_a == faculty_b:
        return home_a

    middle = (PLACES[home_a] + PLACES[home_b]) / 2

    def nearness(item: tuple[str, int]) -> tuple[float, bool, int]:
        name, where = item
        # Closest to the middle first, then whichever belongs to nobody,
        # then whichever was named first.
        return (abs(where - middle), name not in NEUTRAL, _ORDER[name])

    return min(PLACES.items(), key=nearness)[0]


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
