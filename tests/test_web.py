"""What the web layer has to do, written as tests.

Run with:
    python -m unittest discover -s tests -t .

Every test runs against the memory store and a mocked LLM, so the suite
works offline. The signup form, the three result page states, the admin
actions and the exports are each covered.
"""

import csv
import io
import unittest
import unittest.mock

from fastapi.testclient import TestClient

from kebplayground import data, llm, pipeline
from kebplayground.cli import build_parser, run
from kebplayground.web import db
from kebplayground.web.app import app, store

TOKEN = "test-token"

GOOD_FORM = {
    "name": "Ana",
    "contact": "@ana",
    "age": "21",
    "major": "Computer Science",
    "year": "2",
    "mbti": "INFJ",
    "gender": "Female",
    "area": "Central",
    "mode": "friendship",
    "languages": ["Korean"],
    "interests": ["Coding"],
}


def seed_store(count: int = 14, seed: int = 1) -> None:
    """Fill the store with a deterministic cohort."""
    for i, user in enumerate(data.generate_users(count, seed), start=1):
        store.add_user(db.user_to_doc(user, f"Demo {i}", f"demo{i}@example.com"))


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


class TestSignup(WebTest):
    def test_form_renders_with_the_registries(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Computer Science", page.text)
        self.assertIn("friendship", page.text)

    def test_signup_inserts_and_redirects(self) -> None:
        answer = self.client.post("/signup", data=GOOD_FORM, follow_redirects=False)
        self.assertEqual(answer.status_code, 303)
        self.assertEqual(len(store.list_users()), 1)
        doc = store.list_users()[0]
        self.assertEqual(doc["name"], "Ana")
        self.assertTrue(answer.headers["location"].endswith(str(doc["id"])))
        self.assertIn("kb_user", answer.headers.get("set-cookie", ""))

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

    def test_preferences_round_trip_through_the_store(self) -> None:
        form = dict(GOOD_FORM, pref_age_min="19", pref_age_max="25")
        form["pref_genders"] = ["Female", "Non-binary"]
        self.client.post("/signup", data=form)
        user = db.doc_to_user(store.list_users()[0])
        self.assertEqual(user.preferences["age"], (19, 25))
        self.assertEqual(user.preferences["genders"], frozenset({"Female", "Non-binary"}))


class TestResultPages(WebTest):
    def signup_id(self) -> str:
        answer = self.client.post("/signup", data=GOOD_FORM, follow_redirects=False)
        return answer.headers["location"].rsplit("/", 1)[1]

    def test_unknown_id_is_a_404(self) -> None:
        self.assertEqual(self.client.get("/me/nope").status_code, 404)

    def test_before_any_run_the_page_waits(self) -> None:
        page = self.client.get(f"/me/{self.signup_id()}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("has not run yet", page.text)

    def test_after_a_run_an_unmatched_user_keeps_waiting(self) -> None:
        user_id = self.signup_id()
        self.client.post("/admin/run", data={"token": TOKEN})
        page = self.client.get(f"/me/{user_id}")
        self.assertIn("Not matched this round", page.text)

    def test_a_matched_user_sees_the_partner(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        run_doc = store.latest_run()
        assert run_doc is not None
        entry = run_doc["result"]["matches"][0]
        page = self.client.get(f"/me/{entry['a']}")
        self.assertIn("meet", page.text)
        self.assertIn("Reach them at", page.text)
        # The mocked LLM answers None, so the message is the plain fallback.
        self.assertIn("You two were matched on", page.text)

    def test_the_status_partial_redirects_once_matched(self) -> None:
        seed_store()
        self.client.post("/admin/run", data={"token": TOKEN})
        run_doc = store.latest_run()
        assert run_doc is not None
        entry = run_doc["result"]["matches"][0]
        answer = self.client.get(f"/me/{entry['a']}/status")
        self.assertEqual(answer.headers.get("hx-redirect"), f"/me/{entry['a']}")

    def test_the_cookie_brings_a_lost_tab_back(self) -> None:
        user_id = self.signup_id()
        answer = self.client.get("/me", follow_redirects=False)
        self.assertEqual(answer.headers["location"], f"/me/{user_id}")


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
