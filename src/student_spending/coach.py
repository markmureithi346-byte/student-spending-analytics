"""Deterministic suggestions and money-coach answers for the local planner.

Nothing here is a model and nothing leaves the machine. Every sentence is
assembled from the same integer-cent totals shown in the analysis, so the coach
can never invent a figure or a category. When the numbers do not support a
piece of advice, the rule is skipped rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .personal import MoneyPlan, PlanAnalysis

MAX_QUESTION_LENGTH = 200


@dataclass(frozen=True)
class Suggestion:
    key: str
    tone: str
    title: str
    detail: str


@dataclass(frozen=True)
class CoachReply:
    question: str
    topic: str
    paragraphs: tuple[str, ...]


def suggest(plan: MoneyPlan, analysis: PlanAnalysis) -> tuple[Suggestion, ...]:
    """Return up to five grounded suggestions, most urgent first."""
    noun = plan.period_noun
    items: list[Suggestion] = []

    if analysis.remaining_cents < 0:
        items.append(
            Suggestion(
                "overspent",
                "bad",
                "Spending is over the money available",
                f"Recorded spending is {_kes(-analysis.remaining_cents)} more than the "
                f"money available this {noun}. Cover that gap before adding flexible "
                "spending, and check whether an over-plan category can be trimmed.",
            )
        )

    if analysis.over_plan:
        over_total = sum(
            item.spent_cents - item.planned_cents for item in analysis.over_plan
        )
        biggest = max(
            analysis.over_plan,
            key=lambda item: (item.spent_cents - item.planned_cents, item.name.casefold()),
        )
        gap = biggest.spent_cents - biggest.planned_cents
        items.append(
            Suggestion(
                "over_plan",
                "bad" if analysis.remaining_cents < 0 else "warn",
                "Bring over-plan categories back to plan",
                f"{_plural(len(analysis.over_plan), 'category is', 'categories are')} "
                f"over plan by {_kes(over_total)} in total: {_names(analysis.over_plan)}. "
                f"The largest gap is {biggest.name} at {_kes(gap)}; closing it would "
                "recover most of the overspend.",
            )
        )

    if analysis.unplanned:
        unplanned_total = sum(item.spent_cents for item in analysis.unplanned)
        items.append(
            Suggestion(
                "unplanned",
                "warn",
                "Some spending has no plan",
                f"{_kes(unplanned_total)} was spent in categories with no planned "
                f"amount: {_names(analysis.unplanned)}. Give each one a planned amount "
                "next time so the comparison can flag it.",
            )
        )

    if analysis.planned_cents == 0:
        items.append(
            Suggestion(
                "no_plan",
                "note",
                "Set a category plan",
                "No planned amounts were entered, so this analysis can only describe "
                "what was spent. Add a planned amount to each category to see what is "
                "under or over plan.",
            )
        )
    elif analysis.unallocated_cents > 0:
        items.append(
            Suggestion(
                "unallocated",
                "note",
                "Assign the unallocated money",
                f"{_kes(analysis.unallocated_cents)} of the money available is not in "
                "any category plan. Give it a job, such as savings or a buffer, so it "
                "is not spent by default.",
            )
        )

    if (
        analysis.planned_cents
        and analysis.flexible_planned_cents > analysis.essential_planned_cents
    ):
        flexible_share = (
            100.0 * analysis.flexible_planned_cents / analysis.planned_cents
        )
        items.append(
            Suggestion(
                "flexible_plan",
                "note",
                "Flexible categories dominate the plan",
                f"Flexible categories are {_percent(flexible_share)} of the planned "
                f"total ({_kes(analysis.flexible_planned_cents)}). Essentials and "
                "savings come first; consider moving some of that flexibility into one "
                "of them.",
            )
        )

    if analysis.spent_cents and not analysis.essential_spent_cents:
        items.append(
            Suggestion(
                "no_essentials",
                "note",
                "Mark your must-pay categories as essential",
                "No recorded spending went to a category marked Essential. Mark rent, "
                "food, transport and other must-pay items so the essential and flexible "
                "split means something.",
            )
        )
    elif (
        analysis.spent_cents
        and analysis.essential_planned_cents
        and analysis.essential_share_pct < 50.0
    ):
        items.append(
            Suggestion(
                "essential_share",
                "note",
                "Check what essentials are taking",
                f"Essentials are only {_percent(analysis.essential_share_pct)} of "
                f"recorded spending ({_kes(analysis.essential_spent_cents)}). If that "
                "looks too low, check that the categories marked Essential are the ones "
                "that must be paid first.",
            )
        )

    if not _has_savings_category(plan):
        items.append(
            Suggestion(
                "no_savings",
                "note",
                "Name a savings category",
                "There is no category that looks like savings. Even a small planned "
                "amount, set aside first, builds a buffer for the next month.",
            )
        )

    if analysis.remaining_cents > 0 and analysis.planned_cents:
        items.append(
            Suggestion(
                "unspent",
                "good",
                "Some money is still unspent",
                f"{_kes(analysis.remaining_cents)} of the money available has no "
                f"recorded spending. Move it to savings or carry it into the next {noun} "
                "on purpose rather than by habit.",
            )
        )

    if (
        analysis.planned_cents
        and analysis.spent_cents
        and not analysis.over_plan
        and not analysis.unplanned
    ):
        items.append(
            Suggestion(
                "on_track",
                "good",
                "Every category stayed on plan",
                f"All recorded spending was at or under its planned amount this {noun}. "
                f"Keep the same structure next {noun} and adjust only what changed.",
            )
        )

    if not items:
        items.append(
            Suggestion(
                "summary",
                "note",
                "Not enough numbers to suggest a change",
                "Record some spending against two or more planned categories and the "
                "coach will point out the gaps it can see.",
            )
        )
    return tuple(items[:5])


def answer(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    """Answer a question using only the submitted plan and its analysis."""
    asked = " ".join(question.split())[:MAX_QUESTION_LENGTH]
    text = asked.casefold()
    if not text:
        return _start_reply(asked, plan, analysis)
    if _mentions(
        text, "hello", "hey", "help", "what can you", "who are you"
    ) or re.search(r"\bhi\b", text):
        return _help_reply(asked, plan, analysis)
    if _mentions(text, "cut", "reduce", "trim", "lower", "spend less", "cheaper"):
        return _cut_reply(asked, plan, analysis)
    if _mentions(text, "save", "saving", "emergency", "invest", "future"):
        return _savings_reply(asked, plan, analysis)
    if _mentions(
        text, "split", "essential", "flexible", "50/30/20", "needs", "balanced"
    ):
        return _split_reply(asked, plan, analysis)
    if _mentions(text, "over", "overspend", "overspent", "exceed"):
        return _over_reply(asked, plan, analysis)
    if _mentions(text, "left", "unspent", "remaining", "unallocated", "buffer"):
        return _balance_reply(asked, plan, analysis)
    if _mentions(text, "receipt", "recorded", "stamp", "when", "time", "date"):
        return _stamp_reply(asked, plan, analysis)
    if _mentions(text, "week", "weekly", "month", "monthly", "period"):
        return _period_reply(asked, plan, analysis)
    if _mentions(text, "plan", "budget", "method", "total", "summary"):
        return _overview_reply(asked, plan, analysis)
    return _overview_reply(asked, plan, analysis, fallback=True)


def _start_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    noun = plan.period_noun
    return CoachReply(
        question,
        "start",
        (
            "Ask about cuts, savings, the essential and flexible split, balances, or "
            f"the {noun} this plan covers.",
            f"I read the numbers you just submitted: "
            f"{_kes(analysis.money_available_cents)} available this {noun}, "
            f"{_kes(analysis.spent_cents)} recorded, and "
            f"{_kes(analysis.remaining_cents)} left.",
        ),
    )


def _help_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    return CoachReply(
        question,
        "help",
        (
            "I am a local rule set, not an AI model. I only read the plan you just "
            "submitted and I never send anything off this machine.",
            "I can talk about cutting spending, saving, the essential and flexible "
            "split, what is over plan, what is left, the receipt time, or the weekly "
            "or monthly period. Try one of the quick questions under the box.",
        ),
    )


def _cut_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    noun = plan.period_noun
    paragraphs: list[str] = []
    if analysis.over_plan:
        over_total = sum(
            item.spent_cents - item.planned_cents for item in analysis.over_plan
        )
        biggest = max(
            analysis.over_plan,
            key=lambda item: (item.spent_cents - item.planned_cents, item.name.casefold()),
        )
        paragraphs.append(
            f"The clearest cut is {biggest.name}: it is "
            f"{_kes(biggest.spent_cents - biggest.planned_cents)} over its plan, out of "
            f"{_kes(over_total)} of overspending across "
            f"{_names(analysis.over_plan)}."
        )
    else:
        paragraphs.append(
            "No category is over plan, so there is no overspend to claw back. The "
            "question is whether the plan itself matches what you value."
        )

    flexible = [
        item
        for item in analysis.ranked_categories
        if not item.essential and item.spent_cents
    ]
    if flexible:
        top = flexible[0]
        paragraphs.append(
            f"The largest flexible spend is {top.name} at {_kes(top.spent_cents)} "
            f"({_percent(top.share_pct)} of recorded spending). Decide before the next "
            f"{noun} whether that amount is worth repeating."
        )
    else:
        paragraphs.append(
            "No spending is recorded in a flexible category, so cuts would have to "
            "come from essentials or from lowering the planned amounts themselves."
        )

    if analysis.remaining_cents < 0:
        paragraphs.append(
            f"First close the {_kes(-analysis.remaining_cents)} gap between spending "
            f"and the money available this {noun}."
        )
    else:
        paragraphs.append(
            f"Keep planned amounts at or below the "
            f"{_kes(analysis.money_available_cents)} available this {noun}."
        )
    return CoachReply(question, "cut", tuple(paragraphs))


def _savings_reply(
    question: str, plan: MoneyPlan, analysis: PlanAnalysis
) -> CoachReply:
    noun = plan.period_noun
    savings = [
        item for item in analysis.categories if _is_savings_name(item.name)
    ]
    paragraphs: list[str] = []
    if savings:
        described = "; ".join(
            f"{item.name} is planned at {_kes(item.planned_cents)} with "
            f"{_kes(item.spent_cents)} recorded ({item.status.lower()})"
            for item in savings
        )
        paragraphs.append(_sentence(described) + ".")
    else:
        paragraphs.append(
            "There is no category that looks like savings yet. Add one, even with a "
            "small planned amount, and pay it before flexible spending."
        )

    if analysis.unallocated_cents > 0:
        paragraphs.append(
            f"{_kes(analysis.unallocated_cents)} of the money available is still "
            "unallocated, so it could go straight into that savings category."
        )
    if analysis.remaining_cents > 0:
        paragraphs.append(
            f"{_kes(analysis.remaining_cents)} is also unspent; moving it to savings "
            f"at the end of the {noun} turns a leftover into a buffer."
        )
    elif analysis.remaining_cents < 0:
        paragraphs.append(
            f"Recorded spending is {_kes(-analysis.remaining_cents)} above the money "
            "available, so there is nothing left to save until that gap is closed."
        )
    else:
        paragraphs.append(
            "Every shilling of the money available has been recorded, so savings would "
            "need to come from changing the plan rather than from what is left."
        )
    return CoachReply(question, "savings", tuple(paragraphs))


def _split_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    if analysis.planned_cents == 0:
        return CoachReply(
            question,
            "split",
            (
                "No planned amounts were entered, so there is no essential and "
                "flexible split to judge yet.",
                "Mark each category Essential or Flexible and add planned amounts, and "
                "this answer will compare the two sides of the plan.",
            ),
        )
    essential_plan = 100.0 * analysis.essential_planned_cents / analysis.planned_cents
    flexible_plan = 100.0 - essential_plan
    paragraphs = [
        f"Essentials: {_kes(analysis.essential_planned_cents)} planned "
        f"({_percent(essential_plan)} of the plan) and "
        f"{_kes(analysis.essential_spent_cents)} recorded "
        f"({_percent(analysis.essential_share_pct)} of spending).",
        f"Flexible: {_kes(analysis.flexible_planned_cents)} planned "
        f"({_percent(flexible_plan)} of the plan) and "
        f"{_kes(analysis.flexible_spent_cents)} recorded.",
    ]
    if plan.method == "fifty_thirty_twenty":
        paragraphs.append(
            "Your method is labelled 50/30/20. This tool tracks Essential and Flexible, "
            "not needs, wants and savings, so it does not score you against that split."
        )
    elif flexible_plan > essential_plan:
        paragraphs.append(
            "More than half of the plan is flexible. If essentials and savings are "
            "covered first, that is a choice; if not, shift some flexible money across."
        )
    else:
        paragraphs.append(
            "Essentials take the larger share of the plan, which leaves less room to "
            "cut without touching must-pay items."
        )
    return CoachReply(question, "split", tuple(paragraphs))


def _over_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    noun = plan.period_noun
    if not analysis.over_plan and analysis.remaining_cents >= 0:
        return CoachReply(
            question,
            "over",
            (
                "Nothing is over plan: every category with a planned amount is at or "
                "under it, and recorded spending does not exceed the money available.",
                f"There is {_kes(analysis.remaining_cents)} left this {noun}."
                if analysis.remaining_cents > 0
                else "Recorded spending uses exactly the money available.",
            ),
        )
    paragraphs: list[str] = []
    if analysis.over_plan:
        for item in analysis.over_plan:
            paragraphs.append(
                f"{item.name} is {_kes(item.spent_cents - item.planned_cents)} over its "
                f"plan ({_kes(item.spent_cents)} spent against "
                f"{_kes(item.planned_cents)} planned)."
            )
    if analysis.unplanned:
        total = sum(item.spent_cents for item in analysis.unplanned)
        paragraphs.append(
            f"{_kes(total)} was spent in categories with no planned amount: "
            f"{_names(analysis.unplanned)}."
        )
    if analysis.remaining_cents < 0:
        paragraphs.append(
            f"Altogether, recorded spending is {_kes(-analysis.remaining_cents)} more "
            f"than the money available this {noun}."
        )
    return CoachReply(question, "over", tuple(paragraphs))


def _balance_reply(
    question: str, plan: MoneyPlan, analysis: PlanAnalysis
) -> CoachReply:
    noun = plan.period_noun
    if analysis.remaining_cents >= 0:
        left = f"{_kes(analysis.remaining_cents)} of the money available is unspent"
    else:
        left = (
            f"Recorded spending is {_kes(-analysis.remaining_cents)} above the money "
            "available"
        )
    if analysis.unallocated_cents >= 0:
        unallocated = (
            f"{_kes(analysis.unallocated_cents)} is not assigned to any category plan"
        )
    else:
        unallocated = (
            f"The plan allocates {_kes(-analysis.unallocated_cents)} more than the money "
            "available"
        )
    return CoachReply(
        question,
        "balance",
        (
            f"{_sentence(left)}, and {unallocated}.",
            f"That is out of {_kes(analysis.money_available_cents)} available this "
            f"{noun}, with {_kes(analysis.planned_cents)} planned and "
            f"{_kes(analysis.spent_cents)} recorded across "
            f"{_plural(len(plan.spendings), 'spending row')}.",
        ),
    )


def _stamp_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    recorded = analysis.recorded_at.strftime("%d %b %Y, %H:%M")
    return CoachReply(
        question,
        "receipt",
        (
            f"This analysis was recorded at {recorded} from this device's clock and "
            f"covers {_plural(len(plan.spendings), 'spending row')} totalling "
            f"{_kes(analysis.spent_cents)}.",
            "The receipt shows the same figures. Nothing is stored: printing the page "
            "or saving it as a PDF is the only copy.",
        ),
    )


def _period_reply(question: str, plan: MoneyPlan, analysis: PlanAnalysis) -> CoachReply:
    noun = plan.period_noun
    return CoachReply(
        question,
        "period",
        (
            f"This plan is set to a {plan.period_label.lower()} period, so the "
            f"{_kes(analysis.money_available_cents)} available and every category "
            f"amount is treated as a {noun} figure.",
            "Changing the period only changes the wording; it does not convert the "
            f"numbers. Enter the money and the spending for the same {noun}, whichever "
            "period you choose.",
        ),
    )


def _overview_reply(
    question: str,
    plan: MoneyPlan,
    analysis: PlanAnalysis,
    *,
    fallback: bool = False,
) -> CoachReply:
    noun = plan.period_noun
    opening = (
        "I did not match that to a topic, so here is the plan in one line:"
        if fallback
        else "Here is the plan in one line:"
    )
    paragraphs = [
        opening,
        f"{plan.student_name} has {_kes(analysis.money_available_cents)} this {noun}, "
        f"planned {_kes(analysis.planned_cents)} across "
        f"{_plural(len(plan.categories), 'category', 'categories')}, and recorded "
        f"{_kes(analysis.spent_cents)} in {_plural(len(plan.spendings), 'spending row')}.",
    ]
    if analysis.remaining_cents >= 0:
        paragraphs.append(
            f"After those entries, {_kes(analysis.remaining_cents)} is left. Ask about "
            "cuts, savings, the split, what is over plan or what is unallocated."
        )
    else:
        paragraphs.append(
            f"Recorded spending is {_kes(-analysis.remaining_cents)} above the money "
            "available. Ask about cuts to see where the gap comes from."
        )
    return CoachReply(question, "overview", tuple(paragraphs))


def _kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _names(items: list | tuple, limit: int = 4) -> str:
    names = [item.name for item in items]
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
    return ", ".join(names)


def _is_savings_name(name: str) -> bool:
    lowered = name.casefold()
    return any(part in lowered for part in ("sav", "emergency", "invest"))


def _has_savings_category(plan: MoneyPlan) -> bool:
    return any(_is_savings_name(category.name) for category in plan.categories)


def _mentions(text: str, *words: str) -> bool:
    for word in words:
        if " " in word:
            if word in text:
                return True
        elif re.search(rf"\b{re.escape(word)}", text):
            return True
    return False
