# Portfolio Plan: ChemVerse3D for a Full-Stack Role

Goal: when a recruiter or interviewer opens this project, they should see a **live product**, **trustworthy engineering** and **clear reasoning**.
Status key: `[x]` done · `[ ]` to do · `(you)` needs you, because it uses your accounts.

---

## What a full-stack interviewer looks for

| They check | Where this project shows it |
|---|---|
| Frontend skill | Interactive 3D viewer, cover page, quiz, compare page, responsive layout |
| Backend and API design | Flask routes, JSON APIs, validation, rate limiting, caching |
| Data and persistence | PubChem cache today; database in Phase 3 |
| Third-party integration | PubChem REST, Groq LLM, browser Speech API |
| Security thinking | Input slugging, size limits, SRI, CSP and security headers, rate limits |
| Testing and CI | pytest suite, GitHub Actions, linting |
| DevOps | Dockerfile, Render blueprint, health check, environment-based config |
| Communication | README, architecture doc, case study |

---

## Phase 1: Look finished (2-3 days)

- [x] README: badges, screenshots, features, how to run, deploy steps
- [x] Architecture diagram (Mermaid, renders on GitHub) and `docs/ARCHITECTURE.md`
- [x] Screenshots of cover, viewer (bond notation), compare and quiz in `docs/screenshots/`
- [ ] (you) **Deploy on Render** and paste the live URL at the top of the README
- [ ] (you) **Rotate the Groq key**; it appeared in a terminal earlier. Keep it only in Render's environment settings
- [ ] (you) Link the live demo from your portfolio (dhanushnataraj.netlify.app)

## Phase 2: Engineering quality (4-5 days)

- [x] Automated tests with pytest (molecules, GLB export, Blender fallback, APIs, PubChem failures, rate limiting, security headers)
- [x] Linting with ruff
- [x] GitHub Actions CI: lint, tests with coverage, Docker build (written; the workflow has not run yet, and the Dockerfile has not been built locally because Docker was not running)
- [x] Dockerfile and `.dockerignore` (non-root user, health check)
- [x] Structured logging (`LOG_LEVEL`), replacing `print` statements
- [x] Proper error pages (HTML for pages, JSON for `/api`)
- [x] Rate limit on PubChem lookups (protects the external API and CPU)
- [x] Security headers and a Content Security Policy
- [x] `/healthz` endpoint for the host and Docker health checks

## Phase 3: Depth features (about 1 week). Pick 2 or 3

- [x] Persistent cache in SQLite/Postgres (PubChem molecules and AI explanations)
- [x] Accounts and favourites (auth, CSRF, hashed passwords, database). Quiz attempts are stored; a personal history page is not built yet
- [x] Server-side quiz scoring and a leaderboard (answers never reach the browser)
- [ ] Functional-group highlighting (RDKit SMARTS) and a properties panel
- [ ] Shareable `/embed/<name>` page

## Phase 4: Interview preparation (about 2 days)

- [ ] One-page case study (`docs/CASE_STUDY.md`): problem, architecture, trade-offs, what went wrong, next steps
- [ ] 2-minute demo script and a 60-second elevator pitch
- [ ] Practise the questions below out loud

---

## Interview talking points (real decisions made in this project)

| Decision | Why |
|---|---|
| Blender replaced by trimesh, Blender kept as fallback | Blender is a large install that free hosts cannot run. trimesh is pure Python and builds a model in milliseconds |
| Flan-T5 replaced by the Groq API | Removed a ~1 GB model and torch; the app now fits a 512 MB host |
| 3Dmol.js live rendering instead of only baked `.glb` | Labels, bond notation and animation come free in the browser; the `.glb` is kept for download and AR |
| One RDKit conformer for viewer, `.sdf` and `.glb` | Atoms and bonds can never disagree between outputs |
| Names slugged before touching file paths | PubChem names are user input; this blocks path traversal |
| Accounts in a SQL database through SQLAlchemy | Works on SQLite locally and any SQLAlchemy URL (Postgres) in production, with no code change |
| Server-side quiz scoring | The browser never receives answers or sends a score, so the leaderboard cannot be trivially faked |
| Single gunicorn worker, in-memory limiter and caches | Simple and correct for one process; the shared store (Redis) is the documented next step |
| Groq model retired mid-project | Model ID is an environment variable; the app degrades gracefully when the AI is unavailable |

## Likely questions and short answers

- **What breaks at 1,000 users?** The in-memory caches and limiter (per process), the single worker and the Groq quota. Fix: Redis, more workers, a task queue and a CDN.
- **How do you handle untrusted input?** Slugging, a heavy-atom limit, rate limits, validation on every API and a CSP.
- **How do you know it works?** pytest suite on every push in CI, plus manual browser checks.
- **Why not a SPA framework?** The pages are small and server-rendered; plain JS keeps the build step at zero and deploys fast. A framework becomes worthwhile when state grows (accounts, dashboards).
- **What would you do next?** Accounts and a database, server-side quiz scoring, then Redis-backed limits.

## Tailoring for specific roles

- **Frontend-leaning:** polish accessibility (keyboard, screen reader, colour-blind palette) and mobile; talk about the 3D viewer.
- **Backend-leaning:** lead with the database, API design, caching and tests.
- **AI-leaning:** add prompt evaluation and talk about the Groq integration and its fallback.

## Honest limits to state up front

State such as caches and rate limits is in memory (one process); the `.glb` has no labels; the leaderboard has no timer or anti-replay rules; Postgres was checked by hand against Neon but is not part of the automated tests; there are no schema migrations. Present these as the roadmap, not as finished work.
