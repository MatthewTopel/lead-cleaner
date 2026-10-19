# lead-cleaner

A small Python command-line tool that cleans messy B2B lead lists, like exports from Apollo or Clay, so an SDR can start working them right away.

It takes one CSV and writes two:

- **`cleaned.csv`**: good leads only, with a new `seniority` column, sorted by seniority (highest first) and then by company
- **`flagged.csv`**: rows that were removed or look suspicious, with a `reason` column explaining why

It also prints a short summary in the terminal.

## What it does

1. **Detects columns.** Every export names its columns differently, so headers are matched loosely: `First Name`, `first_name` and `FIRSTNAME` all count as the first-name column. It does the same for email, title, company and website/domain (see `COLUMN_ALIASES` in the code). Columns it doesn't recognize, like `City`, are kept unchanged.
2. **Normalizes values.**
   - Trims whitespace in every cell.
   - Fixes name capitalization: `MCDONALD` becomes `McDonald`, `o'brien` becomes `O'Brien`, `MARY-JANE` becomes `Mary-Jane`.
   - Lowercases emails.
   - Turns websites into clean domains: `https://www.acme.com/about` becomes `acme.com`.
3. **Deduplicates.**
   - Removes exact duplicate emails. This runs after lowercasing, so `JANE@ACME.COM` counts as a duplicate of `jane@acme.com`.
   - Flags likely duplicates: same first and last name at the same email domain (for example `john.smith@acme.com` and `jsmith@acme.com`). The first copy is kept.
4. **Flags bad emails.**
   - Missing or invalid format (`mike@brightpath`, `ava@@juniper.com`, `zoe clark@...`)
   - Role-based addresses: `info@`, `sales@`, `support@`, `admin@`, `hello@`, `contact@`
   - Free email providers: Gmail, Yahoo, Outlook, Hotmail and a few others
   - An email domain that doesn't match the company website (a subdomain such as `app.acme.com` still counts as a match)
5. **Scores seniority** from the job title:

   | Score | Matches |
   |---|---|
   | 5 | C-level (CEO, CTO, Chief …), Founder, Owner, President |
   | 4 | VP, SVP, EVP, Vice President |
   | 3 | Director, Head of |
   | 2 | Manager |
   | 1 | everyone else |

6. **Sorts** by seniority (highest first), then by company A–Z.

## How to run it

You need Python 3.9 or later and pandas. pytest is only needed for the tests.

```bash
pip install -r requirements.txt
```

Clean a file (the outputs go to the current folder):

```bash
python lead_cleaner.py sample_messy_leads.csv
```

Send the outputs to a different folder (it's created if it doesn't exist):

```bash
python lead_cleaner.py sample_messy_leads.csv --out output
```

Run the web demo (opens in your browser):

```bash
streamlit run app.py
```

`app.py` is a thin web page on top of the same `clean_leads` function. You can try the sample file or upload your own CSV, see the results in tabs, and download both outputs. The command-line tool itself only needs pandas.

Run the tests:

```bash
python -m pytest
```

## Example: the sample file

`sample_messy_leads.csv` has 40 fake leads that include every problem listed above.

### Terminal summary

```
Lead cleaning summary
---------------------
Rows in:             40
Rows out (cleaned):  20
Duplicates removed:  2
Rows flagged:        20

Flag reasons:
    6  role-based email
    5  free email domain
    4  invalid email format
    2  duplicate email
    2  email domain doesn't match website
    1  missing email
    1  likely duplicate (same name + domain)
```

`contact@gmail.com` is both role-based and a free domain, so it counts toward both reasons. That's why the reasons add up to 21 while only 20 rows were flagged.

### Before (a few rows from `sample_messy_leads.csv`)

```csv
First Name,Last Name,Job Title,Company Name,Email Address,Website
  sarah ,MCDONALD,Chief Executive Officer,Acme Analytics,Sarah.McDonald@AcmeAnalytics.com,https://www.acmeanalytics.com/
Sarah,McDonald,CEO,Acme Analytics,SARAH.MCDONALD@ACMEANALYTICS.COM,acmeanalytics.com
james,o'brien,VP of Sales,Brightpath Software,james.obrien@brightpath.io,http://brightpath.io
MARY-JANE,watson,Director of Marketing,Cobalt Logistics,MJ.Watson@cobaltlogistics.com ,www.cobaltlogistics.com
John,Smith,VP Engineering,Acme Analytics,john.smith@acmeanalytics.com,acmeanalytics.com
JOHN,SMITH,Vice President of Engineering,Acme Analytics,jsmith@acmeanalytics.com,https://acmeanalytics.com
Kevin,Brown,Owner,Juniper Retail,kevin.brown@gmail.com,juniperretail.com
,,,Harbor Security,info@harborsec.com,harborsec.com
Rachel,Adams,"Senior Vice President, Operations",Ironwood Capital,rachel.adams@ironwood-partners.com,https://www.ironwoodcap.com
```

### After: `cleaned.csv` (top rows)

```csv
first_name,last_name,title,company,email,website,City,seniority
Sarah,McDonald,Chief Executive Officer,Acme Analytics,sarah.mcdonald@acmeanalytics.com,acmeanalytics.com,Austin,5
Tom,Nguyen,Co-Founder,Foxglove Media,tom@foxglovemedia.co,foxglovemedia.co,Los Angeles,5
...
John,Smith,VP Engineering,Acme Analytics,john.smith@acmeanalytics.com,acmeanalytics.com,Austin,4
James,O'Brien,VP of Sales,Brightpath Software,james.obrien@brightpath.io,brightpath.io,Boston,4
...
Mary-Jane,Watson,Director of Marketing,Cobalt Logistics,mj.watson@cobaltlogistics.com,cobaltlogistics.com,Chicago,3
```

### After: `flagged.csv` (matching rows)

```csv
first_name,last_name,title,company,email,website,City,seniority,reason
Sarah,McDonald,CEO,Acme Analytics,sarah.mcdonald@acmeanalytics.com,acmeanalytics.com,Austin,5,duplicate email
,,,Harbor Security,info@harborsec.com,harborsec.com,Miami,1,role-based email
Kevin,Brown,Owner,Juniper Retail,kevin.brown@gmail.com,juniperretail.com,Portland,5,free email domain
Rachel,Adams,"Senior Vice President, Operations",Ironwood Capital,rachel.adams@ironwood-partners.com,ironwoodcap.com,Charlotte,4,email domain doesn't match website
John,Smith,Vice President of Engineering,Acme Analytics,jsmith@acmeanalytics.com,acmeanalytics.com,Austin,4,likely duplicate (same name + domain)
```

## How the code is organized

Everything is in `lead_cleaner.py`, from top to bottom:

| Part | What it does |
|---|---|
| Settings | Column aliases, the email regex, role and free-domain lists, seniority rules, reason labels |
| `rename_columns` | Maps whatever headers the file has onto standard names |
| `fix_name`, `clean_domain` | Normalize a single value |
| `email_problems` | Returns a list of reasons an email is bad (an empty list means it's fine) |
| `score_seniority` | Turns a job title into a score from 1 to 5 |
| `clean_leads` | The pipeline: normalize → remove duplicates → check emails → find likely duplicates → sort |
| `main` | Reads command-line arguments, loads the CSV, writes the outputs, prints the summary |

The small functions don't use pandas, so they're easy to test one at a time. `clean_leads` takes and returns DataFrames and never touches files, so the tests can call it directly.

### Design choices worth explaining

- **Likely duplicates are found after the email checks.** If one copy of a person has a Gmail address and the other has a work address, the work address is kept. If duplicates were checked first, the work row could be dropped as the "second copy" and the Gmail row then flagged too, losing the lead entirely.
- **Every cell is read as text** (`dtype=str`). This keeps values like zip codes from losing their leading zeros, and blank cells come in as `""` instead of `NaN`.
- **Seniority rules are checked from highest to lowest**, and the first match wins. Two lookbehinds in the regex handle common traps: "Vice President" doesn't count as President (5), and "Product Owner" doesn't count as Owner (5).

## Known limitations

- Name fixing is rule-based. "MacDonald", "de la Cruz" and "DeShawn" won't come out perfectly.
- The email check catches formatting mistakes. It doesn't check whether the mailbox exists (that needs an SMTP or verification service).
- Seniority scoring uses keywords, so unusual titles ("Assistant to the CEO") can be scored wrong.
- Likely duplicates need both first and last names.
