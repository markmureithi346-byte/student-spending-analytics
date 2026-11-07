from __future__ import annotations

import unittest
from datetime import datetime, timezone

from student_spending import coach, personal

RECORDED_AT = datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc)


def plan_form(
    *,
    name: str = "Amina",
    money: str = "14000",
    period: str = "monthly",
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
    advice_ack: bool = True,
) -> dict[str, list[str]]:
    form: dict[str, list[str]] = {
        "student_name": [name],
        "money_available": [money],
        "period": [period],
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
    if advice_ack:
        form["advice_ack"] = ["yes"]
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
            ({"advice_ack": False},
             "Confirm that you understand Plan It is a planning tool"),
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
        self.assertTrue(draft.advice_ack)
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


class PeriodTests(unittest.TestCase):
    def test_period_defaults_to_monthly_when_missing(self) -> None:
        form = plan_form()
        del form["period"]
        plan, errors = personal.validate_draft(personal.read_draft(form))
        self.assertEqual(errors, [])
        assert plan is not None
        self.assertEqual(plan.period, "monthly")
        self.assertEqual(plan.period_label, "Monthly")
        self.assertEqual(plan.period_noun, "month")

    def test_weekly_period_is_kept_with_its_noun(self) -> None:
        plan, errors = build_plan(period="weekly")
        self.assertEqual(errors, [])
        assert plan is not None
        self.assertEqual(plan.period, "weekly")
        self.assertEqual(plan.period_label, "Weekly")
        self.assertEqual(plan.period_noun, "week")

    def test_unknown_period_is_rejected(self) -> None:
        plan, errors = build_plan(period="daily")
        self.assertIsNone(plan)
        self.assertIn(
            "Choose whether the money is for a month or a week.", errors
        )

    def test_period_does_not_change_the_numbers(self) -> None:
        monthly, _ = build_plan(period="monthly")
        weekly, _ = build_plan(period="weekly")
        assert monthly is not None and weekly is not None
        monthly_analysis = personal.analyse(monthly, recorded_at=RECORDED_AT)
        weekly_analysis = personal.analyse(weekly, recorded_at=RECORDED_AT)
        self.assertEqual(monthly_analysis.planned_cents, weekly_analysis.planned_cents)
        self.assertEqual(monthly_analysis.spent_cents, weekly_analysis.spent_cents)
        self.assertEqual(monthly_analysis.remaining_cents, weekly_analysis.remaining_cents)


class CoachTests(unittest.TestCase):
    def setUp(self) -> None:
        plan, errors = build_plan()
        self.assertEqual(errors, [])
        assert plan is not None
        self.plan = plan
        self.analysis = personal.analyse(plan, recorded_at=RECORDED_AT)

    def test_suggestions_are_grounded_in_the_analysis(self) -> None:
        items = coach.suggest(self.plan, self.analysis)
        self.assertEqual(
            [item.key for item in items],
            ["over_plan", "unplanned", "unallocated", "unspent"],
        )
        over = items[0]
        self.assertEqual(over.tone, "warn")
        self.assertIn("1 category is over plan by KES 300.00 in total: Fun.", over.detail)
        self.assertIn("Fun at KES 300.00", over.detail)
        self.assertIn("KES 200.00", items[1].detail)
        self.assertIn("Books", items[1].detail)
        self.assertIn("KES 500.00", items[2].detail)
        self.assertIn("KES 1,500.00", items[3].detail)

    def test_weekly_suggestions_use_the_week_noun(self) -> None:
        plan, errors = build_plan(period="weekly")
        self.assertEqual(errors, [])
        assert plan is not None
        analysis = personal.analyse(plan, recorded_at=RECORDED_AT)
        detail = " ".join(item.detail for item in coach.suggest(plan, analysis))
        self.assertIn("next week", detail)
        self.assertNotIn("next month", detail)

    def test_overspent_plan_leads_with_the_gap(self) -> None:
        plan, errors = build_plan(
            money="1000",
            categories=(("Food", "500", "essential"), ("Fun", "500", "flexible")),
            spendings=(("Food", "800", ""), ("Fun", "600", "")),
        )
        self.assertEqual(errors, [])
        assert plan is not None
        analysis = personal.analyse(plan, recorded_at=RECORDED_AT)
        items = coach.suggest(plan, analysis)
        self.assertEqual(items[0].key, "overspent")
        self.assertEqual(items[0].tone, "bad")
        self.assertIn("KES 400.00 more", items[0].detail)
        self.assertLessEqual(len(items), 5)

    def test_plan_without_planned_amounts_is_not_judged(self) -> None:
        plan, errors = build_plan(
            categories=(("Food", "", "essential"), ("Fun", "", "flexible")),
            spendings=(("Food", "800", ""),),
        )
        self.assertEqual(errors, [])
        assert plan is not None
        analysis = personal.analyse(plan, recorded_at=RECORDED_AT)
        keys = [item.key for item in coach.suggest(plan, analysis)]
        self.assertIn("no_plan", keys)
        self.assertNotIn("on_track", keys)

    def test_savings_reply_quotes_the_savings_category(self) -> None:
        reply = coach.answer("How can I save more?", self.plan, self.analysis)
        self.assertEqual(reply.topic, "savings")
        joined = " ".join(reply.paragraphs)
        self.assertIn("Savings is planned at KES 1,000.00", joined)
        self.assertIn("KES 500.00", joined)
        self.assertIn("KES 1,500.00 is also unspent", joined)

    def test_cut_reply_names_the_biggest_gap(self) -> None:
        reply = coach.answer("Where can I cut spending?", self.plan, self.analysis)
        self.assertEqual(reply.topic, "cut")
        self.assertIn("clearest cut is Fun", reply.paragraphs[0])
        self.assertIn("KES 300.00", reply.paragraphs[0])
        self.assertIn("Fun at KES 1,800.00", reply.paragraphs[1])

    def test_balanced_question_uses_the_split(self) -> None:
        reply = coach.answer("Is my plan balanced?", self.plan, self.analysis)
        self.assertEqual(reply.topic, "split")
        joined = " ".join(reply.paragraphs)
        self.assertIn("Essentials: KES 12,000.00 planned", joined)
        self.assertIn("Flexible: KES 1,500.00 planned", joined)

    def test_over_and_balance_and_period_topics(self) -> None:
        over = coach.answer("What is over plan?", self.plan, self.analysis)
        self.assertEqual(over.topic, "over")
        self.assertIn("Fun is KES 300.00 over its plan", over.paragraphs[0])

        balance = coach.answer("What is left?", self.plan, self.analysis)
        self.assertEqual(balance.topic, "balance")
        self.assertIn("KES 1,500.00", balance.paragraphs[0])
        self.assertIn("KES 500.00", balance.paragraphs[0])

        period = coach.answer("Is this weekly or monthly?", self.plan, self.analysis)
        self.assertEqual(period.topic, "period")
        self.assertIn("monthly period", period.paragraphs[0])
        self.assertIn("does not convert the numbers", period.paragraphs[1])

    def test_receipt_reply_uses_the_recorded_time(self) -> None:
        reply = coach.answer("What does the receipt time mean?", self.plan, self.analysis)
        self.assertEqual(reply.topic, "receipt")
        self.assertIn("04 Nov 2026, 15:30", reply.paragraphs[0])
        self.assertIn("device's clock", reply.paragraphs[0])

    def test_help_empty_and_fallback_replies(self) -> None:
        hello = coach.answer("hello", self.plan, self.analysis)
        self.assertEqual(hello.topic, "help")
        self.assertIn("not an AI model", hello.paragraphs[0])

        empty = coach.answer("   ", self.plan, self.analysis)
        self.assertEqual(empty.topic, "start")
        self.assertIn("KES 14,000.00 available this month", empty.paragraphs[1])

        fallback = coach.answer("Tell me about volcanoes", self.plan, self.analysis)
        self.assertEqual(fallback.topic, "overview")
        self.assertIn("did not match", fallback.paragraphs[0])

    def test_long_questions_are_truncated_but_answered(self) -> None:
        question = "cut " + "x" * (coach.MAX_QUESTION_LENGTH * 2)
        reply = coach.answer(question, self.plan, self.analysis)
        self.assertEqual(len(reply.question), coach.MAX_QUESTION_LENGTH)
        self.assertTrue(question.startswith(reply.question))
        self.assertEqual(reply.topic, "cut")

    def test_short_words_do_not_match_inside_other_words(self) -> None:
        self.assertEqual(
            coach.answer("This is a cover story", self.plan, self.analysis).topic,
            "overview",
        )
        self.assertEqual(
            coach.answer("The history of planning", self.plan, self.analysis).topic,
            "overview",
        )


class FormParsingTests(unittest.TestCase):
    def test_parse_form_accepts_urlencoded_body(self) -> None:
        body = b"student_name=Amina&money_available=14%2C000&advice_ack=yes"
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
