"""Tests for lead_cleaner.py. Run with:  python -m pytest"""

from pathlib import Path

import pandas as pd
import pytest

import lead_cleaner as lc


@pytest.mark.parametrize("raw, expected", [
    ("  sarah ", "Sarah"),
    ("MCDONALD", "McDonald"),
    ("o'brien", "O'Brien"),
    ("MARY-JANE", "Mary-Jane"),
    ("van  der berg", "Van Der Berg"),  # double space collapsed
    ("", ""),
])
def test_fix_name(raw, expected):
    assert lc.fix_name(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("https://www.Acme.com/about", "acme.com"),
    ("http://acme.com", "acme.com"),
    ("www.acme.com", "acme.com"),
    ("acme.com:8080/login?x=1", "acme.com"),
    ("", ""),
])
def test_clean_domain(raw, expected):
    assert lc.clean_domain(raw) == expected


@pytest.mark.parametrize("title, expected", [
    ("Chief Executive Officer", 5),
    ("Founder & CEO", 5),
    ("Co-Founder", 5),
    ("President", 5),
    ("Vice President of Sales", 4),  # not 5, even though it contains "President"
    ("SVP, Operations", 4),
    ("Head of Growth", 3),
    ("Director, IT", 3),
    ("Sales Manager", 2),
    ("Product Owner", 1),            # not 5, even though it contains "Owner"
    ("Account Executive", 1),
    ("", 1),
])
def test_score_seniority(title, expected):
    assert lc.score_seniority(title) == expected


@pytest.mark.parametrize("email, website, expected", [
    ("jane@acme.com", "acme.com", []),
    ("jane@mail.acme.com", "acme.com", []),                      # subdomain is fine
    ("", "acme.com", [lc.REASON_MISSING]),
    ("jane@acme", "acme.com", [lc.REASON_INVALID]),
    ("jane acme.com", "acme.com", [lc.REASON_INVALID]),
    ("info@acme.com", "acme.com", [lc.REASON_ROLE]),
    ("jane@gmail.com", "acme.com", [lc.REASON_FREE]),
    ("jane@other.com", "acme.com", [lc.REASON_MISMATCH]),
    ("jane@other.com", "", []),                                  # no website, can't compare
    ("sales@gmail.com", "acme.com", [lc.REASON_ROLE, lc.REASON_FREE]),
])
def test_email_problems(email, website, expected):
    assert lc.email_problems(email, website) == expected


def test_detects_column_name_variants():
    raw = pd.DataFrame(columns=["first_name", "Last Name", "Email Address",
                                "Job Title", "Company Name", "Domain", "City"])
    renamed = lc.rename_columns(raw)
    assert list(renamed.columns) == ["first_name", "last_name", "email",
                                     "title", "company", "website", "City"]


def test_missing_email_column_raises_error():
    raw = pd.DataFrame({"Name": ["Jane"]})
    with pytest.raises(ValueError):
        lc.clean_leads(raw)


def test_clean_leads_end_to_end():
    raw = pd.DataFrame({
        "First Name": ["jane", "Jane", "bob", "Ann", "ANN"],
        "Last Name": ["doe", "Doe", "lee", "Kim", "KIM"],
        "Email": ["jane@acme.com", "JANE@ACME.COM", "bob@gmail.com",
                  "ann.kim@zeta.io", "akim@zeta.io"],
        "Title": ["Sales Manager", "Sales Manager", "CEO", "VP Sales", "VP Sales"],
        "Company": ["Acme", "Acme", "Bobco", "Zeta", "Zeta"],
        "Website": ["https://www.acme.com", "acme.com", "bobco.com", "zeta.io", "zeta.io"],
    })
    cleaned, flagged, stats = lc.clean_leads(raw)

    # Ann (VP, 4) sorts above Jane (Manager, 2).
    assert list(cleaned["email"]) == ["ann.kim@zeta.io", "jane@acme.com"]
    assert list(cleaned["seniority"]) == [4, 2]
    assert cleaned.iloc[1]["website"] == "acme.com"

    assert stats["rows_in"] == 5
    assert stats["rows_out"] == 2
    assert stats["duplicates_removed"] == 1
    assert stats["reason_counts"] == {
        lc.REASON_DUPLICATE: 1,
        lc.REASON_FREE: 1,
        lc.REASON_LIKELY_DUPLICATE: 1,
    }
    assert "reason" in flagged.columns


def test_sample_file():
    sample = Path(__file__).parent / "sample_messy_leads.csv"
    raw = pd.read_csv(sample, dtype=str, keep_default_na=False)
    cleaned, flagged, stats = lc.clean_leads(raw)

    assert stats["rows_in"] == 40
    assert stats["rows_out"] + stats["rows_flagged"] == 40
    # Every kind of problem shows up at least once in the sample.
    for reason in [lc.REASON_DUPLICATE, lc.REASON_LIKELY_DUPLICATE, lc.REASON_MISSING,
                   lc.REASON_INVALID, lc.REASON_ROLE, lc.REASON_FREE, lc.REASON_MISMATCH]:
        assert stats["reason_counts"][reason] >= 1
