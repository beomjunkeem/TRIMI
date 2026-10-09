"""Make the rotating-viewer render model web-sized without changing how it looks.

- Bakes every node transform and merges primitives per material (~15.8k draw calls -> ~18).
- Draco-compresses each merged primitive (same triangles; 16-bit positions, 12-bit normals).
- Re-encodes the environment HDR with Radiance RLE (lossless).

Usage (needs numpy + DracoPy):
  python3 tools/optimize_render_glb.py ../rotating-viewer/data/model.glb ../rotating-viewer/data/retail_store.hdr
"""
import json, os, struct, sys
import numpy as np
import DracoPy

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_GLB, SRC_HDR = sys.argv[1], sys.argv[2]
OUT_GLB = os.path.join(HERE, "data", "cad", "trimi_render.glb")
OUT_HDR = os.path.join(HERE, "data", "env", "retail_store.hdr")
CT = {5121: "u1", 5123: "u2", 5125: "u4", 5126: "f4"}

# ---------- read ----------
glb = open(SRC_GLB, "rb").read()
jlen = struct.unpack_from("<I", glb, 12)[0]
doc = json.loads(glb[20:20 + jlen])
binary = glb[20 + jlen + 8:]


def accessor(i):
    a = doc["accessors"][i]
    bv = doc["bufferViews"][a["bufferView"]]
    n = {"SCALAR": 1, "VEC3": 3}[a["type"]]
    arr = np.frombuffer(binary, "<" + CT[a["componentType"]], a["count"] * n, bv.get("byteOffset", 0) + a.get("byteOffset", 0))
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

# ---------- bake + group by material ----------
groups = {}  # material -> list of (positions, normals, faces)
for mi, M in instances:
    A, t = M[:3, :3], M[:3, 3]
    N = np.linalg.inv(A).T
    mirrored = np.linalg.det(A) < 0
    for pr in doc["meshes"][mi]["primitives"]:
        p = accessor(pr["attributes"]["POSITION"]).astype(np.float64) @ A.T + t
        n = accessor(pr["attributes"]["NORMAL"]).astype(np.float64) @ N.T
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        f = accessor(pr["indices"]).reshape(-1, 3).astype(np.int64)
        used = np.unique(f)  # split primitives share one vertex buffer; keep only referenced vertices
        remap = np.full(len(p), -1, np.int64)
        remap[used] = np.arange(len(used))
        f = remap[f]
        if mirrored:  # keep front faces front-facing after a mirror transform
            f = f[:, [0, 2, 1]]
        groups.setdefault(pr.get("material"), []).append((p[used], n[used], f))

# ---------- draco encode ----------
out_blob, views, accessors, prims = bytearray(), [], [], []
total_tris = 0
for mat, parts in groups.items():
    P, Nn, F, off = [], [], [], 0
    for p, n, f in parts:
        P.append(p); Nn.append(n); F.append(f + off); off += len(p)
    P = np.concatenate(P).astype(np.float32)
    Nn = np.concatenate(Nn).astype(np.float64)
    assert np.isfinite(P).all() and np.isfinite(Nn).all(), "non-finite vertex data"
    F = np.concatenate(F).astype(np.uint32)
    enc = DracoPy.encode(P, F, quantization_bits=16, compression_level=7,
                         normals=Nn, normal_quantization_bits=12)
    dec = DracoPy.decode(enc)  # counts/bounds must describe the decoded mesh
    while len(out_blob) % 4:
        out_blob.append(0)
    views.append({"buffer": 0, "byteOffset": len(out_blob), "byteLength": len(enc)})
    out_blob.extend(enc)
    pts = np.asarray(dec.points, np.float32).reshape(-1, 3)
    nf = np.asarray(dec.faces).reshape(-1, 3)
    base = len(accessors)
    accessors += [
        {"componentType": 5126, "count": len(pts), "type": "VEC3", "min": pts.min(0).tolist(), "max": pts.max(0).tolist()},
        {"componentType": 5126, "count": len(pts), "type": "VEC3"},
        {"componentType": 5125, "count": int(nf.size), "type": "SCALAR"},
    ]
    prim = {"attributes": {"POSITION": base, "NORMAL": base + 1}, "indices": base + 2, "mode": 4,
            "extensions": {"KHR_draco_mesh_compression": {"bufferView": len(views) - 1,
                                                           "attributes": {"POSITION": 1, "NORMAL": 0}}}}  # DracoPy adds normals first
    if mat is not None:
        prim["material"] = mat
    prims.append(prim)
    total_tris += len(nf)
    name = doc["materials"][mat]["name"] if mat is not None else "default"
    print(f"  {name:24s} {len(nf):>9,} tris  {len(enc) / 1e6:6.2f} MB")

while len(out_blob) % 4:
    out_blob.append(0)
used_ext = set(doc.get("extensionsUsed", [])) | {"KHR_draco_mesh_compression"}
out = {
    "asset": {"version": "2.0", "generator": "TRIMI optimize_render_glb"},
    "extensionsUsed": sorted(used_ext),
    "extensionsRequired": ["KHR_draco_mesh_compression"],
    "scene": 0, "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": "TRIMI"}],
    "meshes": [{"name": "TRIMI", "primitives": prims}],
    "materials": doc["materials"],
    "buffers": [{"byteLength": len(out_blob)}],
    "bufferViews": views, "accessors": accessors,
}
chunk = json.dumps(out, separators=(",", ":"), ensure_ascii=False).encode()
chunk += b" " * (-len(chunk) % 4)
body = struct.pack("<II", len(chunk), 0x4E4F534A) + chunk + struct.pack("<II", len(out_blob), 0x004E4942) + bytes(out_blob)
os.makedirs(os.path.dirname(OUT_GLB), exist_ok=True)
with open(OUT_GLB, "wb") as f:
    f.write(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
print(f"{len(prims)} primitives, {total_tris:,} tris -> {OUT_GLB} ({(12 + len(body)) / 1e6:.1f} MB)")


# ---------- HDR: flat RGBE -> RLE RGBE ----------
def rle_channel(ch):
    out, i, n = bytearray(), 0, len(ch)
    while i < n:
        run = 1
        while i + run < n and run < 127 and ch[i + run] == ch[i]:
            run += 1
        if run >= 4:
            out += bytes([128 + run, ch[i]]); i += run; continue
        j = i  # literal span until the next run of >= 4
        while j < n and j - i < 128:
            if j + 3 < n and ch[j] == ch[j + 1] == ch[j + 2] == ch[j + 3]:
                break
            j += 1
        out += bytes([j - i]) + bytes(ch[i:j]); i = j
    return out


hdr = open(SRC_HDR, "rb").read()
header_end = hdr.index(b"\n\n") + 2
res_end = hdr.index(b"\n", header_end) + 1
res = hdr[header_end:res_end].split()
h, w = int(res[1]), int(res[3])
px = np.frombuffer(hdr, np.uint8, h * w * 4, res_end).reshape(h, w, 4)
enc = bytearray(hdr[:res_end])
for y in range(h):
    enc += bytes([2, 2, w >> 8, w & 255])
    for c in range(4):
        enc += rle_channel(px[y, :, c].tobytes())
os.makedirs(os.path.dirname(OUT_HDR), exist_ok=True)
open(OUT_HDR, "wb").write(enc)
print(f"HDR {w}x{h}: {len(hdr) / 1e6:.1f} MB -> {len(enc) / 1e6:.1f} MB ({OUT_HDR})")
