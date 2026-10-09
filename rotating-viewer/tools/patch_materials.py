"""Match DexEXO's material style: sRGB color values as baseColor, metallic 0.05, roughness 0.5."""
import json, struct, sys

path = sys.argv[1]
data = open(path, "rb").read()
json_len = struct.unpack("<I", data[12:16])[0]
doc = json.loads(data[20:20 + json_len])
rest = data[20 + json_len:]


def to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


for m in doc.get("materials", []):
    pbr = m.setdefault("pbrMetallicRoughness", {})
    r, g, b, a = pbr.get("baseColorFactor", [1, 1, 1, 1])
    pbr["baseColorFactor"] = [round(to_srgb(r), 6), round(to_srgb(g), 6), round(to_srgb(b), 6), a]
    pbr["metallicFactor"] = 0.05
    pbr["roughnessFactor"] = 0.5
    m["doubleSided"] = True

chunk = json.dumps(doc, separators=(",", ":")).encode()
chunk += b" " * (-len(chunk) % 4)
body = struct.pack("<II", len(chunk), 0x4E4F534A) + chunk + rest
out = struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body
open(path, "wb").write(out)
print("patched", len(doc.get("materials", [])), "materials")
