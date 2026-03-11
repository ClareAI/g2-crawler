"""
G2 Reviews Crawler
Navigates a real Chrome browser (via CDP on port 9222) to G2 review pages and
extracts structured review data. No login required — G2 reviews are public.

Chrome handles all anti-bot challenges (DataDome) naturally since it's a real
browser. The script just tells it which URLs to visit and reads the rendered HTML.

Prerequisites:
  1. Launch Chrome with remote debugging: --remote-debugging-port=9222
  2. Run this script
"""

import json
import os
import re
import asyncio
import time
import random
import urllib.request

import websockets
from scrapling.parser import Adaptor


# --- Configuration -----------------------------------------------------------

PRODUCT_SLUG = os.environ.get("G2_PRODUCT_SLUG", "wati")
BASE_URL = f"https://www.g2.com/products/{PRODUCT_SLUG}/reviews"
PAGINATION_URL = f"https://www.g2.com/products/{PRODUCT_SLUG}/reviews_and_filters?page={{}}"
OUTPUT_FILE = os.environ.get("G2_OUTPUT_FILE", f"{PRODUCT_SLUG}_reviews.json")
CDP_PORT = int(os.environ.get("G2_CDP_PORT", "9222"))
PAGE_LOAD_WAIT = float(os.environ.get("G2_PAGE_WAIT", "4"))


# --- CDP helpers -------------------------------------------------------------


def get_cdp_ws_url() -> str:
    """Find a Chrome tab with G2 open, or fall back to the first available tab."""
    pages = json.loads(urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json").read())
    for p in pages:
        if "g2.com" in p.get("url", ""):
            return p["webSocketDebuggerUrl"]
    if pages:
        return pages[0]["webSocketDebuggerUrl"]
    raise RuntimeError(f"No Chrome tabs found on CDP port {CDP_PORT}")


def fetch_page(ws_url: str, url: str, wait: float = PAGE_LOAD_WAIT) -> Adaptor | None:
    """Navigate Chrome to a URL via CDP, wait for render, return parsed page."""

    async def _fetch():
        async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                "id": 1, "method": "Page.navigate", "params": {"url": url}
            }))
            await ws.recv()
            await asyncio.sleep(wait)
            await ws.send(json.dumps({
                "id": 2,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML"},
            }))
            msg = json.loads(await ws.recv())
            return msg["result"]["result"]["value"]

    try:
        html = asyncio.run(_fetch())
        return Adaptor(html, url=url)
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


# --- Parsing -----------------------------------------------------------------


def parse_review(review_el) -> dict:
    """Extract structured data from a single review element."""
    rating_el = review_el.css('meta[itemprop="ratingValue"]')
    rating = float(rating_el[0].attrib["content"]) if rating_el else None

    author_el = review_el.css('meta[itemprop="name"]')
    author = author_el[0].attrib["content"] if author_el else None

    date_el = review_el.css('meta[itemprop="datePublished"]')
    date = date_el[0].attrib["content"] if date_el else None

    review_id = review_el.attrib.get("id", "")

    all_text = [t.strip() for t in review_el.css("::text").getall() if t.strip()]

    info_els = review_el.css(".elv-text-xs::text").getall()
    info = [i.strip() for i in info_els if i.strip()]
    job_title = info[0] if len(info) > 0 else None
    company_size = info[1] if len(info) > 1 else None

    title = None
    for t in all_text:
        if t.startswith("\u201c") or t.startswith('"'):
            title = t.strip("\u201c\u201d\"")
            break

    likes = extract_section(all_text, "What do you like best about")
    dislikes = extract_section(all_text, "What do you dislike about")
    problems = extract_section(all_text, "What problems is")

    return {
        "review_id": review_id,
        "author": author,
        "job_title": job_title,
        "company_size": company_size,
        "date": date,
        "rating": rating,
        "title": title,
        "likes": likes,
        "dislikes": dislikes,
        "problems_solving": problems,
    }


def extract_section(texts: list[str], header_prefix: str) -> str | None:
    """Extract text between a section header and the next known boundary."""
    boundaries = [
        "What do you like best",
        "What do you dislike",
        "What problems is",
        "Review collected by and hosted on G2.com.",
        "Show More",
        "Current User",
        "Validated Reviewer",
        "Source:",
    ]
    capturing = False
    parts = []
    for t in texts:
        if t.lower().startswith(header_prefix.lower()):
            capturing = True
            continue
        if capturing:
            if any(t.startswith(b) for b in boundaries):
                break
            parts.append(t)
    return " ".join(parts).strip() or None


# --- Page-level helpers ------------------------------------------------------


def get_total_reviews(page: Adaptor) -> int:
    """Get total review count from the reviewCount meta tag or page text."""
    rc = page.css('[itemprop="reviewCount"]')
    if rc:
        content = rc[0].attrib.get("content")
        if content and content.isdigit():
            return int(content)
    for t in page.css("::text").getall():
        m = re.match(r"^\s*(\d[\d,]*)\s+reviews?\s*$", t.strip(), re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    return 0


def get_total_pages(page: Adaptor) -> int:
    """Calculate total pages from total review count (10 per page)."""
    total = get_total_reviews(page)
    if total > 0:
        return (total + 9) // 10
    page_links = page.css('a[href*="page="]')
    pages = []
    for pl in page_links:
        href = pl.attrib.get("href", "")
        m = re.search(r"page=(\d+)", href)
        if m:
            pages.append(int(m.group(1)))
    return max(pages) if pages else 1


def scrape_page(page: Adaptor) -> list[dict]:
    """Parse all reviews from a fetched page."""
    reviews = page.css('[itemprop="review"]')
    return [parse_review(r) for r in reviews]


# --- Persistence -------------------------------------------------------------


def load_existing() -> tuple[list[dict], set[str]]:
    """Load previously saved reviews for incremental writes."""
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            reviews = json.load(f)
        seen = {r["review_id"] for r in reviews if r["review_id"]}
        return reviews, seen
    except (FileNotFoundError, json.JSONDecodeError):
        return [], set()


def save_reviews(reviews: list[dict]):
    """Write all reviews to disk."""
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)


def append_new(all_reviews: list[dict], seen: set[str], page_reviews: list[dict]) -> int:
    """Append new (non-duplicate) reviews, save to disk, return count added."""
    added = 0
    for rev in page_reviews:
        rid = rev["review_id"]
        if rid and rid in seen:
            continue
        all_reviews.append(rev)
        if rid:
            seen.add(rid)
        added += 1
    save_reviews(all_reviews)
    return added


# --- Main --------------------------------------------------------------------


def main():
    ws_url = get_cdp_ws_url()
    print(f"Connected to Chrome CDP on port {CDP_PORT}")

    all_reviews, seen = load_existing()
    if all_reviews:
        print(f"Loaded {len(all_reviews)} existing reviews from {OUTPUT_FILE}")

    # Fetch page 1 to get total counts
    print(f"Fetching first page: {PAGINATION_URL.format(1)}")
    first_page = fetch_page(ws_url, PAGINATION_URL.format(1))
    if not first_page:
        print("Failed to fetch the first page. Exiting.")
        return

    total_pages = get_total_pages(first_page)
    total_reviews = get_total_reviews(first_page)
    print(f"Total reviews: {total_reviews}, pages: {total_pages}")

    page_reviews = scrape_page(first_page)
    added = append_new(all_reviews, seen, page_reviews)
    print(f"Page 1: scraped {len(page_reviews)}, added {added} new (total: {len(all_reviews)})")

    for page_num in range(2, total_pages + 1):
        delay = random.uniform(2, 5)
        print(f"Waiting {delay:.1f}s before page {page_num}...")
        time.sleep(delay)

        url = PAGINATION_URL.format(page_num)
        print(f"Fetching page {page_num}: {url}")
        page = fetch_page(ws_url, url)

        if not page:
            print(f"  Failed to fetch page {page_num}, skipping.")
            continue

        page_reviews = scrape_page(page)
        added = append_new(all_reviews, seen, page_reviews)
        print(f"Page {page_num}: scraped {len(page_reviews)}, added {added} new (total: {len(all_reviews)})")

    print(f"\nDone! {len(all_reviews)} reviews in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
