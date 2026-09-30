#!/usr/bin/env python3
"""Fetch game-industry jobs, filter for LA/OC + US remote, score against John's profile.

Uses only the Python standard library. Output: docs/jobs.json
Optional API keys (environment variables): ADZUNA_APP_ID, ADZUNA_APP_KEY, RAPIDAPI_KEY
Run with --sample to score the bundled sample_jobs.json instead of hitting the network.
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
P = CFG["profile"]
W = CFG["weights"]
UA = {"User-Agent": "job-finder/1.0 (personal use)"}


# ---------- helpers ----------
def get_json(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def job(company, title, location, url, text, source, remote_hint=None,
        salary_min=None, salary_max=None, employment=None, posted=None):
    return dict(company=company, title=title, location=location or "", url=url,
                text=text or "", source=source, remote_hint=remote_hint,
                salary_min=salary_min, salary_max=salary_max,
                employment=employment, posted=posted)


# ---------- sources ----------
def from_greenhouse(token):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    for j in d.get("jobs", []):
        yield job(token, j["title"], (j.get("location") or {}).get("name"), j["absolute_url"],
                  strip_html(j.get("content")), "Greenhouse", posted=j.get("updated_at"))


def from_lever(token):
    for j in get_json(f"https://api.lever.co/v0/postings/{token}?mode=json"):
        c = j.get("categories") or {}
        yield job(token, j["text"], c.get("location"), j["hostedUrl"],
                  (j.get("descriptionPlain") or "") + " " + (j.get("additionalPlain") or ""),
                  "Lever", remote_hint=(j.get("workplaceType") or "").lower() or None,
                  employment=c.get("commitment"))


def from_ashby(token):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    for j in d.get("jobs", []):
        comp = (j.get("compensation") or {}).get("summaryComponents") or []
        lo = hi = None
        for c in comp:
            if c.get("compensationType") == "Salary":
                lo, hi = c.get("minValue"), c.get("maxValue")
        yield job(token, j["title"], j.get("location"), j.get("jobUrl"),
                  j.get("descriptionPlain"), "Ashby",
                  remote_hint="remote" if j.get("isRemote") else (j.get("workplaceType") or "").lower(),
                  salary_min=lo, salary_max=hi, employment=j.get("employmentType"))


def from_adzuna(query, where):
    aid, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (aid and key):
        return
    q = urllib.parse.urlencode({"app_id": aid, "app_key": key, "what": query, "where": where,
                                "results_per_page": 50, "max_days_old": 30,
                                "content-type": "application/json"})
    for j in get_json(f"https://api.adzuna.com/v1/api/jobs/us/search/1?{q}").get("results", []):
        yield job((j.get("company") or {}).get("display_name", ""), j["title"],
                  (j.get("location") or {}).get("display_name"), j["redirect_url"],
                  strip_html(j.get("description")), "Adzuna",
                  salary_min=j.get("salary_min") if not j.get("salary_is_predicted") == "1" else None,
                  salary_max=j.get("salary_max") if not j.get("salary_is_predicted") == "1" else None,
                  employment=j.get("contract_time") or j.get("contract_type"), posted=j.get("created"))


def from_jsearch(query):
    key = os.getenv("RAPIDAPI_KEY")
    if not key:
        return
    q = urllib.parse.urlencode({"query": query, "num_pages": 1, "date_posted": "month",
                                "country": "us"})
    d = get_json(f"https://jsearch.p.rapidapi.com/search?{q}",
                 {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
    for j in d.get("data", []):
        loc = ", ".join(x for x in [j.get("job_city"), j.get("job_state")] if x)
        yield job(j.get("employer_name", ""), j["job_title"], loc, j.get("job_apply_link"),
                  strip_html(j.get("job_description")), "JSearch",
                  remote_hint="remote" if j.get("job_is_remote") else None,
                  salary_min=j.get("job_min_salary"), salary_max=j.get("job_max_salary"),
                  employment=j.get("job_employment_type"), posted=j.get("job_posted_at_datetime_utc"))


# ---------- analysis ----------
MONEY = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK]|\d{2,3}(?:\.\d{2})?)"
                   r"(?:\s?(?:-|–|—|to)\s?\$?\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK]|\d{2,3}(?:\.\d{2})?))?"
                   r"(\s?(?:/|per|an?)\s?(?:hr|hour|year|yr|annum))?", re.I)


def _num(s):
    s = s.replace(",", "").replace(" ", "")
    return float(s[:-1]) * 1000 if s[-1] in "kK" else float(s)


def annualize(v, hourly):
    return v * P["hours_per_year"] if hourly else v


def salary_of(j):
    """Return (annual_min, annual_max, hourly_flag). None when unlisted."""
    lo, hi = j.get("salary_min"), j.get("salary_max")
    if lo or hi:
        lo, hi = lo or hi, hi or lo
        hourly = hi < 1000
        return annualize(lo, hourly), annualize(hi, hourly), hourly
    for m in MONEY.finditer(j["text"]):
        try:
            a = _num(m.group(1))
            b = _num(m.group(2)) if m.group(2) else a
        except ValueError:
            continue
        unit = (m.group(3) or "").lower()
        hourly = bool(re.search(r"hr|hour", unit)) or b < 300
        if hourly and not (15 <= a <= 300):
            continue
        if not hourly and not (40000 <= a <= 900000):
            continue
        if b < a:
            a, b = b, a
        return annualize(a, hourly), annualize(b, hourly), hourly
    return None, None, False


def work_mode(j):
    t = f"{j['title']} {j['location']} {j['text'][:3000]}".lower()
    hint = (j.get("remote_hint") or "")
    if "hybrid" in t or hint == "hybrid":
        return "Hybrid"
    if hint == "remote" or re.search(r"\bremote\b", t) and not re.search(r"not (?:a )?remote|no remote", t):
        return "Remote"
    return "On-site"


def in_la_oc(j):
    loc = j["location"].lower()
    return any(p in loc for p in CFG["la_oc_places"]) or re.search(r"\bla\b", loc) is not None or \
        re.search(r"(?:^|,\s*)ca\b", loc) is not None and not re.search(r"san francisco|san jose|oakland|sacramento|san diego", loc)


def excludes_california(j):
    t = j["text"].lower()
    return bool(re.search(r"(?:excluding|except|not (?:available|eligible|open)[^.]{0,40}|unable to hire in)\s+(?:in\s+)?(?:the\s+state\s+of\s+)?california|\bnot hiring in (?:ca|california)\b", t)) or \
        bool(re.search(r"california[^.]{0,40}(?:not eligible|excluded|not available)", t))


def us_location(j):
    loc = j["location"].lower()
    if not loc or "remote" in loc and not re.search(r"canada|uk|europe|india|emea|apac|latam|germany|poland|ireland", loc):
        return True
    return bool(re.search(r"united states|\busa?\b|,\s*[a-z]{2}\b|anywhere", loc)) and \
        not re.search(r"canada|united kingdom|\buk\b|europe|india|emea|apac|australia", loc)


def org_type(company):
    c = f" {company.lower()} "
    for v in CFG["vendors"]:
        if v in c:
            return "Vendor"
    for s in CFG["studios_publishers"]:
        if s in c:
            return "Studio/Publisher"
    return "Other"


def emp_type(j):
    t = f"{j.get('employment') or ''} {j['title']} {j['text'][:1500]}".lower()
    if re.search(r"contract|freelance|temporary|temp-to-hire|1099|w-?2 contract|contract-to-hire", t):
        return "Contract"
    if "part-time" in t or "part time" in t:
        return "Part-time"
    return "Full-time"


def fit_score(j):
    title = j["title"].lower()
    text = (j["title"] + " " + j["text"]).lower()
    if any(a in title for a in P["avoid_titles"]) and not any(t in title for t in ("producer", "marketing")):
        return 0, []
    tscore = 0
    if any(t in title for t in P["target_titles"]):
        tscore = 45
    elif "producer" in title or "marketing" in title:
        tscore = 32
    elif any(k in title for k in ("content", "creative", "campaign", "brand")):
        tscore = 20
    matched = sorted({t for t in P["resume_terms"] if t in text})
    kscore = min(30, len(matched) * 2.2)
    sen = 0
    if re.search(r"senior|sr\.|lead|principal|manager|director|head of", title):
        sen = 15
    elif re.search(r"associate|coordinator|junior|jr\.|assistant", title):
        sen = -10
    else:
        sen = 8
    game = 10 if re.search(r"\bgam(?:e|es|ing)\b|live service|live ops|esports|player", text) else 0
    return max(0, min(100, tscore + kscore + sen + game)), matched


def gaps_for(j):
    text = j["text"].lower()
    return [g for g in P["gap_terms"] if re.search(r"(?<![a-z])" + re.escape(g) + r"(?![a-z])", text)][:8]


def analyze(j):
    lo, hi, hourly = salary_of(j)
    mode = work_mode(j)
    org = org_type(j["company"])
    et = emp_type(j)
    la = in_la_oc(j)
    if any(x in j["company"].lower() for x in CFG["exclude_companies"]):
        return None
    if mode == "Remote":
        if excludes_california(j) or not us_location(j):
            return None
    elif not la:
        return None
    if et == "Part-time":
        return None
    fit, matched = fit_score(j)
    if fit < 25:
        return None
    # salary
    top = hi if hi else lo
    if top is None:
        sal_pts, sal_tag = 0.5, "Unlisted"
    elif top >= P["min_salary"]:
        sal_pts, sal_tag = 1.0, "≥ $110k"
    elif top >= P["near_floor_salary"]:
        sal_pts, sal_tag = 0.55, "Near floor"
    else:
        return None
    mode_pts = {"Remote": 1.0, "Hybrid": 1.0, "On-site": 0.35}[mode]
    org_pts = {"Studio/Publisher": 1.0, "Other": 0.6, "Vendor": 0.3}[org]
    type_pts = 1.0 if et in ("Full-time", "Contract") else 0.3
    score = round(fit * W["fit"] / 100 + mode_pts * W["remote"] + org_pts * W["org"] +
                  sal_pts * W["salary"] + type_pts * W["type"])
    if lo:
        fmt = (lambda v: f"${v/1000:,.0f}k")
        sal_text = f"{fmt(lo)}–{fmt(hi)}" if hi and hi != lo else fmt(lo)
        if hourly:
            sal_text += " (converted from hourly)"
    else:
        sal_text = "Unlisted"
    return {
        "score": score, "fit": round(fit), "title": j["title"], "company": j["company"],
        "location": j["location"] or "—", "mode": mode, "org": org, "type": et,
        "salary": sal_text, "salary_tag": sal_tag, "url": j["url"], "source": j["source"],
        "matched": matched[:8], "gaps": gaps_for(j), "posted": j.get("posted"),
    }


# ---------- main ----------
def collect():
    jobs = []
    tasks = ([("greenhouse", t) for t in CFG["greenhouse"]] + [("lever", t) for t in CFG["lever"]] +
             [("ashby", t) for t in CFG["ashby"]])
    fn = {"greenhouse": from_greenhouse, "lever": from_lever, "ashby": from_ashby}
    for kind, tok in tasks:
        try:
            jobs += list(fn[kind](tok))
            print(f"ok   {kind}:{tok}")
        except Exception as e:  # a bad board name must never stop the run
            print(f"skip {kind}:{tok} ({e})")
    for q in CFG["search_queries"]:
        for name, gen in (("adzuna-la", lambda: from_adzuna(q, "Los Angeles, CA")),
                          ("adzuna-oc", lambda: from_adzuna(q, "Irvine, CA")),
                          ("jsearch-la", lambda: from_jsearch(q + " in Los Angeles, CA")),
                          ("jsearch-remote", lambda: from_jsearch(q + " remote USA"))):
            try:
                jobs += list(gen())
            except Exception as e:
                print(f"skip {name}:{q} ({e})")
    return jobs


def main():
    raw = json.load(open(os.path.join(HERE, "sample_jobs.json"))) if "--sample" in sys.argv else collect()
    seen, out = set(), []
    for j in raw:
        a = analyze(j)
        if not a:
            continue
        key = (a["company"].lower(), a["title"].lower(), a["location"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    out.sort(key=lambda x: (-x["score"], x["company"]))
    payload = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "count": len(out), "jobs": out}
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    with open(os.path.join(HERE, "docs", "jobs.json"), "w") as f:
        json.dump(payload, f, indent=1)
    print(f"Scored {len(raw)} raw postings -> kept {len(out)}")


if __name__ == "__main__":
    main()
