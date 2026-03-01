---
name: web-scraping
description: "Builds web scrapers and data extraction tools from websites, APIs, and feeds. Use when the user asks to scrape a website, extract data from a page, build a crawler, fetch API data, parse HTML, or automate data collection."
---

# Web Scraping

## When to use this skill

- The user asks to scrape, crawl, or extract data from a website
- The user wants to fetch data from a public API (Reddit, GitHub, HN, etc.)
- The user needs to parse HTML, JSON, or RSS feeds
- The user wants to automate data collection from web sources
- The user mentions "scraper", "crawler", or "data extraction"

## Workflow

### Pre-Scrape Checklist

Before writing any code, answer these:

- [ ] **What data?** — Identify the exact fields to extract
- [ ] **What source?** — URL, API endpoint, or feed
- [ ] **What format?** — JSON, CSV, HTML table, or display in UI
- [ ] **Has an API?** — Always prefer a public API/JSON endpoint over HTML scraping
- [ ] **Rate limits?** — Check for throttling, `robots.txt`, or ToS restrictions
- [ ] **Auth needed?** — API key, OAuth, or cookies required?

### Strategy Selection

Pick the right approach based on the source:

| Source Type | Strategy | Tools |
| :--- | :--- | :--- |
| **Public JSON API** | Direct fetch | `fetch()`, `axios`, `requests` |
| **Static HTML** | Parse DOM | `cheerio`, `BeautifulSoup`, `DOMParser` |
| **JS-rendered SPA** | Headless browser | `puppeteer`, `playwright`, `selenium` |
| **RSS/Atom feed** | XML parse | `rss-parser`, `feedparser`, built-in XML |
| **CSV/file download** | HTTP + parse | `fetch` + `csv-parse`, `pandas` |

> **Rule:** Always check for a JSON API first. Append `.json` (Reddit), use `/api/` routes, or check network tab. HTML scraping is a last resort.

### Implementation Steps

1. **Fetch the data**
   - Use the simplest method that works (fetch > axios > puppeteer)
   - Set a proper `User-Agent` header
   - Implement timeouts and error handling

2. **Parse the response**
   - JSON → access keys directly
   - HTML → use a DOM parser, select with CSS selectors
   - Handle missing/null fields gracefully

3. **Transform and clean**
   - Normalize dates, numbers, and text
   - Strip HTML tags from text content
   - Deduplicate results if paginating

4. **Output the results**
   - Render in UI (cards, tables) for visual apps
   - Write to file (JSON, CSV) for data pipelines
   - Return structured data for API endpoints

## Instructions

### Browser-Based Scrapers (HTML/CSS/JS)

For client-side scrapers that run in the browser:

```javascript
// Fetch from a public JSON API
async function scrape(url) {
    const response = await fetch(url, {
        headers: { 'Accept': 'application/json' }
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}
```

**Key patterns:**

- Use `fetch()` with proper error handling (`response.ok` check)
- Use `async/await` — never raw `.then()` chains for readability
- Add loading states and error UI for the user
- Respect CORS — if blocked, the API doesn't allow browser access; suggest a server proxy

### Server-Side Scrapers (Node.js / Python)

For backend scrapers:

```python
# Python with requests + BeautifulSoup
import requests
from bs4 import BeautifulSoup

def scrape(url, selector):
    headers = {'User-Agent': 'MyScraper/1.0'}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    return [el.get_text(strip=True) for el in soup.select(selector)]
```

```javascript
// Node.js with cheerio
import * as cheerio from 'cheerio';

async function scrape(url, selector) {
    const res = await fetch(url, {
        headers: { 'User-Agent': 'MyScraper/1.0' }
    });
    const html = await res.text();
    const $ = cheerio.load(html);
    return $(selector).map((_, el) => $(el).text().trim()).get();
}
```

### Common API Patterns

| Platform | Endpoint Pattern | Auth |
| :--- | :--- | :--- |
| Reddit | `https://www.reddit.com/r/{sub}/{sort}.json?limit=N` | None |
| Hacker News | `https://hacker-news.firebaseio.com/v0/topstories.json` | None |
| GitHub | `https://api.github.com/repos/{owner}/{repo}` | Optional token |
| Wikipedia | `https://en.wikipedia.org/api/rest_v1/page/summary/{title}` | None |
| JSONPlaceholder | `https://jsonplaceholder.typicode.com/{resource}` | None |

### Error Handling

Always handle these failure modes:

```javascript
try {
    const data = await scrape(url);
} catch (err) {
    if (err.message.includes('404')) {
        // Resource not found — show user-friendly message
    } else if (err.message.includes('403')) {
        // Forbidden — likely blocked or private
    } else if (err.message.includes('429')) {
        // Rate limited — implement backoff
    } else if (err.name === 'TypeError') {
        // Network/CORS error — suggest server-side proxy
    }
}
```

### Rate Limiting & Politeness

- Add delays between requests: `await sleep(1000)` (1 req/sec minimum)
- Check `robots.txt` before scraping HTML
- Cache responses to avoid re-fetching unchanged data
- Set a descriptive `User-Agent` string

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
| :--- | :--- | :--- |
| Scraping HTML when API exists | Fragile, breaks on redesign | Check for JSON API first |
| No error handling | Silent failures | Wrap all fetches in try/catch |
| No rate limiting | Gets IP banned | Add delays between requests |
| Hardcoded selectors everywhere | Brittle | Extract selectors to config |
| Ignoring `robots.txt` | Ethical/legal risk | Always check before scraping |

## Resources

- [`resources/api-endpoints.md`](resources/api-endpoints.md) — Curated list of public APIs with endpoints and auth requirements
