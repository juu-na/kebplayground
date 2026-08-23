"""What each module has to do, written as tests.

Run with:
    python -m unittest discover -s tests -t .

Every test fails with NotImplementedError until the function it covers is
written, so the file works as a checklist. The tests are in the same order as
the pipeline.

The tests check what each module promises the others, not one particular way
of writing it. Where a choice is deliberately left open, such as the cut off
gap in age_similarity, the test only checks that the answer sits between 0
and 1 and moves in the right direction.
"""

import argparse
import csv
import itertools
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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
        "area": "Central",
        "interests": frozenset({"Coding", "Hiking"}),
        "modes": frozenset({"friendship"}),
        "preferences": {},
        "status": "waiting",
    }
    fields.update(overrides)
    return User(**fields)  # type: ignore[arg-type]


# Three users, covering the cases the pipeline has to tell apart.
# ALICE and BOB share friendship and could sensibly be matched. CHARLIE only
# wants a date, so shares nothing with ALICE, and studies at the other end of
# the teachiness scale.
ALICE = make_user("a")
BOB = make_user(
    "b",
    age=21,
    languages=frozenset({"Korean", "Mandarin"}),
    interests=frozenset({"Coding"}),
    modes=frozenset({"friendship", "date"}),
)
CHARLIE = make_user(
    "c",
    major="Law",
    faculty="Auckland Law School",
    age=30,
    languages=frozenset({"Mandarin"}),
    area="South",
    interests=frozenset({"Running"}),
    modes=frozenset({"date"}),
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
            "print([(u.major, sorted(u.interests), sorted(u.preferences)) "
            "for u in data.generate_users(5, seed=1)])"
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
                self.assertIn(user.area, vocabulary.AREAS)
                self.assertIn(user.status, vocabulary.STATUSES)
                self.assertTrue(user.modes, "a user has to want something")
                self.assertEqual(user.modes - vocabulary.MODES, frozenset())
                self.assertEqual(user.languages - vocabulary.LANGUAGES, frozenset())
                self.assertEqual(user.interests - vocabulary.INTERESTS, frozenset())

    def test_saved_users_can_be_read_back(self):
        # The two functions are the only pair that has to agree on the CSV
        # format, so they are tested together.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            data.save_users(USERS, path)
            self.assertEqual(data.load_users(path), USERS)

    def test_made_up_preferences_are_ones_the_schema_allows(self):
        for user in data.generate_users(50, seed=1):
            with self.subTest(user=user.id):
                self.assertIsNone(vocabulary.validate_preferences(user.preferences))

    def test_made_up_users_range_from_no_preferences_to_several(self):
        # A run where everybody takes anyone would never reach the ban rules,
        # and one where everybody is specific would ban almost every pair.
        stated = [len(user.preferences) for user in data.generate_users(200, seed=1)]
        self.assertEqual(min(stated), 0)
        self.assertGreaterEqual(max(stated), 4)

    def test_every_preference_in_the_schema_can_be_made_up(self):
        # A key added to the schema and not to data.py would never appear in
        # a made up user, so nothing downstream would ever meet it.
        buildable = set(data._PREFERENCE_VALUES) | {vocabulary.AGE, vocabulary.SAME_AREA_ONLY}
        self.assertEqual(buildable, set(vocabulary.PREFERENCE_KEYS))

    def test_preferences_survive_being_saved_and_read_back(self):
        # JSON has no set and no pair, so the column has to rebuild both. A
        # user whose preferences come back as lists is not the user that was
        # saved, and every module compares users by value.
        picky = make_user("p", preferences=EVERY_PREFERENCE)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            data.save_users([picky], path)
            self.assertEqual(data.load_users(path), [picky])

    def test_a_preference_in_the_file_is_checked_on_the_way_in(self):
        # A file is the one way a preference arrives without going through
        # the code that built it, so it is the one place worth checking.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            data.save_users([make_user("p")], path)
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
            rows[0]["preferences"] = '{"languages": ["Klingon"]}'
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=data.WRITTEN_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "Klingon"):
                data.load_users(path)

    def test_a_missing_column_is_reported(self):
        # The error names the column, rather than the run failing later in
        # a module that has nothing to do with the file.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            # Omit exactly one required column so the failure is deterministic.
            path.write_text(
                "id,major,year,age,mbti,languages,gender,area,free_slots,interests,mode\n"
                "a,Law,2,20,INTJ,Korean,Female,Central,MON_MORNING,Coding,study buddy\n"
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

    def test_interest_similarity_is_shared_interests_over_all_interests(self):
        # Coding is shared, Hiking is not.
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

    def test_the_year_beside_yours_is_half_as_close_as_your_own(self):
        same = features.year_similarity(make_user("x", year=2), make_user("y", year=2))
        beside = features.year_similarity(make_user("x", year=2), make_user("y", year=3))
        far = features.year_similarity(make_user("x", year=1), make_user("y", year=4))
        self.assertEqual((same, beside, far), (1.0, 0.5, 0.0))

    def test_area_is_left_out_unless_somebody_asked_for_it(self):
        # Where a person lives says nothing about whether they get on, so it
        # only counts when it was asked for and met.
        asked = make_user("x", area="South", preferences={"same_area_only": True})
        same = make_user("y", area="South")
        elsewhere = make_user("z", area="North")
        self.assertEqual(features.view(asked, same)["area"], 1.0)
        self.assertNotIn("area", features.view(asked, elsewhere))
        self.assertNotIn("area", features.view(same, asked))

    def test_asking_for_the_same_area_and_missing_costs_nothing(self):
        # The whole point of leaving it out rather than scoring it 0.0.
        asked = make_user("x", area="South", preferences={"same_area_only": True})
        silent = make_user("y", area="South", preferences={})
        elsewhere = make_user("z", area="North")
        self.assertEqual(
            scoring.score_pair(asked, elsewhere)[0],
            scoring.score_pair(silent, elsewhere)[0],
        )

    def test_same_area_only_set_to_false_is_not_asking(self):
        declined = make_user("x", area="South", preferences={"same_area_only": False})
        self.assertNotIn("area", features.view(declined, make_user("y", area="South")))

    def test_a_missed_preference_falls_back_rather_than_being_punished(self):
        # The bump only ever lifts. Missing it leaves the usual rule alone.
        picky = make_user("x", preferences={"mbti": frozenset({"ENFP"})})
        plain = make_user("y")
        self.assertEqual(
            features.view(picky, plain)["mbti"], features.view(plain, picky)["mbti"]
        )

    def test_asking_about_major_and_faculty_needs_both(self):
        # majors and faculties both speak for the same measurement, so
        # satisfying one of them is not enough to earn the lift.
        picky = make_user(
            "x",
            preferences={
                "majors": frozenset({"Law"}),
                "faculties": frozenset({"Auckland Law School"}),
            },
        )
        both = make_user("y", major="Law", faculty="Auckland Law School")
        # Deliberately inconsistent: the right major in the wrong faculty.
        half = make_user("z", major="Law", faculty="Faculty of Science")
        self.assertEqual(features.view(picky, both)["major"], 1.0)
        self.assertLess(features.view(picky, half)["major"], 1.0)

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

    def test_closer_ages_score_higher(self):
        self.assertGreater(
            features.age_similarity(ALICE, BOB),
            features.age_similarity(ALICE, CHARLIE),
        )

    def test_the_best_possible_personality_pair_scores_one(self):
        # Same S/N, opposite E/I, same T/F, opposite J/P.
        self.assertEqual(features.mbti_similarity(*self.two_types("INTJ", "ENTP")), 1.0)

    def test_the_worst_possible_personality_pair_scores_zero(self):
        self.assertEqual(features.mbti_similarity(*self.two_types("INTJ", "ISFJ")), 0.0)

    def test_two_of_the_same_type_are_not_the_best_pair(self):
        # E/I and J/P reward opposites, so the same type scores below the
        # complementary one. This is the rule rather than an oversight.
        same = features.mbti_similarity(*self.two_types("INTJ", "INTJ"))
        opposite = features.mbti_similarity(*self.two_types("INTJ", "ENTP"))
        self.assertLess(same, opposite)

    def test_sensing_and_intuition_counts_double(self):
        # Breaking S/N costs twice what breaking T/F costs, which is what
        # makes it the letter that matters most.
        best = features.mbti_similarity(*self.two_types("INTJ", "ENTP"))
        without_sn = features.mbti_similarity(*self.two_types("INTJ", "ESTP"))
        without_tf = features.mbti_similarity(*self.two_types("INTJ", "ENFP"))
        self.assertAlmostEqual(best - without_sn, 2 * (best - without_tf))

    def test_personality_reads_the_same_either_way_round(self):
        a, b = self.two_types("INTJ", "ESFP")
        self.assertEqual(
            features.mbti_similarity(a, b), features.mbti_similarity(b, a)
        )

    @staticmethod
    def two_types(one: str, other: str) -> tuple[User, User]:
        """Two users who differ only in personality type."""
        return make_user("x", mbti=one), make_user("y", mbti=other)

    def test_measure_returns_every_listed_measurement(self):
        self.assertEqual(set(features.measure(ALICE, BOB)), set(features.FEATURES))


# One soft preference of each kind that ALICE does not meet, worked out from
# the registry rather than written down, so it stays unmet whatever is added
# to vocabulary.py later.
UNMET_SOFT_PREFERENCES: dict[str, object] = {
    "majors": one_of(vocabulary.ALL_MAJORS - {ALICE.major}),
    "faculties": one_of(vocabulary.FACULTIES - {ALICE.faculty}),
    "years": one_of(vocabulary.YEARS - {ALICE.year}),
    "mbti": one_of(vocabulary.MBTIS - {ALICE.mbti}),
    "languages": one_of(vocabulary.LANGUAGES - ALICE.languages),
    "interests": one_of(vocabulary.INTERESTS - ALICE.interests),
    # Held against a user living somewhere other than ALICE does.
    "same_area_only": True,
}


class TestConstraints(unittest.TestCase):
    # Each test below changes one thing about a pair that would otherwise be
    # allowed. A rule that is missing from is_allowed then fails its own
    # test, rather than being covered by whichever other rule the same pair
    # happens to break.

    def test_a_sensible_pair_is_allowed(self):
        self.assertTrue(constraints.is_allowed(ALICE, BOB))

    def test_a_user_cannot_be_matched_with_themselves(self):
        self.assertFalse(constraints.is_allowed(ALICE, ALICE))

    def test_two_users_with_the_same_details_are_still_two_users(self):
        # The rule is about the id. Two users who happen to agree on every
        # other field are a real pair, and a good one.
        twin = make_user("d")
        self.assertTrue(constraints.is_allowed(ALICE, twin))

    def test_the_same_id_is_the_same_user_however_the_details_differ(self):
        # A file holding one id twice is how this arrives. Comparing whole
        # users instead of ids would let the pair through, since the two
        # differ on everything except the one field that matters.
        same_id = make_user("a", age=30, mbti="ENFP", area="South")
        self.assertFalse(constraints.is_allowed(ALICE, same_id))

    def test_wanting_no_connection_in_common_is_banned(self):
        dater = make_user("d", modes=frozenset({"date"}))
        self.assertFalse(constraints.is_allowed(ALICE, dater))

    def test_one_shared_connection_is_enough(self):
        # BOB is open to both, ALICE only to friendship.
        self.assertTrue(constraints.is_allowed(ALICE, BOB))

    def test_a_gender_preference_rules_the_other_out(self):
        picky = make_user("d", preferences={"genders": frozenset({"Non-binary"})})
        self.assertFalse(constraints.is_allowed(picky, ALICE))

    def test_a_gender_preference_holds_whichever_way_round_the_pair_comes(self):
        # A rule read off the first user only would pass the test above and
        # let this one through.
        picky = make_user("d", preferences={"genders": frozenset({"Non-binary"})})
        self.assertFalse(constraints.is_allowed(ALICE, picky))

    def test_an_age_preference_rules_the_other_out(self):
        picky = make_user("d", preferences={"age": (25, 30)})
        self.assertFalse(constraints.is_allowed(picky, ALICE))

    def test_an_age_preference_holds_whichever_way_round_the_pair_comes(self):
        picky = make_user("d", preferences={"age": (25, 30)})
        self.assertFalse(constraints.is_allowed(ALICE, picky))

    def test_the_ends_of_an_age_range_are_included(self):
        exact = make_user("d", preferences={"age": (ALICE.age, ALICE.age)})
        self.assertTrue(constraints.is_allowed(exact, ALICE))

    def test_a_preference_that_is_met_allows_the_pair(self):
        # Stating a preference bans nobody on its own.
        happy = make_user(
            "d", preferences={"genders": frozenset({ALICE.gender}), "age": (18, 25)}
        )
        self.assertTrue(constraints.is_allowed(happy, ALICE))

    def test_every_hard_preference_is_one_is_allowed_reads(self):
        # is_allowed names the two it checks. A key added to
        # HARD_PREFERENCES and not read there would ban nobody.
        self.assertEqual(set(vocabulary.HARD_PREFERENCES), {"genders", "age"})

    def test_a_soft_preference_never_bans_a_pair(self):
        # The soft keys move the score in scoring.py. Reading them here would
        # ban pairs that are a worse match rather than an impossible one.
        self.assertEqual(set(UNMET_SOFT_PREFERENCES), set(vocabulary.SOFT_PREFERENCES))
        for key, value in UNMET_SOFT_PREFERENCES.items():
            with self.subTest(preference=key):
                fussy = make_user("d", area="South", preferences={key: value})
                self.assertTrue(constraints.is_allowed(fussy, ALICE))

    def test_the_allow_table_covers_every_pair_once(self):
        table = constraints.build_allow_table(USERS)
        self.assertEqual(len(table), 3)  # ab, ac, bc
        self.assertTrue(table[("a", "b")])   # both want friendship
        self.assertFalse(table[("a", "c")])  # friendship against date
        self.assertTrue(table[("b", "c")])   # both want a date

    def test_the_allow_table_holds_one_entry_for_every_pair(self):
        users = data.generate_users(12, seed=1)
        self.assertEqual(len(constraints.build_allow_table(users)), 12 * 11 // 2)

    def test_the_allow_table_never_pairs_a_user_with_themselves(self):
        table = constraints.build_allow_table(USERS)
        self.assertFalse([key for key in table if key[0] == key[1]])

    def test_the_allow_table_is_keyed_the_way_pair_key_is(self):
        # Everything reading H looks a pair up through pair_key, so a table
        # keyed any other way cannot be read at all.
        table = constraints.build_allow_table(USERS)
        for x, y in itertools.combinations(USERS, 2):
            with self.subTest(pair=(x.id, y.id)):
                self.assertIn(pair_key(y, x), table)

    def test_the_allow_table_agrees_with_is_allowed(self):
        # The table is the only version anything downstream sees, so the two
        # going out of step would be invisible until a banned pair matched.
        users = data.generate_users(12, seed=1)
        table = constraints.build_allow_table(users)
        for x, y in itertools.combinations(users, 2):
            with self.subTest(pair=(x.id, y.id)):
                self.assertEqual(table[pair_key(x, y)], constraints.is_allowed(x, y))


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

    def test_score_pair_returns_the_score_the_mode_and_the_measurements(self):
        score, mode, breakdown = scoring.score_pair(ALICE, BOB)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertIn(mode, ALICE.modes & BOB.modes)
        # Area is only measured when somebody asked for it, so it may be out.
        self.assertLessEqual(set(breakdown), set(features.FEATURES))

    def test_score_pair_turns_down_a_pair_wanting_nothing_in_common(self):
        # H should have banned it long before here.
        with self.assertRaises(ValueError):
            scoring.score_pair(ALICE, make_user("d", modes=frozenset({"date"})))

    def test_a_pair_is_scored_by_whichever_side_likes_it_less(self):
        # picky gets INTJ lifted to 1.0 looking at plain. plain asked for
        # nothing, so their view is the usual rule, and that is the one the
        # pair keeps. Stating the preference changes the pair not at all.
        picky = make_user("d", preferences={"mbti": frozenset({"INTJ"})})
        plain = make_user("e")
        lifted = scoring.score_pair(picky, plain)[0]
        neither = scoring.score_pair(plain, make_user("f"))[0]
        self.assertEqual(lifted, neither)

    def test_a_preference_lifts_the_side_that_asked(self):
        # The same bump seen from the asking side alone, where it does show.
        picky = make_user("d", preferences={"mbti": frozenset({"INTJ"})})
        plain = make_user("e")
        self.assertEqual(features.view(picky, plain)["mbti"], 1.0)
        self.assertLess(features.view(plain, picky)["mbti"], 1.0)

    def test_score_table_holds_only_the_allowed_pairs(self):
        # A banned pair cannot be matched whatever it scores, so scoring it
        # would be wasted work.
        allowed = {("a", "b"): True, ("a", "c"): False, ("b", "c"): False}
        table, modes, live = scoring.build_score_table(USERS, allowed, floor=0.0)
        self.assertEqual(set(table), {("a", "b")})
        self.assertEqual(set(modes), {("a", "b")})

    def test_a_pair_under_the_floor_is_left_out_of_both_tables(self):
        allowed = {("a", "b"): True, ("a", "c"): False, ("b", "c"): False}
        table, _, live = scoring.build_score_table(USERS, allowed, floor=1.01)
        self.assertEqual(table, {})
        self.assertFalse(live[("a", "b")])

    def test_the_table_that_went_in_is_left_alone(self):
        allowed = {("a", "b"): True, ("a", "c"): False, ("b", "c"): False}
        scoring.build_score_table(USERS, allowed, floor=1.01)
        self.assertTrue(allowed[("a", "b")], "build_score_table edited its argument")


# Small tables written out by hand. The algorithms read S and H and nothing
# else, so they are tested on bare ids with no users involved.
SCORES = {("a", "b"): 0.9, ("a", "c"): 0.5, ("b", "c"): 0.4}
ALLOWED = {("a", "b"): True, ("a", "c"): True, ("b", "c"): True}

# Four ids, chosen so that taking the best pair first and looking after the
# worst off user first come out differently.
FOUR = {
    ("a", "b"): 0.9,
    ("a", "c"): 0.5,
    ("b", "d"): 0.5,
    ("c", "d"): 0.1,
    ("a", "d"): 0.0,
    ("b", "c"): 0.0,
}
FOUR_ALLOWED = {pair: True for pair in FOUR}


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

    def test_evaluate_reports_per_mode_and_lists_who_is_waiting(self):
        modes = {("a", "b"): "friendship"}
        result = scoring.evaluate(USERS, [("a", "b")], SCORES, modes, ALLOWED)
        self.assertEqual(set(result), {"modes", "waiting"})
        self.assertEqual(set(result["modes"]), set(scoring.WEIGHTS))
        self.assertEqual(result["modes"]["friendship"]["pairs"], 1)
        self.assertEqual(result["modes"]["date"]["pairs"], 0)
        # Waiting is not a failure, so c is listed rather than counted against.
        self.assertEqual(result["waiting"], ["c"])

    def test_evaluate_turns_down_a_match_naming_a_stranger(self):
        with self.assertRaisesRegex(ValueError, "ghost"):
            scoring.unmatched_count(USERS, [("a", "ghost")])


def made_up_tables(count: int = 30, seed: int = 2, floor: float = 0.0):
    """Users, S and H, built the way cli.py builds them.

    The floor defaults to nothing here, because a test about the matcher
    wants a table with pairs in it rather than the handful that clear the
    real floor.
    """
    users = data.generate_users(count, seed=seed)
    allowed = constraints.build_allow_table(users)
    scores, _, live = scoring.build_score_table(users, allowed, floor)
    return users, scores, live


class TestMatcher(unittest.TestCase):
    def assert_valid_matching(self, matches, allowed=None):
        """Nobody is matched twice, and no banned pair was used."""
        allowed = ALLOWED if allowed is None else allowed
        seen = [uid for pair in matches for uid in pair]
        self.assertEqual(len(seen), len(set(seen)), "a user was matched twice")
        for pair in matches:
            self.assertTrue(allowed.get(tuple(sorted(pair))), f"{pair} is banned")

    def assert_nobody_wants_to_swap(self, matches, scores, allowed):
        """No two people would both rather drop the partner they were given
        and take each other instead."""
        partner = {}
        for x, y in matches:
            partner[x] = y
            partner[y] = x
        for key, score in scores.items():
            if not allowed.get(key):
                continue
            x, y = key
            x_prefers = partner.get(x) is None or score > scores[pair_key(x, partner[x])]
            y_prefers = partner.get(y) is None or score > scores[pair_key(y, partner[y])]
            self.assertFalse(x_prefers and y_prefers, f"{key} would rather swap")

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

    def test_greedy_leaves_nobody_wanting_to_swap(self):
        # Both halves of a pair read the same score, so everybody agrees
        # which pairs are good, and the best pair left has to be taken.
        # Taking it and repeating is what greedy does.
        self.assert_nobody_wants_to_swap(matcher.greedy(SCORES, ALLOWED), SCORES, ALLOWED)

    def test_fairest_produces_a_valid_matching(self):
        self.assert_valid_matching(matcher.fairest(SCORES, ALLOWED))

    def test_fairest_gives_the_same_answer_every_time(self):
        # Without this, two algorithms cannot be compared.
        self.assertEqual(
            matcher.fairest(SCORES, ALLOWED),
            matcher.fairest(SCORES, ALLOWED),
        )

    def test_fairest_lifts_the_lowest_match(self):
        # greedy takes ab at 0.9 and is then stuck giving c and d each other
        # at 0.1. fairest serves c first, and everybody ends up on 0.5.
        worst_greedy = min(FOUR[pair] for pair in matcher.greedy(FOUR, FOUR_ALLOWED))
        worst_fairest = min(FOUR[pair] for pair in matcher.fairest(FOUR, FOUR_ALLOWED))
        self.assertGreater(worst_fairest, worst_greedy)

    def test_every_listed_algorithm_can_be_run(self):
        for name, fn in matcher.ALGORITHMS.items():
            with self.subTest(algo=name):
                self.assert_valid_matching(fn(SCORES, ALLOWED))

    def test_every_algorithm_handles_made_up_users(self):
        # Three ids is small enough to hide a wrong answer. These run the
        # whole pipeline, so the tables are the shape the CLI really passes.
        users, scores, allowed = made_up_tables()
        for name, fn in matcher.ALGORITHMS.items():
            with self.subTest(algo=name):
                matches = fn(scores, allowed)
                self.assert_valid_matching(matches, allowed)
                self.assertEqual(matches, fn(scores, allowed), "not the same twice")
                # evaluate raises on a banned pair, so this is a second
                # opinion on the matching being a legal one.
                scoring.evaluate(users, matches, scores, {}, allowed)

    def test_nobody_wants_to_swap_on_made_up_users(self):
        # The property only holds by luck on three ids, so it is worth
        # checking at a size where luck runs out.
        _, scores, allowed = made_up_tables()
        self.assert_nobody_wants_to_swap(matcher.greedy(scores, allowed), scores, allowed)

    def test_the_prompt_names_both_users(self):
        breakdown = {"major": 1.0, "timetable": 0.33}
        prompt = llm.build_prompt(ALICE, BOB, 0.7, "friendship", breakdown)
        self.assertIn("a", prompt)
        self.assertIn("b", prompt)

    def test_an_empty_message_is_turned_down(self):
        self.assertFalse(llm.verify("", {"major": 1.0}))

    def test_a_sensible_message_is_accepted(self):
        self.assertTrue(
            llm.verify("You both study CS and share a free hour on Monday.",
                       {"major": 1.0, "timetable": 0.33})
        )

    def test_a_reason_that_was_not_measured_is_turned_down(self):
        # The whole point of the check. Nothing measured how close in age
        # the two are, so the model made that up.
        self.assertFalse(
            llm.verify("You are both the same age, so grab a coffee.",
                       {"major": 1.0, "timetable": 0.33})
        )

    def test_a_word_holding_another_word_inside_it_is_not_a_mention(self):
        # language holds age, and manage holds age. Matching on the bare
        # letters turned both of these down.
        self.assertTrue(
            llm.verify("You both speak Korean, so swap a language tip.",
                       {"languages": 1.0, "interests": 0.5})
        )
        self.assertTrue(
            llm.verify("You share three interests, so manage a catch up.",
                       {"interests": 1.0})
        )

    def test_a_plural_still_counts_as_a_mention(self):
        self.assertFalse(
            llm.verify("You have interests in common.", {"major": 1.0})
        )

    def test_every_measurement_has_words_that_give_it_away(self):
        # A measurement added to FEATURES without words here would never be
        # checked, so the model could name it without having been given it.
        self.assertEqual(set(llm.REASON_WORDS), set(features.FEATURES))

    def test_a_long_message_is_turned_down(self):
        self.assertFalse(llm.verify("x" * (llm.LONGEST + 1), {"major": 1.0}))

    def test_the_plain_message_names_only_what_was_measured(self):
        plain = llm.plain_message({"interests": 0.8, "timetable": 0.4})
        self.assertIn("interests", plain)
        self.assertTrue(llm.verify(plain, {"interests": 0.8, "timetable": 0.4}))

    def test_the_plain_message_copes_with_nothing_in_common(self):
        self.assertTrue(llm.plain_message({"interests": 0.0}).strip())

    def test_no_api_key_gives_the_plain_message_rather_than_raising(self):
        # A missing key is the normal state for anyone who has not set one
        # up, and it must not stop a run.
        with unittest.mock.patch.object(llm, "_api_key", return_value=None):
            message = llm.explain(ALICE, BOB, 0.7, "friendship", {"major": 1.0})
        self.assertEqual(message, llm.plain_message({"major": 1.0}))

    def test_an_answer_is_kept_and_read_back(self):
        saved = "You both study CS and share a free hour on Monday."
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "llm_cache.json"
            with unittest.mock.patch.object(llm, "_ask_the_model", return_value=saved):
                first = llm.explain(ALICE, BOB, 0.7, "friendship", {"major": 1.0}, cache=cache)
            # The model is not reachable the second time round. The answer
            # has to come out of the file.
            with unittest.mock.patch.object(llm, "_ask_the_model", return_value=None):
                second = llm.explain(ALICE, BOB, 0.7, "friendship", {"major": 1.0}, cache=cache)
        self.assertEqual(first, saved)
        self.assertEqual(second, saved)

    def test_the_cache_directory_is_made_when_it_is_not_there(self):
        # The cache sits in its own directory, which does not exist on a
        # first run. Writing into a missing one would end the run.
        saved = "You both study CS and share a free hour on Monday."
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".cache" / "llm.json"
            with unittest.mock.patch.object(llm, "_ask_the_model", return_value=saved):
                llm.explain(ALICE, BOB, 0.7, "friendship", {"major": 1.0}, cache=cache)
            self.assertTrue(cache.exists())

    def test_a_plain_message_is_never_kept(self):
        # Caching it would keep handing it back on later runs that could
        # have asked the model properly.
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "llm_cache.json"
            with unittest.mock.patch.object(llm, "_ask_the_model", return_value=None):
                llm.explain(ALICE, BOB, 0.7, "friendship", {"major": 1.0}, cache=cache)
            self.assertFalse(cache.exists())


class TestCLI(unittest.TestCase):
    def test_the_parser_is_built(self):
        self.assertIsInstance(build_parser(), argparse.ArgumentParser)

    def test_the_parser_reads_the_floor(self):
        self.assertEqual(build_parser().parse_args([]).min_score, scoring.MIN_MATCH_SCORE)
        self.assertEqual(build_parser().parse_args(["--min-score", "0.4"]).min_score, 0.4)

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
