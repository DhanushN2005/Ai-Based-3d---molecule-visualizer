import os
import traceback
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, send_from_directory

from molecules_db import MOLECULE_DB
from generate_xyz import build_molecule, write_xyz
from blender_script_gen import generate_blender_py
from export_glb_blender import run_blender_script

# LLM (Offline)
from transformers import T5Tokenizer, T5ForConditionalGeneration
import torch

# Load model and tokenizer once from local directory
MODEL_PATH = "models/flan-t5-base"
tokenizer = T5Tokenizer.from_pretrained(MODEL_PATH)
model = T5ForConditionalGeneration.from_pretrained(MODEL_PATH)

app = Flask(__name__)

molecule_db = MOLECULE_DB

# Molecule explanation generator using LLM
def explain_molecule(molecule: str) -> str:
    prompt = (
        f"You are a chemistry expert. Write a detailed explanation about the molecule '{molecule}'that a school student can easily understand, including:\n"
        f"- Its molecular structure and chemical formula\n"
        f"- Functional groups present\n"
        f"- Physical and chemical properties\n"
        f"- Common uses in real life or industry\n"
        f"- Any biological or environmental relevance\n\n"
        f"Start your explanation now:"
    )

    input_ids = tokenizer(prompt, return_tensors="pt").input_ids
    output = model.generate(
        input_ids,
        max_length=400,
        temperature=0.9,
        top_k=50,
        top_p=0.95,
        do_sample=True,
        num_return_sequences=1,
        repetition_penalty=1.3
    )
    explanation = tokenizer.decode(output[0], skip_special_tokens=True)
    return explanation

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            name = request.form['molecule'].strip().lower()
            if name in molecule_db:
                smiles = molecule_db[name]
                os.makedirs('outputs', exist_ok=True)

                mol = build_molecule(smiles, name)  # one conformer for everything
                write_xyz(mol, name)
                blender_script = generate_blender_py(mol, name)
                stale = f"outputs/{name}.glb"
                if os.path.exists(stale):
                    os.remove(stale)  # so an old file can't mask a failed export
                run_blender_script(blender_script)  # blocks until Blender exits

                glb_path = f"outputs/{name}.glb"
                if os.path.exists(glb_path):
                    print(f"✅ File created: {glb_path}")
                    return jsonify(success=True, viewer_url=f"/viewer/{quote(name)}")

                print(f"❌ GLB file not created: {glb_path}")
                return jsonify(success=False, error="Failed to generate 3D model.")
            else:
                return jsonify(success=False, error="Invalid molecule name.")
        except Exception as e:
            print("❌ Error:")
            traceback.print_exc()
            return jsonify(success=False, error=str(e))
    return render_template('index.html')

@app.route('/viewer/<molecule>')
def viewer(molecule):
    molecule = molecule.strip().lower()
    if molecule not in molecule_db:  # whitelist: blocks path traversal / injection
        return "Unknown molecule.", 404
    glb_file = f"outputs/{molecule}.glb"
    if not os.path.exists(glb_file):
        return f"File not found: {glb_file}", 404

    explanation = explain_molecule(molecule)
    return render_template("viewer.html", molecule=molecule, explanation=explanation)

@app.route('/outputs/<path:filename>')
def serve_outputs(filename):
    return send_from_directory("outputs", filename)

if __name__ == '__main__':
    # Never enable the Werkzeug debugger on a reachable server; opt in locally.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", use_reloader=False)
