"""Copy SOLIDWORKS Visualize materials (.svpj) onto the STEP-exported GLB.

Visualize groups geometry by appearance, so its project stores one mesh per material.
Each GLB triangle is matched to the nearest Visualize mesh surface (same STEP coordinates),
and each primitive takes the majority material. Primitives with no Visualize counterpart
(parts added after the render project was made) keep their STEP color.
Also writes the scene's HDR environment as a Radiance .hdr for model-viewer.

Usage: python3 tools/apply_visualize_materials.py <project.svpj> [--model Big_Assem1]
"""
import argparse, io, json, os, struct, zipfile
import xml.etree.ElementTree as ET
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"
VOXEL_MM = 0.6
# glTF (Y-up, metres) -> STEP / Visualize (Z-up, millimetres)
TO_STEP = np.array([[1000, 0, 0], [0, 0, -1000], [0, 1000, 0]], float)
# Materials not in the Visualize project (base color is sRGB, like Visualize's color picker).
CUSTOM_MATERIALS = {
    # Formlabs Tough 2000 SLA print: dark grey, satin gloss
    "Tough 2000 dark grey": dict(base=[0.33, 0.345, 0.357], metallic=0.0, roughness=0.32),
    # Meta Quest 3 / 3S Touch Plus controller: matte off-white plastic
    "Quest controller white": dict(base=[0.90, 0.90, 0.885], metallic=0.0, roughness=0.5),
    # FDM black PLA print: near-black, satin
    "Black PLA": dict(base=[0.07, 0.07, 0.075], metallic=0.0, roughness=0.55),
}
# Every primitive using the left material gets the right one.
MATERIAL_REPLACE = {
    "STEP mat_17": "Tough 2000 dark grey",  # sky-blue STEP color: thumb IP/MCP and finger MCP motor holders
}
# Same, but only inside one part: (GLB mesh name, old material) -> new material.
PART_MATERIAL_REPLACE = {
    # camera holder (light blue in STEP; the Quest controller shares that color and stays)
    ("Part 1", "STEP mat_7"): "Tough 2000 dark grey",
    ("Part 194", "STEP mat_7"): "Tough 2000 dark grey",
    ("Part 195", "STEP mat_7"): "Tough 2000 dark grey",
    ("Part 327", "STEP mat_7"): "Tough 2000 dark grey",
    ("quest_controller__quest_controller", "STEP mat_7"): "Quest controller white",
    ("quest_controller__quest_controller001", "STEP mat_7"): "Quest controller white",
}
# Manual fixes applied after matching: GLB mesh (STEP part) name -> material name from the list printed below.
OVERRIDES = {
    "Rigid": "Appearance-14",  # thumb fingercot -> black
    "Rigid001": "Appearance-14",
    "Thumb for reference_1001": "Tough 2000 dark grey",  # first thumb IP motor holder
    "Wrist_Gripper_CNC_umi_v2_2-Combine11__Wrist_Gripper_CNC_umi_v2_2-Combine11": "Black PLA",  # Quest holder
}

parser = argparse.ArgumentParser()
parser.add_argument("svpj")
parser.add_argument("--model", default="Big_Assem1", help="model instance name inside the project")
parser.add_argument("--src", default=os.path.join(HERE, "data", "model_step.glb"))
parser.add_argument("--out", default=os.path.join(HERE, "data", "model.glb"))
parser.add_argument("--env-out", default=os.path.join(HERE, "data", "environment.hdr"))
args = parser.parse_args()
pkg = zipfile.ZipFile(args.svpj)


# ---------- Visualize project ----------
def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def read_bmd(data):
    def chunk(tag):
        i = data.find(tag)
        return i + 16, struct.unpack("<I", data[i + 12:i + 16])[0]
    o, n = chunk(b"CMD0")
    pos = np.frombuffer(data, "<f4", n * 3, o).reshape(-1, 3).astype(float)
    o, n = chunk(b"DMD0")
    return pos, np.frombuffer(data, "<u4", n * 3, o).reshape(-1, 3)


root = ET.fromstring(pkg.read("Project.xml"))
materials, parts, textures = {}, {}, {}
for bn in root.iter("BaseNode"):
    kind = bn.get(XSI)
    if kind == "InventoryMaterialNode":
        m = bn.find("Material_UserMaterial")
        materials[bn.get("Guid")] = dict(
            name=bn.get("Name"),
            subtype=m.findtext("MaterialSubType"),
            base=[float(m.find("BaseColor").get(k)) for k in "RGB"],
            metallic=float(m.findtext("PbrMetallic")),
            roughness=float(m.findtext("PbrRoughness")),
            transparency=float(m.findtext("PbrTransparency")),
            ior=float(m.findtext("PbrIor")),
        )
    elif kind == "InventoryPartNode":
        h = bn.find(".//ImportedMeshHandle")
        if h is not None:
            parts[bn.get("Guid")] = h.get("Guid")
    elif kind == "InventoryTextureNode":
        h = bn.find(".//UriImageHandle")
        ops = bn.find(".//TextureOperations")
        textures[bn.get("Guid")] = dict(asset=h.get("Guid"), flip_rb=ops.findtext("FlipRB") == "true",
                                        flip_v=float(ops.findtext("TileT")) < 0)

groups = []  # (material guid, mesh asset guid)
for tn in root.iter("TreeNode"):
    bn = tn.find("BaseNode")
    if bn is None or bn.get(XSI) != "ModelInstanceNode" or bn.get("Name") != args.model:
        continue
    for c in tn.iter("BaseNode"):
        mesh = parts.get(c.findtext("InventoryPartGuid") or "")
        if c.get(XSI) == "PartInstanceVariantNode" and mesh:
            groups.append((c.findtext("MaterialGuid"), mesh, c.get("Name")))
if not groups:
    raise SystemExit(f"model '{args.model}' not found in project")
print(f"{len(groups)} material groups in '{args.model}'")

# ---------- environment ----------
current_bg = ET.fromstring(pkg.read("Currents.xml")).findtext("Background")
for bn in root.iter("BaseNode"):
    if bn.get(XSI) == "BackgroundNode" and bn.get("Guid") == current_bg:
        tex = textures.get(bn.findtext("TextureNodeGuid"))
        if tex:
            dds = pkg.read(f"Assets/{tex['asset']}.dds")
            h, w = struct.unpack("<II", dds[12:20])
            px = np.frombuffer(dds, np.uint8, h * w * 4, 128).reshape(h, w, 4)
            if tex["flip_v"]:
                px = px[::-1]
            rgbe = px if tex["flip_rb"] else px[..., [2, 1, 0, 3]]
            with open(args.env_out, "wb") as f:
                f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n" + f"-Y {h} +X {w}\n".encode())
                f.write(np.ascontiguousarray(rgbe).tobytes())
            print(f"environment '{bn.get('Name')}' {w}x{h} (Visualize brightness {bn.findtext('Brightness')}) -> {args.env_out}")

# ---------- voxel grid of labelled Visualize surface samples ----------
rng = np.random.default_rng(0)
pts, lab = [], []
for gi, (_, mesh, _) in enumerate(groups):
    p, t = read_bmd(pkg.read(f"Assets/{mesh}.bmd"))
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    rep = np.repeat(np.arange(len(t)), np.maximum(1, np.ceil(area / (VOXEL_MM ** 2 / 4))).astype(int))
    u, v = rng.random(len(rep)), rng.random(len(rep))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    s = a[rep] + u[:, None] * (b - a)[rep] + v[:, None] * (c - a)[rep]
    pts += [s, p]
    lab += [np.full(len(s) + len(p), gi)]
pts, lab = np.concatenate(pts), np.concatenate(lab)
G = len(groups)

OFF = 1 << 14
def pack(q):
    q = q + OFF
    return (q[:, 0] << 32) | (q[:, 1] << 16) | q[:, 2]

uk, cnt = np.unique(pack(np.floor(pts / VOXEL_MM).astype(np.int64)) * 32 + lab, return_counts=True)
vox_keys = np.unique(uk // 32)
hist = np.zeros((len(vox_keys), G), np.float32)
np.add.at(hist, (np.searchsorted(vox_keys, uk // 32), uk % 32), cnt)


def votes_near(q, radius=1):
    acc = np.zeros((len(q), G), np.float32)
    base = np.floor(q / VOXEL_MM).astype(np.int64)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                k = pack(base + [dx, dy, dz])
                i = np.minimum(np.searchsorted(vox_keys, k), len(vox_keys) - 1)
                ok = vox_keys[i] == k
                acc[ok] += hist[i[ok]] / (1 + dx * dx + dy * dy + dz * dz)
    return acc


# ---------- GLB ----------
CT = {5121: "u1", 5123: "u2", 5125: "u4", 5126: "f4"}
glb = open(args.src, "rb").read()
jlen = struct.unpack("<I", glb[12:16])[0]
doc = json.loads(glb[20:20 + jlen])
src_binary = glb[20 + jlen + 8:]
binary = bytearray(src_binary)  # grows with split-primitive indices


def read_accessor(i):
    a = doc["accessors"][i]
    bv = doc["bufferViews"][a["bufferView"]]
    n = {"SCALAR": 1, "VEC3": 3}[a["type"]]
    arr = np.frombuffer(src_binary, "<" + CT[a["componentType"]], a["count"] * n, bv.get("byteOffset", 0) + a.get("byteOffset", 0))
    return arr.reshape(-1, n) if n > 1 else arr


def node_matrix(n):
    if "matrix" in n:
        return np.array(n["matrix"], float).reshape(4, 4).T
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * np.array(n.get("scale", [1, 1, 1]))
    M[:3, 3] = n.get("translation", [0, 0, 0])
    return M


instances = []
def walk(i, parent):
    M = parent @ node_matrix(doc["nodes"][i])
    if "mesh" in doc["nodes"][i]:
        instances.append((doc["nodes"][i]["mesh"], M))
    for c in doc["nodes"][i].get("children", []):
        walk(c, M)
for r in doc["scenes"][doc.get("scene", 0)]["nodes"]:
    walk(r, np.eye(4))

# glTF materials from Visualize ones (shared by guid)
step_materials = doc.get("materials", [])
new_materials, mat_index = [], {}
def visualize_material(gi):
    guid = groups[gi][0]
    if guid not in mat_index:
        m = materials[guid]
        out = {"name": m["name"], "doubleSided": True, "pbrMetallicRoughness": {
            "baseColorFactor": [*np.round(srgb_to_linear(m["base"]), 6).tolist(), 1.0],
            "metallicFactor": m["metallic"], "roughnessFactor": m["roughness"]}}
        if m["subtype"] == "glass" or m["transparency"] > 0:
            out["extensions"] = {"KHR_materials_transmission": {"transmissionFactor": max(m["transparency"], 1.0)},
                                 "KHR_materials_ior": {"ior": m["ior"]}}
        mat_index[guid] = len(new_materials)
        new_materials.append(out)
    return mat_index[guid]

fallback_index = {}
def fallback_material(old):
    """STEP color, rendered like a Visualize 'basic' material"""
    if old not in fallback_index:
        src = step_materials[old] if old is not None else {}
        color = src.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.5, 0.5, 0.5, 1])
        fallback_index[old] = len(new_materials)
        new_materials.append({"name": f"STEP {src.get('name', 'default')}", "doubleSided": True,
                              "pbrMetallicRoughness": {"baseColorFactor": color, "metallicFactor": 0.0, "roughnessFactor": 0.3}})
    return fallback_index[old]

# groups that Visualize split at face level inside one part (only "Body" groups do this)
face_split = {gi for gi, g in enumerate(groups) if g[2].startswith("Body")}

def append_indices(idx):
    data = idx.astype("<u4").tobytes()
    while len(binary) % 4:
        binary.append(0)
    doc["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": 34963})
    binary.extend(data)
    doc["accessors"].append({"bufferView": len(doc["bufferViews"]) - 1, "componentType": 5125,
                             "count": len(idx), "type": "SCALAR"})
    return len(doc["accessors"]) - 1

stats = {"visualize": 0, "split": 0, "fallback": 0}
fallback_tris = 0
done_meshes = set()
for mi, M in instances:
    if mi in done_meshes:
        continue
    done_meshes.add(mi)
    new_prims = []
    for pr in doc["meshes"][mi]["primitives"]:
        v = read_accessor(pr["attributes"]["POSITION"]).astype(float)
        w = (v @ M[:3, :3].T + M[:3, 3]) @ TO_STEP.T
        idx = read_accessor(pr["indices"]).reshape(-1, 3)
        votes = 2 * votes_near(w[idx].mean(1)) + votes_near(w)[idx].sum(1)
        tri = np.where(votes.sum(1) > 0, votes.argmax(1), G)
        counts = np.bincount(tri, minlength=G + 1)
        if counts[G] > 0.5 * len(tri):
            new_prims.append({**pr, "material": fallback_material(pr.get("material"))})
            stats["fallback"] += 1
            fallback_tris += len(tri)
            continue
        order = np.argsort(-counts[:G])
        top, second = order[0], order[1]
        if top in face_split and second in face_split and counts[second] > 0.05 * len(tri):
            tri[tri == G] = top
            for gi in np.unique(tri):
                sel = idx[tri == gi].reshape(-1)
                new_prims.append({**pr, "indices": append_indices(sel), "material": visualize_material(gi)})
            stats["split"] += 1
        else:
            new_prims.append({**pr, "material": visualize_material(top)})
            stats["visualize"] += 1
    doc["meshes"][mi]["primitives"] = new_prims

for name, m in CUSTOM_MATERIALS.items():
    new_materials.append({"name": name, "doubleSided": True, "pbrMetallicRoughness": {
        "baseColorFactor": [*np.round(srgb_to_linear(m["base"]), 6).tolist(), 1.0],
        "metallicFactor": m["metallic"], "roughnessFactor": m["roughness"]}})
by_name = {m["name"]: i for i, m in enumerate(new_materials)}
for old, new in MATERIAL_REPLACE.items():
    if old in by_name:
        for mesh in doc["meshes"]:
            for pr in mesh["primitives"]:
                if pr["material"] == by_name[old]:
                    pr["material"] = by_name[new]
        print(f"replace: material {old} -> {new}")
for mesh in doc["meshes"]:
    replaced = set()
    for pr in mesh["primitives"]:
        key = (mesh.get("name"), new_materials[pr["material"]]["name"])
        if key in PART_MATERIAL_REPLACE:
            pr["material"] = by_name[PART_MATERIAL_REPLACE[key]]
            replaced.add(key)
    for name, old in replaced:
        print(f"replace: part {name} {old} -> {PART_MATERIAL_REPLACE[(name, old)]}")
for mesh in doc["meshes"]:
    target = OVERRIDES.get(mesh.get("name"))
    if target is None:
        continue
    if target not in by_name:
        raise SystemExit(f"override material '{target}' not found; available: {sorted(by_name)}")
    for pr in mesh["primitives"]:
        pr["material"] = by_name[target]
    print(f"override: {mesh['name']} -> {target}")

doc["materials"] = new_materials
used = set(doc.get("extensionsUsed", []))
if any("extensions" in m for m in new_materials):
    used |= {"KHR_materials_transmission", "KHR_materials_ior"}
doc["extensionsUsed"] = sorted(used)
while len(binary) % 4:
    binary.append(0)
doc["buffers"][0]["byteLength"] = len(binary)

chunk = json.dumps(doc, separators=(",", ":")).encode()
chunk += b" " * (-len(chunk) % 4)
body = struct.pack("<II", len(chunk), 0x4E4F534A) + chunk + struct.pack("<II", len(binary), 0x004E4942) + bytes(binary)
with open(args.out, "wb") as f:
    f.write(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)

print(f"primitives: {stats['visualize']} Visualize material, {stats['split']} split per face, "
      f"{stats['fallback']} kept STEP color ({fallback_tris} triangles, parts not in the Visualize project)")
for m in new_materials:
    print(f"  {m['name']:18s} base={m['pbrMetallicRoughness']['baseColorFactor'][:3]} "
          f"metal={m['pbrMetallicRoughness']['metallicFactor']} rough={m['pbrMetallicRoughness']['roughnessFactor']}"
          + ("  [glass]" if "extensions" in m else ""))
print("wrote", args.out)
