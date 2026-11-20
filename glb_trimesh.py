"""Build a .glb for an RDKit molecule with trimesh (no Blender needed).

Colours and normals are set per vertex, on purpose. If they are left to trimesh, exporting converts
face colours and computes normals through scipy, which is a large extra install the app does not
otherwise need. For spheres and cylinders the exact normals are simple, and they shade smoothly.
"""
import logging
import os

import numpy as np
import trimesh

from blender_script_gen import element_color  # same colours as the Blender path

log = logging.getLogger("chemverse")

ATOM_RADIUS = 0.3
BOND_RADIUS = 0.07
BOND_SHIFT = 0.15  # spacing between lines of a double/triple bond
BOND_RGBA = [150, 150, 150, 255]


def _rgba(el):
    return [int(c * 255) for c in element_color(el)]


def _finish(mesh, rgba, normals):
    """Attach per-vertex colours and unit normals (no scipy needed to export)."""
    mesh.vertex_normals = normals
    mesh.visual.vertex_colors = np.tile(rgba, (len(mesh.vertices), 1))
    return mesh


def _atom(pos, rgba):
    sphere = trimesh.creation.uv_sphere(radius=ATOM_RADIUS, count=[24, 24])
    normals = sphere.vertices / ATOM_RADIUS             # a sphere's normal points away from its centre
    sphere.apply_translation(pos)
    return _finish(sphere, rgba, normals)


def _bond_line(start, end, direction, length, offset_vec, rot):
    cyl = trimesh.creation.cylinder(radius=BOND_RADIUS, height=length, sections=16)
    cyl.apply_transform(rot)
    centre = (start + end) / 2 + offset_vec
    cyl.apply_translation(centre)
    # radial normals around the bond axis (the end caps sit inside the atom spheres, so they are never seen)
    rel = cyl.vertices - centre
    radial = rel - np.outer(rel @ direction, direction)
    norm = np.linalg.norm(radial, axis=1, keepdims=True)
    return _finish(cyl, BOND_RGBA, radial / np.where(norm == 0, 1, norm))


def build_glb(mol, name: str) -> str:
    """Write outputs/<name>.glb from an RDKit mol that has a 3D conformer."""
    conf = mol.GetConformer()
    coords = []
    parts = []

    for atom in mol.GetAtoms():
        p = conf.GetAtomPosition(atom.GetIdx())
        pos = np.array([p.x, p.y, p.z])
        coords.append(pos)
        parts.append(_atom(pos, _rgba(atom.GetSymbol())))

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
            parts.append(_bond_line(start, end, direction, length, side * offset, rot))

    os.makedirs("outputs", exist_ok=True)
    path = f"outputs/{name}.glb"
    trimesh.util.concatenate(parts).export(path)
    log.info("GLB written with trimesh: %s", path)
    return path
