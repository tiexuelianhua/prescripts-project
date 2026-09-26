// Home's arrival glitch: the screen breaks into flat horizontal blocks, which
// melt into streaky TV static that clears as the prompt starts typing (see
// home_page.py, which inlines this file and calls playHomeGlitch()). Drawn on
// a canvas laid over the page and removed when it's done, so nothing is left
// running afterwards. Inspired by the glitches in Limbus Company's [000]
// trailer, not copied from it.
window.playHomeGlitch = function ({ accent, seconds = 1.0, amount = 1.0, blockShare = 0.45 }) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.getElementById("home-glitch")?.remove();

  const canvas = document.createElement("canvas");
  canvas.id = "home-glitch";
  canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:999990";
  canvas.width = innerWidth;
  canvas.height = innerHeight;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  // Shades of the accent colour, dark to light, for the blocks.
  const hex = accent.replace("#", "");
  const rgb = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
  const shade = f => `rgb(${rgb.map(c => Math.min(255, Math.round(c * f))).join(",")})`;
  const shades = [0.25, 0.37, 0.54, 0.77, 1, 1.3, 1.65].map(shade);

  // 0.2 in the middle up to 1 at the edges -- most of it gathers at the
  // edges, with a little still over the content.
  const edginess = (fx, fy) => {
    const d = Math.hypot((fx - 0.5) * 2, (fy - 0.5) * 2) / 1.3;
    return 0.2 + 0.8 * Math.min(1, d * d);
  };

  // The whole screen broken into wide, flat blocks of black and dark grey.
  function blockBackground(strength) {
    ctx.globalAlpha = Math.min(1, strength);
    for (let y = 0; y < canvas.height; ) {
      const h = [8, 12, 16, 24][Math.floor(Math.random() * 4)];
      for (let x = 0; x < canvas.width; ) {
        const w = 24 + Math.random() * 180;
        const g = Math.floor(Math.random() ** 2 * 42);  // mostly near-black
        ctx.fillStyle = `rgb(${g},${g},${g + 2})`;
        ctx.fillRect(Math.round(x), y, Math.ceil(w), h);
        x += w;
      }
      y += h;
    }
  }

  // A clump of wide, flat blocks in the accent colour, spreading sideways.
  function clump(strength) {
    let x, y;
    do {
      x = Math.random() * canvas.width;
      y = Math.random() * canvas.height;
    } while (Math.random() > edginess(x / canvas.width, y / canvas.height));
    const size = [6, 8, 12, 16][Math.floor(Math.random() * 4)];
    const n = 4 + Math.floor(Math.random() * 10 * strength);
    const dx = (Math.random() < 0.5 ? -1 : 1) * (1 + Math.random() * 2);
    const dy = (Math.random() - 0.5) * 0.5;
    for (let i = 0; i < n; i++) {
      ctx.globalAlpha = 0.45 + Math.random() * 0.55;
      ctx.fillStyle = shades[Math.floor(Math.random() * shades.length)];
      const w = size * (2 + Math.floor(Math.random() * 4));
      const h = size * (Math.random() < 0.5 ? 0.5 : 1);
      ctx.fillRect(Math.round(x / 4) * 4, Math.round(y / 4) * 4, w, h);
      x += dx * size + (Math.random() - 0.5) * size * 0.6;
      y += dy * size + (Math.random() - 0.5) * size * 0.6;
    }
  }

  // A thin horizontal band of colour, broken into three parts.
  function streak() {
    ctx.globalAlpha = 0.6;
    const y = Math.random() * canvas.height, x = Math.random() * canvas.width * 0.8;
    const w = 60 + Math.random() * 260;
    [shades[3], shades[4], shades[6]].forEach((colour, i) => {
      ctx.fillStyle = colour;
      ctx.fillRect(x + (i * w) / 3, y + (i ? 0 : -3), w / 3, 3 + Math.random() * 8);
    });
  }

  // Static: drawn small and stretched up smoothly, much more sideways than
  // up and down, so each speck becomes a soft horizontal dash. Sparse, in
  // bands that come and go down the screen, heavier at the edges.
  const noise = document.createElement("canvas");
  noise.width = Math.ceil(innerWidth / 10);
  noise.height = Math.ceil(innerHeight / 3);
  const nctx = noise.getContext("2d");
  const edgeMask = new Float32Array(noise.width * noise.height);
  for (let y = 0; y < noise.height; y++)
    for (let x = 0; x < noise.width; x++)
      edgeMask[y * noise.width + x] = edginess(x / noise.width, y / noise.height);

  function staticNoise(strength) {
    const img = nctx.createImageData(noise.width, noise.height), d = img.data;
    let band = Math.random();
    for (let y = 0; y < noise.height; y++) {
      if (Math.random() < 0.15) band = Math.random();  // a new band starts
      for (let x = 0; x < noise.width; x++) {
        const p = y * noise.width + x, i = p * 4;
        if (Math.random() <= 1 - (0.04 + 0.2 * band) * strength * edgeMask[p]) continue;
        const glow = (0.7 + Math.random() * 0.6) * 1.5;
        d[i] = Math.min(255, rgb[0] * glow);
        d[i + 1] = Math.min(255, rgb[1] * glow);
        d[i + 2] = Math.min(255, rgb[2] * glow);
        d[i + 3] = 255;
      }
    }
    nctx.putImageData(img, 0, 0);
    ctx.globalAlpha = 1;
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(noise, 0, 0, canvas.width, canvas.height);
  }

  const clamp01 = v => Math.max(0, Math.min(1, v));
  const start = performance.now();
  function frame() {
    const t = (performance.now() - start) / (seconds * 1000);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (t >= 1) {
      canvas.remove();
      return;
    }
    // Blocks fade out over the first part while the static ("snow") fades in over
    // them; the static then dies away by the end.
    const blocks = amount * clamp01(1 - t / blockShare) ** 0.7;
    const snow = amount * clamp01((t - blockShare * 0.6) / (blockShare * 0.5)) * clamp01((1 - t) / (1 - blockShare)) ** 1.2;
    if (blocks > 0) blockBackground(blocks * 1.3);
    for (let i = 0; i < Math.round(55 * blocks); i++) clump(blocks);
    if (Math.random() < 0.5 * blocks) streak();
    if (snow > 0) staticNoise(Math.min(1, snow));
    // The blocks stutter (fewer redraws), like broken video; the static
    // runs smoother.
    setTimeout(frame, blocks > snow ? 70 + Math.random() * 40 : 33);
  }
  frame();
};
