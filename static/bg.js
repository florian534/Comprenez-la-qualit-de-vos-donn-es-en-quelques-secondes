/* Fond animé 3D : champ de points en profondeur + plans de verre flottants.
   Réagit à la souris et au défilement (parallaxe). Aucune dépendance. */
(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = document.documentElement;
  const rand = (a, b) => a + Math.random() * (b - a);

  /* ---------- structure ---------- */
  const bg = document.createElement('div');
  bg.id = 'bg'; bg.setAttribute('aria-hidden', 'true');
  bg.innerHTML = '<canvas id="bgc"></canvas><div class="scene"><div class="world" id="world"></div></div><div class="floor"></div><div class="veil"></div>';
  document.body.prepend(bg);
  const cv = bg.querySelector('#bgc'), ctx = cv.getContext('2d'), world = bg.querySelector('#world');

  /* ---------- couleurs du thème ---------- */
  let col = {brand: '47,143,91', brand2: '42,157,143'};
  const hex2rgb = h => { h = h.trim().replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); const n = parseInt(h, 16); return isNaN(n) ? null : `${n >> 16 & 255},${n >> 8 & 255},${n & 255}`; };
  const readColors = () => {
    const cs = getComputedStyle(root);
    col = {brand: hex2rgb(cs.getPropertyValue('--brand')) || col.brand, brand2: hex2rgb(cs.getPropertyValue('--brand2')) || col.brand2};
  };

  /* ---------- points en profondeur ---------- */
  let W = 0, H = 0, dpr = 1, pts = [];
  const resize = () => {
    dpr = Math.min(devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.round(Math.min(130, Math.max(45, W * H / 14000)));
    pts = Array.from({length: n}, () => ({c: Math.random() < .3, x: Math.random(), y: Math.random(), z: rand(.08, 1), vx: rand(-.00004, .00004), vy: rand(-.00004, .00004)}));
    syncPlanes();
  };

  /* ---------- plans 3D ---------- */
  const KIND = ['glass', 'grid', 'chart', 'ring', 'glass', 'grid'];
  const planes = [];
  const K_SCROLL = .28;                       // vitesse de défilement du monde 3D
  const docH = () => Math.max(document.documentElement.scrollHeight, innerHeight);
  const totalH = () => innerHeight + (docH() - innerHeight) * K_SCROLL + 300;

  function makePlane(y, side) {
    const kind = KIND[Math.floor(Math.random() * KIND.length)];
    const el = document.createElement('div'); el.className = 'plane ' + kind;
    const w = kind === 'ring' ? rand(180, 300) : rand(200, 420), h = kind === 'ring' ? w : rand(130, 280);
    el.style.width = w + 'px'; el.style.height = h + 'px';
    if (kind === 'chart') el.innerHTML = Array.from({length: 7}, () => `<i style="height:${rand(25, 95).toFixed(0)}%"></i>`).join('');
    world.appendChild(el);
    planes.push({el, x: side * rand(.08, .42) * innerWidth, y, z: rand(-700, 120), rx: rand(-28, 28), ry: rand(-38, 38), rz: rand(-14, 14),
      ph: rand(0, 6.28), sp: rand(.35, .8), amp: rand(8, 18), w, h});
  }
  function syncPlanes() {
    const need = totalH();
    let last = planes.length ? Math.max(...planes.map(p => p.y)) : -300;
    let side = planes.length % 2 ? 1 : -1;
    while (last < need) { last += rand(230, 340); makePlane(last, side); side = -side; }
  }

  /* ---------- entrées : souris + défilement (lissés) ---------- */
  const T = {mx: 0, my: 0, sy: scrollY}, C = {mx: 0, my: 0, sy: scrollY};
  addEventListener('pointermove', e => { T.mx = e.clientX / innerWidth * 2 - 1; T.my = e.clientY / innerHeight * 2 - 1; }, {passive: true});
  addEventListener('scroll', () => { T.sy = scrollY; }, {passive: true});
  addEventListener('resize', resize);
  new ResizeObserver(() => syncPlanes()).observe(document.body);   // la page grandit quand le rapport s'affiche

  /* ---------- mode allégé automatique (machines sans carte graphique) ---------- */
  let lite = false;
  const goLite = () => { lite = true; bg.classList.add('lite'); pts = pts.filter((_, i) => i % 2 === 0); };

  /* ---------- dessin ---------- */
  function drawPoints(t) {
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    const pos = pts.map(p => {
      const par = 1 - p.z;                                       // proche = grande parallaxe
      let x = (p.x + p.vx * t) % 1, y = (p.y + p.vy * t) % 1;
      if (x < 0) x += 1; if (y < 0) y += 1;
      let sy = (y * H - C.sy * par * .55) % H; if (sy < 0) sy += H;
      return {c: p.c, x: x * W - C.mx * par * 70, y: sy - C.my * par * 40, r: .6 + par * 2.2, a: .25 + par * .65};
    });
    for (let i = 0; i < pos.length; i++) {
      const a = pos[i];
      for (let j = i + 1; j < pos.length; j++) {
        const b = pos[j], dx = a.x - b.x, dy = a.y - b.y, d = dx * dx + dy * dy;
        if (d < 12000) { ctx.strokeStyle = `rgba(${col.brand},${(1 - d / 12000) * .3 * Math.min(a.a, b.a) * 2})`; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      }
    }
    for (const p of pos) { ctx.fillStyle = `rgba(${p.c ? col.brand2 : col.brand},${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832); ctx.fill(); }
  }

  function frame(ms) {
    const t = ms / 1000;
    C.mx += (T.mx - C.mx) * .06; C.my += (T.my - C.my) * .06; C.sy += (T.sy - C.sy) * .08;
    world.style.transform = `rotateX(${(-C.my * 5).toFixed(2)}deg) rotateY(${(C.mx * 7).toFixed(2)}deg) translate3d(0,${(-C.sy * K_SCROLL).toFixed(1)}px,0)`;
    for (const p of planes) {
      const bob = lite ? 0 : Math.sin(t * p.sp + p.ph);
      p.el.style.transform = `translate3d(${(innerWidth / 2 + p.x - p.w / 2).toFixed(0)}px,${(p.y + bob * p.amp).toFixed(1)}px,${p.z.toFixed(0)}px) rotateX(${(p.rx + bob * 3).toFixed(1)}deg) rotateY(${(p.ry + (lite ? 0 : Math.cos(t * p.sp + p.ph) * 4)).toFixed(1)}deg) rotateZ(${p.rz}deg)`;
    }
    if (!lite || n % 2 === 0) drawPoints(t);
  }

  let raf = 0, n = 0, last = 0, acc = 0, cnt = 0;
  const loop = ms => {
    if (!document.hidden) {
      if (++n % 90 === 0) readColors();
      if (!lite && last) { acc += ms - last; if (++cnt === 150) { if (acc / cnt > 45) goLite(); cnt = 0; acc = 0; } }   // moyenne > 45 ms = moins de 22 images/s
      last = ms; frame(ms);
    } else last = 0;
    raf = requestAnimationFrame(loop);
  };

  readColors(); resize();
  if (reduce) { frame(0); addEventListener('scroll', () => frame(0), {passive: true}); }
  else raf = requestAnimationFrame(loop);
  new MutationObserver(readColors).observe(root, {attributes: true, attributeFilter: ['data-theme']});
})();
