# AI-Based 3D Molecule Visualizer 🎥🧪

An AI-powered system for **visualizing chemical molecules in 3D**, converting molecular data into interactive 3D models and enabling **experiential science learning** through visualization and voice-based interaction.

---

## 🚀 Project Overview

Understanding molecular structures through textbooks is often abstract and difficult.  
This project bridges that gap by generating **3D molecular models** from chemical data and enabling users to visualize, interact, and explore molecules in a more intuitive way.

The system integrates **Python automation, trimesh/Blender export, and basic web interfaces** to support molecule generation, visualization, and interaction.

---

## ✨ Key Features

- 🔎 **Any molecule**: 59 built-in molecules, plus anything on **PubChem** (dopamine, ibuprofen, vitamin C…)
- 🧬 **Live 3D viewer** (3Dmol.js): rotate, zoom, 4 draw styles, vibration animation, screenshot, fullscreen
- 🎨 **Full element colours** (Jmol/CPK) shared by the viewer, legend and `.glb` export
- 🏷️ **Structure notation in 3D**: name + formula floating above the molecule, colour-coded atom labels, and bond labels such as `C–H`, `C=O`, `C≡N`
- ⚖️ **Compare** two molecules side by side with a differences table and an AI summary
- 🎯 **Quiz mode**: identify molecules in 3D, recall formulas, count atoms
- 🤖 **AI explanation** and "Ask the AI teacher" (Groq), with sentence-highlighted text-to-speech
- 📦 Downloads: `.glb` (built with trimesh, Blender as fallback) and `.sdf`

See [FEATURES.md](FEATURES.md) for the roadmap and what could come next.

---

## 🛠️ Tech Stack

- **Programming Language:** Python  
- **3D Tools:** trimesh (default), Blender scripting (fallback)  
- **Web:** HTML, CSS (Templates)  
- **AI / Logic:** Python-based processing  
- **Automation:** Python GLB export  

> **Note:** Explanations use the free Groq API. You need a `GROQ_API_KEY`. See [Requirements](#requirements).

---

## ⚙️ How it works

This is a Flask web app. Type a molecule name (for example `caffeine`) and it:

1. Looks up the molecule's SMILES string in `molecules_db.py`.
2. Builds a 3D structure with **RDKit** (one conformer, used for both atoms and bonds).
3. Builds a `.glb` model with **trimesh** (pure Python). If that fails, it falls back to a generated Blender script run in the background.
4. Shows the model in the browser (`<model-viewer>`) with an AI-written explanation (**Groq** LLM) and a "Speak" button.

---

## 📂 Project Structure

| File | Purpose |
|---|---|
| `main.py` | Flask app: pages (`/`, `/viewer/<name>`, `/compare`, `/quiz`) and JSON APIs (`/api/ask`, `/api/compare`, `/api/quiz`, `/api/suggest`, `/api/frames/<name>`), PubChem lookup, rate limiting |
| `elements.py` | One colour table for every element (unknown elements are bright pink) |
| `static/js/molview.js` | Shared 3Dmol.js wrapper: styles, labels, bond notation, hover |
| `molecules_db.py` | The list of molecules and their SMILES |
| `generate_xyz.py` | Builds the 3D molecule with RDKit and writes `molecules/<name>.xyz` |
| `glb_trimesh.py` | Builds `outputs/<name>.glb` with trimesh (default) |
| `blender_script_gen.py` | Fallback: writes `molecules/<name>_blender.py` (spheres for atoms, cylinders for bonds) |
| `export_glb_blender.py` | Finds and runs Blender, which produces `outputs/<name>.glb` |
| `templates/` | HTML pages (`index.html`, `viewer.html`) |

Generated files go to `molecules/` and `outputs/`.

<img width="330" height="341" alt="image" src="https://github.com/user-attachments/assets/a586da85-89af-420c-a1ab-99ee62739584" />

**Sample output:**

_(add a screenshot of the viewer here)_

---

## How many molecules can it generate?

Any molecule PubChem knows, up to 80 heavy atoms (set `MAX_HEAVY_ATOMS` in `.env` to change it). PubChem needs internet; results are cached in `data/pubchem_cache.json` (git-ignored). The built-in list below works offline.

Built-in list:

**59 names, which is 58 different molecules.** `aspirin` and `acetylsalicylic acid` are the same molecule.

| Group | Molecules |
|---|---|
| Alkanes, alkenes, alkynes, aromatics | methane, ethane, propane, butane, pentane, hexane, ethene, ethyne, benzene |
| Alcohols | methanol, ethanol, propanol, butanol, isopropanol, glycerol |
| Acids | formic acid, acetic acid, propanoic acid, butanoic acid, benzoic acid |
| Amines | methylamine, ethylamine, aniline |
| Aldehydes and ketones | formaldehyde, acetaldehyde, acetone |
| Carbohydrates | glucose, fructose, sucrose |
| Amino acids | glycine, alanine, valine, leucine, phenylalanine, tryptophan |
| Inorganic | water, ammonia, carbon dioxide, nitric acid, sulfuric acid, phosphoric acid, hydrogen peroxide, ozone |
| Nucleobases | adenine, guanine, cytosine, uracil, thymine |
| Biological and drugs | cholesterol, caffeine, nicotine, aspirin, acetylsalicylic acid, paracetamol |
| Gases | oxygen, hydrogen, nitrogen, chlorine, fluorine |

**To add more:** add one line to `MOLECULE_DB` in `molecules_db.py` (`"name": "SMILES"`). Also add its formula to `formulaMap` in `templates/viewer.html`, or the page will show "Unknown" for the formula.

## Requirements

- Windows, Python 3.10+
- [Blender](https://www.blender.org/download/) is **optional**. Models are built with `trimesh` by default; Blender (2.8+, 4.x recommended) is only used as a fallback if that fails.
- Python packages:

```powershell
pip install -r requirements.txt
```

- A free [Groq](https://console.groq.com/keys) API key for the explanations (no model download needed).

### Configuration (`.env`)

Copy the example file and fill it in:

```powershell
copy .env.example .env
```

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | For explanations | none | Groq API key. Without it the 3D model still works and the explanation box says it is unavailable. |
| `GROQ_MODEL` | No | `openai/gpt-oss-20b` | Groq model used for explanations. |
| `BLENDER_PATH` | No | auto-detected | Full path to `blender.exe` if it is not on PATH or in `C:\Program Files\Blender Foundation\`. |
| `HOST` | No | `127.0.0.1` | Interface the server listens on. |
| `PORT` | No | `5000` | Port the server listens on. |
| `FLASK_DEBUG` | No | `0` | `1` enables debug mode. Local development only. |
| `MAX_HEAVY_ATOMS` | No | `80` | Largest PubChem molecule the app will build. |

`.env` is in `.gitignore`, so your key is never committed. On a hosting service, set these as environment variables or secrets instead of uploading `.env`.

## How to run

```powershell
cd "E:\project\AI&ML\chemistry"
python main.py
```

Open <http://127.0.0.1:5000>, type a molecule name and submit. Generation usually takes under a second.

Always start the app from the project folder, because it uses relative paths such as `outputs/` and `molecules/`.

### Blender fallback (optional)
If trimesh fails, the app looks for Blender in this order:
1. The `BLENDER_PATH` environment variable
2. `blender` on your PATH
3. The newest `C:\Program Files\Blender Foundation\Blender *\blender.exe`

If none exist, the app shows "Blender not found" with instructions.

### Debug mode
Off by default. For local development only: set `FLASK_DEBUG=1` in `.env`.

## Troubleshooting

- **"Blender not found"**: only appears if trimesh failed too. Check the console for the trimesh error, or install Blender / set `BLENDER_PATH`.
- **"Blender Failed" in the console**: the Blender output is printed there. Look at the STDERR section.
- **"not found in the built-in list or on PubChem"**: check the spelling, or try a common synonym. Names are case-insensitive.
- **"Too many requests"**: the built-in rate limit (per IP, per minute). Wait a minute.
- **Speak does nothing**: click the Speak button itself (browsers block speech without a click). The page shows the reason if the browser refuses.
- **Viewer is blank**: the page loads 3Dmol.js from a CDN, so it needs internet and WebGL.
- **Explanation unavailable**: set `GROQ_API_KEY` (see Requirements) and check the console for a Groq error.
- **Explanations look odd**: they are written by an LLM, so double-check facts.
