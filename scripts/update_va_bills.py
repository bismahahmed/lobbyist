#!/usr/bin/env python3
"""
LobbyistIQ — Virginia bill data updater.

Pulls the official BILLS.CSV for a Virginia General Assembly session from
LIS public data files (https://lis.virginia.gov/data-files), filters bills
relevant to LobbyistIQ's tracked industries, and regenerates bills-data.js.

Usage:
    python3 scripts/update_va_bills.py            # 2026 regular session
    python3 scripts/update_va_bills.py 20271      # any session code

Data source: https://lis.blob.core.windows.net/lisfiles/<session>/BILLS.CSV
Session codes: 20261 = 2026 Regular Session, 20271 = 2027 Regular, etc.
"""

import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

SESSION = sys.argv[1] if len(sys.argv) > 1 else "20261"
SESSION_YEAR = int(SESSION[:4])
CSV_URL = f"https://lis.blob.core.windows.net/lisfiles/{SESSION}/BILLS.CSV"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = REPO_ROOT / "bills-data.js"

# Keyword → industry tagging. A bill matches an industry if any keyword
# appears in its official description (case-insensitive).
INDUSTRY_KEYWORDS = {
    "restaurants": [
        "restaurant", "food establishment", "food service", "food handler",
        "alcoholic beverage", "tipped employee", "tip ", "meals tax",
        "food and beverage", "catering", "menu",
    ],
    "retail": [
        "retail", "organized retail", "sales tax holiday", "shoplifting",
        "point of sale", "grocery", "convenience store",
    ],
    "childcare": [
        "child care", "childcare", "child day program", "early childhood",
        "family day home", "preschool",
    ],
    "construction": [
        "contractor", "subcontractor", "construction", "mechanics' lien",
        "building code", "occupational licensing", "skilled trades",
        "workers' compensation",
    ],
    "hospitality": [
        "hotel", "lodging", "short-term rental", "tourism", "innkeeper",
        "hospitality", "special events",
    ],
}

# Broad employer/business bills that hit every industry.
ALL_INDUSTRY_KEYWORDS = [
    "minimum wage", "paid leave", "paid sick", "paid family", "overtime",
    "employee misclassification", "independent contractor", "noncompete",
    "non-compete", "covenants not to compete", "wage theft", "payment of wage",
    "unemployment compensation", "employment discrimination",
    "business license", "BPOL", "corporate income tax", "pass-through entity",
    "small business", "data privacy", "consumer data", "artificial intelligence",
    "health insurance mandate", "employer-sponsored",
]

CATEGORY_RULES = [
    ("Labor", ["wage", "employee", "employment", "paid leave", "paid sick",
               "overtime", "workers' compensation", "unemployment",
               "independent contractor", "noncompete", "non-compete", "tip"]),
    ("Health & Safety", ["health", "safety", "food", "inspection", "child care",
                          "childcare", "hazard", "violence"]),
    ("Tax & Fees", ["tax", "fee", "assessment", "levy", "BPOL"]),
    ("Legal", ["liability", "lien", "court", "civil action", "license",
               "licensing", "penalty", "enforcement"]),
]


def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "LobbyistIQ-updater/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


def derive_status(row):
    if row["Approved"] == "Y":
        return "Enacted"
    if row["Vetoed"] == "Y":
        return "Vetoed"
    if row["Failed"] == "Y":
        return "Defeated"
    if row["Carried_over"] == "Y":
        return "Carried over"
    if row["Passed"] == "Y":
        return "Passed — awaiting Governor"
    return "In progress"


def derive_effective(row, status):
    """VA default: regular-session acts take effect July 1 after adjournment.
    Emergency bills take effect on approval. This is a heuristic — bills can
    specify other dates in their text; treat as estimated."""
    if status != "Enacted":
        return None
    if row["Emergency"] == "Y" and row["Last_governor_action_date"]:
        m, d, y = row["Last_governor_action_date"].split("/")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return f"{SESSION_YEAR}-07-01"


def match_industries(desc):
    d = desc.lower()
    hits = [ind for ind, kws in INDUSTRY_KEYWORDS.items()
            if any(kw in d for kw in kws)]
    if any(kw.lower() in d for kw in ALL_INDUSTRY_KEYWORDS):
        hits.append("all")
    return sorted(set(hits))


def categorize(desc):
    d = desc.lower()
    for cat, kws in CATEGORY_RULES:
        if any(kw in d for kw in kws):
            return cat
    return "General business"


def derive_urgency(status, effective):
    today = date.today().isoformat()
    if status == "Enacted" and effective and effective >= today:
        return "high"      # compliance deadline ahead
    if status == "Enacted":
        return "high" if effective and effective >= f"{SESSION_YEAR}-07-01" else "medium"
    if status in ("Carried over", "Passed — awaiting Governor", "In progress"):
        return "medium"    # coming back / still moving
    return "low"           # defeated / vetoed


def derive_impact(status, effective, cats):
    if status == "Enacted":
        return f"Now law — compliance expected as of {effective}. Review your {cats.lower()} practices."
    if status == "Carried over":
        return "Not dead — returns next session. Time to organize before it moves again."
    if status == "Vetoed":
        return "Vetoed this year — likely to return under a future administration."
    if status == "Defeated":
        return "Defeated this session — watch for reintroduction next year."
    return "Still in play — monitor and be ready to weigh in."


def main():
    print(f"Fetching {CSV_URL} …")
    raw = fetch_csv(CSV_URL)
    rows = list(csv.DictReader(io.StringIO(raw)))
    print(f"  {len(rows)} bills in session {SESSION}")

    va_bills = []
    for row in rows:
        desc = row["Bill_description"].strip()
        industries = match_industries(desc)
        if not industries:
            continue
        status = derive_status(row)
        effective = derive_effective(row, status)
        bill_id = row["Bill_id"].strip()
        # "HB1" -> "HB 1" for display
        display_id = re.sub(r"^([A-Z]+)(\d+)$", r"\1 \2", bill_id)
        title = desc.split(";")[0].strip().rstrip(".")
        cat = categorize(desc)
        va_bills.append({
            "state": "VA",
            "bill": display_id,
            "lisId": bill_id,
            "title": title if len(title) <= 90 else title[:87] + "…",
            "patron": row["Patron_name"].strip(),
            "category": cat,
            "status": status,
            "chapter": row["Chapter_id"].strip() or None,
            "effectiveDate": effective,
            "effectiveEstimated": status == "Enacted",
            "industries": industries,
            "summary": desc,
            "impact": derive_impact(status, effective, cat),
            "urgency": derive_urgency(status, effective),
            "lisLink": f"https://lis.virginia.gov/bill-details/{SESSION}/{bill_id}",
            "lastUpdate": row["Last_governor_action_date"]
                          or row["Last_house_action_date"]
                          or row["Last_senate_action_date"] or None,
        })

    # Rank: enacted first, then still-moving, then defeated; within each, lower bill number first.
    status_rank = {"Enacted": 0, "Passed — awaiting Governor": 1, "In progress": 2,
                   "Carried over": 3, "Vetoed": 4, "Defeated": 5}
    va_bills.sort(key=lambda b: (status_rank.get(b["status"], 9), b["lisId"]))

    enacted = sum(1 for b in va_bills if b["status"] == "Enacted")
    print(f"  {len(va_bills)} bills match tracked industries ({enacted} enacted)")

    # Flag the single highest-profile enacted bill as the breaking alert.
    for b in va_bills:
        if b["lisId"] == "HB1":     # $15 minimum wage — the story of the session
            b["breaking"] = True
            break
    else:
        if va_bills:
            va_bills[0]["breaking"] = True

    # Demo bills for other states (illustrative until their pipelines exist).
    demo_states = generate_demo_states()

    header = (
        "/* LobbyistIQ bill data.\n"
        f" * VIRGINIA: REAL DATA — {len(va_bills)} bills matched to tracked industries\n"
        f" * out of {len(rows)} total bills in the {SESSION_YEAR} Regular Session.\n"
        f" * Source: {CSV_URL} (official LIS public data files)\n"
        f" * Generated by scripts/update_va_bills.py on {date.today().isoformat()}.\n"
        " * Effective dates for enacted bills are estimated (VA default July 1)\n"
        " * unless the bill text specifies otherwise — verify on LIS before relying.\n"
        " * MD/NC/TX/CA: demo data only.\n"
        " */\n\n"
    )

    js = header
    js += "const STATES = " + json.dumps({
        "VA": "Virginia", "NJ": "New Jersey", "MD": "Maryland",
        "NC": "North Carolina", "TX": "Texas", "CA": "California"}, indent=2) + ";\n\n"
    js += f"const VA_SESSION = {json.dumps({'code': SESSION, 'name': f'{SESSION_YEAR} Regular Session', 'totalBills': len(rows), 'matched': len(va_bills), 'enacted': enacted, 'updated': date.today().isoformat()})};\n\n"
    js += "const BILLS = " + json.dumps(va_bills + demo_states, indent=2) + ";\n"

    OUT_FILE.write_text(js)
    print(f"  Wrote {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} KB)")


def generate_demo_states():
    return [
        {
            "state": "NJ", "bill": "S 2310", "title": "Temporary workers' bill of rights expansion",
            "patron": "Sen. Cruz", "category": "Labor", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["all"],
            "summary": "Expands scheduling, pay transparency, and equal-pay protections for temporary and staffing-agency workers. (SAMPLE DATA)",
            "impact": "Staffing-agency arrangements would need new documentation and pay parity review.",
            "urgency": "high", "breaking": True, "demo": True,
        },
        {
            "state": "NJ", "bill": "A 1780", "title": "Liquor license availability reform for restaurants",
            "patron": "Asm. Patel", "category": "Legal", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["restaurants", "hospitality"],
            "summary": "Phases in new restaurant liquor licenses by municipality and creates a transfer credit for existing license holders. (SAMPLE DATA)",
            "impact": "Could finally make licenses attainable for independents — and change resale values for current holders.",
            "urgency": "high", "demo": True,
        },
        {
            "state": "NJ", "bill": "S 1450", "title": "AI hiring tools: bias audit requirement",
            "patron": "Sen. Okafor", "category": "Legal", "status": "In progress",
            "effectiveDate": "2027-06-01", "industries": ["all"],
            "summary": "Requires annual independent bias audits and candidate notice for automated hiring decision tools. (SAMPLE DATA)",
            "impact": "If you use AI screening software, your vendor's compliance becomes your problem.",
            "urgency": "medium", "demo": True,
        },
        {
            "state": "NJ", "bill": "A 2004", "title": "Minimum wage annual indexing adjustment",
            "patron": "Asm. Rivera", "category": "Labor", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["all"],
            "summary": "Adjusts the formula for annual CPI-based minimum wage increases and tipped-wage credit. (SAMPLE DATA)",
            "impact": "Changes how fast the wage floor moves each January.",
            "urgency": "medium", "demo": True,
        },
        {
            "state": "NJ", "bill": "A 3110", "title": "Childcare facility grants and ratio flexibility",
            "patron": "Asm. Chen", "category": "Health & Safety", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["childcare"],
            "summary": "Creates facility improvement grants and pilot flexibility on staff ratios for high-rated providers. (SAMPLE DATA)",
            "impact": "Grant money plus operating flexibility for quality-rated centers.",
            "urgency": "medium", "demo": True,
        },
        {
            "state": "MD", "bill": "HB 220", "title": "Service fee disclosure on restaurant checks",
            "patron": "Del. Carter", "category": "Legal", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["restaurants", "hospitality"],
            "summary": "Restaurants must disclose all automatic service fees before ordering, in plain language. (DEMO DATA)",
            "impact": "Menu and receipt updates; possible fee restructuring.",
            "urgency": "high", "breaking": True, "demo": True,
        },
        {
            "state": "MD", "bill": "SB 310", "title": "Retail organized theft penalties",
            "patron": "Sen. Okafor", "category": "Legal", "status": "In progress",
            "effectiveDate": "2026-10-01", "industries": ["retail"],
            "summary": "Increases penalties for organized retail theft and creates a state task force. (DEMO DATA)",
            "impact": "Generally favorable; may reduce shrink losses.",
            "urgency": "low", "demo": True,
        },
        {
            "state": "NC", "bill": "H 142", "title": "Childcare staff-to-child ratio changes",
            "patron": "Rep. Bell", "category": "Health & Safety", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["childcare"],
            "summary": "Tightens staff-to-child ratios for children under 3 in licensed childcare facilities. (DEMO DATA)",
            "impact": "May require additional staff hires per classroom.",
            "urgency": "high", "demo": True,
        },
        {
            "state": "TX", "bill": "HB 890", "title": "Contractor licensing reciprocity",
            "patron": "Rep. Trevino", "category": "Legal", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["construction"],
            "summary": "Recognizes out-of-state contractor licenses for firms in good standing. (DEMO DATA)",
            "impact": "Easier expansion into Texas; more competition in-state.",
            "urgency": "medium", "demo": True,
        },
        {
            "state": "CA", "bill": "AB 512", "title": "Fast food council wage standards expansion",
            "patron": "Asm. Nguyen", "category": "Labor", "status": "In progress",
            "effectiveDate": "2027-01-01", "industries": ["restaurants", "hospitality"],
            "summary": "Expands fast food council authority to set wage and scheduling standards for chains with 40+ locations. (DEMO DATA)",
            "impact": "Potential wage floor increases for franchise operators.",
            "urgency": "high", "demo": True,
        },
    ]


if __name__ == "__main__":
    main()
