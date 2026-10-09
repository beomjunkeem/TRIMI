"""STEP -> GLB with per-part colors, using FreeCAD's GUI importer (the headless one drops colors).

Run:  /Applications/FreeCAD.app/Contents/MacOS/FreeCAD tools/step_to_glb_freecad.py
(paths below; FreeCAD opens briefly and exits)
"""
import os, time, traceback

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(os.path.dirname(HERE), "Big_Assem1.step")
OUT = os.path.join(HERE, "data", "model_step.glb")
LOG = os.path.join(HERE, "tools", "step_to_glb.log")
TOLERANCE_MM = 0.08  # linear deflection of the tessellation

log = open(LOG, "w")
try:
    import FreeCAD, ImportGui
    t = time.time()
    doc = FreeCAD.newDocument("conv")
    ImportGui.insert(SRC, doc.Name)
    n = 0
    for o in doc.Objects:
        if o.TypeId == "Part::Feature" and o.Shape.Faces:
            o.Shape.tessellate(TOLERANCE_MM, True)
            n += 1
    ImportGui.export([o for o in doc.Objects if not o.InList], OUT)
    log.write("tessellated %d shapes, wrote %s in %.1fs\n" % (n, OUT, time.time() - t))
except Exception:
    log.write(traceback.format_exc())
log.close()
os._exit(0)
