/* ============================================
   RedditRadar — Application Logic
   ============================================ */

(function () {
    'use strict';

    // --- DOM Elements ---
    const subredditInput = document.getElementById('subredditInput');
    const addBtn = document.getElementById('addBtn');
    const chipContainer = document.getElementById('chipContainer');
    const sortSelect = document.getElementById('sortSelect');
    const scrapeBtn = document.getElementById('scrapeBtn');
    const resultsSection = document.getElementById('resultsSection');

    // --- State ---
    let subreddits = [];

    // --- Helpers ---
    function sanitizeSubreddit(name) {
        return name.trim().replace(/^r\//, '').replace(/[^a-zA-Z0-9_]/g, '').toLowerCase();
    }

    function formatNumber(num) {
        if (num >= 1000000) return (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
        return num.toString();
    }

    function timeAgo(utcSeconds) {
        const now = Date.now() / 1000;
        const diff = now - utcSeconds;
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        if (diff < 2592000) return Math.floor(diff / 86400) + 'd ago';
        return Math.floor(diff / 2592000) + 'mo ago';
    }

    // --- Chip Management ---
    function addSubreddit(name) {
        const clean = sanitizeSubreddit(name);
        if (!clean || subreddits.includes(clean)) return;
        if (subreddits.length >= 10) return;

        subreddits.push(clean);
        renderChips();
        subredditInput.value = '';
        subredditInput.focus();
        updateScrapeBtn();
    }

    function removeSubreddit(name) {
        subreddits = subreddits.filter(s => s !== name);
        renderChips();
        updateScrapeBtn();
    }

    function renderChips() {
        chipContainer.innerHTML = subreddits.map(name => `
            <div class="chip">
                r/${name}
                <button class="chip-remove" data-name="${name}" title="Remove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                        <line x1="18" y1="6" x2="6" y2="18"/>
                        <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }

    function updateScrapeBtn() {
        scrapeBtn.disabled = subreddits.length === 0;
    }

    // --- SVG Icon Helpers ---
    const icons = {
        upvote: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 4l-8 8h5v8h6v-8h5z"/></svg>',
        comment: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
        user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
        empty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="8.5" cy="10.5" r="1.5" fill="currentColor"/><circle cx="15.5" cy="10.5" r="1.5" fill="currentColor"/><path d="M8 15c1.333 1.333 2.667 2 4 2s2.667-.667 4-2"/></svg>'
    };

    // --- Fetch Reddit Data ---
    async function fetchSubreddit(name, sort) {
        const url = `https://www.reddit.com/r/${name}/${sort}.json?limit=5&raw_json=1`;
        const response = await fetch(url, {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            if (response.status === 404) throw new Error(`r/${name} not found`);
            if (response.status === 403) throw new Error(`r/${name} is private`);
            throw new Error(`Failed to fetch r/${name} (${response.status})`);
        }

        const data = await response.json();

        if (!data.data || !data.data.children || data.data.children.length === 0) {
            throw new Error(`r/${name} has no posts`);
        }

        return data.data.children.map(child => child.data);
    }

    // --- Render Posts ---
    function renderPost(post, rank) {
        const thumbnail = post.thumbnail &&
            post.thumbnail !== 'self' &&
            post.thumbnail !== 'default' &&
            post.thumbnail !== 'nsfw' &&
            post.thumbnail !== 'spoiler' &&
            post.thumbnail.startsWith('http')
            ? `<img class="post-thumbnail" src="${post.thumbnail}" alt="" loading="lazy" onerror="this.style.display='none'">`
            : '';

        const flair = post.link_flair_text
            ? `<div class="post-flair">${post.link_flair_text}</div>`
            : '';

        return `
            <a class="post-card" href="https://www.reddit.com${post.permalink}" target="_blank" rel="noopener" title="Open on Reddit">
                <div class="post-rank">${rank}</div>
                <div class="post-content">
                    ${flair}
                    <div class="post-title">${post.title}</div>
                    <div class="post-meta">
                        <span class="post-meta-item meta-upvotes">
                            ${icons.upvote}
                            ${formatNumber(post.ups)}
                        </span>
                        <span class="post-meta-item meta-comments">
                            ${icons.comment}
                            ${formatNumber(post.num_comments)}
                        </span>
                        <span class="post-meta-item meta-author">
                            ${icons.user}
                            u/${post.author}
                        </span>
                        <span class="post-meta-item">
                            ${icons.clock}
                            ${timeAgo(post.created_utc)}
                        </span>
                    </div>
                </div>
                ${thumbnail}
            </a>
        `;
    }

    function renderSubredditBlock(name, posts) {
        return `
            <div class="subreddit-block">
                <div class="subreddit-header">
                    <h2><span>r/</span>${name}</h2>
                    <span class="post-count">${posts.length} posts</span>
                </div>
                <div class="post-list">
                    ${posts.map((post, i) => renderPost(post, i + 1)).join('')}
                </div>
            </div>
        `;
    }

    function renderError(name, message) {
        return `
            <div class="subreddit-block">
                <div class="subreddit-header">
                    <h2><span>r/</span>${name}</h2>
                </div>
                <div class="error-block">
                    ${icons.error}
                    <span>${message}</span>
                </div>
            </div>
        `;
    }

    function renderLoading() {
        return `
            <div class="loading-block">
                <div class="spinner"></div>
                <div class="loading-text">Scraping subreddits...</div>
            </div>
        `;
    }

    // --- Main Scrape Action ---
    async function scrape() {
        if (subreddits.length === 0) return;

        const sort = sortSelect.value;
        scrapeBtn.disabled = true;
        resultsSection.innerHTML = renderLoading();

        const results = [];

        for (const name of subreddits) {
            try {
                const posts = await fetchSubreddit(name, sort);
                results.push({ name, posts, error: null });
            } catch (err) {
                results.push({ name, posts: null, error: err.message });
            }
        }

        // Render results
        resultsSection.innerHTML = results.map(r => {
            if (r.error) return renderError(r.name, r.error);
            return renderSubredditBlock(r.name, r.posts);
        }).join('');

        // Stagger animations
        const blocks = resultsSection.querySelectorAll('.subreddit-block');
        blocks.forEach((block, i) => {
            block.style.animationDelay = `${i * 100}ms`;
        });

        scrapeBtn.disabled = false;
    }

    // --- Event Listeners ---
    addBtn.addEventListener('click', () => addSubreddit(subredditInput.value));

    subredditInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addSubreddit(subredditInput.value);
        }
    });

    chipContainer.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.chip-remove');
        if (removeBtn) {
            removeSubreddit(removeBtn.dataset.name);
        }
    });

    scrapeBtn.addEventListener('click', scrape);

    // --- Init ---
    resultsSection.innerHTML = `
        <div class="empty-state">
            ${icons.empty}
            <h3>Add subreddits to get started</h3>
            <p>Type a subreddit name above and press Enter or click +</p>
        </div>
    `;
})();
