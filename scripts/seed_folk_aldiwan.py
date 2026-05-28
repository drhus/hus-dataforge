"""One-off generator: discover all Levant poets on folk.aldiwan.net, write
poet manifests + a config.yaml source block for any we don't already have.

Run via: .venv/bin/python3 scripts/seed_folk_aldiwan.py [--dry-run]

Output:
  - projects/levant-zajal/poets/<slug>.yaml  (one per new poet)
  - prints YAML for sources to append to projects/levant-zajal/config.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx
import yaml
from selectolax.lexbor import LexborHTMLParser

ROOT = Path(__file__).resolve().parent.parent
POETS_DIR = ROOT / "projects" / "levant-zajal" / "poets"
COUNTRIES = ["lebanon", "syria", "palestine", "jordan"]
COUNTRY_AR = {
    "lebanon": "Lebanon",
    "syria": "Syria",
    "palestine": "Palestine",
    "jordan": "Jordan",
}

# Slug normalization: convert folk.aldiwan's CamelCase slugs to dataforge's
# kebab-case convention used everywhere else (matches existing manifests).
_SLUG_OVERRIDES = {
    "Khalil-rokz": "khalil-roukoz",          # match existing
    "Talal-Haider": "talal-haidar",
    "Moussa-Zgheib": "moussa-zgheib",
    "Said-Akl": "said-akl",
    "Joseph-Al-Hashim": "joseph-elhachem",
    "Zain-Shoaib": "zein-shoeib",
    "assad-saeed": "asaad-saeed",
    "Omar-elfra": "omar-elfra",
    "husam-tahsin-bik": "husam-tahsin-bik",
    "Juliet-Bader": "juliet-bader",
    "abu-selina": "abu-selina",
    "Abdulaziz-Al-rawaba": "abdulaziz-alrawaba",
    "Asaad-Alrawaba": "asaad-alrawaba",
}


def slugify(folk_slug: str) -> str:
    if folk_slug in _SLUG_OVERRIDES:
        return _SLUG_OVERRIDES[folk_slug]
    # Default: lowercase + replace _ with -
    s = re.sub(r"[_\s]+", "-", folk_slug.lower())
    # Collapse multiple dashes
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def discover(country: str) -> list[tuple[str, str]]:
    """Returns [(folk_slug, arabic_name), ...]."""
    url = f"https://folk.aldiwan.net/cat-poets-{country}"
    html = httpx.get(url, headers={"User-Agent": "dataforge-recon"}, timeout=30).text
    p = LexborHTMLParser(html)
    seen: dict[str, str] = {}
    for a in p.css('a[href*="/cat-poet-"]'):
        href = a.attributes.get("href", "")
        m = re.search(r"/cat-poet-([^/?#]+)", href)
        if not m:
            continue
        slug = m.group(1).strip()
        txt = a.text(strip=True)
        # First non-empty text per slug wins; later entries overwrite only if
        # currently empty.
        if slug not in seen or not seen[slug]:
            seen[slug] = txt
    return [(slug, name) for slug, name in seen.items()]


def write_manifest(slug: str, name_ar: str, country: str, folk_slug: str) -> bool:
    """Returns True if a new file was written; False if it already existed."""
    path = POETS_DIR / f"{slug}.yaml"
    if path.exists():
        return False
    payload = {
        "name_ar": name_ar or slug,
        "country": COUNTRY_AR[country],
        "genre": "zajal" if country == "lebanon" else "colloquial",
        "dialect": (
            "lebanese"
            if country == "lebanon"
            else (
                "syrian"
                if country == "syria"
                else "palestinian"
                if country == "palestine"
                else "jordanian"
            )
        ),
        "sources": {"folk_aldiwan": folk_slug},
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return True


def source_block(slug: str, folk_slug: str, max_records: int) -> dict:
    """The YAML source spec to add to config.yaml."""
    return {
        "name": f"folk-aldiwan-{slug}",
        "type": "list_detail",
        "subject": slug,
        "list_url": f"https://folk.aldiwan.net/cat-poet-{folk_slug}",
        "list_link_selector": 'a[href*="/poems/"]',
        "base_url": "https://folk.aldiwan.net/",
        "rate_limit_sec": 3.5,
        "max_records": max_records,
        "record_selector": "body",
        "fields": {
            "title": {"selector": 'meta[property="og:title"]', "attr": "content"},
            "verses": {
                "selector": "div.bet-1 h3",
                "attr": "text",
                "multi": True,
                "join_with": "\n",
            },
            "topics": {
                "selector": 'a[href*="poem-topics/"]',
                "attr": "text",
                "multi": True,
                "join_with": "|",
            },
            "country": {
                "selector": 'a[href*="cat-poets-"]',
                "attr": "text",
            },
            "related_poets": {
                "selector": 'a[href*="cat-poet-"]',
                "attr": "text",
                "multi": True,
                "join_with": "|",
            },
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Don't write manifests; just print plan")
    ap.add_argument(
        "--max-records",
        type=int,
        default=30,
        help="max_records per source on first batch (default 30)",
    )
    args = ap.parse_args()

    POETS_DIR.mkdir(parents=True, exist_ok=True)

    all_sources: list[dict] = []
    counts: dict[str, int] = {}
    new_manifests: list[str] = []

    for country in COUNTRIES:
        try:
            entries = discover(country)
        except Exception as e:
            print(f"# {country}: discovery failed — {e}", file=sys.stderr)
            continue
        counts[country] = len(entries)
        for folk_slug, name_ar in entries:
            canonical_slug = slugify(folk_slug)
            if args.dry_run:
                already = (POETS_DIR / f"{canonical_slug}.yaml").exists()
                marker = "exists" if already else "NEW"
                print(f"  {country:10s} {folk_slug:30s} → {canonical_slug:25s} [{marker}] {name_ar}", file=sys.stderr)
            else:
                wrote = write_manifest(canonical_slug, name_ar, country, folk_slug)
                if wrote:
                    new_manifests.append(canonical_slug)
            all_sources.append(source_block(canonical_slug, folk_slug, args.max_records))

    print(f"# Discovered: {sum(counts.values())} poets — " +
          ", ".join(f"{c}={counts[c]}" for c in counts), file=sys.stderr)
    print(f"# New manifests: {len(new_manifests)}", file=sys.stderr)
    if new_manifests:
        print(f"# New: {', '.join(new_manifests)}", file=sys.stderr)
    print(f"# Sources generated: {len(all_sources)}", file=sys.stderr)

    if args.dry_run:
        return
    # Print only the *new* sources for easy paste into config.yaml (existing
    # source `folk-aldiwan-omar-elfra` already there; don't duplicate).
    print(yaml.safe_dump(all_sources, allow_unicode=True, sort_keys=False, default_flow_style=False))


if __name__ == "__main__":
    main()
