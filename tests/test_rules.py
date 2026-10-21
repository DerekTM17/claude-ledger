import re

import pytest

from ledger import rules
from ledger.rules import check_entry, check_item, fk_grade, _sentences

GOOD_WHY = "Two sessions saving at once could erase each other's notes. Now they take turns."


def msgs(problems):
    return " | ".join(p.message for p in problems)


def test_good_entry_passes():
    assert check_entry("Sessions can no longer overwrite each other's records", GOOD_WHY) == []


def test_rules_text_examples_pass_and_fail():
    # The "Good" examples printed by `ledger rules` must pass; the "Bad" titles must fail.
    goods = re.findall(r"Good: (.+)\n  Why:  ((?:.+\n)(?:        .+\n)*)", rules.RULES_TEXT)
    assert len(goods) == 2
    for title, why in goods:
        assert check_entry(title, " ".join(why.split())) == [], title
    for bad in re.findall(r"Bad:  (.+)", rules.RULES_TEXT):
        assert check_entry(bad, GOOD_WHY) != [], bad


@pytest.mark.parametrize("title,needle", [
    ("", "empty"),
    ("x" * 71, "71 characters"),
    ("line one\nline two", "one line"),
])
def test_title_shape(title, needle):
    assert needle in msgs(check_entry(title, GOOD_WHY))


@pytest.mark.parametrize("text,needle", [
    ("Fixed `thing` today", "backticks"),
    ("Updated config.js for the form", '"config.js" is a file name'),
    ("Moved docs/specs/plan into place", '"docs/specs/plan" is a file path'),
    ("Call locked() before saving", '"locked()" is a function name'),
    ("Set CONGRESS_API_KEY again", '"CONGRESS_API_KEY" is a code name'),
    ("The stub_pending flag was lost", '"stub_pending" is a code name'),
    ("The isPreRegistered check was wrong", '"isPreRegistered" is a code name'),
    ("Merged as 1eda39c yesterday", '"1eda39c" looks like a commit hash'),
    ("Run it with --force next time", '"--force" is a command-line flag'),
    ("Merged in PR #92 this week", '"PR #92" is a PR or issue number'),
    ("Closes #40 for good", '"#40" is a PR or issue number'),
])
def test_no_code_patterns(text, needle):
    assert needle in msgs(check_entry(text, GOOD_WHY))
    assert needle.replace("Title", "Why") in msgs(check_entry("Fine title", text + ". It matters."))


@pytest.mark.parametrize("text", [
    "Cut the database from 2.9 GB to 1.3 GB (55%)",
    "Added $806.9M across 581 districts on 2026-08-20",
    "Works on iPhone and iPad now",
    "Site is live at https://example.com/a/b_c.js now",
    "Fixed the #1 complaint and/or the 24/7 alert",
    "Rotating a piece now turns it around its center",
    "Pick the domain name for attractor-xi.vercel.app",
])
def test_plain_text_allowed(text):
    assert check_entry(text[:70], GOOD_WHY) == []


def test_each_code_snippet_reported_once():
    # `state.locked_state()` would match backticks, snake_case and function-call.
    probs = check_entry("Uses `state.locked_state()` now", GOOD_WHY)
    assert len(probs) == 1


def test_why_limits():
    long_why = " ".join(["Short words here."] * 21)  # 63 words, 21 sentences
    m = msgs(check_entry("Fine title", long_why))
    assert "63 words" in m and "21 sentences" in m
    hard = ("Comprehensive infrastructural reorganization necessitated extraordinarily "
            "sophisticated administrative coordination mechanisms.")
    assert "reads at grade" in msgs(check_entry("Fine title", hard))
    assert "empty" in msgs(check_entry("Fine title", ""))


def test_sentences_with_abbreviations():
    # Test exact sentence counts with abbreviations
    assert _sentences("The rollout worked well, i.e. no incidents reported. Every team confirmed it. Support tickets dropped fast.") == 3
    assert _sentences("List items, etc. Now it's ready. The launch succeeded.") == 3
    assert _sentences("Dr. Smith signed it. It shipped.") == 2
    assert _sentences("Use tools, e.g. hammers. Then stop.") == 2
    assert _sentences("One. Two. Three. Four.") == 4
    # vs. and approx. never end sentences
    assert _sentences("Compare A vs. B today. Done.") == 2
    assert _sentences("It took approx. 30 minutes. Done.") == 2


def test_sentences_with_bill_numbers_and_dotted_abbreviations():
    # Bill numbers and dotted abbreviations don't end a sentence unless they end the text.
    assert _sentences("The House passed H.R. 29 today. It now goes to the Senate.") == 2
    assert _sentences("S. 5 passed the Senate.") == 1
    assert _sentences("It passed the U.S. Senate in May.") == 1
    assert _sentences("It shipped Aug. 28 to users.") == 1
    assert _sentences("H.J.Res. 12 passed.") == 1
    assert _sentences("S.Con.Res. 4 passed. It ends the session.") == 2
    assert _sentences("See H.R. 29. It passed.") == 2
    assert _sentences("It moved to the U.S.") == 1
    # A single letter not followed by a digit keeps the normal rule.
    assert _sentences("We fixed it. Plan B. It works.") == 3


def test_abbreviations_in_check_entry():
    # i.e. followed by lowercase letter should not end sentence
    why = "The rollout worked well, i.e. no incidents reported. Every team confirmed it. Support tickets dropped fast."
    probs = check_entry("Fine title", why)
    assert probs == [], msgs(probs)

    # etc. followed by uppercase letter SHOULD end sentence
    why2 = "List items, etc. Now it's ready. The launch succeeded."
    probs2 = check_entry("Fine title", why2)
    assert probs2 == [], msgs(probs2)

    # e.g. followed by lowercase should not end sentence
    why3 = "Consider options, e.g. red or blue. The team decided on red. It works well."
    probs3 = check_entry("Fine title", why3)
    assert probs3 == [], msgs(probs3)


def test_title_abbreviations_never_end_sentences():
    # Mr., Mrs., Ms., Dr., St. never end sentences
    why = "Dr. Smith signed it. It shipped."
    probs = check_entry("Fine title", why)
    assert probs == [], msgs(probs)


def test_four_real_sentences_fails():
    # Four actual sentences should fail the 3-sentence limit
    why = "One. Two. Three. Four."
    m = msgs(check_entry("Fine title", why))
    assert "4 sentences" in m


def test_fk_grade_ignores_numbers():
    assert fk_grade("It cost $806.9M in 2026.") == fk_grade("It cost ten in ten.")


def test_item_rules():
    assert check_item("Pick the domain name") == []
    assert "26 words" in msgs(check_item(" ".join(["word"] * 26)))
    assert '"config.js" is a file name' in msgs(check_item("Paste the URL into config.js"))
    assert check_item("Paste the form link into the site", "Set it in `frontend/src/config.js`.") == []
    assert "81 words" in msgs(check_item("Fine", " ".join(["w"] * 81)))
    assert "empty" in msgs(check_item("  "))


def test_rule_violation_carries_problems():
    probs = check_entry("", "")
    err = rules.RuleViolation(probs)
    assert err.problems == probs
    assert str(err).count("\n") == len(probs) - 1


def test_bare_carriage_return_counts_as_a_second_line():
    # A lone CR (old Mac line ending, or a stray one from a web form) is a
    # line break to anything that reads the file, so it's a second line too.
    assert "one line" in msgs(check_entry("First part\rsecond part", GOOD_WHY))
    assert "one line" in msgs(check_item("First part\rsecond part"))


def test_tag_must_be_a_short_single_word():
    assert check_item("Fix the footer", tag="tech-debt") == []
    assert check_item("Fix the footer", tag="HIGH2") == []
    for bad in ("two words", "data/quality", "<b>", "x" * 21, "a]b"):
        probs = check_item("Fix the footer", tag=bad)
        assert [p.field for p in probs] == ["tag"], bad
        assert probs[0].message.startswith("Tag:")
