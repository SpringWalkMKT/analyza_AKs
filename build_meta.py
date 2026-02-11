#!/usr/bin/env python3
# Build meta.json for the dashboard by merging /data/source_*.json
#
# - Repairs a common issue where a JSON file starts with '"metadata": {...}' (missing leading '{')
# - Skips inputs that are not valid JSON (without inventing data)
# - Merges firms/offices/reviews; deduplicates reviews (platform+author+date+rating+text hash+url hash)
# - Produces:
#   - public/meta.json: { merged_dataset, analysis }
#
# Run:
#   python3 scripts/build_meta.py

import json, re, hashlib, datetime, unicodedata
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_FILE = ROOT / "public" / "meta.json"

PLATFORMS_PRIORITY = ["Google Maps", "Firmy.cz", "Facebook", "Other"]
REVIEWS_PER_FIRM_MIN = 10
REVIEWS_PER_FIRM_TARGET = 20
REVIEWS_PER_FIRM_MAX = 60
TARGET_FIRMS_MIN = 20

def norm_platform(p):
    if not p:
        return "Other"
    x = str(p).lower()
    if "google" in x:
        return "Google Maps"
    if "firmy" in x:
        return "Firmy.cz"
    if "facebook" in x:
        return "Facebook"
    return "Other"

def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    s = re.sub(r"-{2,}", "-", s)
    return s or "unknown"

def firm_key(f: dict) -> str:
    w = (f.get("website") or "").strip().lower()
    if w:
        return "w:" + w
    n = re.sub(r"\s+", " ", (f.get("firm_name") or "").strip().lower())
    return "n:" + n

def office_key(o: dict) -> str:
    city = (o.get("city") or "").strip().lower()
    addr = (o.get("address") or "").strip().lower()
    if city and addr:
        return f"{city}|{addr}"
    if city:
        return city
    if addr:
        return f"addr:{addr}"
    return "unknown"

def norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip()).lower()

def review_dedupe_key(r: dict) -> str:
    plat = norm_platform(r.get("platform"))
    if r.get("review_id"):
        return plat + "|rid:" + str(r["review_id"])
    author = norm_text(r.get("author_name") or "")
    dp = r.get("date_published") or ""
    dr = r.get("date_raw") or ""
    rv = "" if r.get("rating_value") is None else str(r.get("rating_value"))
    rs = "" if r.get("rating_scale") is None else str(r.get("rating_scale"))
    text = norm_text(r.get("review_text") or "")
    url = norm_text(r.get("source_url") or "")
    h = hashlib.sha1(text.encode("utf-8")).hexdigest() if text else "no_text"
    uh = hashlib.sha1(url.encode("utf-8")).hexdigest() if url else "no_url"
    return f"{plat}|a:{author}|dp:{dp}|dr:{dr}|r:{rv}/{rs}|t:{h}|u:{uh}"

def completeness_score(r: dict) -> int:
    s = 0
    if r.get("review_id"): s += 4
    if r.get("date_published"): s += 2
    if r.get("rating_value") is not None and r.get("rating_scale") is not None: s += 2
    if (r.get("review_text") or "").strip(): s += 2
    if r.get("author_name"): s += 1
    if r.get("source_url"): s += 1
    return s

def normalize_review(r: dict) -> dict:
    rr = dict(r)
    rr["platform"] = norm_platform(rr.get("platform"))
    return rr

def normalize_profile(p: dict) -> dict:
    return {"platform": norm_platform(p.get("platform")), "source_url": p.get("source_url")}

def load_json(path: Path):
    txt = path.read_text(encoding="utf-8", errors="replace").strip()
    # repair: missing opening brace, common when file starts with '"metadata":'
    if txt.startswith('"metadata"') or txt.startswith("'metadata'"):
        txt = "{" + txt
    return json.loads(txt)

def merge_datasets(datasets):
    firms_map = {}

    for src_name, ds in datasets:
        for f in ds.get("firms", []) or []:
            fk = firm_key(f)
            if fk not in firms_map:
                firms_map[fk] = {
                    "firm_name": f.get("firm_name"),
                    "website": f.get("website"),
                    "firm_ids": set([f.get("firm_id")] if f.get("firm_id") else []),
                    "offices": {}  # office_key -> office
                }
            mf = firms_map[fk]
            if f.get("firm_name") and (not mf["firm_name"] or len(f["firm_name"]) > len(mf["firm_name"])):
                mf["firm_name"] = f["firm_name"]
            if not mf.get("website") and f.get("website"):
                mf["website"] = f.get("website")
            if f.get("firm_id"):
                mf["firm_ids"].add(f["firm_id"])

            for o in f.get("offices", []) or []:
                ok = office_key(o)
                if ok not in mf["offices"]:
                    mf["offices"][ok] = {
                        "city": o.get("city"),
                        "address": o.get("address"),
                        "platform_profiles": [],
                        "reviews_map": {}
                    }
                mo = mf["offices"][ok]
                if not mo.get("city") and o.get("city"):
                    mo["city"] = o.get("city")
                if not mo.get("address") and o.get("address"):
                    mo["address"] = o.get("address")

                for pp in o.get("platform_profiles", []) or []:
                    npp = normalize_profile(pp)
                    if npp.get("source_url"):
                        mo["platform_profiles"].append(npp)

                for r in o.get("reviews", []) or []:
                    nr = normalize_review(r)
                    k = review_dedupe_key(nr)
                    if k not in mo["reviews_map"] or completeness_score(nr) > completeness_score(mo["reviews_map"][k]):
                        mo["reviews_map"][k] = nr

    merged_firms = []
    for fk, f in firms_map.items():
        if f.get("website"):
            base = slugify(re.sub(r"^https?://", "", f["website"]).split("/")[0])
        else:
            base = slugify(f.get("firm_name") or "unknown")

        fid_candidates = [x for x in f["firm_ids"] if x]
        firm_id = sorted(fid_candidates, key=lambda x: (len(x), x))[0] if fid_candidates else base

        offices_out = []
        cities, platforms = set(), set()
        reviews_total = 0

        for ok, o in f["offices"].items():
            seen_pp, pps = set(), []
            for pp in o["platform_profiles"]:
                key = (pp["platform"], pp.get("source_url"))
                if key in seen_pp: 
                    continue
                if pp.get("source_url"):
                    seen_pp.add(key)
                    pps.append(pp)

            reviews = list(o["reviews_map"].values())
            reviews_total += len(reviews)
            for r in reviews:
                if r.get("platform"): platforms.add(r["platform"])
            if o.get("city"): cities.add(o["city"])

            office_obj = {}
            if o.get("city"): office_obj["city"] = o.get("city")
            if o.get("address"): office_obj["address"] = o.get("address")
            if pps: office_obj["platform_profiles"] = pps
            office_obj["reviews"] = reviews
            offices_out.append(office_obj)

        collection_summary = {
            "reviews_collected_total": reviews_total,
            "platforms_used": sorted(list(platforms)),
            "cities_covered": sorted(list(cities)),
        }
        if reviews_total == 0:
            collection_summary["warnings"] = ["No reviews present in merged sources."]

        firm_obj = {
            "firm_id": firm_id,
            "firm_name": f.get("firm_name"),
            "offices": offices_out,
            "collection_summary": collection_summary
        }
        if f.get("website"):
            firm_obj["website"] = f.get("website")
        merged_firms.append(firm_obj)

    dataset_quality = {
        "firms_collected": len(merged_firms),
        "reviews_collected": sum(x["collection_summary"]["reviews_collected_total"] for x in merged_firms),
        "firms_below_min_reviews": [x["firm_id"] for x in merged_firms if x["collection_summary"]["reviews_collected_total"] < REVIEWS_PER_FIRM_MIN],
        "known_limitations": [
            "Merged from provided JSON sources; public review availability varies widely by firm."
        ]
    }

    return merged_firms, dataset_quality

def rating_to5(r: dict):
    rv, rs = r.get("rating_value"), r.get("rating_scale")
    if isinstance(rv, (int, float)) and isinstance(rs, (int, float)) and rs:
        return (rv / rs) * 5
    return None

# Lightweight theme extraction for reporting (counts only)
TAX = {
    "communication_responsiveness": ["komunik", "neodpov", "email", "telefon", "call", "reply", "respond", "dovolat"],
    "professionalism_competence": ["profesion", "expert", "kvalit", "professionals", "excellent", "brilliant", "neprofesion", "lajd"],
    "ethics_trust": ["etika", "ethic", "nefér", "podvod", "lži", "lies", "slander", "dirty", "zneuž", "zatajuj", "neserióz", "without ethics"],
    "fees_value_transparency": ["cena", "náklad", "cost", "fees", "price", "záloha", "prachy", "peníze", "value", "finance", "majetek"],
    "speed_timeliness": ["rychl", "fast", "delay", "zpožd", "roky", "late", "pozd", "nikam se nepohnul"],
    "outcome_effectiveness": ["vyřeš", "solution", "help", "pomoc", "nepomoh", "result", "success", "spravedlnost", "pokrok"],
    "empathy_human_approach": ["přístup", "human", "arrog", "arogant", "poniž", "zesměš", "unpleasant", "reception"],
    "enforcement_debt_mass_mail": ["dluh", "vymáh", "exekuc", "pojist", "předžalob", "automatiz", "picrights", "copyright", "mass", "threat"],
}

def categorize(text: str):
    t = norm_text(text)
    if not t:
        return []
    out = []
    for cat, kws in TAX.items():
        if any(kw.lower() in t for kw in kws):
            out.append(cat)
    return out[:3]

def excerpt(text: str, max_words=25):
    if not text:
        return None
    words = re.findall(r"\S+", text.strip())
    if not words:
        return None
    return " ".join(words[:max_words])

def build_analysis(merged_firms: list, dataset_quality: dict, skipped_sources: list):
    firm_stats = []
    overall_pos, overall_neg = Counter(), Counter()
    sentiment_dist = Counter()
    themes_by_firm = []

    for f in merged_firms:
        reviews = []
        for o in f.get("offices", []):
            reviews.extend(o.get("reviews", []) or [])

        ratings = [rating_to5(r) for r in reviews]
        ratings = [x for x in ratings if x is not None]
        sentiments = [r.get("sentiment_score") for r in reviews if isinstance(r.get("sentiment_score"), (int, float))]

        pos, neg = Counter(), Counter()
        quotes_pos, quotes_neg = [], []

        for r in reviews:
            lab = r.get("sentiment_label") or "unknown"
            sentiment_dist[lab] += 1
            cats = categorize(r.get("review_text") or "")
            if lab == "positive":
                for c in cats: pos[c] += 1; overall_pos[c] += 1
                ex = excerpt(r.get("review_text") or "")
                if ex and len(quotes_pos) < 4: quotes_pos.append(ex)
            elif lab == "negative":
                for c in cats: neg[c] += 1; overall_neg[c] += 1
                ex = excerpt(r.get("review_text") or "")
                if ex and len(quotes_neg) < 4: quotes_neg.append(ex)

        if pos or neg:
            themes_by_firm.append({
                "firm_id": f.get("firm_id"),
                "top_positive_categories": [{"category": c, "count": n} for c, n in pos.most_common(5)],
                "top_negative_categories": [{"category": c, "count": n} for c, n in neg.most_common(5)],
                "representative_quotes_positive": quotes_pos,
                "representative_quotes_negative": quotes_neg,
            })

        firm_stats.append({
            "firm_id": f.get("firm_id"),
            "firm_name": f.get("firm_name"),
            "reviews_n": len(reviews),
            "ratings_n": len(ratings),
            "avg_rating_5": (sum(ratings) / len(ratings)) if ratings else None,
            "scored_n": len(sentiments),
            "avg_sentiment_score": (sum(sentiments) / len(sentiments)) if sentiments else None,
        })

    rank_by_rating = [x for x in firm_stats if x["ratings_n"] >= 3 and x["avg_rating_5"] is not None]
    rank_by_rating.sort(key=lambda x: (-x["avg_rating_5"], -x["ratings_n"], (x["firm_name"] or "")))

    rank_by_sent = [x for x in firm_stats if x["scored_n"] >= 3 and x["avg_sentiment_score"] is not None]
    rank_by_sent.sort(key=lambda x: (-x["avg_sentiment_score"], -x["scored_n"], (x["firm_name"] or "")))

    coverage = {
        "firms_total": dataset_quality["firms_collected"],
        "reviews_total": dataset_quality["reviews_collected"],
        "reviews_with_text": sum(1 for f in merged_firms for o in f.get("offices", []) for r in o.get("reviews", []) if (r.get("review_text") or "").strip()),
        "reviews_with_rating": sum(1 for f in merged_firms for o in f.get("offices", []) for r in o.get("reviews", []) if rating_to5(r) is not None),
        "platforms_used": sorted(list({r.get("platform") for f in merged_firms for o in f.get("offices", []) for r in o.get("reviews", []) if r.get("platform")})),
        "cities_covered": sorted(list({o.get("city") for f in merged_firms for o in f.get("offices", []) if o.get("city")})),
    }

    return {
        "coverage": coverage,
        "rankings": {
            "by_avg_rating_5": [
                {
                    "firm_id": x["firm_id"],
                    "firm_name": x["firm_name"],
                    "avg_rating_5": round(x["avg_rating_5"], 3),
                    "ratings_n": x["ratings_n"],
                    "reviews_n": x["reviews_n"],
                }
                for x in rank_by_rating[:30]
            ],
            "by_avg_sentiment_score": [
                {
                    "firm_id": x["firm_id"],
                    "firm_name": x["firm_name"],
                    "avg_sentiment_score": round(x["avg_sentiment_score"], 3),
                    "scored_n": x["scored_n"],
                    "reviews_n": x["reviews_n"],
                }
                for x in rank_by_sent[:30]
            ],
        },
        "sentiment_distribution": dict(sentiment_dist),
        "themes_overall": {
            "top_positive_categories": [{"category": c, "count": n} for c, n in overall_pos.most_common(10)],
            "top_negative_categories": [{"category": c, "count": n} for c, n in overall_neg.most_common(10)],
        },
        "themes_by_firm": themes_by_firm,
        "limitations": [
            *(f"Skipped invalid JSON input: {x}" for x in skipped_sources),
            "Most firms have limited or zero publicly captured reviews in the provided inputs; rankings may be unstable for low n."
        ],
    }

def main():
    inputs = sorted(DATA_DIR.glob("source_*.json"))
    if not inputs:
        raise SystemExit(f"No inputs found in {DATA_DIR} (expected: data/source_*.json)")

    datasets = []
    skipped = []
    for p in inputs:
        try:
            ds = load_json(p)
            datasets.append((p.name, ds))
        except Exception as e:
            skipped.append(f"{p.name}: {e}")

    if not datasets:
        raise SystemExit("All inputs failed to parse as JSON. Fix the source files in /data.")

    merged_firms, dataset_quality = merge_datasets(datasets)
    analysis = build_analysis(merged_firms, dataset_quality, skipped)

    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    merged_dataset = {
        "metadata": {
            "country": "Czech Republic",
            "created_at": created_at,
            "target_firms_min": TARGET_FIRMS_MIN,
            "reviews_per_firm_min": REVIEWS_PER_FIRM_MIN,
            "reviews_per_firm_target": REVIEWS_PER_FIRM_TARGET,
            "reviews_per_firm_max": REVIEWS_PER_FIRM_MAX,
            "platforms_priority": PLATFORMS_PRIORITY,
            "notes": "Merged from local /data/source_*.json. Public web sources only. No hallucinated fields."
        },
        "firms": merged_firms,
        "dataset_quality": dataset_quality
    }

    OUT_FILE.write_text(json.dumps({"merged_dataset": merged_dataset, "analysis": analysis}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_FILE} (firms={dataset_quality['firms_collected']}, reviews={dataset_quality['reviews_collected']}, skipped_inputs={len(skipped)})")

if __name__ == "__main__":
    main()
