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

from kebplayground import data, llm, pipeline
from kebplayground.cli import build_parser, run
from kebplayground.web import auth, db
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
        self.assertEqual(answer.headers["location"], "/me")
        self.assertEqual(len(store.list_users()), 1)
        doc = store.list_users()[0]
        self.assertEqual(doc["name"], "Ana")

    def test_the_address_becomes_the_id(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)
        doc = store.list_users()[0]
        self.assertEqual(doc["id"], EMAIL)
        self.assertEqual(doc["contact"], EMAIL)

    def test_signing_in_again_finds_the_same_profile(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)
        answer = self.client.get("/", follow_redirects=False)
        self.assertEqual(answer.status_code, 303)
        self.assertEqual(answer.headers["location"], "/me")
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


class TestResultPages(WebTest):
    def setUp(self) -> None:
        super().setUp()
        self.sign_in()

    def test_without_a_session_me_goes_to_the_front_door(self) -> None:
        self.client.cookies.clear()
        answer = self.client.get("/me", follow_redirects=False)
        self.assertEqual(answer.headers["location"], "/")

    def test_signed_in_without_a_profile_goes_back_to_the_form(self) -> None:
        answer = self.client.get("/me", follow_redirects=False)
        self.assertEqual(answer.headers["location"], "/")

    def test_before_any_run_the_page_waits(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)
        page = self.client.get("/me")
        self.assertEqual(page.status_code, 200)
        self.assertIn("has not run yet", page.text)

    def test_after_a_run_an_unmatched_user_keeps_waiting(self) -> None:
        self.client.post("/signup", data=GOOD_FORM)
        self.client.post("/admin/run", data={"token": TOKEN})
        page = self.client.get("/me")
        self.assertIn("Not matched this round", page.text)

    def test_a_matched_user_sees_the_partner(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        run_doc = store.latest_run()
        assert run_doc is not None
        entry = run_doc["result"]["matches"][0]
        self.sign_in(str(entry["a"]))
        page = self.client.get("/me")
        self.assertIn("meet", page.text)
        self.assertIn("Email them at", page.text)
        # The mocked LLM answers None, so the message is the plain fallback.
        self.assertIn("You two were matched on", page.text)

    def test_the_status_partial_redirects_once_matched(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        run_doc = store.latest_run()
        assert run_doc is not None
        self.sign_in(str(run_doc["result"]["matches"][0]["a"]))
        answer = self.client.get("/me/status")
        self.assertEqual(answer.headers.get("hx-redirect"), "/me")

    def test_nobody_can_read_another_persons_match(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        run_doc = store.latest_run()
        assert run_doc is not None
        other = str(run_doc["result"]["matches"][0]["a"])
        # Signed in as somebody with no profile, asking for nothing in
        # particular: there is no id to pass any more, so the only page on
        # offer is the signed in user's own.
        self.sign_in("stranger@aucklanduni.ac.nz")
        answer = self.client.get("/me", follow_redirects=False)
        self.assertEqual(answer.headers["location"], "/")
        self.assertEqual(self.client.get(f"/me/{other}").status_code, 404)


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


class TestPipelineSeam(unittest.TestCase):
    def test_cli_run_and_run_matching_agree(self) -> None:
        args = build_parser().parse_args(["--count", "20", "--seed", "1"])
        self.assertEqual(run(args), pipeline.run_matching(data.generate_users(20, 1)))


if __name__ == "__main__":
    unittest.main()
