#!/usr/bin/env python3
"""
Box Office Scraper for Dhurandhar 2: The Revenge
Scrapes sacnilk.com and updates data.json

Strategy:
  - For each language, find the h2 "X Version - Daily Net Collection"
  - Then find the NEXT div with id="collection-cards-{N}" after that h2
  - Pull each <a class="collection-card"> using data-day attribute (reliable)
  - Parse amount and rating from within each card
"""

import requests
import json
import re
import os
from datetime import datetime, timezone
from bs4 import BeautifulSoup

MOVIE_URL = "https://www.sacnilk.com/movie/Dhurandhar_2_2026"
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Languages to scrape, in display order
LANGUAGES = ["Hindi", "Telugu", "Tamil", "Kannada", "Malayalam"]


def parse_crore(text: str) -> float:
    """Extract numeric crore value from strings like '₹ 99.1Cr' or '₹633.72 Cr'."""
    text = text.replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*Cr", text, re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def scrape_movie_page() -> dict:
    print(f"Fetching: {MOVIE_URL}")
    resp = requests.get(MOVIE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    data = {
        "movie": "Dhurandhar 2: The Revenge",
        "release_date": "2026-03-19",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": MOVIE_URL,
        "summary": parse_summary(soup),
        "languages": {},
        "combined_daywise": [],
    }

    for lang in LANGUAGES:
        result = parse_language_section(soup, lang)
        if result:
            data["languages"][lang] = result
            print(f"  {lang}: {len(result['days'])} days, total Rs{result['total']} Cr")
        else:
            print(f"  {lang}: section not found")

    data["combined_daywise"] = build_combined_daywise(data["languages"])
    return data


def parse_summary(soup: BeautifulSoup) -> dict:
    """
    The summary cards use Tailwind colour classes to distinguish values:
      text-green-600  -> India Gross
      text-blue-600   -> Worldwide
      text-purple-600 -> Overseas
      text-orange-600 -> India Net

    We take the LARGEST value found per colour class to avoid picking up
    small partial figures (e.g. a day collection labelled orange elsewhere).
    """
    summary = {
        "india_gross": 0.0,
        "india_net":   0.0,
        "overseas":    0.0,
        "worldwide":   0.0,
        "verdict":     "N/A",
        "budget":      "N/A",
    }

    color_map = {
        "text-green-600":  "india_gross",
        "text-blue-600":   "worldwide",
        "text-purple-600": "overseas",
        "text-orange-600": "india_net",
    }

    for color_class, field in color_map.items():
        best = 0.0
        for el in soup.find_all(class_=re.compile(r"\b" + color_class + r"\b")):
            text = el.get_text(strip=True)
            if "Rs" in text or chr(8377) in text or "Cr" in text:
                val = parse_crore(text)
                if val > best:
                    best = val
        if best > 0:
            summary[field] = best

    # Verdict — look for the specific verdict text block
    verdict_el = soup.find(
        string=re.compile(
            r"ALL TIME BLOCKBUSTER|BLOCKBUSTER|SUPER HIT|HIT|AVERAGE|FLOP|DISASTER",
            re.IGNORECASE,
        )
    )
    if verdict_el:
        summary["verdict"] = verdict_el.strip().upper()

    return summary


def parse_language_section(soup: BeautifulSoup, language: str):
    """
    Correct approach — targets structure directly:

      <h2>🇮🇳 Hindi Version - Daily Net Collection</h2>
        <div>Net Collection: Rs633.72 Cr</div>
        <div>Verdict: All Time Blockbuster</div>
        <div id="collection-cards-2">           <- find_next on id pattern
          <a class="collection-card" data-day="0">
            <div>Day 0</div>
            <div>Rs 43Cr</div>
            <div>star <span class="ml-1">Excellent</span></div>
          </a>
          ...more days...
        </div>

      <h2>🇮🇳 Telugu Version - Daily Net Collection</h2>
        <div id="collection-cards-8"> ...       <- completely different ID
    """

    # Step 1: find the h2 for this language
    h2 = soup.find(
        "h2",
        string=re.compile(
            rf"{language}\s+Version\s*[-\u2013]\s*Daily Net Collection",
            re.IGNORECASE,
        ),
    )
    if not h2:
        # Some pages render it as text node inside h2, not direct string
        for tag in soup.find_all("h2"):
            if re.search(
                rf"{language}\s+Version\s*[-\u2013]\s*Daily Net Collection",
                tag.get_text(),
                re.IGNORECASE,
            ):
                h2 = tag
                break

    if not h2:
        return None

    # Step 2: extract Net Collection total and Verdict from siblings
    # Only scan until the NEXT h2 (next language section)
    total   = 0.0
    verdict = "N/A"

    for sib in h2.find_next_siblings():
        if sib.name == "h2":
            break  # stop at next language section
        stext = sib.get_text(separator=" ", strip=True)
        if "Net Collection" in stext and total == 0.0:
            val = parse_crore(stext)
            if val > 0:
                total = val
        if verdict == "N/A":
            vm = re.search(
                r"(All Time Blockbuster|Blockbuster|Super Hit|Hit|Average|Flop|Disaster)",
                stext, re.IGNORECASE,
            )
            if vm:
                verdict = vm.group(1)

    # Step 3: find the collection-cards div AFTER this h2
    # (find_next searches forward in document order — never looks backwards)
    cards_div = h2.find_next("div", id=re.compile(r"^collection-cards-\d+$"))
    if not cards_div:
        return None

    # Step 4: parse every day card
    # Each card is: <a class="collection-card" data-day="N">
    days = []
    for card in cards_div.find_all("a", class_="collection-card"):

        # data-day attribute — authoritative, no regex needed
        day_attr = card.get("data-day")
        if day_attr is None:
            continue
        try:
            day_num = int(day_attr)
        except ValueError:
            continue

        # Amount — parse ₹ N Cr from card text
        card_text = card.get_text(separator=" ", strip=True)
        amount = parse_crore(card_text)
        if amount == 0.0:
            continue  # skip placeholder cards with no collection yet

        # Rating label — in <span class="ml-1">Excellent</span>
        rating = "N/A"
        span = card.find("span", class_=re.compile(r"\bml-\d\b"))
        if span:
            rating = span.get_text(strip=True)
        else:
            for label in ["Excellent", "Strong", "Good", "Average", "Low"]:
                if label in card_text:
                    rating = label
                    break

        days.append({
            "day":        day_num,
            "label":      f"Day {day_num}",
            "collection": amount,
            "rating":     rating,
        })

    if not days:
        return None

    days.sort(key=lambda d: d["day"])

    if total == 0.0:
        total = round(sum(d["collection"] for d in days), 2)

    return {
        "total":   total,
        "verdict": verdict,
        "days":    days,
    }


def build_combined_daywise(languages: dict) -> list:
    """Sum all languages per day for the combined India Net day-wise table."""
    combined = {}
    for lang_data in languages.values():
        for d in lang_data.get("days", []):
            combined[d["day"]] = round(
                combined.get(d["day"], 0.0) + d["collection"], 2
            )
    return [
        {"day": day, "label": f"Day {day}", "india_net": total}
        for day, total in sorted(combined.items())
    ]


def merge_with_existing(new_data: dict, existing: dict) -> dict:
    """
    Merge new scraped data into existing data.json.
    - New days overwrite existing (sacnilk may update/correct figures)
    - Days present in existing but absent from new scrape are preserved
    - Summary fields kept from existing when new scrape returns 0
    """
    merged = new_data.copy()
    merged["languages"] = {}

    all_langs = set(
        list(new_data.get("languages", {}).keys()) +
        list(existing.get("languages", {}).keys())
    )

    for lang in all_langs:
        new_lang = new_data.get("languages", {}).get(lang)
        old_lang = existing.get("languages", {}).get(lang)

        if new_lang and old_lang:
            old_days = {d["day"]: d for d in old_lang.get("days", [])}
            new_days = {d["day"]: d for d in new_lang.get("days", [])}
            merged_days = {**old_days, **new_days}  # new overwrites old
            merged["languages"][lang] = {
                "total":   new_lang["total"] or old_lang.get("total", 0.0),
                "verdict": (
                    new_lang["verdict"]
                    if new_lang["verdict"] != "N/A"
                    else old_lang.get("verdict", "N/A")
                ),
                "days": sorted(merged_days.values(), key=lambda d: d["day"]),
            }
        elif new_lang:
            merged["languages"][lang] = new_lang
        else:
            merged["languages"][lang] = old_lang

    merged["combined_daywise"] = build_combined_daywise(merged["languages"])

    # Preserve summary totals if scraper got zero this run
    for key in ["india_gross", "india_net", "overseas", "worldwide"]:
        if merged["summary"].get(key, 0.0) == 0.0:
            merged["summary"][key] = existing.get("summary", {}).get(key, 0.0)
    if merged["summary"].get("verdict") == "N/A":
        merged["summary"]["verdict"] = existing.get("summary", {}).get("verdict", "N/A")

    return merged


def load_existing() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved -> {DATA_FILE}")


def main():
    try:
        existing = load_existing()
        scraped  = scrape_movie_page()

        has_data = (
            bool(scraped.get("languages")) or
            scraped.get("summary", {}).get("worldwide", 0) > 0
        )

        if has_data:
            final = merge_with_existing(scraped, existing)
        else:
            print("WARNING: Scrape returned no useful data -- keeping existing.")
            final = existing
            final["last_updated"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        # Print summary
        s = final.get("summary", {})
        print(f"\n-- Summary ---------------------")
        print(f"  Worldwide  : Rs{s.get('worldwide',  0):.2f} Cr")
        print(f"  India Net  : Rs{s.get('india_net',  0):.2f} Cr")
        print(f"  India Gross: Rs{s.get('india_gross', 0):.2f} Cr")
        print(f"  Overseas   : Rs{s.get('overseas',   0):.2f} Cr")
        print(f"  Verdict    : {s.get('verdict', 'N/A')}")

        print(f"\n-- Days per language -----------")
        for lang, ld in final.get("languages", {}).items():
            days     = ld.get("days", [])
            day_nums = [str(d["day"]) for d in days]
            print(
                f"  {lang:<12}: {len(days)} days "
                f"[{', '.join(day_nums)}]  "
                f"total Rs{ld.get('total', 0):.2f} Cr"
            )

        save(final)

    except requests.RequestException as e:
        print(f"ERROR: Network error: {e}")
        raise SystemExit(1)
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
