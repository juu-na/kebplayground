"""Running a round, and deciding when one should start.

A round claims everybody waiting, matches them, and turns each pair into a
match the two people can answer. Rounds start either because an organiser
pressed the button or because the pool reached the size the settings name.

Only one round runs at a time, which run_lock enforces. The service runs as
a single instance, so a lock in the process is enough.
"""

import math
import os
import threading
from pathlib import Path

from .. import pipeline
from . import db

# Held for the whole of a round. Taken without blocking everywhere, since a
# second round starting while one is going is something to skip, not queue.
run_lock = threading.Lock()

# Where each spot sits on the city campus, read off the campus map as grid
# coordinates. Only the distances between them mean anything, so the units
# and which way up they are do not matter.
PLACES = {
    "the Davis Library": (5.8, 0.0),
    "the General Library": (1.6, 5.7),
    "the Arts Building": (5.5, 6.5),
    "Kate Edger": (1.9, 7.8),
    "Hiwa Recreation Centre": (1.0, 8.6),
    "the OGGB": (4.7, 9.1),
    "the Science Centre": (0.0, 9.9),
    "the Leech study space": (1.7, 10.0),
    "the Grafton campus": (2.5, 29.2),
}

# Away from the middle of the city campus. A pair from two faculties is
# always sent somewhere on the city campus instead, however the distances
# come out, since one of them would otherwise be walking to another campus.
OFF_CAMPUS = frozenset({"the Davis Library", "the Grafton campus"})

# The spots that are nobody's home faculty. A pair from two faculties is
# sent to one of these in preference to either of their own buildings, since
# neither side then has to walk into the other's.
NEUTRAL = frozenset({"the General Library", "Kate Edger", "Hiwa Recreation Centre"})

# How much further than the nearest spot a neutral one may be and still be
# worth it. Past that the walk costs more than the neutral ground is worth,
# and the nearest spot wins even though it belongs to one of them.
#
# Tuned rather than picked: below about 1.6 the Leech study space starts
# turning up for pairs with no reason to know where it is, and above about
# 1.8 every pair ends up on neutral ground whatever the walk.
NEUTRAL_DETOUR = 1.7

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

# Which spot wins a tie nothing else settles is decided by where it appears
# above, so the answer is the same every time rather than depending on how a
# dict happens to iterate.
_ORDER = {name: index for index, name in enumerate(PLACES)}

# Made up users answer their match on their own, so that a rehearsal with
# nobody else around still reaches the page that says where to meet.
SEED_MARK = "demo"


def place_for(faculty_a: str, faculty_b: str) -> str:
    """Where to send a pair.

    Two people from the same faculty meet at their own building, wherever
    that is. Otherwise aim for the halfway point between the two buildings
    and take the nearest spot to it, keeping to the city campus and
    preferring somewhere that belongs to neither of them.
    """
    home_a = MEETING_PLACES.get(faculty_a, DEFAULT_PLACE)
    home_b = MEETING_PLACES.get(faculty_b, DEFAULT_PLACE)
    if faculty_a == faculty_b:
        return home_a

    (ax, ay), (bx, by) = PLACES[home_a], PLACES[home_b]
    middle = ((ax + bx) / 2, (ay + by) / 2)

    on_campus = [
        (name, math.dist(spot, middle))
        for name, spot in PLACES.items()
        if name not in OFF_CAMPUS
    ]
    closest = min(distance for _, distance in on_campus)

    def nearness(item: tuple[str, float]) -> tuple:
        name, distance = item
        worth_it = name in NEUTRAL and distance <= closest + NEUTRAL_DETOUR
        # Somewhere belonging to nobody first, as long as it is not a walk,
        # then closest, then whichever was named first.
        return (not worth_it, distance, _ORDER[name])

    return min(on_campus, key=nearness)[0]


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
