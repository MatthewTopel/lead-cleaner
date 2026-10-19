"""
lead-cleaner: clean messy B2B lead list CSVs (Apollo, Clay, etc.)

Usage:
    python lead_cleaner.py input.csv
    python lead_cleaner.py input.csv --out results/

Writes two files:
    cleaned.csv  - good leads only, sorted by seniority then company
    flagged.csv  - removed or suspicious rows, with a "reason" column
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Every export names its columns a little differently. For each standard
# column we list the header spellings we accept. Headers are "simplified"
# before comparing (lowercase, letters and digits only), so "First Name",
# "first_name" and "FIRSTNAME" all become "firstname".
COLUMN_ALIASES = {
    "first_name": ["firstname", "first", "givenname"],
    "last_name": ["lastname", "last", "surname", "familyname"],
    "email": ["email", "emailaddress", "workemail", "businessemail"],
    "title": ["title", "jobtitle", "position"],
    "company": ["company", "companyname", "organization", "organizationname", "account"],
    "website": ["website", "domain", "companywebsite", "companydomain", "url"],
}

# A simple email format check: something@something.tld
# It isn't a full RFC 5322 validator, but it catches the typos and
# formatting errors you actually see in lead lists.
EMAIL_PATTERN = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")

# Shared inboxes. They don't belong to a person, so cold emails sent to
# them rarely get answered.
ROLE_PREFIXES = {"info", "sales", "support", "admin", "hello", "contact"}

# Personal email providers. On a B2B list, a work address is what we want.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.co.uk",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com",
    "aol.com", "icloud.com",
}

# Seniority rules, checked from highest score to lowest. The first rule
# that matches wins, so "VP & Director" scores 4, not 3.
# \b means "word boundary", so "cto" matches "CTO" but not "director".
SENIORITY_RULES = [
    # C-level, founders, owners. Two lookbehinds stop false positives:
    # (?<!vice ) skips "Vice President" and (?<!product ) skips "Product Owner".
    (5, r"\b(chief|ceo|cfo|cto|coo|cmo|cro|cio|ciso|founder|cofounder)\b"
        r"|(?<!product )\bowner\b"
        r"|(?<!vice )\bpresident\b"),
    (4, r"\b(vp|svp|evp|vice president)\b"),
    (3, r"\b(director|head of)\b"),
    (2, r"\b(manager|mgr)\b"),
]

# Reason labels for flagged.csv. Keeping them as constants means the
# summary can count them and the tests can check them.
REASON_DUPLICATE = "duplicate email"
REASON_LIKELY_DUPLICATE = "likely duplicate (same name + domain)"
REASON_MISSING = "missing email"
REASON_INVALID = "invalid email format"
REASON_ROLE = "role-based email"
REASON_FREE = "free email domain"
REASON_MISMATCH = "email domain doesn't match website"


# ---------------------------------------------------------------------------
# Step 0: detect columns
# ---------------------------------------------------------------------------

def simplify_header(header):
    """'First Name' -> 'firstname', 'Email_Address' -> 'emailaddress'."""
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def rename_columns(df):
    """Rename the columns we recognize to standard names (first_name, email, ...).

    Columns we don't recognize (like "City") are kept as they are.
    """
    renames = {}
    for column in df.columns:
        simple = simplify_header(column)
        for standard, aliases in COLUMN_ALIASES.items():
            # Only use the first matching column for each standard name.
            if simple in aliases and standard not in renames.values():
                renames[column] = standard
                break
    return df.rename(columns=renames)


# ---------------------------------------------------------------------------
# Step 1: normalize values
# ---------------------------------------------------------------------------

def fix_name(name):
    """Fix capitalization: 'MCDONALD' -> 'McDonald', "o'brien" -> "O'Brien",
    'mary-jane' -> 'Mary-Jane'.
    """
    # " ".join(name.split()) trims the ends and collapses double spaces.
    name = " ".join(str(name).split())

    # Split on spaces, hyphens and apostrophes. The parentheses in the
    # pattern tell re.split to keep the separators, so we can glue the
    # pieces back together afterwards.
    pieces = re.split(r"([ \-'’])", name.lower())

    fixed = []
    for piece in pieces:
        if piece.startswith("mc") and len(piece) > 2:
            # Scottish/Irish "Mc" prefix: capitalize the letter after it.
            piece = "Mc" + piece[2:].capitalize()
        else:
            piece = piece.capitalize()
        fixed.append(piece)
    return "".join(fixed)


def clean_domain(website):
    """'https://www.Acme.com/about' -> 'acme.com'."""
    domain = str(website).strip().lower()
    domain = re.sub(r"^[a-z]+://", "", domain)   # remove http:// or https://
    if domain.startswith("www."):
        domain = domain[4:]                       # remove www.
    domain = re.split(r"[/?#:]", domain)[0]      # remove path, query and port
    return domain


# ---------------------------------------------------------------------------
# Step 3: check emails
# ---------------------------------------------------------------------------

def domains_match(email_domain, website_domain):
    """True if the two domains are the same, or one is a subdomain of the other
    (for example, mail.acme.com and acme.com)."""
    return (
        email_domain == website_domain
        or email_domain.endswith("." + website_domain)
        or website_domain.endswith("." + email_domain)
    )


def email_problems(email, website_domain):
    """Return a list of reasons this email is bad. An empty list means it's fine.

    email is assumed to be lowercased and trimmed already.
    """
    if not email:
        return [REASON_MISSING]
    if not EMAIL_PATTERN.match(email):
        # No point checking anything else if we can't even parse it.
        return [REASON_INVALID]

    local_part, email_domain = email.split("@")
    problems = []

    if local_part in ROLE_PREFIXES:
        problems.append(REASON_ROLE)

    if email_domain in FREE_EMAIL_DOMAINS:
        problems.append(REASON_FREE)
    elif website_domain and not domains_match(email_domain, website_domain):
        # Only checked for work domains: a gmail address never matches the
        # website, and it's already flagged above.
        problems.append(REASON_MISMATCH)

    return problems


# ---------------------------------------------------------------------------
# Step 4: score seniority
# ---------------------------------------------------------------------------

def score_seniority(title):
    """C-level/Founder/Owner = 5, VP = 4, Director/Head of = 3,
    Manager = 2, everyone else = 1."""
    title = str(title).lower()
    for score, pattern in SENIORITY_RULES:
        if re.search(pattern, title):
            return score
    return 1


# ---------------------------------------------------------------------------
# The main pipeline
# ---------------------------------------------------------------------------

def clean_leads(raw):
    """Clean a DataFrame of leads.

    Returns (cleaned, flagged, stats):
        cleaned - good leads, sorted, with a seniority column
        flagged - removed or suspicious rows, with a reason column
        stats   - numbers for the terminal summary
    """
    df = rename_columns(raw)
    if "email" not in df.columns:
        raise ValueError(
            "Couldn't find an email column. Columns found: " + ", ".join(raw.columns)
        )

    # Remember which columns to write out: the input's columns plus seniority.
    output_columns = list(df.columns) + ["seniority"]

    # If the file has no website (or name, title...) column, add an empty one
    # so the rest of the code doesn't have to check every time.
    for standard in COLUMN_ALIASES:
        if standard not in df.columns:
            df[standard] = ""

    # --- Step 1: normalize --------------------------------------------------
    # Trim whitespace in every cell. astype(str) guards against numbers/NaN.
    df = df.fillna("").astype(str)
    for column in df.columns:
        df[column] = df[column].str.strip()

    df["first_name"] = df["first_name"].apply(fix_name)
    df["last_name"] = df["last_name"].apply(fix_name)
    df["email"] = df["email"].str.lower()
    df["website"] = df["website"].apply(clean_domain)

    # --- Step 4: seniority (done early so flagged rows have it too) ---------
    df["seniority"] = df["title"].apply(score_seniority)

    # --- Step 2a: remove exact duplicate emails -----------------------------
    # duplicated(keep="first") marks every repeat after the first one.
    # Blank emails aren't duplicates of each other; they're caught in step 3.
    is_duplicate = df.duplicated("email", keep="first") & (df["email"] != "")
    duplicates = df[is_duplicate].copy()
    duplicates["reason"] = REASON_DUPLICATE
    df = df[~is_duplicate]

    # --- Step 3: flag bad emails --------------------------------------------
    # A row can have several problems, so join them: "role-based email; free email domain".
    df["reason"] = df.apply(
        lambda row: "; ".join(email_problems(row["email"], row["website"])),
        axis=1,
    )
    bad_emails = df[df["reason"] != ""]
    df = df[df["reason"] == ""]

    # --- Step 2b: flag likely duplicates ------------------------------------
    # Same first + last name at the same domain, e.g. john.smith@acme.com and
    # jsmith@acme.com. We do this AFTER the email checks on purpose: if one copy
    # has a gmail address and the other a work address, we want to keep the
    # work one, not throw it away as the "second copy".
    # Every row left here has a valid email, so the email domain is reliable.
    email_domain = df["email"].str.split("@").str[1]
    match_key = df["first_name"].str.lower() + "|" + df["last_name"].str.lower() + "|" + email_domain
    has_name = (df["first_name"] != "") & (df["last_name"] != "")
    is_likely_duplicate = match_key.duplicated(keep="first") & has_name
    likely_duplicates = df[is_likely_duplicate].copy()
    likely_duplicates["reason"] = REASON_LIKELY_DUPLICATE
    df = df[~is_likely_duplicate]

    # --- Step 5: sort -------------------------------------------------------
    # Highest seniority first, then company A-Z. A temporary lowercase column
    # makes the company sort case-insensitive ("acme" next to "Acme").
    cleaned = (
        df.assign(company_sort=df["company"].str.lower())
        .sort_values(["seniority", "company_sort"], ascending=[False, True], kind="stable")
    )
    cleaned = cleaned[output_columns]

    flagged = pd.concat([duplicates, bad_emails, likely_duplicates])
    flagged = flagged[output_columns + ["reason"]]

    # Count each reason. A row with two reasons counts toward both.
    reason_counts = Counter()
    for reasons in flagged["reason"]:
        reason_counts.update(reasons.split("; "))

    stats = {
        "rows_in": len(raw),
        "rows_out": len(cleaned),
        "duplicates_removed": len(duplicates),
        "rows_flagged": len(flagged),
        "reason_counts": reason_counts,
    }
    return cleaned, flagged, stats


def print_summary(stats, out_dir):
    """Print a short report to the terminal."""
    print()
    print("Lead cleaning summary")
    print("---------------------")
    print(f"Rows in:             {stats['rows_in']}")
    print(f"Rows out (cleaned):  {stats['rows_out']}")
    print(f"Duplicates removed:  {stats['duplicates_removed']}")
    print(f"Rows flagged:        {stats['rows_flagged']}")
    if stats["reason_counts"]:
        print()
        print("Flag reasons:")
        for reason, count in stats["reason_counts"].most_common():
            print(f"  {count:>3}  {reason}")
    print()
    print(f"Wrote {out_dir / 'cleaned.csv'} and {out_dir / 'flagged.csv'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Clean a messy B2B lead list CSV.")
    parser.add_argument("input_csv", help="path to the lead list CSV")
    parser.add_argument("--out", default=".", help="folder for cleaned.csv and flagged.csv (default: current folder)")
    args = parser.parse_args(argv)

    # dtype=str keeps everything as text (so zip codes keep leading zeros) and
    # keep_default_na=False reads blank cells as "" instead of NaN.
    # utf-8-sig handles the invisible BOM character Excel adds to CSVs.
    try:
        raw = pd.read_csv(args.input_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except FileNotFoundError:
        sys.exit(f"Error: file not found: {args.input_csv}")

    try:
        cleaned, flagged, stats = clean_leads(raw)
    except ValueError as error:
        sys.exit(f"Error: {error}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(out_dir / "cleaned.csv", index=False)
    flagged.to_csv(out_dir / "flagged.csv", index=False)

    print_summary(stats, out_dir)


if __name__ == "__main__":
    main()
