# AI-Based 3D Molecule Visualizer 🎥🧪

An AI-powered system for **visualizing chemical molecules in 3D**, converting molecular data into interactive 3D models and enabling **experiential science learning** through visualization and voice-based interaction.

---

## 🚀 Project Overview

Understanding molecular structures through textbooks is often abstract and difficult.  
This project bridges that gap by generating **3D molecular models** from chemical data and enabling users to visualize, interact, and explore molecules in a more intuitive way.

The system integrates **Python automation, Blender scripting, and basic web interfaces** to support molecule generation, visualization, and interaction.

---

## ✨ Key Features

- 🧬 Generate molecular structures from XYZ data  
- 🎨 Export 3D molecule models using Blender automation  
- 🗣️ Voice-assisted interaction for user commands  
- 🌐 Web-based interface using HTML templates  
- 📦 Lightweight codebase (no large models or binaries committed)

---

## 🛠️ Tech Stack

- **Programming Language:** Python  
- **3D Tools:** Blender (Python scripting)  
- **Web:** HTML, CSS (Templates)  
- **AI / Logic:** Python-based processing  
- **Automation:** Blender scripting for GLB export  

> **Note:** You need to download an LLM model (Flan-T5) for the explanations. See [Requirements](#requirements).

---

## ⚙️ How it works

This is a Flask web app. Type a molecule name (for example `caffeine`) and it:

1. Looks up the molecule's SMILES string in `molecules_db.py`.
2. Builds a 3D structure with **RDKit** (one conformer, used for both atoms and bonds).
3. Generates a Blender script and runs **Blender** in the background to export a `.glb` model.
4. Shows the model in the browser (`<model-viewer>`) with an AI-written explanation (offline **Flan-T5**) and a "Speak" button.

---

## 📂 Project Structure

| File | Purpose |
|---|---|
| `main.py` | Flask app and routes (`/`, `/viewer/<name>`, `/outputs/<file>`) |
| `molecules_db.py` | The list of molecules and their SMILES |
| `generate_xyz.py` | Builds the 3D molecule with RDKit and writes `molecules/<name>.xyz` |
| `blender_script_gen.py` | Writes `molecules/<name>_blender.py` (spheres for atoms, cylinders for bonds) |
| `export_glb_blender.py` | Finds and runs Blender, which produces `outputs/<name>.glb` |
| `templates/` | HTML pages (`index.html`, `viewer.html`) |
| `model.py` | One-time download of Flan-T5 |

Generated files go to `molecules/` and `outputs/`.

<img width="330" height="341" alt="image" src="https://github.com/user-attachments/assets/a586da85-89af-420c-a1ab-99ee62739584" />

**Sample output:**

_(add a screenshot of the viewer here)_

---

## How many molecules can it generate?

**59 names, which is 58 different molecules.** `aspirin` and `acetylsalicylic acid` are the same molecule.
Any name that is not in the list returns "Invalid molecule name."

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
- [Blender](https://www.blender.org/download/) (4.x or newer). **It must be installed**, because the app calls `blender.exe`.
- Python packages:

```powershell
pip install flask rdkit transformers torch sentencepiece
```

- The Flan-T5 model in `models/flan-t5-base/`. If the folder is empty or missing, download it once (needs internet):

```powershell
python model.py
```

## How to run

```powershell
cd "E:\project\AI&ML\chemistry"

# Optional: only needed if Blender is not on PATH or not in C:\Program Files\Blender Foundation\
$env:BLENDER_PATH = "C:\Path\To\blender.exe"

python main.py
```

Open <http://127.0.0.1:5000>, type a molecule name and submit. Generation takes a few seconds because Blender runs in the background. The first start is slow while the T5 model loads.

Always start the app from the project folder, because it uses relative paths such as `models/`, `outputs/` and `molecules/`.

### Blender is found in this order
1. The `BLENDER_PATH` environment variable
2. `blender` on your PATH
3. The newest `C:\Program Files\Blender Foundation\Blender *\blender.exe`

If none exist, the app shows "Blender not found" with instructions.

### Debug mode
Off by default. For local development only: `$env:FLASK_DEBUG = "1"`

## Troubleshooting

- **"Blender not found"**: install Blender or set `BLENDER_PATH`.
- **"Blender Failed" in the console**: the Blender output is printed there. Look at the STDERR section.
- **"Invalid molecule name"**: the name is not in the list above (names are case-insensitive).
- **Model files missing**: run `python model.py`.
- **Explanations look odd**: Flan-T5-base is a small model, so treat its text as a rough draft.
