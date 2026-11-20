import pytest
import trimesh
from rdkit import Chem

import main
from molecules_db import MOLECULE_DB


# ---- slugify: it keys molecules AND file names, so it must never pass path characters
@pytest.mark.parametrize("raw,expected", [
    ("Caffeine", "caffeine"),
    ("  Vitamin   C ", "vitamin c"),
    ("../../etc/passwd", "etcpasswd"),
    ("a/b\c", "abc"),
    ("<script>x</script>", "scriptxscript"),
    ("x" * 200, "x" * 60),
])
def test_slugify(raw, expected):
    assert main.slugify(raw) == expected


def test_every_builtin_smiles_parses():
    bad = [n for n, smi in MOLECULE_DB.items() if Chem.MolFromSmiles(smi) is None]
    assert bad == []


@pytest.mark.parametrize("name,formula,atoms", [
    ("water", "H2O", 3),
    ("methane", "CH4", 5),
    ("ethanol", "C2H6O", 9),
    ("carbon dioxide", "CO2", 3),
    ("benzene", "C6H6", 12),
])
def test_molecule_info_formula_and_atom_count(name, formula, atoms):
    info = main.molecule_info(name)
    assert info["formula"] == formula
    assert info["atoms"] == atoms
    assert info["bonds"] >= atoms - 1
    assert info["mass"] > 0


def test_molecule_info_has_everything_the_viewer_needs():
    info = main.molecule_info("caffeine")
    for key in ("title", "smiles", "formula", "mass", "elements", "colors", "molblock", "unknown_color"):
        assert key in info
    assert info["title"] == "Caffeine"
    symbols = {e["symbol"] for e in info["elements"]}
    assert symbols == {"C", "H", "N", "O"}
    assert set(info["colors"]) == symbols
    assert info["elements"][0]["symbol"] == "C"          # carbon first, then hydrogen
    assert info["elements"][1]["symbol"] == "H"
    assert "M  END" in info["molblock"]


def test_vibration_frames_are_valid_multi_record_sdf():
    sdf = main.vibration_frames("water", n=6)
    assert sdf.count("$$$$") == 6
    first, second = sdf.split("$$$$\n")[:2]
    assert first != second                                # atoms actually move


def test_glb_export_produces_a_loadable_model(tmp_path):
    mol = main.get_mol("ethanol")
    path = main.ensure_glb("ethanol", mol, force=True)
    assert path and path.endswith("ethanol.glb")
    scene = trimesh.load(path)
    assert scene.bounds is not None
    assert (scene.bounds[1] - scene.bounds[0]).min() > 0.5   # real 3D extent, not flat or empty


def test_ensure_glb_reuses_existing_file_unless_forced(tmp_path):
    mol = main.get_mol("water")
    main.ensure_glb("water", mol, force=True)
    before = (tmp_path / "outputs" / "water.glb").stat().st_mtime_ns
    main.ensure_glb("water", mol)                         # no force -> untouched
    assert (tmp_path / "outputs" / "water.glb").stat().st_mtime_ns == before


def test_blender_fallback_runs_only_when_trimesh_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "build_glb", lambda mol, name: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(main, "generate_blender_py", lambda mol, name: calls.append("script") or "s.py")
    monkeypatch.setattr(main, "run_blender_script", lambda path: calls.append("blender"))
    result = main.ensure_glb("water", main.get_mol("water"), force=True)
    assert calls == ["script", "blender"]
    assert result is None                                  # fake Blender wrote nothing -> reported as missing


def test_blender_failure_does_not_crash_the_request(monkeypatch):
    monkeypatch.setattr(main, "build_glb", lambda mol, name: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(main, "generate_blender_py", lambda mol, name: "s.py")
    monkeypatch.setattr(main, "run_blender_script", lambda path: (_ for _ in ()).throw(FileNotFoundError("no blender")))
    assert main.ensure_glb("water", main.get_mol("water"), force=True) is None


def test_glb_export_does_not_need_scipy(tmp_path):
    """Regression: on a clean install (Render, CI) scipy is absent and trimesh's default colour and
    normal handling needs it. The export must work with scipy blocked."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    script = (
        "import sys\n"
        "sys.modules['scipy'] = None\n"                     # any 'import scipy' now raises ImportError
        f"sys.path.insert(0, {str(repo)!r})\n"
        "from generate_xyz import build_molecule\n"
        "from glb_trimesh import build_glb\n"
        "build_glb(build_molecule('CCO', 'ethanol'), 'ethanol')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-800:]
    scene = trimesh.load(tmp_path / "outputs" / "ethanol.glb")
    assert scene.bounds is not None


def test_glb_keeps_element_colours_and_normals(tmp_path):
    mol = main.get_mol("water")
    path = main.ensure_glb("water", mol, force=True)
    scene = trimesh.load(path)
    geoms = list(scene.geometry.values())
    colours = {tuple(c[:3]) for g in geoms for c in g.visual.vertex_colors}
    assert (255, 13, 13) in colours                          # oxygen red
    assert (255, 255, 255) in colours                        # hydrogen white
    assert all(len(g.vertex_normals) == len(g.vertices) for g in geoms)
