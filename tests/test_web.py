"""What the web layer has to do, written as tests.

Run with:
    python -m unittest discover -s tests -t .

Every test runs against the memory store and a mocked LLM, so the suite
works offline. Google is never called: a test signs in by writing the
session the callback would have written.

The signup form, the result page states, the admin actions and the exports
are each covered.
"""

import csv
import io
import unittest
import unittest.mock

from fastapi.testclient import TestClient

from kebplayground import data, llm, pipeline, vocabulary
from kebplayground.cli import build_parser, run
from kebplayground.models import User
from kebplayground.web import auth, db, matchflow
from kebplayground.web.app import app, store

TOKEN = "test-token"
EMAIL = "ana@aucklanduni.ac.nz"

GOOD_FORM = {
    "name": "Ana",
    "age": "21",
    "major": "Computer Science",
    "year": "2",
    "mbti": "INFJ",
    "gender": "Female",
    "area": "Central",
    "mode": "friendship",
    "languages": ["Korean"],
    "interests": ["Coding"],
    "pref_genders": ["Female", "Male", "Non-binary"],
}


PARTNER = "ben@aucklanduni.ac.nz"


def add_partner(email: str = PARTNER, **overrides) -> None:
    """Store somebody who suits GOOD_FORM, and is not a made up user.

    Not seeded, so they do not answer their own match, which is what lets a
    test drive accept and decline by hand.
    """
    fields = {
        "id": email,
        "major": "Computer Science",
        "faculty": "Faculty of Science",
        "year": 2,
        "age": 22,
        "mbti": "INFJ",
        "languages": frozenset({"Korean"}),
        "gender": "Female",
        "area": "Central",
        "interests": frozenset({"Coding"}),
        "mode": "friendship",
        "preferences": {"genders": frozenset({"Female", "Male", "Non-binary"})},
    }
    fields.update(overrides)
    store.add_user(db.user_to_doc(User(**fields), "Ben", email))


def seed_store(count: int = 14, seed: int = 1) -> None:
    """Fill the store with a deterministic cohort, keyed by made up addresses."""
    import dataclasses

    for i, user in enumerate(data.generate_users(count, seed), start=1):
        email = f"demo{i}@aucklanduni.ac.nz"
        made = dataclasses.replace(user, id=email)
        store.add_user(db.user_to_doc(made, f"Demo {i}", email))


class WebTest(unittest.TestCase):
    """Shared client, a clean store and no real LLM or admin token."""

    def setUp(self) -> None:
        store.reset()
        self.client = TestClient(app)
        patches = [
            unittest.mock.patch.object(llm, "_ask_the_model", return_value=None),
            unittest.mock.patch.dict("os.environ", {"ADMIN_TOKEN": TOKEN}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def sign_in(self, email: str = EMAIL, name: str = "Ana"):
        """Sign in through the real callback, with Google's answer faked.

        Going through the route rather than writing the cookie means the
        domain check and the session write are both covered, and the cookie
        is the one the server set, so /logout can clear it.
        """
        token = {"userinfo": {"email": email, "email_verified": True, "name": name}}
        with unittest.mock.patch.object(
            auth.oauth.google,
            "authorize_access_token",
            new=unittest.mock.AsyncMock(return_value=token),
        ):
            return self.client.get("/auth/callback", follow_redirects=False)


class TestSigningIn(WebTest):
    def test_a_stranger_gets_the_sign_in_page(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Sign in with Google", page.text)
        self.assertIn("aucklanduni.ac.nz", page.text)

    def test_the_allowed_domain_is_checked(self) -> None:
        self.assertTrue(auth.is_allowed("someone@aucklanduni.ac.nz"))
        self.assertTrue(auth.is_allowed("SOMEONE@AucklandUni.AC.NZ"))
        self.assertFalse(auth.is_allowed("someone@gmail.com"))
        # The domain has to be the real one, not part of the name.
        self.assertFalse(auth.is_allowed("someone@aucklanduni.ac.nz@evil.com"))
        self.assertFalse(auth.is_allowed("someone@notaucklanduni.ac.nz"))

    def test_the_domain_can_be_widened_by_env_var(self) -> None:
        with unittest.mock.patch.dict("os.environ", {auth.DOMAIN_VAR: "example.com"}):
            self.assertTrue(auth.is_allowed("someone@example.com"))
            self.assertFalse(auth.is_allowed("someone@aucklanduni.ac.nz"))

    def test_a_personal_account_is_turned_away(self) -> None:
        answer = self.sign_in("someone@gmail.com")
        self.assertEqual(answer.status_code, 403)
        self.assertIn("Sign in with Google", self.client.get("/").text)

    def test_an_unverified_address_is_turned_away(self) -> None:
        token = {"userinfo": {"email": EMAIL, "email_verified": False, "name": "Ana"}}
        with unittest.mock.patch.object(
            auth.oauth.google,
            "authorize_access_token",
            new=unittest.mock.AsyncMock(return_value=token),
        ):
            answer = self.client.get("/auth/callback", follow_redirects=False)
        self.assertEqual(answer.status_code, 403)

    def test_a_cancelled_sign_in_goes_back_to_the_front_door(self) -> None:
        with unittest.mock.patch.object(
            auth.oauth.google,
            "authorize_access_token",
            new=unittest.mock.AsyncMock(side_effect=RuntimeError("cancelled")),
        ):
            answer = self.client.get("/auth/callback", follow_redirects=False)
        self.assertEqual(answer.status_code, 303)
        self.assertTrue(answer.headers["location"].startswith("/?error="))

    def test_signing_out_clears_the_session(self) -> None:
        self.sign_in()
        self.client.get("/logout")
        self.assertIn("Sign in with Google", self.client.get("/").text)

    def test_signup_needs_a_session(self) -> None:
        answer = self.client.post("/signup", data=GOOD_FORM, follow_redirects=False)
        self.assertEqual(answer.status_code, 303)
        self.assertEqual(answer.headers["location"], "/")
        self.assertEqual(store.list_users(), [])


class TestSignup(WebTest):
    def setUp(self) -> None:
        super().setUp()
        self.sign_in()

    def test_form_renders_with_the_registries(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Computer Science", page.text)
        self.assertIn("friendship", page.text)

    def test_the_form_shows_the_signed_in_address(self) -> None:
        self.assertIn(EMAIL, self.client.get("/").text)

    def test_signup_inserts_and_redirects(self) -> None:
        answer = self.client.post("/signup", data=GOOD_FORM, follow_redirects=False)
        self.assertEqual(answer.status_code, 303)
        self.assertEqual(answer.headers["location"], "/")
        self.assertEqual(len(store.list_users()), 1)
        doc = store.list_users()[0]
        self.assertEqual(doc["name"], "Ana")
        self.assertEqual(doc["status"], "waiting")

    def test_the_address_becomes_the_id(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)
        doc = store.list_users()[0]
        self.assertEqual(doc["id"], EMAIL)
        self.assertEqual(doc["contact"], EMAIL)

    def test_signing_in_again_finds_the_same_profile(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Kia ora, Ana", page.text)
        self.assertEqual(len(store.list_users()), 1)

    def test_signup_turns_down_an_unregistered_major(self) -> None:
        bad = dict(GOOD_FORM, major="Alchemy")
        answer = self.client.post("/signup", data=bad)
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(store.list_users(), [])

    def test_signup_turns_down_a_backwards_age_range(self) -> None:
        bad = dict(GOOD_FORM, pref_age_min="25", pref_age_max="19")
        answer = self.client.post("/signup", data=bad)
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(store.list_users(), [])

    def test_signup_keeps_what_was_typed_when_turned_down(self) -> None:
        bad = dict(GOOD_FORM, major="Alchemy")
        answer = self.client.post("/signup", data=bad)
        self.assertIn("Ana", answer.text)

    def test_signup_needs_at_least_one_gender_ticked(self) -> None:
        bad = dict(GOOD_FORM)
        bad["pref_genders"] = []
        answer = self.client.post("/signup", data=bad)
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(store.list_users(), [])

    def test_friendship_is_offered_first(self) -> None:
        page = self.client.get("/").text
        self.assertLess(page.index('value="friendship"'), page.index('value="date"'))

    def test_preferences_round_trip_through_the_store(self) -> None:
        form = dict(GOOD_FORM, pref_age_min="19", pref_age_max="25")
        form["pref_genders"] = ["Female", "Non-binary"]
        self.client.post("/signup", data=form)
        user = db.doc_to_user(store.list_users()[0])
        self.assertEqual(user.preferences["age"], (19, 25))
        self.assertEqual(user.preferences["genders"], frozenset({"Female", "Non-binary"}))


class TestTheRound(WebTest):
    """Signup, a round, and answering the match it produced."""

    def setUp(self) -> None:
        super().setUp()
        self.sign_in()

    def join(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)

    def test_without_a_session_home_shows_the_sign_in(self) -> None:
        self.client.cookies.clear()
        self.assertIn("Sign in with Google", self.client.get("/").text)

    def test_me_redirects_home(self) -> None:
        answer = self.client.get("/me", follow_redirects=False)
        self.assertEqual(answer.headers["location"], "/")

    def test_before_a_round_the_page_counts_the_pool(self) -> None:
        self.join()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("You are 1 of 10", page.text)

    def test_an_unmatched_user_goes_back_in_the_pool(self) -> None:
        self.join()
        self.client.post("/admin/run", data={"token": TOKEN})
        self.assertEqual(store.get_user(EMAIL)["status"], "waiting")
        self.assertIn("You are 1 of 10", self.client.get("/").text)

    def test_a_round_offers_a_match_with_a_place(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        matches = store.list_matches()
        self.assertGreater(len(matches), 0)
        match = matches[0]
        self.assertIn(match["place"], set(matchflow.PLACES))
        # Seeded users answer on their own, so the pair is already settled.
        self.assertEqual(match["state"], "accepted")
        for uid in (match["a"], match["b"]):
            self.assertEqual(store.get_user(uid)["status"], "accepted")
            self.assertEqual(store.get_user(uid)["match_id"], match["id"])

    def matched_pair(self) -> dict:
        """Run a round with two real users who suit each other.

        Built rather than generated, so the pair always clears the score
        floor and the test is about the answering, not the matching.
        """
        self.join()
        add_partner(PARTNER)
        self.client.post("/admin/run", data={"token": TOKEN})
        doc = store.get_user(EMAIL)
        self.assertIsNotNone(doc["match_id"])
        return store.get_match(str(doc["match_id"]))

    def test_an_offered_match_shows_accept_and_decline(self) -> None:
        self.matched_pair()
        page = self.client.get("/")
        self.assertIn("lined up", page.text)
        self.assertIn("Say yes", page.text)
        self.assertIn("Not this one", page.text)

    def test_the_reveal_shows_the_bars_and_what_is_shared(self) -> None:
        self.matched_pair()
        page = self.client.get("/").text
        # Ana and Ben share Computer Science, Coding and Korean.
        self.assertIn("You both like", page)
        self.assertIn("Coding", page)
        self.assertIn("You both speak", page)
        self.assertIn("Korean", page)
        self.assertIn("How you two line up", page)
        self.assertIn("bar-fill", page)

    def test_the_written_reason_is_kept_on_the_match(self) -> None:
        match = self.matched_pair()
        self.assertIn("Computer Science", str(match["why"]))
        self.assertIn(str(match["why"]), self.client.get("/").text)

    def test_the_reason_is_not_said_twice(self) -> None:
        # With no model the message is the written reason, so the page must
        # not print the same sentence under it.
        match = self.matched_pair()
        page = self.client.get("/").text
        self.assertEqual(match["message"], match["why"])
        self.assertEqual(page.count(str(match["why"])), 1)

    def test_a_measurement_of_zero_is_left_off_the_bars(self) -> None:
        from kebplayground.web.app import _bars

        drawn = _bars({"interests": 0.0, "major": 0.5})
        self.assertEqual([bar["label"] for bar in drawn], ["Study"])

    def test_the_bars_read_strongest_first(self) -> None:
        from kebplayground.web.app import _bars

        drawn = _bars({"age": 0.2, "interests": 0.9, "mbti": 0.5})
        self.assertEqual(
            [bar["label"] for bar in drawn], ["Interests", "Personality", "Age"]
        )

    def test_every_measurement_has_a_label(self) -> None:
        from kebplayground import features
        from kebplayground.web.app import FEATURE_LABELS

        self.assertEqual(set(FEATURE_LABELS), set(features.FEATURES))

    def test_both_accepting_says_where_to_meet(self) -> None:
        match = self.matched_pair()
        other = match["b"] if match["a"] == EMAIL else match["a"]
        store.respond_to_match(match["id"], other, "accepted")
        self.client.post("/match/respond", data={"answer": "accepted"})

        self.assertEqual(store.get_match(match["id"])["state"], "accepted")
        self.assertEqual(store.get_user(EMAIL)["status"], "accepted")
        page = self.client.get("/")
        self.assertIn("Meet ", page.text)
        self.assertIn(match["place"], page.text)

    def test_declining_puts_both_back_in_the_pool(self) -> None:
        match = self.matched_pair()
        other = match["b"] if match["a"] == EMAIL else match["a"]
        self.client.post("/match/respond", data={"answer": "declined"})

        self.assertEqual(store.get_match(match["id"])["state"], "declined")
        for uid in (EMAIL, other):
            doc = store.get_user(uid)
            self.assertEqual(doc["status"], "waiting")
            self.assertIsNone(doc["match_id"])

    def test_answering_twice_changes_nothing(self) -> None:
        match = self.matched_pair()
        self.client.post("/match/respond", data={"answer": "declined"})
        self.client.post("/match/respond", data={"answer": "accepted"})
        self.assertEqual(store.get_match(match["id"])["state"], "declined")

    def test_a_stranger_cannot_answer_a_match(self) -> None:
        match = self.matched_pair()
        self.assertIsNone(
            store.respond_to_match(match["id"], "nobody@aucklanduni.ac.nz", "declined")
        )
        self.assertEqual(store.get_match(match["id"])["state"], "offered")

    def test_pause_and_resume(self) -> None:
        self.join()
        self.client.post("/pause")
        self.assertEqual(store.get_user(EMAIL)["status"], "paused")
        self.assertEqual(store.count_waiting(), 0)
        self.assertIn("sitting this one out", self.client.get("/").text)

        self.client.post("/resume")
        self.assertEqual(store.get_user(EMAIL)["status"], "waiting")

    def test_pause_is_refused_once_a_round_has_claimed_you(self) -> None:
        self.join()
        store.claim_waiting()
        answer = self.client.post("/pause", follow_redirects=False)
        self.assertIn("too+late", answer.headers["location"])
        self.assertEqual(store.get_user(EMAIL)["status"], "matching")

    def test_the_status_fragment_matches_the_page(self) -> None:
        self.join()
        self.assertIn("You are 1 of 10", self.client.get("/me/status").text)

    def test_the_fragment_sends_a_stranger_home(self) -> None:
        self.client.cookies.clear()
        answer = self.client.get("/me/status")
        self.assertEqual(answer.headers.get("hx-redirect"), "/")


class TestProfileEdit(WebTest):
    def setUp(self) -> None:
        super().setUp()
        self.sign_in()
        self.client.post("/signup", data=GOOD_FORM)

    def test_the_form_comes_back_filled_in(self) -> None:
        page = self.client.get("/profile/edit")
        self.assertEqual(page.status_code, 200)
        self.assertIn('value="Ana"', page.text)
        self.assertIn("Your profile", page.text)

    def test_an_edit_saves_and_keeps_the_matching_fields(self) -> None:
        before = store.get_user(EMAIL)
        store.update_user(EMAIL, {"status": "paused"})

        edited = dict(GOOD_FORM, name="Ana K", age="22", mode="date")
        answer = self.client.post("/profile/edit", data=edited, follow_redirects=False)
        self.assertEqual(answer.status_code, 303)

        doc = store.get_user(EMAIL)
        self.assertEqual(doc["name"], "Ana K")
        self.assertEqual(doc["age"], 22)
        self.assertEqual(doc["mode"], "date")
        # Where they are up to is not the form's business.
        self.assertEqual(doc["status"], "paused")
        self.assertEqual(doc["created_at"], before["created_at"])

    def test_a_bad_edit_changes_nothing(self) -> None:
        answer = self.client.post("/profile/edit", data=dict(GOOD_FORM, major="Alchemy"))
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(store.get_user(EMAIL)["major"], "Computer Science")

    def test_the_area_preference_round_trips(self) -> None:
        self.client.post("/profile/edit", data=dict(GOOD_FORM, same_area_only="on"))
        user = db.doc_to_user(store.get_user(EMAIL))
        self.assertIs(user.preferences["same_area_only"], True)
        self.assertIn("checked", self.client.get("/profile/edit").text)

    def test_leaving_the_area_box_alone_leaves_the_key_out(self) -> None:
        user = db.doc_to_user(store.get_user(EMAIL))
        self.assertNotIn("same_area_only", user.preferences)


class TestRounds(WebTest):
    """When a round starts on its own."""

    def setUp(self) -> None:
        super().setUp()
        # Run the round on this thread, so a test never waits on one.
        patch = unittest.mock.patch.object(
            matchflow, "_spawn", new=lambda work: work()
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_full_pool_starts_a_round(self) -> None:
        store.set_settings({"pool_size": 4})
        seed_store(count=4, seed=3)
        matchflow.maybe_trigger(store)
        self.assertIsNotNone(store.latest_run())

    def test_a_short_pool_does_not(self) -> None:
        store.set_settings({"pool_size": 4})
        seed_store(count=3, seed=3)
        matchflow.maybe_trigger(store)
        self.assertIsNone(store.latest_run())

    def test_the_last_signup_sets_a_round_going(self) -> None:
        store.set_settings({"pool_size": 2})
        seed_store(count=1, seed=4)
        self.sign_in()
        self.client.post("/signup", data=GOOD_FORM)
        self.assertIsNotNone(store.latest_run())

    def test_lowering_the_pool_size_starts_a_round(self) -> None:
        seed_store(count=4, seed=3)
        self.assertIsNone(store.latest_run())
        self.client.post("/admin/settings", data={"token": TOKEN, "pool_size": "4"})
        self.assertIsNotNone(store.latest_run())

    def test_a_pool_size_under_two_is_refused(self) -> None:
        self.client.post("/admin/settings", data={"token": TOKEN, "pool_size": "1"})
        self.assertEqual(store.get_settings()["pool_size"], 10)

    def test_leftovers_alone_do_not_start_another_round(self) -> None:
        # Two users who cannot be matched to each other stay waiting. Without
        # the guard the run would keep starting itself forever.
        store.set_settings({"pool_size": 2})
        seed_store(count=2, seed=5)
        for doc in store.list_users():
            store.update_user(str(doc["id"]), {"mode": "friendship"})
        store.update_user(str(store.list_users()[0]["id"]), {"mode": "date"})
        matchflow.run_now(store)
        self.assertEqual(store.count_waiting(), 2)
        # One run only: a second would have been started by the re-check.
        self.assertEqual(len(store.list_matches()), 0)

    def test_a_round_left_half_done_is_swept_up(self) -> None:
        seed_store(count=3, seed=6)
        store.claim_waiting()
        self.assertEqual(store.count_waiting(), 0)
        matchflow.run_now(store)
        # Everyone was picked back up rather than being stranded.
        self.assertEqual(
            sum(1 for d in store.list_users() if d["status"] == "matching"), 0
        )

    def test_every_faculty_has_somewhere_to_meet(self) -> None:
        self.assertEqual(set(matchflow.MEETING_PLACES), set(vocabulary.FACULTIES))

    def test_a_faculty_meets_its_own_at_home(self) -> None:
        for faculty, home in matchflow.MEETING_PLACES.items():
            self.assertEqual(matchflow.place_for(faculty, faculty), home)

    def test_a_cross_faculty_pair_stays_on_the_city_campus(self) -> None:
        for a in matchflow.MEETING_PLACES:
            for b in matchflow.MEETING_PLACES:
                if a != b:
                    self.assertNotIn(matchflow.place_for(a, b), matchflow.OFF_CAMPUS)

    def test_the_places_are_the_same_whichever_way_round(self) -> None:
        for a in matchflow.MEETING_PLACES:
            for b in matchflow.MEETING_PLACES:
                self.assertEqual(matchflow.place_for(a, b), matchflow.place_for(b, a))

    def test_every_meeting_place_sits_on_the_map(self) -> None:
        self.assertLessEqual(set(matchflow.MEETING_PLACES.values()), set(matchflow.PLACES))
        self.assertLessEqual(matchflow.NEUTRAL, set(matchflow.PLACES))
        self.assertLessEqual(matchflow.OFF_CAMPUS, set(matchflow.PLACES))
        self.assertIn(matchflow.DEFAULT_PLACE, matchflow.PLACES)
        # Nothing neutral is also somebody's home, or off campus.
        self.assertFalse(matchflow.NEUTRAL & set(matchflow.MEETING_PLACES.values()))
        self.assertFalse(matchflow.NEUTRAL & matchflow.OFF_CAMPUS)

    def test_settings_round_trip_and_reset_to_the_default(self) -> None:
        store.set_settings({"pool_size": 6})
        self.assertEqual(store.get_settings()["pool_size"], 6)
        store.reset()
        self.assertEqual(store.get_settings()["pool_size"], 10)

    def test_reset_clears_matches_too(self) -> None:
        add_partner(PARTNER)
        add_partner("cara@aucklanduni.ac.nz")
        matchflow.run_now(store)
        self.assertGreater(len(store.list_matches()), 0)
        store.reset()
        self.assertEqual(store.list_matches(), [])
        self.assertIsNone(store.latest_run())


class TestAdmin(WebTest):
    def test_the_token_is_checked(self) -> None:
        self.assertEqual(self.client.get("/admin").status_code, 403)
        self.assertEqual(self.client.get("/admin?token=wrong").status_code, 403)
        self.assertEqual(self.client.get(f"/admin?token={TOKEN}").status_code, 200)

    def test_a_missing_env_token_locks_admin_out(self) -> None:
        with unittest.mock.patch.dict("os.environ", {"ADMIN_TOKEN": ""}):
            self.assertEqual(self.client.get("/admin?token=").status_code, 403)

    def test_a_run_writes_a_run_document(self) -> None:
        seed_store()
        answer = self.client.post(
            "/admin/run", data={"token": TOKEN}, follow_redirects=False
        )
        self.assertEqual(answer.status_code, 303)
        run_doc = store.latest_run()
        assert run_doc is not None
        self.assertGreater(len(run_doc["result"]["matches"]), 0)

    def test_seed_fills_the_store(self) -> None:
        self.client.post("/admin/seed", data={"token": TOKEN, "count": "8"})
        self.assertEqual(len(store.list_users()), 8)

    def test_reset_empties_everything(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        self.client.post("/admin/reset", data={"token": TOKEN})
        self.assertEqual(store.list_users(), [])
        self.assertIsNone(store.latest_run())

    def test_the_exports_parse_as_csv(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        users = list(csv.DictReader(io.StringIO(
            self.client.get(f"/admin/export.csv?token={TOKEN}").text
        )))
        self.assertEqual(len(users), 14)
        self.assertIn("name", users[0])
        matches = list(csv.DictReader(io.StringIO(
            self.client.get(f"/admin/matches.csv?token={TOKEN}").text
        )))
        self.assertGreater(len(matches), 0)
        self.assertIn("a_name", matches[0])


class TestMessagesAtOnce(unittest.TestCase):
    """The LLM calls in a round go out together, and share one cache file."""

    def test_the_breakdown_comes_without_asking_for_a_message(self) -> None:
        result = pipeline.run_matching(data.generate_users(20, 1))
        for entry in result["matches"]:
            self.assertIn("breakdown", entry)
            self.assertNotIn("message", entry)

    def test_every_answer_reaches_the_cache(self) -> None:
        """A slow model is what makes the writes overlap.

        Without the lock, each worker would write back the copy of the file
        it read before its own call, and the last one would win.
        """
        import json
        import tempfile
        import time
        from pathlib import Path

        users = [
            make_pair_user("a@x.nz"), make_pair_user("b@x.nz"),
            make_pair_user("c@x.nz"), make_pair_user("d@x.nz"),
        ]

        def slow_answer(a, b, score, mode, breakdown):
            time.sleep(0.05)
            return f"{a.id} and {b.id} were matched on interests. Say hi!"

        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "llm.json"
            with unittest.mock.patch.object(llm, "_ask_the_model", slow_answer):
                result = pipeline.run_matching(users, explain=True, cache=cache)

            pairs = len(result["matches"])
            self.assertGreater(pairs, 1)
            self.assertEqual(len(json.loads(cache.read_text())), pairs)


def make_pair_user(uid: str) -> User:
    """A user who suits every other user this helper makes."""
    return User(
        id=uid,
        major="Computer Science",
        faculty="Faculty of Science",
        year=2,
        age=21,
        mbti="INFJ",
        languages=frozenset({"Korean"}),
        gender="Female",
        area="Central",
        interests=frozenset({"Coding", "Hiking"}),
        mode="friendship",
        preferences={},
    )


class TestPipelineSeam(unittest.TestCase):
    def test_cli_run_and_run_matching_agree(self) -> None:
        args = build_parser().parse_args(["--count", "20", "--seed", "1"])
        self.assertEqual(run(args), pipeline.run_matching(data.generate_users(20, 1)))


if __name__ == "__main__":
    unittest.main()
