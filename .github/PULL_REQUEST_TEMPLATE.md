## What and why

<!-- Short description of the change and the reason for it. -->

## Checklist

- [ ] `python -m unittest discover -s tests` passes
- [ ] `ruff check .` passes
- [ ] If I touched `frontend/` or `Design/*.css`, `index.html` was regenerated with `server.assemble_frontend_html('.', write_to_disk=True)` (never edited by hand)
- [ ] No real data and no secrets (tokens, keys, project IDs, emails, `data/` files, CSV exports) in the diff
- [ ] `Design/contratto_ui.json` only received additions (no contracted ID, handler, attribute, class or column removed)
- [ ] Google Cloud access stays read-only, and permission restrictions are enforced on the route and the API, not only in the UI
