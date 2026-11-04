from __future__ import annotations

import unittest
from datetime import datetime, timezone

from student_spending import personal

RECORDED_AT = datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc)


def plan_form(
    *,
    name: str = "Amina",
    money: str = "14000",
    method: str = "envelope",
    note: str = "Weekly envelopes; rent first.",
    categories: tuple[tuple[str, str, str], ...] = (
        ("Rent", "6000", "essential"),
        ("Food", "5000", "essential"),
        ("Fun", "1500", "flexible"),
        ("Books", "", "flexible"),
        ("Savings", "1000", "essential"),
    ),
    spendings: tuple[tuple[str, str, str], ...] = (
        ("Rent", "6000", "October rent"),
        ("Food", "3000", "Groceries"),
        ("Food", "1500", "Lunch"),
        ("Fun", "1800", "Concert"),
        ("Books", "200", "Notebook"),
    ),
    synthetic: bool = True,
) -> dict[str, list[str]]:
    form: dict[str, list[str]] = {
        "student_name": [name],
        "money_available": [money],
        "method": [method],
        "method_note": [note],
    }
    for number, (category_name, planned, kind) in enumerate(categories, start=1):
        form[f"category_name_{number}"] = [category_name]
        form[f"category_amount_{number}"] = [planned]
        form[f"category_essential_{number}"] = [kind]
    for number, (category, amount, entry_note) in enumerate(spendings, start=1):
        form[f"spending_category_{number}"] = [category]
        form[f"spending_amount_{number}"] = [amount]
        form[f"spending_note_{number}"] = [entry_note]
    if synthetic:
        form["synthetic"] = ["yes"]
    return form


def build_plan(**kwargs: object) -> tuple[personal.MoneyPlan | None, list[str]]:
    draft = personal.read_draft(plan_form(**kwargs))  # type: ignore[arg-type]
    return personal.validate_draft(draft)


class AmountParsingTests(unittest.TestCase):
    def test_accepts_common_money_forms(self) -> None:
        cases = {
            "2500": 250000,
            "2,500.50": 250050,
            "KES 2500": 250000,
            "ksh 1,000.5": 100050,
            "1 000": 100000,
            "0.05": 5,
            "0.00": 0,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(personal.parse_amount(raw), expected)

    def test_rejects_malformed_amounts(self) -> None:
        for raw in ("", "ten", "-50", "12.345", "1,00", "1,000,00", ".50", "1."):
            with self.subTest(raw=raw):
                self.assertIsNone(personal.parse_amount(raw))


class ValidationTests(unittest.TestCase):
    def test_valid_form_becomes_typed_plan(self) -> None:
        plan, errors = build_plan()
        self.assertEqual(errors, [])
        assert plan is not None
        self.assertEqual(plan.student_name, "Amina")
        self.assertEqual(plan.money_available_cents, 1_400_000)
        self.assertEqual(plan.method, "envelope")
        self.assertEqual(len(plan.categories), 5)
        self.assertEqual(plan.categories[3].planned_cents, 0)
        self.assertEqual(len(plan.spendings), 5)
        self.assertEqual(plan.spendings[0].category, "Rent")
        self.assertEqual(plan.spendings[0].amount_cents, 600_000)
        self.assertEqual(plan.spendings[0].note, "October rent")

    def test_category_matching_ignores_case_and_extra_spaces(self) -> None:
        form = plan_form()
        form["spending_category_2"] = ["  fOoD  "]
        plan, errors = personal.validate_draft(personal.read_draft(form))
        self.assertEqual(errors, [])
        assert plan is not None
        self.assertEqual(plan.spendings[1].category, "Food")

    def test_money_and_basic_fields_are_required(self) -> None:
        cases = [
            ({"money": ""}, "Enter the money available."),
            ({"money": "0"}, "must be more than zero"),
            ({"money": "ten"}, "must be a number"),
            ({"name": ""}, "Add a display name"),
            ({"method": "magic"}, "Choose a budgeting method"),
            ({"synthetic": False}, "Confirm that the numbers are made up"),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs):
                _, errors = build_plan(**kwargs)
                self.assertTrue(any(message in error for error in errors), errors)

    def test_at_least_two_named_categories_are_required(self) -> None:
        _, errors = build_plan(categories=(("Food", "5000", "essential"),))
        self.assertIn("Add at least two categories with names.", errors)

        _, errors = build_plan(
            categories=(("Food", "5000", "essential"), ("", "", "flexible"))
        )
        self.assertIn("Add at least two categories with names.", errors)

    def test_duplicate_categories_are_rejected_case_insensitively(self) -> None:
        _, errors = build_plan(
            categories=(("Food", "1000", "essential"), ("food", "500", "flexible"))
        )
        self.assertTrue(any("appears more than once" in error for error in errors))

    def test_nameless_essential_row_is_explained(self) -> None:
        _, errors = build_plan(
            categories=(
                ("Food", "1000", "essential"),
                ("Fun", "500", "flexible"),
                ("", "", "essential"),
            )
        )
        self.assertTrue(any("marked essential but has no name" in error for error in errors))

    def test_spending_rows_need_a_known_category_and_amount(self) -> None:
        _, errors = build_plan(
            spendings=(("Groceries", "0", ""),)
        )
        joined = " ".join(errors)
        self.assertNotIn("needs a date", joined)
        self.assertIn("not one of your categories", joined)
        self.assertIn("must be more than zero", joined)

    def test_a_date_field_alone_is_not_a_spending_entry(self) -> None:
        form = plan_form(spendings=())
        form["spending_date_1"] = ["2026-10-01"]
        _, errors = personal.validate_draft(personal.read_draft(form))
        self.assertIn(
            "Add at least one spending entry with a category and amount.", errors
        )

    def test_a_form_without_spending_is_rejected(self) -> None:
        _, errors = build_plan(spendings=())
        self.assertIn(
            "Add at least one spending entry with a category and amount.", errors
        )

    def test_field_lengths_are_bounded(self) -> None:
        _, errors = build_plan(name="x" * 61)
        self.assertTrue(any("display name" in error for error in errors))
        _, errors = build_plan(
            categories=(
                ("Food" + "x" * 40, "1000", "essential"),
                ("Fun", "500", "flexible"),
            )
        )
        self.assertTrue(any("too long" in error for error in errors))
        _, errors = build_plan(note="x" * 301)
        self.assertTrue(any("budgeting note" in error for error in errors))
        _, errors = build_plan(
            spendings=(("Food", "100", "x" * 121),)
        )
        self.assertTrue(any("note in spending row" in error for error in errors))

    def test_blank_planned_amount_means_zero(self) -> None:
        plan, errors = build_plan(
            categories=(("Food", "", "essential"), ("Fun", "500", "flexible")),
            spendings=(("Food", "100", ""),),
        )
        self.assertEqual(errors, [])
        assert plan is not None
        self.assertEqual(plan.categories[0].planned_cents, 0)

    def test_read_draft_keeps_raw_text_for_redisplay(self) -> None:
        draft = personal.read_draft(plan_form(name="  Amina  ", money="bad"))
        self.assertEqual(draft.student_name, "  Amina  ")
        self.assertEqual(draft.money_available, "bad")
        self.assertTrue(draft.synthetic)
        self.assertEqual(draft.category(1).name, "Rent")


class AnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        plan, errors = build_plan()
        self.assertEqual(errors, [])
        assert plan is not None
        self.plan = plan
        self.analysis = personal.analyse(plan, recorded_at=RECORDED_AT)

    def test_totals_and_remaining_money(self) -> None:
        self.assertEqual(self.analysis.planned_cents, 1_350_000)
        self.assertEqual(self.analysis.spent_cents, 1_250_000)
        self.assertEqual(self.analysis.remaining_cents, 150_000)
        self.assertEqual(self.analysis.unallocated_cents, 50_000)
        self.assertAlmostEqual(self.analysis.spent_share_pct, 100 * 1_250_000 / 1_400_000)
        self.assertAlmostEqual(self.analysis.planned_share_pct, 100 * 1_350_000 / 1_400_000)

    def test_category_statuses_and_ranking(self) -> None:
        statuses = {item.name: item.status for item in self.analysis.categories}
        self.assertEqual(statuses["Rent"], "On plan")
        self.assertEqual(statuses["Food"], "Under plan")
        self.assertEqual(statuses["Fun"], "Over plan")
        self.assertEqual(statuses["Books"], "No plan")
        self.assertEqual(statuses["Savings"], "Not used")
        self.assertEqual(
            [item.name for item in self.analysis.ranked_categories],
            ["Rent", "Food", "Fun", "Books", "Savings"],
        )
        self.assertEqual([item.name for item in self.analysis.over_plan], ["Fun"])
        self.assertEqual([item.name for item in self.analysis.unplanned], ["Books"])
        food = next(item for item in self.analysis.categories if item.name == "Food")
        self.assertEqual(food.entry_count, 2)
        self.assertAlmostEqual(food.share_pct, 36.0)

    def test_essential_flexible_and_average_entry(self) -> None:
        self.assertEqual(self.analysis.essential_planned_cents, 1_200_000)
        self.assertEqual(self.analysis.flexible_planned_cents, 150_000)
        self.assertEqual(self.analysis.essential_spent_cents, 1_050_000)
        self.assertEqual(self.analysis.flexible_spent_cents, 200_000)
        self.assertAlmostEqual(self.analysis.essential_share_pct, 84.0)
        self.assertEqual(self.analysis.recorded_at, RECORDED_AT)
        self.assertAlmostEqual(self.analysis.average_entry_cents, 250_000.0)

    def test_zero_plan_and_overspending_are_represented(self) -> None:
        plan, errors = build_plan(
            money="1000",
            categories=(("Food", "", "essential"), ("Fun", "", "flexible")),
            spendings=(
                ("Food", "800", ""),
                ("Fun", "500", ""),
            ),
        )
        self.assertEqual(errors, [])
        assert plan is not None
        analysis = personal.analyse(plan, recorded_at=RECORDED_AT)
        self.assertEqual(analysis.planned_cents, 0)
        self.assertEqual(analysis.remaining_cents, -30000)
        self.assertEqual(analysis.unallocated_cents, 100000)
        self.assertAlmostEqual(analysis.essential_share_pct, 800 / 1300 * 100)
        self.assertEqual(
            {item.status for item in analysis.categories}, {"No plan"}
        )
        self.assertEqual(len(analysis.unplanned), 2)
        self.assertEqual(analysis.over_plan, ())


class FormParsingTests(unittest.TestCase):
    def test_parse_form_accepts_urlencoded_body(self) -> None:
        body = b"student_name=Amina&money_available=14%2C000&synthetic=yes"
        parsed = personal.parse_form("application/x-www-form-urlencoded", body)
        self.assertEqual(parsed["student_name"], ["Amina"])
        self.assertEqual(parsed["money_available"], ["14,000"])

    def test_parse_form_rejects_bad_requests(self) -> None:
        cases = [
            ("multipart/form-data; boundary=x", b"x", 415),
            ("application/x-www-form-urlencoded", b"", 400),
            ("application/x-www-form-urlencoded", b"\xff", 400),
            (
                "application/x-www-form-urlencoded",
                b"x=" + b"a" * (personal.MAX_PLAN_REQUEST_BYTES + 1),
                413,
            ),
        ]
        for content_type, body, status in cases:
            with self.subTest(status=status):
                with self.assertRaises(personal.PlanRequestError) as caught:
                    personal.parse_form(content_type, body)
                self.assertEqual(caught.exception.status, status)

    def test_too_many_fields_are_rejected(self) -> None:
        body = "&".join(
            f"field{index}=x" for index in range(personal.MAX_FORM_FIELDS + 1)
        ).encode()
        with self.assertRaises(personal.PlanRequestError) as caught:
            personal.parse_form("application/x-www-form-urlencoded", body)
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("too many fields", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
