/* Visionneuse de présentations PowerPoint : robot endormi -> diaporama flouté au centre de la page.
   Les fichiers .pptx sont lus dans static/presentations/ (liste fournie par /api/presentations)
   (le premier par ordre alphabétique). Le rendu est fait dans le navigateur par pptx-preview. */
(() => {
  const DIR = '/presentations/', LIB = '/pptx-preview.umd.js';
  let ov, stage, host, msg, titleEl, dotsEl, countEl, prevB, nextB, closeB;
  let pv = null, buf = null, ratio = 16 / 9, total = 0, lastFocus = null, libP = null, job = 0, timer = 0;

  /* ---------- structure ---------- */
  function build() {
    ov = document.createElement('div');
    ov.className = 'deckov'; ov.hidden = true;
    ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true');
    ov.setAttribute('aria-label', 'Présentation du projet');
    ov.innerHTML =
      '<div class="decktop"><span class="decktitle"></span>' +
      '<button class="deckx" type="button" aria-label="Fermer la présentation">\u2715</button></div>' +
      '<div class="deckwrap"><div class="deckstage"><div class="deckhost"></div><p class="deckmsg" hidden></p></div>' +
      '<div class="deckbar"><button class="deckb" data-d="prev" type="button" aria-label="Slide précédent">\u2039</button>' +
      '<div class="deckdots"></div>' +
      '<button class="deckb" data-d="next" type="button" aria-label="Slide suivant">\u203a</button>' +
      '<span class="deckcount"></span></div></div>';
    document.body.appendChild(ov);
    const q = s => ov.querySelector(s);
    stage = q('.deckstage'); host = q('.deckhost'); msg = q('.deckmsg'); titleEl = q('.decktitle');
    dotsEl = q('.deckdots'); countEl = q('.deckcount');
    prevB = q('[data-d=prev]'); nextB = q('[data-d=next]'); closeB = q('.deckx');

    prevB.addEventListener('click', () => go(cur() - 1));
    nextB.addEventListener('click', () => go(cur() + 1));
    closeB.addEventListener('click', close);
    ov.addEventListener('click', e => { if (e.target === ov || e.target.classList.contains('deckwrap')) close(); });
    let x0 = null;
    ov.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; }, {passive: true});
    ov.addEventListener('touchend', e => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0; x0 = null;
      if (Math.abs(dx) > 50) go(cur() + (dx < 0 ? 1 : -1));
    }, {passive: true});
    addEventListener('resize', () => {
      if (ov.hidden) return;
      clearTimeout(timer);
      timer = setTimeout(() => { if (buf) render(cur()).catch(fail); else resizeStage(); }, 250);
    });
    document.addEventListener('keydown', onKey);
  }

  /* ---------- utilitaires ---------- */
  const cur = () => (pv ? pv.currentIndex : 0);
  const say = html => { msg.innerHTML = html; msg.hidden = !html; };
  const esc = s => String(s).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
  function fail(e) {
    console.error(e);
    say('Impossible d\u2019afficher cette présentation.<br>' + esc(e && e.message ? e.message : e));
    total = 0; pv = null; ui();
  }
  function size() {
    let w = Math.min(1200, innerWidth * .92, (innerHeight - 170) * ratio);
    w = Math.max(260, Math.floor(w));
    return {w, h: Math.round(w / ratio)};
  }
  function resizeStage() { const s = size(); stage.style.width = s.w + 'px'; stage.style.height = s.h + 'px'; }

  function loadLib() {
    if (window.pptxPreview) return Promise.resolve();
    if (!libP) libP = new Promise((ok, ko) => {
      const s = document.createElement('script');
      s.src = LIB; s.onload = ok;
      s.onerror = () => { libP = null; ko(new Error('Le fichier pptx-preview.umd.js est introuvable dans le dossier static.')); };
      document.head.appendChild(s);
    });
    return libP;
  }

  /* ---------- chargement et rendu ---------- */
  async function loadFile(name) {
    say('Chargement de \u00AB ' + esc(name) + ' \u00BB\u2026');
    try {
      const r = await fetch(DIR + encodeURIComponent(name));
      if (!r.ok) throw new Error('Fichier introuvable : ' + name);
      await useBuffer(await r.arrayBuffer(), name);
    } catch (e) { fail(e); }
  }
  async function useBuffer(b, name) {
    buf = b; titleEl.textContent = name; titleEl.title = name;
    say('Préparation des slides\u2026');
    await loadLib();
    await render(0);
  }
  async function render(keep) {
    const my = ++job;
    resizeStage();
    const {w, h} = size();
    if (pv) { try { pv.destroy(); } catch (e) {} pv = null; }
    host.innerHTML = '';
    const p = window.pptxPreview.init(host, {width: w, height: h, mode: 'slide'});
    await p.preview(buf.slice(0));
    if (my !== job) return;
    const r = p.pptx.width / p.pptx.height;
    if (r > 0 && Math.abs(r - ratio) > .01) { ratio = r; return render(keep); }
    pv = p; total = p.slideCount; say('');
    for (let i = 0; i < Math.min(keep, total - 1); i++) p.renderNextSlide();
    dots(); ui();
  }

  /* ---------- navigation ---------- */
  function go(n) {
    if (!pv) return;
    n = Math.max(0, Math.min(total - 1, n));
    let guard = total + 2;
    while (pv.currentIndex < n && guard--) pv.renderNextSlide();
    while (pv.currentIndex > n && guard--) pv.renderPreSlide();
    ui();
  }
  function dots() {
    dotsEl.innerHTML = '';
    for (let i = 0; i < total; i++) {
      const b = document.createElement('button');
      b.type = 'button'; b.setAttribute('aria-label', 'Slide ' + (i + 1));
      b.addEventListener('click', () => go(i));
      dotsEl.appendChild(b);
    }
  }
  function ui() {
    const i = cur();
    [...dotsEl.children].forEach((d, k) => d.setAttribute('aria-current', k === i ? 'true' : 'false'));
    countEl.textContent = total ? (i + 1) + ' / ' + total : '';
    prevB.disabled = !total || i === 0; nextB.disabled = !total || i >= total - 1;
  }
  function onKey(e) {
    if (!ov || ov.hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); go(cur() + 1); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); go(cur() - 1); }
    else if (e.key === 'Home') { e.preventDefault(); go(0); }
    else if (e.key === 'End') { e.preventDefault(); go(total - 1); }
    else if (e.key === 'Tab') {
      const f = [...ov.querySelectorAll('button:not([disabled])')];
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }

  /* ---------- ouverture / fermeture ---------- */
  async function open() {
    if (!ov) build();
    lastFocus = document.activeElement;
    ov.hidden = false; document.body.style.overflow = 'hidden';
    resizeStage();
    requestAnimationFrame(() => ov.classList.add('open'));
    document.getElementById('robot')?.classList.add('awake');
    closeB.focus();
    if (pv) { go(0); return; }               // déjà chargée : on repart de la première slide
    say('Recherche des présentations\u2026');
    let files = [];
    try { files = (await (await fetch('/api/presentations')).json()).files || []; } catch (e) {}
    if (files.length) loadFile(files[0]);      // la présentation affichée est celle du dossier static/presentations
    else say('Aucune présentation trouvée.<br>Déposez un fichier <code>.pptx</code> dans <code>static/presentations</code>.');
  }
  function close() {
    ov.classList.remove('open');
    document.body.style.overflow = '';
    document.getElementById('robot')?.classList.remove('awake');
    setTimeout(() => { ov.hidden = true; }, 220);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  document.getElementById('infoBtn')?.addEventListener('click', open);
  document.getElementById('robotSvg')?.addEventListener('click', open);
})();
