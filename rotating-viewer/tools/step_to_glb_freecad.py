import os, time, traceback
log = open("/private/tmp/claude-501/-Users-jun-Downloads-TRIMI/a30014c1-3ce7-4f24-91fe-0db398ce3a92/scratchpad/conv/gui.log", "w")
try:
    import FreeCAD, FreeCADGui, ImportGui
    t = time.time()
    doc = FreeCAD.newDocument("conv")
    ImportGui.insert("/Users/jun/Downloads/TRIMI/Big_Assem1.step", doc.Name)
    log.write("imported %d in %.1fs\n" % (len(doc.Objects), time.time()-t)); log.flush()
    tol = 0.08
    n = 0
    for o in doc.Objects:
        if o.TypeId == "Part::Feature" and o.Shape.Faces:
            o.Shape.tessellate(tol, True)
            n += 1
    roots = [o for o in doc.Objects if not o.InList]
    ImportGui.export(roots, "/Users/jun/Downloads/TRIMI/rotating-viewer/data/model.glb")
    log.write("tessellated %d, exported in %.1fs\n" % (n, time.time()-t))
except Exception:
    log.write(traceback.format_exc())
log.close()
os._exit(0)
