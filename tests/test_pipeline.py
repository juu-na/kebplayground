"""What each module has to do, written as tests.

Run with:
    python -m unittest discover -s tests -t .

Every test fails with NotImplementedError until the function it covers is
written, so the file works as a checklist. The tests are in the same order as
the pipeline.

The tests check what each module promises the others, not one particular way
of writing it. Where a choice is deliberately left open, such as the cut off
distance in proximity_similarity, the test only checks that the answer sits
between 0 and 1 and moves in the right direction.
"""

import argparse
import unittest

from kebplayground import constraints, features, llm, matcher, scoring
from kebplayground.cli import build_parser
from kebplayground.models import User, pair_key


def make_user(uid: str, **overrides: object) -> User:
    """Build a user. Every field has a default, so a test sets only the ones it reads."""
    fields: dict[str, object] = {
        "id": uid,
        "major": "CS",
        "degree": "BSc",
        "year": 2,
        "age": 20,
        "mbti": "INTJ",
        "languages": frozenset({"en"}),
        "gender": "f",
        "proximity_km": 2.0,
        "free_slots": frozenset({"MON-09", "MON-10"}),
        "interests": frozenset({"chess", "hiking"}),
        "mode": "study buddy",
        "preferences": {},
    }
    fields.update(overrides)
    return User(**fields)  # type: ignore[arg-type]


# Three users, covering the cases the pipeline has to tell apart.
# ALICE and BOB could sensibly be matched. CHARLIE has nothing in common with
# either of them and wants a different mode.
ALICE = make_user("a")
BOB = make_user(
    "b",
    age=21,
    languages=frozenset({"en", "ko"}),
    proximity_km=3.0,
    free_slots=frozenset({"MON-10", "MON-11"}),
    interests=frozenset({"chess"}),
)
CHARLIE = make_user(
    "c",
    major="Law",
    age=30,
    languages=frozenset({"ko"}),
    proximity_km=20.0,
    free_slots=frozenset({"FRI-15"}),
    interests=frozenset({"tennis"}),
    mode="lunch mate",
)
USERS = [ALICE, BOB, CHARLIE]


class TestModels(unittest.TestCase):
    def test_pair_key_is_sorted(self):
        self.assertEqual(pair_key(ALICE, BOB), ("a", "b"))

    def test_pair_key_ignores_argument_order(self):
        self.assertEqual(pair_key(BOB, ALICE), pair_key(ALICE, BOB))

    def test_pair_key_accepts_bare_ids(self):
        self.assertEqual(pair_key("b", "a"), ("a", "b"))


class TestFeatures(unittest.TestCase):
    def test_every_measurement_stays_between_zero_and_one(self):
        # The shared 0.0 to 1.0 range is what lets scoring.py weigh one
        # measurement against another, so it is checked on every function and
        # every pair.
        for name, fn in features.FEATURES.items():
            for x in USERS:
                for y in USERS:
                    with self.subTest(feature=name, a=x.id, b=y.id):
                        self.assertGreaterEqual(fn(x, y), 0.0)
                        self.assertLessEqual(fn(x, y), 1.0)

    def test_timetable_overlap_is_shared_slots_over_all_slots(self):
        # One slot is shared, and there are three slots in total.
        self.assertAlmostEqual(features.timetable_overlap(ALICE, BOB), 1 / 3)

    def test_timetable_overlap_is_zero_when_no_slot_is_shared(self):
        self.assertEqual(features.timetable_overlap(ALICE, CHARLIE), 0.0)

    def test_interest_similarity_is_shared_interests_over_all_interests(self):
        # chess is shared, hiking is not.
        self.assertAlmostEqual(features.interest_similarity(ALICE, BOB), 0.5)

    def test_major_similarity_rewards_the_same_subject(self):
        self.assertEqual(features.major_similarity(ALICE, BOB), 1.0)
        self.assertEqual(features.major_similarity(ALICE, CHARLIE), 0.0)

    def test_language_similarity_needs_one_shared_language(self):
        self.assertEqual(features.language_similarity(ALICE, BOB), 1.0)
        self.assertEqual(features.language_similarity(ALICE, CHARLIE), 0.0)

    def test_closer_commutes_score_higher(self):
        # The cut-off distance is a free choice, so only the direction is
        # checked here.
        near = features.proximity_similarity(ALICE, BOB)
        far = features.proximity_similarity(ALICE, CHARLIE)
        self.assertGreater(near, far)

    def test_closer_ages_score_higher(self):
        self.assertGreater(
            features.age_similarity(ALICE, BOB),
            features.age_similarity(ALICE, CHARLIE),
        )

    def test_measure_returns_every_listed_measurement(self):
        self.assertEqual(set(features.measure(ALICE, BOB)), set(features.FEATURES))


class TestConstraints(unittest.TestCase):
    def test_a_user_cannot_be_matched_with_themselves(self):
        self.assertFalse(constraints.is_allowed(ALICE, ALICE))

    def test_two_different_modes_are_banned(self):
        self.assertFalse(constraints.is_allowed(ALICE, CHARLIE))

    def test_a_sensible_pair_is_allowed(self):
        self.assertTrue(constraints.is_allowed(ALICE, BOB))

    def test_allow_table_covers_every_pair_once(self):
        table = constraints.build_allow_table(USERS)
        self.assertEqual(len(table), 3)  # ab, ac, bc
        self.assertTrue(table[("a", "b")])
        self.assertFalse(table[("a", "c")])

    def test_allow_table_never_pairs_a_user_with_themselves(self):
        table = constraints.build_allow_table(USERS)
        self.assertFalse([key for key in table if key[0] == key[1]])


class TestScoring(unittest.TestCase):
    def test_each_mode_gives_a_weight_to_every_measurement(self):
        for mode, weights in scoring.WEIGHTS.items():
            with self.subTest(mode=mode):
                self.assertEqual(set(weights), set(features.FEATURES))

    def test_weights_add_up_to_one(self):
        # This is what keeps the final score between 0.0 and 1.0.
        for mode, weights in scoring.WEIGHTS.items():
            with self.subTest(mode=mode):
                self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_score_pair_returns_the_score_and_the_measurements(self):
        score, breakdown = scoring.score_pair(ALICE, BOB, "study buddy")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertEqual(set(breakdown), set(features.FEATURES))

    def test_an_unknown_mode_raises(self):
        # Falling back to default weights would turn a typo in the command
        # line argument into a run that looks like it worked.
        # A plain Exception is not accepted here. It would also catch the
        # NotImplementedError of the unwritten function and pass for nothing.
        with self.assertRaises((KeyError, ValueError)):
            scoring.score_pair(ALICE, BOB, "not a real mode")

    def test_the_mode_changes_the_score(self):
        # ALICE and BOB study the same subject but share little free time, so
        # study buddy is to rate them higher than lunch mate does.
        study, _ = scoring.score_pair(ALICE, BOB, "study buddy")
        lunch, _ = scoring.score_pair(ALICE, BOB, "lunch mate")
        self.assertGreater(study, lunch)

    def test_score_table_holds_only_the_allowed_pairs(self):
        # A banned pair cannot be matched whatever it scores, so scoring it
        # would be wasted work.
        allowed = {("a", "b"): True, ("a", "c"): False, ("b", "c"): False}
        table = scoring.build_score_table(USERS, "study buddy", allowed)
        self.assertEqual(set(table), {("a", "b")})


# Small tables written out by hand. The algorithms read S and H and nothing
# else, so they are tested on bare ids with no users involved.
SCORES = {("a", "b"): 0.9, ("a", "c"): 0.5, ("b", "c"): 0.4}
ALLOWED = {("a", "b"): True, ("a", "c"): True, ("b", "c"): True}


class TestMetrics(unittest.TestCase):
    def test_average_of_no_matches_is_zero(self):
        self.assertEqual(scoring.average_score([], SCORES), 0.0)

    def test_average_score(self):
        self.assertAlmostEqual(
            scoring.average_score([("a", "b"), ("a", "c")], SCORES), 0.7
        )

    def test_worst_off_reports_the_lowest_match(self):
        self.assertAlmostEqual(
            scoring.worst_off_score([("a", "b"), ("a", "c")], SCORES), 0.5
        )

    def test_unmatched_count(self):
        self.assertEqual(scoring.unmatched_count(USERS, [("a", "b")]), 1)

    def test_evaluate_returns_all_three_numbers(self):
        result = scoring.evaluate(USERS, [("a", "b")], SCORES, ALLOWED)
        self.assertEqual(set(result), {"average", "worst_off", "unmatched"})


class TestMatcher(unittest.TestCase):
    def assert_valid_matching(self, matches):
        """Nobody is matched twice, and no banned pair was used."""
        seen = [uid for pair in matches for uid in pair]
        self.assertEqual(len(seen), len(set(seen)), "a user was matched twice")
        for pair in matches:
            self.assertTrue(ALLOWED.get(tuple(sorted(pair))), f"{pair} is banned")

    def test_greedy_takes_the_best_pair_first(self):
        matches = matcher.greedy(SCORES, ALLOWED)
        self.assertIn(("a", "b"), matches)
        self.assert_valid_matching(matches)

    def test_greedy_leaves_the_spare_user_out(self):
        # Three users cannot all be put into pairs.
        self.assertEqual(len(matcher.greedy(SCORES, ALLOWED)), 1)

    def test_greedy_skips_banned_pairs(self):
        allowed = {**ALLOWED, ("a", "b"): False}
        matches = matcher.greedy(SCORES, allowed)
        self.assertNotIn(("a", "b"), matches)

    def test_gale_shapley_produces_a_valid_matching(self):
        self.assert_valid_matching(matcher.gale_shapley(SCORES, ALLOWED))

    def test_gale_shapley_gives_the_same_answer_every_time(self):
        # Without this, two algorithms cannot be compared.
        self.assertEqual(
            matcher.gale_shapley(SCORES, ALLOWED),
            matcher.gale_shapley(SCORES, ALLOWED),
        )

    def test_nobody_wants_to_swap(self):
        # This is the whole point of the algorithm. There must be no two
        # people who would both rather drop the partner they were given and
        # take each other instead.
        matches = matcher.gale_shapley(SCORES, ALLOWED)
        partner = {}
        for x, y in matches:
            partner[x] = y
            partner[y] = x
        for key, score in SCORES.items():
            if not ALLOWED.get(key):
                continue
            x, y = key
            x_prefers = partner.get(x) is None or score > SCORES[pair_key(x, partner[x])]
            y_prefers = partner.get(y) is None or score > SCORES[pair_key(y, partner[y])]
            self.assertFalse(x_prefers and y_prefers, f"{key} would rather swap")

    def test_cluster_keeps_groups_under_the_size_limit(self):
        for group in matcher.cluster(SCORES, ALLOWED, max_size=2):
            self.assertLessEqual(len(group), 2)

    def test_cluster_puts_every_user_in_exactly_one_group(self):
        groups = matcher.cluster(SCORES, ALLOWED, max_size=2)
        members = [uid for group in groups for uid in group]
        self.assertEqual(sorted(members), ["a", "b", "c"])

    def test_every_listed_algorithm_can_be_run(self):
        for name, fn in matcher.ALGORITHMS.items():
            with self.subTest(algo=name):
                self.assert_valid_matching(fn(SCORES, ALLOWED))


class TestLLM(unittest.TestCase):
    def test_the_prompt_names_both_users(self):
        breakdown = {"major": 1.0, "timetable": 0.33}
        prompt = llm.build_prompt(ALICE, BOB, 0.7, breakdown)
        self.assertIn("a", prompt)
        self.assertIn("b", prompt)

    def test_an_empty_message_is_turned_down(self):
        self.assertFalse(llm.verify("", {"major": 1.0}))

    def test_a_sensible_message_is_accepted(self):
        self.assertTrue(
            llm.verify("You both study CS and share a free hour on Monday.",
                       {"major": 1.0, "timetable": 0.33})
        )


class TestCLI(unittest.TestCase):
    def test_the_parser_is_built(self):
        self.assertIsInstance(build_parser(), argparse.ArgumentParser)

    def test_the_parser_reads_the_mode_and_the_algorithm(self):
        args = build_parser().parse_args(["--mode", "study buddy", "--algo", "greedy"])
        self.assertEqual(args.mode, "study buddy")
        self.assertEqual(args.algo, "greedy")

    def test_seed_and_count_come_back_as_numbers(self):
        args = build_parser().parse_args(["--count", "50", "--seed", "7"])
        self.assertEqual(args.count, 50)
        self.assertEqual(args.seed, 7)

    def test_explain_is_off_unless_asked_for(self):
        # The LLM call has to be asked for, so a demo cannot break on a
        # failed request.
        self.assertFalse(build_parser().parse_args([]).explain)


if __name__ == "__main__":
    unittest.main()
