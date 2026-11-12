# Contributing to JanusTower

Thanks for your interest. JanusTower is a **local, single-user, read-only** web app for Google Cloud
(Python backend, plain HTML/CSS/JS frontend assembled into one `index.html`). Issues and pull requests
are welcome at https://github.com/Nextmind-srl/janus-tower.

## Local setup

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Nextmind-srl/janus-tower
cd JanusTower
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install ruff
cp .env.example .env   # never commit your .env
python server.py       # http://localhost:8095
```

See the [README](./README.md) for creating your own OAuth client. Tests do not need Google credentials.

## Tests and lint

```bash
JANUSTOWER_DEMO=0 python -m unittest discover -s tests -v   # tests (standard library unittest; the demo is switched off so the tests exercise the real behaviour)
ruff check .                              # Python lint (configuration in pyproject.toml)
npm install && npm run lint               # ESLint on frontend/js (needs Node.js)
```

The same checks run in CI (`.github/workflows/ci.yml`) on Python 3.11 and 3.12.

## Changing the frontend

`index.html` is **generated**. Edit `frontend/` or `Design/*.css`, never `index.html`, then regenerate it:

```bash
python -c "import server; server.assemble_frontend_html('.', write_to_disk=True)"
```

`tests/test_app.py` fails when `index.html` is stale, and CI regenerates it and fails on any difference.

`Design/contratto_ui.json` is the machine-checked UI contract (DOM IDs, inline handlers, `data-*`
attributes, classes, table columns), verified by `tests/test_ui_contract.py`. **Only add to it**: do not
remove or rename contracted items. Escape every dynamic value put in HTML (`escapeHtml`, `jsArg`) and
insert HTML only through `setSafeHtml()`. See [AI_AGENT_CONTEXT.md](./AI_AGENT_CONTEXT.md) for the details.

## Project rules

- **Read-only towards Google Cloud.** No call that creates, changes or deletes anything in Google Cloud.
- **No personal data to external LLMs.** Scan results can contain user emails and identities; nothing of
  that kind may be sent to an external model service.
- **No secrets and no real data in the repository**: no tokens, keys, OAuth client secrets, real project
  IDs or emails, `data/` files or CSV exports. Use `.env.example` for new settings (empty value only).
- **Permissions are enforced everywhere.** Hiding a button is not enough: restrict the menu entry, the
  direct URL route and the server API endpoint.
- Keep changes small and focused; do not rename functions or IDs that are wired elsewhere, and do not
  reformat unrelated code.

## Commits and pull requests

- Use short, imperative commit messages with a type prefix, for example `fix(ui): ...`,
  `feat(costs): ...`, `docs: ...`, `chore: ...`, `test: ...`.
- Open an issue first for larger changes so the approach can be discussed.
- Fork, create a branch, and open a pull request using the template. Tests, `ruff` and the regenerated
  `index.html` must be in place before review.

## Security

Do not open a public issue for vulnerabilities: follow [SECURITY.md](./SECURITY.md)
(contact: info@nextmind.it).

## Conduct

Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md).
