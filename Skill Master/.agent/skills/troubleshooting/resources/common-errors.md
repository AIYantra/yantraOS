# Common Error Patterns & Solutions

Quick-reference for frequently encountered errors and their typical resolutions.

---

## HTTP / API Errors

### 400 Bad Request
- **Cause:** Malformed request body, missing required fields, invalid data types
- **Fix:** Validate request payload against API schema; check Content-Type header

### 401 Unauthorized
- **Cause:** Missing, expired, or invalid auth token
- **Fix:** Refresh token; verify API key; check token expiration

### 403 Forbidden
- **Cause:** Valid auth but insufficient permissions
- **Fix:** Check user roles/permissions; verify resource ownership; check CORS policy

### 404 Not Found
- **Cause:** Wrong URL, deleted resource, typo in route
- **Fix:** Verify endpoint URL; check if resource exists; review routing config

### 429 Too Many Requests
- **Cause:** Rate limit exceeded
- **Fix:** Implement exponential backoff; cache responses; check rate limit headers

### 500 Internal Server Error
- **Cause:** Unhandled exception on server
- **Fix:** Check server logs for stack trace; reproduce locally

### 502 Bad Gateway
- **Cause:** Upstream server unreachable (proxy/load balancer can't reach backend)
- **Fix:** Check if backend service is running; verify ports and health checks

### 503 Service Unavailable
- **Cause:** Server overloaded or in maintenance
- **Fix:** Check resource usage (CPU, memory, connections); scale or wait

---

## Database Errors

### Connection Refused
- **Cause:** Database not running, wrong host/port, firewall
- **Fix:** Verify connection string; check service status; test with `ping`/`telnet`

### Authentication Failed
- **Cause:** Wrong credentials, expired password, IP not whitelisted
- **Fix:** Verify credentials in env/config; check database user permissions

### Connection Pool Exhausted
- **Cause:** Too many open connections; connections not being released
- **Fix:** Increase pool size; ensure connections close in `finally` blocks; check for leaks

### Query Timeout
- **Cause:** Slow query, missing index, table locks, large result set
- **Fix:** Run `EXPLAIN` on query; add indexes; paginate results; check for locks

### "MySQL server has gone away"
- **Cause:** Connection idle too long; packet too large; server restarted
- **Fix:** Implement connection keep-alive/reconnect; increase `wait_timeout`; check `max_allowed_packet`

---

## JavaScript / Frontend Errors

### "Cannot read property of undefined"
- **Cause:** Accessing property on null/undefined object
- **Fix:** Add null checks; use optional chaining (`?.`); verify data loading state

### "CORS policy" blocked
- **Cause:** Server not sending correct CORS headers
- **Fix:** Add `Access-Control-Allow-Origin` header on server; check preflight (OPTIONS) handling

### "Module not found"
- **Cause:** Package not installed, wrong import path, case sensitivity
- **Fix:** Run `npm install`; verify import path; check `package.json`

### Unhandled Promise Rejection
- **Cause:** Missing `.catch()` or try-catch around `await`
- **Fix:** Add error handling to all async operations

---

## Deployment / Build Errors

### "Out of memory" during build
- **Cause:** Node heap limit, too many assets, circular deps
- **Fix:** Increase `--max-old-space-size`; split bundles; check for circular imports

### Environment variable not found
- **Cause:** Missing from `.env`, not set in CI/CD, not passed to container
- **Fix:** Verify env file loaded; check CI/CD config; verify Docker `--env` flags

### "Permission denied"
- **Cause:** File permissions, user context, SELinux, container security
- **Fix:** Check file ownership; run with correct user; adjust permissions

---

## Performance Issues

### Slow Page Load
- **Check:** Network tab waterfall, bundle size, render-blocking resources
- **Fix:** Code-split; lazy load; compress assets; add caching headers

### N+1 Query Problem
- **Check:** Database query log — hundreds of similar queries
- **Fix:** Use eager loading / `JOIN`; batch queries; add DataLoader pattern

### Memory Leak
- **Check:** Memory usage grows over time; never returns to baseline
- **Fix:** Check for growing arrays/maps; remove event listeners; clear intervals
