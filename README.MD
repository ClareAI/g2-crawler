# G2 Reviews Crawler

Crawls product reviews from [G2.com](https://www.g2.com) and saves them as structured JSON. Uses your real Chrome browser (via CDP) so anti-bot protections are handled naturally — no proxies, cookies, or stealth tricks needed.

## How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│  1. You launch Chrome with --remote-debugging-port=9222          │
│  2. The script connects to Chrome via CDP (DevTools Protocol)    │
│  3. It navigates Chrome to each G2 review page                   │
│  4. Chrome renders the page normally (handles DataDome/anti-bot) │
│  5. The script reads the rendered HTML and parses reviews        │
│  6. Reviews are deduplicated and saved incrementally to JSON     │
└──────────────────────────────────────────────────────────────────┘
```

### Architecture

```
  Script (CDP client)              Chrome Browser
  ┌──────────────────┐            ┌──────────────────┐
  │ Page.navigate    │───────────▶│ loads G2 page    │
  │ to each review   │            │ passes anti-bot  │
  │ page URL         │            │ renders HTML     │
  │                  │◀───────────│                  │
  │ reads outerHTML  │            │ port 9222        │
  └──────────────────┘            └──────────────────┘
           │
           ▼
  ┌──────────────────┐
  │ Scrapling parser │
  │ CSS selectors    │──▶ reviews.json
  │ (itemprop based) │
  └──────────────────┘
```

G2 uses DataDome anti-bot protection which blocks headless browsers and HTTP
clients. By driving your real Chrome, the script avoids this entirely — Chrome
is already a trusted browser with a valid session.

### What Gets Extracted

Each review is saved with these fields (see `example_output.json`):

| Field             | Description                              |
|-------------------|------------------------------------------|
| `review_id`       | G2's internal review identifier          |
| `author`          | Reviewer name (as shown on G2)           |
| `job_title`       | Reviewer's job title                     |
| `company_size`    | Company size bucket                      |
| `date`            | Publication date (ISO format)            |
| `rating`          | Star rating (1.0–5.0)                    |
| `title`           | Review title                             |
| `likes`           | "What do you like best" section          |
| `dislikes`        | "What do you dislike" section            |
| `problems_solving`| "What problems is it solving" section    |

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Launch Chrome with remote debugging

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

### 3. Run the crawler

```bash
python crawl_g2_reviews.py
```

The script will:
1. Connect to Chrome via CDP on port 9222
2. Navigate to each review page (Chrome handles anti-bot naturally)
3. Read the rendered HTML and parse reviews with CSS selectors
4. Save reviews incrementally to a JSON file (safe to interrupt and resume)

## Configuration

All settings can be overridden with environment variables:

| Variable          | Default              | Description                        |
|-------------------|----------------------|------------------------------------|
| `G2_PRODUCT_SLUG` | `wati`               | G2 product slug from the URL       |
| `G2_OUTPUT_FILE`  | `{slug}_reviews.json`| Output JSON file path              |
| `G2_CDP_PORT`     | `9222`               | Chrome DevTools Protocol port      |
| `G2_PAGE_WAIT`    | `4`                  | Seconds to wait for page render    |

### Example: crawl a different product

```bash
G2_PRODUCT_SLUG=slack python crawl_g2_reviews.py
```

## Resumability

The crawler supports incremental crawling. If interrupted, just run it again — it loads previously saved reviews from the output JSON and skips duplicates based on `review_id`.

## Files

| File                   | Tracked | Description                            |
|------------------------|---------|----------------------------------------|
| `crawl_g2_reviews.py`  | Yes     | Main crawler script                    |
| `requirements.txt`     | Yes     | Python dependencies                    |
| `example_output.json`  | Yes     | Sample output showing the data format  |
| `*_reviews.json`       | No      | Crawled review data                    |
