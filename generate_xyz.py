import os

from rdkit import Chem  # type: ignore
from rdkit.Chem import AllChem  # type: ignore


def build_molecule(smiles: str, name: str = ""):
    """Parse SMILES, add hydrogens and embed ONE 3D conformer.

    The returned mol is the single source of truth for atoms, coordinates and
    bonds, so the XYZ file and the Blender script can never disagree.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES string: {smiles}")

    mol = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(mol, randomSeed=42) != 0:
        raise RuntimeError("Embedding failed for molecule: " + name)

    # Returns 0 if converged, 1 if more iterations needed, -1 if no force field
    # parameters. Atoms like O3 or F2 may lack UFF terms; that's not fatal.
    if AllChem.UFFOptimizeMolecule(mol, maxIters=1000) != 0:
        print("⚠️ Warning: Optimization not fully converged.")
    return mol


def write_xyz(mol, name: str) -> str:
    conf = mol.GetConformer()
    atoms = []
    for atom in mol.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        atoms.append(f"{atom.GetSymbol()} {pos.x:.4f} {pos.y:.4f} {pos.z:.4f}")

    os.makedirs("molecules", exist_ok=True)
    xyz_path = f"molecules/{name}.xyz"
    with open(xyz_path, "w") as f:
        f.write(f"{len(atoms)}\n{name}\n" + "\n".join(atoms) + "\n")

    print(f"✅ XYZ written: {xyz_path}")
    return xyz_path


def generate_xyz(smiles: str, name: str) -> str:
    """Backwards-compatible helper: build + write in one call."""
    return write_xyz(build_molecule(smiles, name), name)
