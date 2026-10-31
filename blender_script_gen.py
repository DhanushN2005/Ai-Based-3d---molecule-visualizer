def element_color(el):
    colors = {
        'H': (1, 1, 1, 1),
        'C': (0.2, 0.2, 0.2, 1),
        'O': (1, 0, 0, 1),
        'N': (0, 0, 1, 1),
        'S': (1, 1, 0, 1),
        'Cl': (0, 1, 0, 1),
        'F': (0.5, 1, 0.5, 1)
    }
    return colors.get(el, (0.5, 0.5, 0.5, 1))

def generate_blender_py(mol, name):
    """Write a Blender script from an RDKit mol that already has a 3D conformer.

    Atoms and bonds both come from the same `mol`, so they always line up.
    """
    import os

    conf = mol.GetConformer()
    coordinates = []
    elements = []
    for atom in mol.GetAtoms():
        p = conf.GetAtomPosition(atom.GetIdx())
        coordinates.append((p.x, p.y, p.z))
        elements.append(atom.GetSymbol())

    bonds = [
        (b.GetBeginAtomIdx(), b.GetEndAtomIdx(), b.GetBondTypeAsDouble())
        for b in mol.GetBonds()
    ]

    py_path = f"molecules/{name}_blender.py"
    os.makedirs("molecules", exist_ok=True)

    with open(py_path, 'w') as f:
        f.write("import bpy\nimport mathutils\nimport math\n\n")
        f.write("bpy.ops.object.select_all(action='SELECT')\n")
        f.write("bpy.ops.object.delete(use_global=False)\n\n")

        f.write("# === ATOMS ===\n")
        for i, (el, (x, y, z)) in enumerate(zip(elements, coordinates)):
            color = element_color(el)
            offset_x = 0

            f.write(f"# Atom {i}: {el}\n")
            f.write(f"bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=({x + offset_x}, {y}, {z}))\n")
            f.write(f"atom = bpy.context.object\n")
            f.write(f"mat = bpy.data.materials.new(name='Mat_{i}')\n")
            f.write(f"mat.diffuse_color = {color}\n")
            f.write("atom.data.materials.append(mat)\n")

            f.write(f"atom.keyframe_insert(data_path='location', frame=1)\n")
            f.write(f"atom.location = ({x}, {y}, {z})\n")
            f.write(f"atom.keyframe_insert(data_path='location', frame=50)\n\n")

            f.write(f"bpy.ops.object.text_add(location=({x + 0.4}, {y}, {z}))\n")
            f.write("text_obj = bpy.context.object\n")
            f.write(f"text_obj.data.body = '{el}'\n")
            f.write(f"text_obj.scale = (0.3, 0.3, 0.3)\n\n")

        f.write("# === BONDS ===\n")
        for i, (start_idx, end_idx, order) in enumerate(bonds):
            start = coordinates[start_idx]
            end = coordinates[end_idx]
            dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
            bond_count = max(1, int(order))  # aromatic (1.5) -> single cylinder
            shift = 0.15

            for b in range(bond_count):
                offset = (b - (bond_count - 1)/2) * shift
                f.write(f"# Bond {i} - {b+1}/{bond_count}\n")
                f.write(f"start = mathutils.Vector(({start[0]}, {start[1]}, {start[2]}))\n")
                f.write(f"end = mathutils.Vector(({end[0]}, {end[1]}, {end[2]}))\n")
                f.write("mid = (start + end) / 2\n")
                f.write("vec = end - start\n")
                f.write("length = vec.length\n")
                f.write("bpy.ops.mesh.primitive_cylinder_add(radius=0.07, depth=length, location=mid)\n")
                f.write("cyl = bpy.context.object\n")
                f.write("cyl.rotation_mode = 'QUATERNION'\n")
                f.write("cyl.rotation_quaternion = vec.to_track_quat('Z', 'Y')\n")
                if bond_count > 1:
                    f.write(f"cyl.location += vec.cross(mathutils.Vector((0, 0, 1))).normalized() * {offset}\n")
                f.write("\n")

        # Absolute path so the export doesn't depend on Blender's working dir.
        os.makedirs("outputs", exist_ok=True)
        glb_path = os.path.abspath(f"outputs/{name}.glb").replace("\\", "/")
        f.write(f"bpy.ops.export_scene.gltf(filepath={glb_path!r}, export_animations=True)\n")

    print("✅ Blender script written")

    return py_path
