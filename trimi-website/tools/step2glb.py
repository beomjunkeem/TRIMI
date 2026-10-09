# STEP -> compact GLB for the TRIMI hero viewer (run with FreeCAD's freecadcmd).
# Positions are float32 (hero-viewer.js bakes transforms into the geometry), indices uint16 per chunk.
import sys, json, struct
import Part, Mesh, MeshPart
import numpy as np

SRC = "../Big_Assem1.step"  # run from trimi-website/: freecadcmd tools/step2glb.py
OUT = "data/cad/trimi_assembly.glb"
LIN, ANG = 1.0, 0.7   # mm, rad
LOOSE_REDUCTION = 0.85

shape = Part.read(SRC)
solid_ids = set(f.hashCode() for sol in shape.Solids for f in sol.Faces)
loose = [f for f in shape.Faces if f.hashCode() not in solid_ids]

parts = []
for sol in shape.Solids:
    parts.append(MeshPart.meshFromShape(Shape=sol, LinearDeflection=LIN, AngularDeflection=ANG, Relative=False))
if loose:
    m = MeshPart.meshFromShape(Shape=Part.Compound(loose), LinearDeflection=LIN, AngularDeflection=ANG, Relative=False)
    before = m.CountFacets
    m.decimate(0.5, LOOSE_REDUCTION)
    print("loose facets", before, "->", m.CountFacets)
    parts.append(m)

# Pack meshes into chunks with < 65536 vertices each.
chunks, cur_p, cur_i, n = [], [], [], 0
for m in parts:
    pts, tris = m.Topology
    p = np.array([[v.x, v.y, v.z] for v in pts], dtype=np.float64)
    t = np.array(tris, dtype=np.int64)
    if n + len(p) > 65535 and cur_p:
        chunks.append((np.concatenate(cur_p), np.concatenate(cur_i))); cur_p, cur_i, n = [], [], 0
    cur_p.append(p); cur_i.append(t + n); n += len(p)
if cur_p:
    chunks.append((np.concatenate(cur_p), np.concatenate(cur_i)))

# CAD is Z-up; glTF is Y-up: (x, y, z) -> (x, z, -y). Kept in mm: hero-viewer.js clamps maxDim to >= 1.
allp = np.concatenate([c[0] for c in chunks])
conv = lambda p: np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1)
blob, views, accessors, prims = bytearray(), [], [], []
def add_view(data, target, stride=None):
    while len(blob) % 4: blob.append(0)
    v = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target}
    if stride: v["byteStride"] = stride
    views.append(v); blob.extend(data); return len(views) - 1

for p, t in chunks:
    q = conv(p).astype(np.float32)
    pv = add_view(q.tobytes(), 34962)
    accessors.append({"bufferView": pv, "componentType": 5126, "count": len(q), "type": "VEC3",
                      "min": q.min(0).tolist(), "max": q.max(0).tolist()})
    iv = add_view(t.reshape(-1).astype(np.uint16).tobytes(), 34963)
    accessors.append({"bufferView": iv, "componentType": 5123, "count": int(t.size), "type": "SCALAR"})
    prims.append({"attributes": {"POSITION": len(accessors) - 2}, "indices": len(accessors) - 1, "mode": 4})

while len(blob) % 4: blob.append(0)
gltf = {
    "asset": {"version": "2.0", "generator": "TRIMI step2glb"},
    "scene": 0, "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": "TRIMI"}],
    "meshes": [{"primitives": prims}],
    "buffers": [{"byteLength": len(blob)}],
    "bufferViews": views, "accessors": accessors,
}
js = json.dumps(gltf, separators=(",", ":")).encode()
js += b" " * ((4 - len(js) % 4) % 4)
total = 12 + 8 + len(js) + 8 + len(blob)
with open(OUT, "wb") as f:
    f.write(struct.pack("<III", 0x46546C67, 2, total))
    f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
    f.write(struct.pack("<II", len(blob), 0x004E4942)); f.write(bytes(blob))
print("chunks", len(chunks), "verts", len(allp), "tris", sum(len(c[1]) for c in chunks), "size KB", total // 1024)
