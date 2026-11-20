# Feature Roadmap

What the project does today, what is being added, and what could come next.
Each idea says **what** it is, **why** it matters, **how** to build it, and a rough **effort**.

Status key: ✅ done · 🚧 in this release · 📋 planned

---

## 1. Where the project is today

| Status | Feature |
|---|---|
| ✅ | 59 built-in molecules, 3D structure from RDKit (one conformer used everywhere) |
| ✅ | Live 3D viewer (3Dmol.js): rotate, zoom, 4 draw styles, labels, vibrate animation, screenshot, fullscreen |
| ✅ | Facts panel: formula, molar mass, atom and bond counts, per-element legend |
| ✅ | AI explanation and "Ask the AI teacher" (Groq), sentence-highlighted text-to-speech |
| ✅ | `.glb` export with trimesh (Blender as fallback), `.sdf` download |

---

## 2. In this release ✅ (built and tested)

### 2.1 PubChem search: any molecule, not just 59
- **What:** type any compound name (dopamine, ibuprofen, vitamin C) and get its 3D model.
- **Why:** the biggest limit of the app is the fixed list. PubChem has 100M+ compounds, so this turns a demo into a tool.
- **How:** PubChem's free PUG REST API returns a SMILES string for a name. RDKit embeds it in 3D, and the rest of the pipeline is unchanged. Results are cached on disk so each name is fetched once. Names are sanitised before they touch any file path, and very large molecules are refused.
- **Effort:** medium. **Needs:** internet access to `pubchem.ncbi.nlm.nih.gov`. No API key.

### 2.2 Quiz mode
- **What:** 10-question rounds: "Which molecule is this?" (shown in 3D), "What is the formula of X?", "How many oxygen atoms does X have?". Score, streak, review, best score saved in the browser.
- **Why:** it makes the app a learning tool for students instead of a viewer. Active recall teaches more than reading.
- **How:** the server builds questions from the molecule database; the browser shows them and keeps the score. Best score is stored in `localStorage`.
- **Effort:** medium.

### 2.3 Compare two molecules
- **What:** two molecules side by side in 3D, with a table of formula, mass, atoms, bonds and elements, plus an AI summary of the differences.
- **Why:** chemistry is about differences (ethanol vs methanol, glucose vs fructose). Seeing both at once makes them stick.
- **How:** two viewer instances and a facts table. Rotation can be synced. The AI paragraph comes from one Groq call.
- **Effort:** medium.

### 2.4 Full element colours
- **What:** every element has a colour (standard Jmol/CPK scheme). Unknown elements get a bright pink so they never look like carbon.
- **Why:** before, only 7 elements had colours and everything else was grey. The colours must also match between the live viewer, the legend and the `.glb` file.
- **How:** one colour table (`elements.py`) is the single source of truth for the viewer, legend and `.glb` export.
- **Effort:** small.

### 2.5 Structure notation in 3D
- **What:** the 3D scene shows the molecule's name and formula as an on-screen title, atoms labelled with colour-coded symbols, and bond labels such as `C–H`, `C=O`, `C≡N` placed on each bond. Single, double and triple bonds get different label colours.
- **Why:** it links the 3D shape to the textbook structure notation students must learn to read.
- **How:** 3Dmol.js labels, positioned at bond midpoints from the RDKit bond data. A selector switches between off, bond-order symbols (`–  =  ≡`) and element pairs (`C=O`).
- **Effort:** small–medium.
- **Limit:** labels exist in the live viewer and screenshots, not in the `.glb` file.

---

## 3. Next, ranked by value

### 3.1 Learning and teaching

| Priority | Feature | Why | How | Effort |
|---|---|---|---|---|
| High | **Structure drawing (Ketcher or JSME)** | Lets users build molecules PubChem does not have, and test their own ideas | Embed the editor, export SMILES, feed it to the same pipeline | Medium |
| High | **Functional-group highlighting** | The main idea in organic chemistry: find −OH, C=O, −NH₂ | RDKit SMARTS patterns, then colour the matched atoms in 3D | Medium |
| High | **Molecular properties** (polarity, logP, H-bond donors/acceptors, rotatable bonds) | Connects structure to behaviour (solubility, drug-likeness) | `rdkit.Chem.Descriptors`, show as a panel | Small |
| Medium | **Reaction viewer** (reactants to products, animated) | Reactions are what students struggle with most | RDKit reaction SMARTS plus frame interpolation in 3Dmol | Large |
| Medium | **Measurement tool** (bond length, angle, dihedral) | Makes VSEPR geometry visible (104.5° in water) | 3Dmol click selection plus label | Medium |
| Medium | **Electron density / electrostatic surface** | Shows polarity and where reactions happen | 3Dmol `addSurface` with partial charges from RDKit Gasteiger | Medium |
| Medium | **Orbitals and bond-angle (VSEPR) explainer** | Explains why the shape is what it is | Text from the AI plus an angle overlay | Medium |
| Low | **Flashcards with spaced repetition** | Efficient memorisation of names, formulas and groups | Simple scheduling in `localStorage` | Small |
| Low | **Classroom mode** (teacher sets a quiz, students join with a code) | Real classroom use | Needs accounts and a database | Large |

### 3.2 Users and sharing

| Priority | Feature | Why | How | Effort |
|---|---|---|---|---|
| High | **Shareable links and embeds** (`<iframe>` viewer) | Teachers paste a molecule into slides or an LMS | A minimal `/embed/<name>` page without chrome | Small |
| High | **Accounts, favourites and history** | Personal collections and quiz progress | Flask-Login or an OAuth provider plus SQLite/Postgres | Medium |
| Medium | **Leaderboard** | Motivation for quizzes | Needs accounts and server-side scoring | Medium |
| Medium | **Multi-language UI and explanations** | Reach students outside English | A language parameter in the AI prompt plus i18n strings | Medium |
| Low | **Export to PDF / printable study sheet** | Offline revision | Render the page to PDF or build a template | Medium |

### 3.3 3D, AR and VR

| Priority | Feature | Why | How | Effort |
|---|---|---|---|---|
| Medium | **AR in the browser** | See the molecule on a desk | The `.glb` already exists. Add `<model-viewer ar>` as a second tab | Small |
| Medium | **WebXR / VR headset view** | Immersive classroom demo | 3Dmol or three.js WebXR session | Large |
| Low | **Crystal and protein viewing** (PDB files, 100s of atoms) | Biology and materials classes | Load PDB IDs from RCSB, use cartoon style in 3Dmol | Medium |
| Low | **Real vibrational modes** (not random jiggle) | Accurate IR-spectrum teaching | Needs a quantum chemistry package (xtb, psi4) | Large |

### 3.4 Engineering and operations

| Priority | Feature | Why | How | Effort |
|---|---|---|---|---|
| **Critical** | **Rate limiting** — 🚧 basic in-memory limit per IP is done on the home form, `/api/ask`, `/api/compare`, `/api/quiz` and `/api/suggest`. Still needed: the viewer page (it can trigger PubChem + AI), and a shared store (Redis) once you run more than one worker | These endpoints spend your Groq quota and PubChem's rate limit | Flask-Limiter with Redis | Small |
| **Critical** | **Deployment** (Docker plus a free host) | Nobody can use it while it only runs on your PC | Dockerfile, gunicorn, secrets as environment variables | Small |
| High | **Automated tests and CI** | Safe changes. Today nothing is tested | pytest for molecule building, the GLB export, API validation; GitHub Actions | Medium |
| High | **Persistent cache** (SQLite) for molecules, AI text and PubChem results | Faster pages, fewer API calls, survives restarts | Replace the in-memory dicts | Medium |
| High | **Input validation and error pages** | Clear messages instead of tracebacks | Central error handlers | Small |
| Medium | **Background jobs** for slow molecules | Big molecules block a request | A task queue or a thread pool with polling | Medium |
| Medium | **Logging and monitoring** (Sentry, structured logs) | Know when something breaks in production | Add a logger and an error tracker | Small |
| Medium | **Accessibility** (keyboard use, screen-reader text, colour-blind palette) | Real products must be usable by everyone | ARIA labels, focus styles, an alternate palette | Medium |
| Low | **Offline mode (PWA)** | Use in classrooms with poor internet | Service worker plus a bundled 3Dmol | Medium |

---

## 4. Suggested order

1. **Done:** PubChem search, quiz, compare, full colours, 3D notation, basic rate limiting.
2. **Before going public:** rate limiting, Docker deployment, tests, persistent cache.
3. **Next:** functional-group highlighting, properties panel, share/embed links, structure drawing.
4. **Later:** accounts and leaderboards, reactions, AR/VR, multi-language.

## 5. Known limits to keep in mind

- PubChem needs internet. Names it does not recognise return "not found".
- The `.glb` file has no labels or animation. The live viewer does.
- The Groq free tier has request limits. Cached explanations help, but heavy use needs rate limiting and a paid plan.
- Quiz answers are checked in the browser, so a determined user can read them. Fine for learning, not for graded exams (those need server-side scoring).
