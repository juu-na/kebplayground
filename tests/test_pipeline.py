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
import itertools
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kebplayground import constraints, data, features, llm, matcher, scoring, vocabulary
from kebplayground.cli import build_parser
from kebplayground.models import User, pair_key


def make_user(uid: str, **overrides: object) -> User:
    """Build a user. Every field has a default, so a test sets only the ones it reads."""
    fields: dict[str, object] = {
        "id": uid,
        "major": "Computer Science",
        "faculty": "Faculty of Science",
        "year": 2,
        "age": 20,
        "mbti": "INTJ",
        "languages": frozenset({"Korean"}),
        "gender": "Female",
        "proximity_km": 2.0,
        "free_slots": frozenset({"MON_MORNING", "MON_AFTERNOON"}),
        "interests": frozenset({"Chess", "Hiking"}),
        "mode": "study buddy",
        "preferences": {},
    }
    fields.update(overrides)
    return User(**fields)  # type: ignore[arg-type]


# Three users, covering the cases the pipeline has to tell apart.
# ALICE and BOB could sensibly be matched. CHARLIE wants a different mode, is
# free at a different time, and studies at the other end of the teachiness
# scale, so the two of them are the furthest apart the registry allows.
ALICE = make_user("a")
BOB = make_user(
    "b",
    age=21,
    languages=frozenset({"Korean", "Mandarin"}),
    proximity_km=3.0,
    free_slots=frozenset({"MON_AFTERNOON", "MON_EVENING"}),
    interests=frozenset({"Chess"}),
)
CHARLIE = make_user(
    "c",
    major="Law",
    faculty="Auckland Law School",
    age=30,
    languages=frozenset({"Mandarin"}),
    proximity_km=20.0,
    free_slots=frozenset({"FRI_EVENING"}),
    interests=frozenset({"Tennis"}),
    mode="lunch mate",
)
USERS = [ALICE, BOB, CHARLIE]


def one_of(registered: frozenset) -> frozenset:
    """One value out of a registry, so a fixture does not go stale when the
    registry is edited."""
    return frozenset(sorted(registered)[:1])


# One preference of every kind, used to check that each key is accepted and
# that no key has been added to the schema without a test covering it.
EVERY_PREFERENCE: dict[str, object] = {
    "genders": one_of(vocabulary.GENDERS),
    "age": (19, 24),
    "majors": one_of(vocabulary.ALL_MAJORS),
    "faculties": one_of(vocabulary.FACULTIES),
    "years": one_of(vocabulary.YEARS),
    "mbti": one_of(vocabulary.MBTIS),
    "languages": one_of(vocabulary.LANGUAGES),
    "interests": one_of(vocabulary.INTERESTS),
    "same_area_only": True,
}


class TestVocabulary(unittest.TestCase):
    def test_every_major_belongs_to_one_faculty(self):
        # Two faculties claiming the same major would make faculty_of depend
        # on the order the dict happens to be written in.
        seen: list[str] = []
        for majors in vocabulary.MAJORS.values():
            seen.extend(majors)
        self.assertEqual(sorted(seen), sorted(set(seen)))

    def test_all_majors_is_every_group_together(self):
        self.assertEqual(len(vocabulary.ALL_MAJORS), sum(map(len, vocabulary.MAJORS.values())))

    def test_faculty_of_finds_the_faculty(self):
        for faculty, majors in vocabulary.MAJORS.items():
            for major in majors:
                with self.subTest(major=major):
                    self.assertEqual(vocabulary.faculty_of(major), faculty)

    def test_faculty_of_turns_down_an_unknown_major(self):
        with self.assertRaisesRegex(ValueError, "Basket Weaving"):
            vocabulary.faculty_of("Basket Weaving")

    def test_english_is_not_a_listed_language(self):
        # Everyone is taken to share English, so preferring it would rule
        # nobody out.
        self.assertNotIn("English", vocabulary.LANGUAGES)

    def test_a_preference_is_either_hard_or_soft(self):
        self.assertFalse(set(vocabulary.HARD_PREFERENCES) & set(vocabulary.SOFT_PREFERENCES))

    def test_there_is_a_slot_for_every_day_and_block(self):
        self.assertEqual(
            len(vocabulary.SLOTS), len(vocabulary.DAYS) * len(vocabulary.BLOCKS)
        )
        self.assertIn("MON_MORNING", vocabulary.SLOTS)

    def test_stating_no_preference_is_allowed(self):
        # The default for the field, so this has to stay allowed.
        self.assertIsNone(vocabulary.validate_preferences({}))

    def test_every_key_in_the_schema_is_accepted(self):
        # Adding a key to the schema without adding it here fails on the
        # first assertion rather than going untested.
        self.assertEqual(set(EVERY_PREFERENCE), set(vocabulary.PREFERENCE_KEYS))
        self.assertIsNone(vocabulary.validate_preferences(EVERY_PREFERENCE))

    def test_an_unknown_key_is_turned_down(self):
        with self.assertRaisesRegex(ValueError, "star sign"):
            vocabulary.validate_preferences({"star sign": frozenset({"Leo"})})

    def test_a_value_outside_the_registry_is_turned_down(self):
        with self.assertRaisesRegex(ValueError, "Klingon"):
            vocabulary.validate_preferences({"languages": frozenset({"Klingon"})})

    def test_an_empty_set_is_turned_down(self):
        # Leaving the key out is the one way of saying there is no
        # restriction. An empty set would otherwise read as either that or
        # as ruling everybody out.
        with self.assertRaisesRegex(ValueError, "genders"):
            vocabulary.validate_preferences({"genders": frozenset()})

    def test_a_set_is_needed_where_a_set_is_asked_for(self):
        with self.assertRaisesRegex(ValueError, "genders"):
            vocabulary.validate_preferences({"genders": "Female"})

    def test_an_age_range_that_ends_before_it_starts_is_turned_down(self):
        with self.assertRaisesRegex(ValueError, "age"):
            vocabulary.validate_preferences({"age": (30, 20)})

    def test_an_age_range_takes_two_whole_numbers(self):
        # bool is a subclass of int, so True would otherwise be read as 1.
        with self.assertRaisesRegex(ValueError, "age"):
            vocabulary.validate_preferences({"age": (True, 24)})
        with self.assertRaisesRegex(ValueError, "age"):
            vocabulary.validate_preferences({"age": (19,)})

    def test_same_area_only_takes_true_or_false(self):
        with self.assertRaisesRegex(ValueError, "same_area_only"):
            vocabulary.validate_preferences({"same_area_only": "yes"})


class TestModels(unittest.TestCase):
    def test_pair_key_is_sorted(self):
        self.assertEqual(pair_key(ALICE, BOB), ("a", "b"))

    def test_pair_key_ignores_argument_order(self):
        self.assertEqual(pair_key(BOB, ALICE), pair_key(ALICE, BOB))

    def test_pair_key_accepts_bare_ids(self):
        self.assertEqual(pair_key("b", "a"), ("a", "b"))


class TestData(unittest.TestCase):
    def test_generate_users_makes_the_number_asked_for(self):
        self.assertEqual(len(data.generate_users(10, seed=1)), 10)

    def test_the_same_seed_gives_the_same_users(self):
        # Without this, two runs of the same algorithm cannot be compared.
        self.assertEqual(
            data.generate_users(10, seed=1), data.generate_users(10, seed=1)
        )

    def test_the_same_seed_gives_the_same_users_in_a_new_process(self):
        # A set of strings iterates in an order that depends on hash
        # randomisation, which changes between processes. Generating from one
        # directly would break the seed without any single run noticing.
        script = (
            "from kebplayground import data;"
            "print([(u.major, sorted(u.interests)) for u in data.generate_users(5, seed=1)])"
        )
        runs = set()
        for hash_seed in ("0", "1"):
            finished = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
                env={**os.environ, "PYTHONHASHSEED": hash_seed},
            )
            self.assertEqual(finished.returncode, 0, finished.stderr)
            runs.add(finished.stdout)
        self.assertEqual(len(runs), 1)

    def test_made_up_users_only_use_registered_values(self):
        for user in data.generate_users(30, seed=1):
            with self.subTest(user=user.id):
                self.assertIn(user.faculty, vocabulary.FACULTIES)
                self.assertIn(user.major, vocabulary.MAJORS[user.faculty])
                self.assertIn(user.year, vocabulary.YEARS)
                self.assertIn(user.mbti, vocabulary.MBTIS)
                self.assertIn(user.gender, vocabulary.GENDERS)
                self.assertIn(user.mode, vocabulary.MODES)
                self.assertEqual(user.languages - vocabulary.LANGUAGES, frozenset())
                self.assertEqual(user.free_slots - vocabulary.SLOTS, frozenset())
                self.assertEqual(user.interests - vocabulary.INTERESTS, frozenset())

    def test_saved_users_can_be_read_back(self):
        # The two functions are the only pair that has to agree on the CSV
        # format, so they are tested together.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            data.save_users(USERS, path)
            self.assertEqual(data.load_users(path), USERS)

    def test_a_missing_column_is_reported(self):
        # The error names the column, rather than the run failing later in
        # a module that has nothing to do with the file.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            # Omit exactly one required column so the failure is deterministic.
            path.write_text(
                "id,major,year,age,mbti,languages,gender,proximity_km,free_slots,interests,mode\n"
                "a,CS,2,20,INTJ,en,f,2.0,MON-09,chess,study buddy\n"
            )
            with self.assertRaisesRegex((KeyError, ValueError), r"\bfaculty\b"):
                data.load_users(path)


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
        # Chess is shared, Hiking is not.
        self.assertAlmostEqual(features.interest_similarity(ALICE, BOB), 0.5)

    def test_major_similarity_rewards_the_same_subject(self):
        self.assertEqual(features.major_similarity(ALICE, BOB), 1.0)
        self.assertLess(
            features.major_similarity(ALICE, CHARLIE),
            features.major_similarity(ALICE, BOB),
        )

    def test_each_shared_language_scores_higher_than_the_last(self):
        spoken = ["Korean", "Mandarin", "Japanese"]
        polyglot = make_user("p", languages=frozenset(spoken))
        # Nothing listed in common, then one shared language, then two, then
        # three. The first is English on its own.
        climbing = [
            features.language_similarity(
                polyglot, make_user("q", languages=frozenset(spoken[:shared]))
            )
            for shared in range(len(spoken) + 1)
        ]
        self.assertEqual(climbing, sorted(climbing))
        self.assertEqual(len(set(climbing)), len(climbing))
        self.assertEqual(climbing[-1], 1.0)

    def test_sharing_no_listed_language_still_scores_above_zero(self):
        # vocabulary.LANGUAGES leaves English out because everyone is taken
        # to speak it, so two users with nothing listed in common can still
        # talk to each other.
        both_ways = features.language_similarity(ALICE, CHARLIE)
        self.assertGreater(both_ways, 0.0)
        self.assertLess(both_ways, features.language_similarity(ALICE, BOB))

    def test_a_long_shared_list_cannot_beat_the_top_of_the_range(self):
        many = frozenset(sorted(vocabulary.LANGUAGES)[:8])
        both = make_user("m", languages=many), make_user("n", languages=many)
        self.assertEqual(features.language_similarity(*both), 1.0)

    def test_every_faculty_has_a_teachiness_score(self):
        # A faculty missing here makes major_similarity raise on anyone
        # studying in it, which only shows up once users are made up.
        self.assertEqual(set(features.FACULTY_TECHINESS), vocabulary.FACULTIES)

    def test_measuring_made_up_users_stays_between_zero_and_one(self):
        # The three users written out above cannot catch a value data.py
        # produces that features.py does not know about.
        users = data.generate_users(15, seed=1)
        for x, y in itertools.combinations(users, 2):
            for name, value in features.measure(x, y).items():
                with self.subTest(feature=name, a=x.id, b=y.id):
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)

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
    def test_every_mode_on_offer_has_weights(self):
        # cli.py builds its --mode choices out of WEIGHTS, so a mode that is
        # missing here cannot be asked for at all.
        self.assertEqual(set(scoring.WEIGHTS), vocabulary.MODES)

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
        args = build_parser().parse_args(["--mode", "study buddy", "--algo", "greedy", "--count", "50", "--seed", "7"])
        self.assertEqual(args.count, 50)
        self.assertEqual(args.seed, 7)

    def test_explain_is_off_unless_asked_for(self):
        # The LLM call has to be asked for, so a demo cannot break on a
        # failed request.
        self.assertFalse(build_parser().parse_args(["--mode", "study buddy", "--algo", "greedy"]).explain)


if __name__ == "__main__":
    unittest.main()
