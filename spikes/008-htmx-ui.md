# Decision #8 Spike: htmx vs Alpine for v2.1 UI

**Status**: ✅ Complete
**Date**: 2026-05-14
**Architecture Review**: `plans/v2_1-architecture-review.md` §8

## Current State

- `static/index.html` — minimal HTML/JS test harness with EventSource consumer
- No framework, no styling, no choice buttons
- Developers interact via curl or bare HTML page
- v2.1 demands: styled output, choice buttons, dark theme, basic image rendering

## Candidates

| | htmx | Alpine.js |
|---|---|---|
| Size | ~14KB | ~15KB |
| Paradigm | Hypermedia-driven (HTML from server) | Client-side reactive (JS components) |
| SSE support | Native (`hx-sse` extension) | Manual (custom JS) |
| Build step | None | None (both are script-tag libraries) |
| Learning curve | Low (HTML attributes) | Medium (JS directives) |
| Fit with TTA | Excellent — server already sends HTML via SSE | Moderate — adds client-side state management |

## Decision: htmx

### Why htmx wins

1. **Natural SSE fit**: TTA already streams HTML fragments via SSE. htmx's `hx-sse`
   extension consumes SSE events and swaps HTML directly into the DOM. Alpine
   requires writing a custom SSE consumer in JS.

2. **No client-side state**: The server owns all state (world, character, game).
   htmx keeps the server as the single source of truth. Alpine would introduce
   client-side state management that duplicates server state.

3. **Smaller migration path**: The existing `index.html` is already server-rendered
   HTML with SSE. htmx enhances this pattern — add `hx-sse` attributes to the
   existing DOM. Alpine would require rewriting the client as a reactive app.

4. **v3 plans**: React/Svelte is deferred to v3 when character sheet + map arrive.
   htmx is the right stepping stone — it upgrades the existing hypermedia pattern
   without committing to an SPA architecture.

### Integration pattern

```html
<!-- Current: raw EventSource -->
<div id="narrative"></div>
<script>
  const es = new EventSource('/api/v1/games/...');
  es.onmessage = (e) => { document.getElementById('narrative').innerHTML += e.data; };
</script>

<!-- v2.1: htmx SSE -->
<div hx-ext="sse" sse-connect="/api/v1/games/.../stream" sse-swap="narrative_token">
  <!-- Narrative text streams in automatically -->
</div>
<button hx-post="/api/v1/games/.../turns" hx-vals='{"input": "look around"}'>
  Look Around
</button>
```

### What htmx gives us for v2.1

| Feature | Implementation |
|---------|---------------|
| Styled text output | Server sends styled HTML fragments; htmx swaps them |
| Choice buttons | Server sends `<button>` elements with `hx-post` attributes |
| Dark theme | CSS classes on server-rendered HTML |
| Image rendering | Server sends `<img>` tags; htmx swaps them |
| Scene metadata | Server sends metadata as HTML; htmx swaps |

## Action

Add htmx as a script-tag dependency in `static/index.html`:

```html
<script src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"></script>
<script src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js"></script>
```

No npm, no build step, no pyproject.toml change. Just two script tags.
