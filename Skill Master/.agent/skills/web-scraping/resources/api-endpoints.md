# Public API Endpoints

Curated list of free, public APIs useful for scraping projects. No API key required unless noted.

---

## Social & Content

| Platform | Endpoint | Data | Auth |
| :--- | :--- | :--- | :--- |
| **Reddit** | `reddit.com/r/{sub}/{sort}.json?limit=N` | Posts, comments, user data | None |
| **Hacker News** | `hacker-news.firebaseio.com/v0/topstories.json` | Story IDs, items, users | None |
| **Wikipedia** | `en.wikipedia.org/api/rest_v1/page/summary/{title}` | Article summaries | None |
| **Open Library** | `openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json` | Book metadata | None |

### Reddit Endpoints

```
# Top posts from a subreddit
GET https://www.reddit.com/r/{subreddit}/top.json?limit=5&t=day

# Hot posts
GET https://www.reddit.com/r/{subreddit}/hot.json?limit=10

# Search posts
GET https://www.reddit.com/r/{subreddit}/search.json?q={query}&restrict_sr=1

# User posts
GET https://www.reddit.com/user/{username}/submitted.json?limit=10

# Subreddit info
GET https://www.reddit.com/r/{subreddit}/about.json
```

### Hacker News Endpoints

```
# Top 500 story IDs
GET https://hacker-news.firebaseio.com/v0/topstories.json

# Single item (story, comment, job)
GET https://hacker-news.firebaseio.com/v0/item/{id}.json

# User profile
GET https://hacker-news.firebaseio.com/v0/user/{username}.json

# New stories
GET https://hacker-news.firebaseio.com/v0/newstories.json
```

---

## Developer Tools

| Platform | Endpoint | Data | Auth |
| :--- | :--- | :--- | :--- |
| **GitHub** | `api.github.com/repos/{owner}/{repo}` | Repos, issues, PRs | Optional token |
| **npm Registry** | `registry.npmjs.org/{package}` | Package metadata | None |
| **PyPI** | `pypi.org/pypi/{package}/json` | Python package info | None |
| **crates.io** | `crates.io/api/v1/crates/{name}` | Rust crate info | None |

### GitHub Endpoints

```
# Repo info
GET https://api.github.com/repos/{owner}/{repo}

# Repo contents
GET https://api.github.com/repos/{owner}/{repo}/contents/{path}

# Search code
GET https://api.github.com/search/code?q={query}+repo:{owner}/{repo}

# User repos
GET https://api.github.com/users/{username}/repos?sort=stars

# Rate limit: 60 req/hr unauthenticated, 5000/hr with token
```

---

## Data & Reference

| Platform | Endpoint | Data | Auth |
| :--- | :--- | :--- | :--- |
| **JSONPlaceholder** | `jsonplaceholder.typicode.com/{resource}` | Fake REST data (testing) | None |
| **REST Countries** | `restcountries.com/v3.1/all` | Country info | None |
| **Open Meteo** | `api.open-meteo.com/v1/forecast?latitude=X&longitude=Y` | Weather forecasts | None |
| **CoinGecko** | `api.coingecko.com/api/v3/coins/markets?vs_currency=usd` | Crypto prices | None |
| **Exchange Rates** | `open.er-api.com/v6/latest/USD` | Currency rates | None |

---

## Media

| Platform | Endpoint | Data | Auth |
| :--- | :--- | :--- | :--- |
| **Unsplash** | `api.unsplash.com/photos/random` | Random photos | API key |
| **OMDb** | `omdbapi.com/?t={title}&apikey={key}` | Movie info | API key (free tier) |
| **iTunes Search** | `itunes.apple.com/search?term={query}&media=music` | Music/podcasts | None |

---

## Tips

- **Always add `&raw_json=1`** to Reddit URLs to get unescaped HTML
- **GitHub rate limit** is 60/hr without auth — add `Authorization: token {PAT}` for 5000/hr
- **CORS:** Most APIs work server-side but not all work from the browser; use a proxy if blocked
- **Pagination:** Check for `after`, `next`, `offset`, or `page` params in API responses
