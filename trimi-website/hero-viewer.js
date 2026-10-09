import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";

const host = document.querySelector("[data-hero-model]");

if (host) {
  const canvas = host.querySelector(".hero-canvas");
  const modelUrl = host.dataset.heroModel;
  // "edges" = feature edges only (clean), "wire" = full triangulation (dense crosshatch)
  const mode = host.dataset.heroWireMode || "edges";
  const edgeAngle = Number(host.dataset.heroEdgeAngle || 18);
  // Larger = smaller hand (more zoomed out). Pan = fraction of size to lift the hand up in frame.
  const zoom = Number(host.dataset.heroZoom || 1.28);

  // Dark charcoal lines for the light page; subtle vertical depth fade.
  const COLOR_TIP = new THREE.Color("#2f3332"); // crisp at the top
  const COLOR_BASE = new THREE.Color("#6e7774"); // muted charcoal toward the base

  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 10000);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  } catch (error) {
    host.classList.add("is-error");
    console.error("Hero viewer requires WebGL:", error);
  }

  if (renderer) {
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    // Drag-to-rotate only: zoom/pan off so the page still scrolls over the hero.
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enableZoom = false;
    controls.enablePan = false;
    controls.autoRotate = !prefersReduced;
    controls.autoRotateSpeed = 0.9;

    const root = new THREE.Group();
    scene.add(root);

    // Vertical-gradient line material driven by world-space height (Y).
    const makeLineMaterial = (minY, maxY) => {
      const mat = new THREE.LineBasicMaterial({ transparent: true });
      mat.onBeforeCompile = (shader) => {
        shader.uniforms.uMinY = { value: minY };
        shader.uniforms.uMaxY = { value: maxY };
        shader.uniforms.uTip = { value: COLOR_TIP };
        shader.uniforms.uBase = { value: COLOR_BASE };
        shader.vertexShader = shader.vertexShader
          .replace(
            "#include <common>",
            "#include <common>\n varying float vHeight; uniform float uMinY; uniform float uMaxY;",
          )
          .replace(
            "#include <begin_vertex>",
            "#include <begin_vertex>\n vHeight = clamp((position.y - uMinY) / max(uMaxY - uMinY, 0.0001), 0.0, 1.0);",
          );
        shader.fragmentShader = shader.fragmentShader
          .replace(
            "#include <common>",
            "#include <common>\n varying float vHeight; uniform vec3 uTip; uniform vec3 uBase;",
          )
          .replace(
            "vec4 diffuseColor = vec4( diffuse, opacity );",
            "vec3 grad = mix(uBase, uTip, vHeight);\n vec4 diffuseColor = vec4( grad, opacity * (0.72 + 0.28 * vHeight) );",
          );
      };
      return mat;
    };

    const buildLines = (model) => {
      const bounds = new THREE.Box3().setFromObject(model);
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z, 1);
      // Geometry is centered below, so gradient bounds are centered too.
      const material = makeLineMaterial(bounds.min.y - center.y, bounds.max.y - center.y);

      model.updateMatrixWorld(true);
      model.traverse((object) => {
        if (!object.isMesh || !object.geometry) return;
        // Bake world transform, then center on the origin so the spin axis
        // runs through the hand and the gradient uses true (centered) height.
        const geom = object.geometry.clone().applyMatrix4(object.matrixWorld);
        geom.translate(-center.x, -center.y, -center.z);
        const lineGeom =
          mode === "wire"
            ? new THREE.WireframeGeometry(geom)
            : new THREE.EdgesGeometry(geom, edgeAngle);
        const lines = new THREE.LineSegments(lineGeom, material);
        lines.frustumCulled = false;
        root.add(lines);
        geom.dispose();
      });

      // Faint horizon arc under the hand.
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(maxDim * 0.62, maxDim * 0.625, 96),
        new THREE.MeshBasicMaterial({
          color: 0x9aa3a0,
          transparent: true,
          opacity: 0.35,
          side: THREE.DoubleSide,
        }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = bounds.min.y - center.y - maxDim * 0.02;
      scene.add(ring);

      // Frame the camera. Target sits at the hand's center so auto-rotate and
      // drag both pivot through the hand (no off-center wobble).
      const dist = maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)));
      const camDist = dist * zoom;
      camera.near = Math.max(camDist / 1000, 0.001);
      camera.far = camDist * 100;
      camera.position.set(0, maxDim * 0.05, camDist);
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();
    };

    const dracoLoader = new DRACOLoader();
    dracoLoader.setDecoderPath("https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/libs/draco/");
    const loader = new GLTFLoader();
    loader.setDRACOLoader(dracoLoader);
    loader.load(
      modelUrl,
      (gltf) => {
        buildLines(gltf.scene);
        host.classList.add("is-loaded");
      },
      undefined,
      (error) => {
        host.classList.add("is-error");
        console.error("Failed to load hero model:", error);
      },
    );

    const resize = () => {
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };

    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    const render = () => {
      requestAnimationFrame(render);
      controls.update();
      renderer.render(scene, camera);
    };
    render();
  }
}
