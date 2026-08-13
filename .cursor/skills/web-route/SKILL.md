---
name: web-route
description: Adds or changes ArborDocs FastAPI routes, Jinja templates, and HTMX interactions with matching tests. Use for web UI, admin, OAuth, review queue, and portal work.
---

# Web Route

1. Read the closest existing route, template, and `tests/test_web_*.py`.
2. Determine whether the route requires a verified user, admin, or no login.
3. Keep the handler thin: validate input, call domain/pipeline code, return a template, partial, JSON response, or redirect.
4. Reuse dependencies from `app/web/deps.py` and rendering helpers from `app/web/templating.py`.
5. Put templates in `app/web/templates/`; use HTMX only for progressive enhancement.
6. Register a new router in `app/web/main.py` when needed.
7. Add behavior-focused tests and run the focused test file.

Never introduce React, Next.js, or a frontend build. Portal routes may expose
only approved decision states; `proposed` decisions remain in the review flow.
