// Frame-by-frame recorder. Only runs when the page is opened with ?record.
// Each frame sets the turntable angle explicitly (same 12deg/s as auto-rotate),
// paints the page background behind the render, and POSTs a PNG to tools/record_server.py.
const params = new URLSearchParams(location.search);

if (params.has("record")) {
  const fps = Number(params.get("fps") || 60);
  const degPerSecond = Number(params.get("speed") || 12);
  const seconds = Number(params.get("seconds") || 360 / degPerSecond); // default: one full turn
  const totalFrames = Math.round(fps * seconds);
  const radPerFrame = (degPerSecond * Math.PI) / 180 / fps;

  const mv = document.getElementById("viewer");
  const status = document.getElementById("status");
  document.body.classList.add("recording");
  const frame = document.querySelector(".viewer-frame");
  frame.style.width = `${params.get("w") || 1920}px`;
  frame.style.height = `${params.get("h") || 1080}px`;
  mv.autoRotate = false;
  mv.interactionPrompt = "none";

  const nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const log = (msg) => {
    status.textContent = msg;
    console.log(msg);
  };

  // Paint the same layers the live page shows behind the model (see index.html CSS).
  const paintBackground = (ctx, w, h) => {
    const radial = (cx, cy, r, color) => {
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
      g.addColorStop(0, color);
      g.addColorStop(1, color.replace(/[\d.]+\)$/, "0)"));
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    };
    // CSS "circle" radial gradients default to farthest-corner sizing.
    const farthest = (cx, cy) => Math.hypot(Math.max(cx, w - cx), Math.max(cy, h - cy));

    ctx.fillStyle = "#fdfaf4";
    ctx.fillRect(0, 0, w, h);
    radial(0.9 * w, 0.15 * h, 0.38 * farthest(0.9 * w, 0.15 * h), "rgba(240, 232, 231, 0.34)");
    radial(0.1 * w, 0, 0.36 * farthest(0.1 * w, 0), "rgba(232, 232, 232, 0.26)");
    radial(0.15 * w, 0.15 * h, 0.4 * farthest(0.15 * w, 0.15 * h), "rgba(33, 150, 243, 0.09)");
    const linear = ctx.createLinearGradient(0, 0, 0, h);
    linear.addColorStop(0, "rgba(255, 255, 255, 0.78)");
    linear.addColorStop(1, "rgba(240, 232, 231, 0.7)");
    ctx.fillStyle = linear;
    ctx.fillRect(0, 0, w, h);
  };

  const post = (path, body) => fetch(path, { method: "POST", body });

  const run = async () => {
    // model-viewer lowers its render scale when frames are slow; keep full resolution.
    customElements.get("model-viewer").minimumRenderScale = 1;

    if (!mv.loaded) await new Promise((resolve) => mv.addEventListener("load", resolve, { once: true }));
    await sleep(2000); // let the environment map and first renders settle

    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    for (let i = 0; i < totalFrames; i++) {
      mv.resetTurntableRotation(i * radPerFrame);
      await nextFrame();
      await nextFrame();

      const render = await createImageBitmap(await mv.toBlob({ mimeType: "image/png", idealAspect: false }));
      if (canvas.width !== render.width || canvas.height !== render.height) {
        canvas.width = render.width;
        canvas.height = render.height;
        log(`render size ${render.width}x${render.height}`);
      }
      paintBackground(ctx, canvas.width, canvas.height);
      ctx.drawImage(render, 0, 0);
      render.close();

      const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      await post(`/frame?i=${i}`, png);
      if (i % 30 === 0) log(`frame ${i + 1}/${totalFrames}`);
    }
    await post("/done", `${totalFrames}`);
    log("done");
  };

  run().catch((error) => {
    log(`record failed: ${error}`);
    post("/error", String(error.stack || error));
  });
}
