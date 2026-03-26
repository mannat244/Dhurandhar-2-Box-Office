#!/usr/bin/env python3
"""
Box Office Scraper for Dhurandhar 2: The Revenge
Scrapes sacnilk.com and updates data.json
"""

import requests
import json
import re
import os
from datetime import datetime, timezone
from bs4 import BeautifulSoup

MOVIE_URL = "https://www.sacnilk.com/movie/Dhurandhar_2_2026"
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

LANGUAGE_ALIASES = {
    "hindi": "Hindi",
    "telugu": "Telugu",
    "tamil": "Tamil",
    "malayalam": "Malayalam",
    "kannada": "Kannada",
}

RATING_EMOJI_MAP = {
    "🌟": "Excellent",
    "🔥": "Strong",
    "📈": "Good",
    "📊": "Average",
    "📉": "Low",
}


def parse_crore(text: str) -> float:
    """Extract numeric crore value from strings like '₹ 99.1Cr' or '₹623.97 Cr'."""
    if not text:
        return 0.0
    text = text.replace(",", "").strip()
    match = re.search(r"[\d]+(?:\.\d+)?", text)
    return float(match.group()) if match else 0.0


def get_rating(text: str) -> str:
    """Map emoji to rating label, fallback to stripped text."""
    for emoji, label in RATING_EMOJI_MAP.items():
        if emoji in text:
            return label
    # Try plain text labels
    for label in ["Excellent", "Strong", "Good", "Average", "Low"]:
        if label.lower() in text.lower():
            return label
    return "N/A"


def scrape_movie_page() -> dict:
    """Fetch and parse the sacnilk movie page."""
    print(f"Fetching: {MOVIE_URL}")
    resp = requests.get(MOVIE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text(separator="\n")

    data = {
        "movie": "Dhurandhar 2: The Revenge",
        "release_date": "2026-03-19",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": MOVIE_URL,
        "summary": parse_summary(soup, page_text),
        "languages": parse_languages(soup, page_text),
        "combined_daywise": [],
    }

    data["combined_daywise"] = build_combined_daywise(data["languages"])
    return data


def parse_summary(soup: BeautifulSoup, page_text: str) -> dict:
    """Extract summary totals: worldwide, india net, overseas, india gross, verdict."""
    summary = {
        "india_gross": 0.0,
        "india_net": 0.0,
        "overseas": 0.0,
        "worldwide": 0.0,
        "verdict": "N/A",
        "budget": "N/A",
    }

    # Patterns to match "Label: ₹123.45 Cr" or "Label\n₹123.45 Cr"
    patterns = {
        "worldwide": r"(?:Total Gross|Worldwide)[:\s\n]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
        "india_net": r"India Net[:\s\n]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
        "overseas": r"Overseas[:\s\n]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
        "india_gross": r"India Gross[:\s\n]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
        "budget": r"Budget[:\s\n]*₹?\s*([\d,NA]+(?:\.\d+)?)\s*(?:Cr)?",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            val = match.group(1).replace(",", "").strip()
            if key == "budget":
                summary[key] = val if val.upper() != "NA" else "N/A"
            else:
                try:
                    summary[key] = float(val)
                except ValueError:
                    pass

    # Verdict
    verdict_match = re.search(
        r"(ALL TIME BLOCKBUSTER|BLOCKBUSTER|HIT|SUPER HIT|FLOP|AVERAGE|DISASTER)",
        page_text,
        re.IGNORECASE,
    )
    if verdict_match:
        summary["verdict"] = verdict_match.group(1).upper()

    return summary


def parse_languages(soup: BeautifulSoup, page_text: str) -> dict:
    """Parse per-language daily collection sections."""
    languages = {}

    # Strategy 1: Find headings like "Hindi Version - Daily Net Collection"
    headings = soup.find_all(["h2", "h3", "h4"])
    for heading in headings:
        heading_text = heading.get_text(strip=True)
        lang_match = re.search(
            r"(Hindi|Telugu|Tamil|Malayalam|Kannada)", heading_text, re.IGNORECASE
        )
        if not lang_match:
            continue

        lang = LANGUAGE_ALIASES.get(lang_match.group(1).lower(), lang_match.group(1))
        section = heading.find_next_sibling() or heading.parent

        # Walk siblings/descendants to find day cards
        days = []
        total = 0.0
        verdict = "N/A"

        # Look for total and verdict near this heading
        next_els = heading.find_all_next(limit=40)
        for el in next_els:
            el_text = el.get_text(separator=" ", strip=True)

            # Stop if we hit another language section heading
            if el.name in ["h2", "h3", "h4"] and el != heading:
                other_lang = re.search(
                    r"(Hindi|Telugu|Tamil|Malayalam|Kannada)", el.get_text()
                )
                if other_lang and other_lang.group(1).lower() != lang.lower():
                    break

            # Net Collection total
            if "net collection" in el_text.lower():
                cr_match = re.search(r"₹\s*([\d,.]+)\s*Cr", el_text)
                if cr_match:
                    total = float(cr_match.group(1).replace(",", ""))

            # Verdict
            verdict_match = re.search(
                r"(All Time Blockbuster|Blockbuster|Hit|Super Hit|Flop|Average|N/A)",
                el_text,
                re.IGNORECASE,
            )
            if verdict_match and el.name not in ["h2", "h3", "h4"]:
                verdict = verdict_match.group(1)

            # Day cards — anchor tags with "Day N" pattern
            if el.name == "a":
                day_text = el.get_text(separator="\n", strip=True)
                day_match = re.search(r"Day\s+(\d+)", day_text, re.IGNORECASE)
                cr_match = re.search(r"₹\s*([\d,.]+)\s*Cr", day_text)
                if day_match and cr_match:
                    day_num = int(day_match.group(1))
                    collection = float(cr_match.group(1).replace(",", ""))
                    rating = get_rating(day_text)
                    # Avoid duplicates
                    if not any(d["day"] == day_num for d in days):
                        days.append({
                            "day": day_num,
                            "label": f"Day {day_num}",
                            "collection": collection,
                            "rating": rating,
                        })

        if days:
            days.sort(key=lambda d: d["day"])
            languages[lang] = {
                "total": total or sum(d["collection"] for d in days),
                "verdict": verdict,
                "days": days,
            }

    # Strategy 2 (fallback): regex on raw page text if soup parsing missed languages
    lang_section_pattern = (
        r"(Hindi|Telugu|Tamil|Malayalam|Kannada)\s+Version.*?"
        r"Net Collection.*?₹\s*([\d,.]+)\s*Cr"
    )
    for m in re.finditer(lang_section_pattern, page_text, re.IGNORECASE | re.DOTALL):
        lang_key = LANGUAGE_ALIASES.get(m.group(1).lower(), m.group(1))
        if lang_key not in languages:
            languages[lang_key] = {
                "total": float(m.group(2).replace(",", "")),
                "verdict": "N/A",
                "days": [],
            }

    return languages


def build_combined_daywise(languages: dict) -> list:
    """Sum all languages per day to build combined India Net day-wise list."""
    combined = {}
    day_labels = {}

    for lang, lang_data in languages.items():
        for day_entry in lang_data.get("days", []):
            d = day_entry["day"]
            combined[d] = combined.get(d, 0.0) + day_entry["collection"]
            if d not in day_labels:
                day_labels[d] = day_entry.get("label", f"Day {d}")

    result = []
    for day in sorted(combined.keys()):
        result.append({
            "day": day,
            "label": day_labels.get(day, f"Day {day}"),
            "india_net": round(combined[day], 2),
        })
    return result


def merge_with_existing(new_data: dict, existing_data: dict) -> dict:
    """
    Merge new scraped data with existing data.json, preserving
    days that the scraper may have missed (e.g. if page updates late).
    """
    merged = new_data.copy()

    # Merge each language: keep existing days not returned by new scrape
    for lang, existing_lang in existing_data.get("languages", {}).items():
        if lang not in merged["languages"]:
            merged["languages"][lang] = existing_lang
            continue

        new_days = {d["day"]: d for d in merged["languages"][lang].get("days", [])}
        for existing_day in existing_lang.get("days", []):
            if existing_day["day"] not in new_days:
                merged["languages"][lang]["days"].append(existing_day)

        merged["languages"][lang]["days"].sort(key=lambda d: d["day"])

    # Rebuild combined from merged languages
    merged["combined_daywise"] = build_combined_daywise(merged["languages"])

    # Preserve summary fields that scraper returned 0 for (data not available yet)
    for key in ["india_gross", "india_net", "overseas", "worldwide"]:
        if merged["summary"].get(key, 0) == 0.0:
            merged["summary"][key] = existing_data.get("summary", {}).get(key, 0.0)

    return merged


def load_existing() -> dict:
    """Load existing data.json if it exists."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(data: dict):
    """Write updated data.json."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved to {DATA_FILE}")


def main():
    try:
        existing = load_existing()
        scraped = scrape_movie_page()

        # Only merge if we got meaningful data
        if scraped["languages"] or scraped["summary"]["worldwide"] > 0:
            final = merge_with_existing(scraped, existing)
        else:
            print("WARNING: Scrape returned no useful data. Keeping existing data.")
            final = existing
            final["last_updated"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        # Print summary
        s = final.get("summary", {})
        print(f"  Worldwide  : ₹{s.get('worldwide', 0):.2f} Cr")
        print(f"  India Net  : ₹{s.get('india_net', 0):.2f} Cr")
        print(f"  India Gross: ₹{s.get('india_gross', 0):.2f} Cr")
        print(f"  Overseas   : ₹{s.get('overseas', 0):.2f} Cr")
        print(f"  Verdict    : {s.get('verdict', 'N/A')}")
        print(f"  Languages  : {list(final.get('languages', {}).keys())}")

        save(final)

    except requests.RequestException as e:
        print(f"ERROR: Network error while fetching page: {e}")
        raise SystemExit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
