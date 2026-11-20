"""Build a .glb for an RDKit molecule with trimesh (no Blender needed)."""
import os

import numpy as np
import trimesh

from blender_script_gen import element_color  # same colours as the Blender path

ATOM_RADIUS = 0.3
BOND_RADIUS = 0.07
BOND_SHIFT = 0.15  # spacing between lines of a double/triple bond


def _rgba(el):
    return [int(c * 255) for c in element_color(el)]


def _colored(mesh, rgba):
    mesh.visual.face_colors = np.tile(rgba, (len(mesh.faces), 1))
    return mesh


def build_glb(mol, name: str) -> str:
    """Write outputs/<name>.glb from an RDKit mol that has a 3D conformer."""
    conf = mol.GetConformer()
    coords = []
    parts = []

    for atom in mol.GetAtoms():
        p = conf.GetAtomPosition(atom.GetIdx())
        pos = np.array([p.x, p.y, p.z])
        coords.append(pos)
        sphere = trimesh.creation.uv_sphere(radius=ATOM_RADIUS, count=[24, 24])
        sphere.apply_translation(pos)
        parts.append(_colored(sphere, _rgba(atom.GetSymbol())))

    bond_rgba = [150, 150, 150, 255]
    for bond in mol.GetBonds():
        start = coords[bond.GetBeginAtomIdx()]
        end = coords[bond.GetEndAtomIdx()]
        vec = end - start
        length = float(np.linalg.norm(vec))
        if length == 0:
            continue
        direction = vec / length
        count = max(1, int(bond.GetBondTypeAsDouble()))  # aromatic (1.5) -> single

        # Direction perpendicular to the bond, used to spread double/triple bonds.
        side = np.cross(direction, [0, 0, 1])
        if np.linalg.norm(side) < 1e-6:
            side = np.cross(direction, [1, 0, 0])
        side /= np.linalg.norm(side)

        rot = trimesh.geometry.align_vectors([0, 0, 1], direction)
        for i in range(count):
            offset = (i - (count - 1) / 2) * BOND_SHIFT
            cyl = trimesh.creation.cylinder(radius=BOND_RADIUS, height=length, sections=16)
            cyl.apply_transform(rot)
            cyl.apply_translation((start + end) / 2 + side * offset)
            parts.append(_colored(cyl, bond_rgba))

    os.makedirs("outputs", exist_ok=True)
    path = f"outputs/{name}.glb"
    trimesh.util.concatenate(parts).export(path)
    print(f"✅ GLB written with trimesh: {path}")
    return path
