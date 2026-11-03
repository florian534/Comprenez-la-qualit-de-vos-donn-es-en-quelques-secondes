/* Confort d'utilisation : retour en haut, repli des sections, accessibilité clavier,
   étapes de progression de l'analyse IA. Aucune dépendance ; s'appuie sur le DOM créé par app.js.
   Pour tout désactiver : retirer la ligne <script src="/ux.js"> de index.html. */
(() => {
  const $ = s => document.querySelector(s);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const behavior = reduce ? 'auto' : 'smooth';

  /* ---------- 1. Bouton « retour en haut » ---------- */
  const topBtn = document.createElement('button');
  topBtn.type = 'button'; topBtn.className = 'totop'; topBtn.hidden = true;
  topBtn.setAttribute('aria-label', 'Retour en haut de la page');
  topBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  topBtn.addEventListener('click', () => window.scrollTo({top: 0, behavior}));
  document.body.appendChild(topBtn);
  const onScroll = () => { topBtn.hidden = scrollY < 600; };
  addEventListener('scroll', onScroll, {passive: true}); onScroll();

  /* ---------- 2. Sections repliables ---------- */
  const toggleAll = $('#toggleAll');
  const sections = () => [...document.querySelectorAll('#report > section')];

  function syncAllBtn() {
    if (!toggleAll) return;
    const list = sections();
    toggleAll.hidden = !list.length;
    const anyOpen = list.some(s => !s.classList.contains('collapsed'));
    toggleAll.textContent = anyOpen ? 'Tout replier' : 'Tout déplier';
    toggleAll.setAttribute('aria-label', anyOpen ? 'Replier toutes les sections' : 'Déplier toutes les sections');
  }

  function setOpen(sec, open) {
    sec.classList.toggle('collapsed', !open);
    const head = sec.querySelector(':scope > .sh');
    if (head) head.setAttribute('aria-expanded', String(open));
  }

  function enhanceSections() {
    sections().forEach(sec => {
      const head = sec.querySelector(':scope > .sh');
      if (!head || head.dataset.ux) return;
      head.dataset.ux = '1';
      head.setAttribute('role', 'button');
      head.setAttribute('aria-expanded', 'true');
      head.setAttribute('title', 'Replier / déplier cette section');
      head.tabIndex = 0;
      head.addEventListener('click', () => { setOpen(sec, sec.classList.contains('collapsed')); syncAllBtn(); });
      head.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); head.click(); }
      });
    });
    syncAllBtn();
  }

  if (toggleAll) toggleAll.addEventListener('click', () => {
    const open = sections().every(s => s.classList.contains('collapsed'));   // tout replié -> on déplie
    sections().forEach(s => setOpen(s, open));
    syncAllBtn();
  });

  // Cliquer sur un lien du menu déplie d'abord la section visée
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('#nav a[href^="#"]');
    if (!a) return;
    const sec = document.getElementById(a.getAttribute('href').slice(1));
    if (sec && sec.classList.contains('collapsed')) { setOpen(sec, true); syncAllBtn(); }
  });

  /* ---------- 3. Accessibilité : zones annoncées, zone de dépôt au clavier, lien d'évitement ---------- */
  function enhanceLive() {
    ['#aiNote', '#rag-eval-results', '#sql-eval-results'].forEach(sel => {
      const el = $(sel);
      if (el && !el.hasAttribute('aria-live')) { el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite'); }
    });
  }

  const drop = $('#drop');
  if (drop) {
    drop.tabIndex = 0; drop.setAttribute('role', 'button');
    drop.setAttribute('aria-label', 'Déposer des fichiers ou ouvrir le sélecteur de fichiers');
    drop.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); drop.click(); }
    });
  }

  const skip = $('.skip');
  if (skip) skip.addEventListener('click', e => {
    e.preventDefault();
    const report = $('#report');
    const target = $('#result') && !$('#result').classList.contains('hide') && report ? report : drop;
    if (!target) return;
    target.setAttribute('tabindex', '-1');
    target.focus({preventScroll: true});
    target.scrollIntoView({behavior, block: 'start'});
  });

  // app.js reconstruit tout #report à chaque analyse : on réapplique les améliorations
  const report = $('#report');
  if (report) new MutationObserver(() => { enhanceSections(); enhanceLive(); }).observe(report, {childList: true});
  enhanceSections(); enhanceLive();

  /* ---------- 4. Étapes de progression de l'analyse IA ---------- */
  // Les étapes viennent du serveur (/api/progress) : elles reflètent ce qui se passe réellement.
  let timer = 0, poll = 0, t0 = 0, state = {step: 'search', pdf: false}, noteEl = null;

  const fmtTime = s => s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + ' s';

  function draw() {
    if (!noteEl || !noteEl.isConnected) return;
    const s = state.step;
    const item = (label, status) => `<li class="${status}"><span class="dot" aria-hidden="true"></span>${label}</li>`;
    const pdfStatus = !state.pdf ? 'skip' : s === 'search' ? 'active' : 'done';
    const writeStatus = s === 'write' ? 'active' : 'todo';
    noteEl.innerHTML =
      '<ol class="steps" aria-label="Étapes de l’analyse">' +
      item('Audit des données', 'done') +
      item(state.pdf ? 'Recherche dans les PDF' : 'Recherche dans les PDF (aucun PDF ajouté)', pdfStatus) +
      item('Rédaction par Ollama', writeStatus) +
      '</ol><span class="steptime">Temps écoulé : ' + fmtTime(Math.round((Date.now() - t0) / 1000)) + '</span>';
  }

  async function refresh() {
    try {
      const r = await fetch('/api/progress', {cache: 'no-store'});
      if (r.ok) { const j = await r.json(); if (j.step && j.step !== 'idle') state = {step: j.step, pdf: !!j.pdf}; }
    } catch (e) { /* le serveur répond plus tard : on garde l'état précédent */ }
    draw();
  }

  window.UX = {
    aiStart(note) {
      this.aiStop();
      noteEl = note; t0 = Date.now(); state = {step: 'search', pdf: false};
      note.className = 'ainote muted';
      draw();
      timer = setInterval(draw, 1000);          // le chronomètre avance chaque seconde
      poll = setInterval(refresh, 1500);        // l'étape est demandée au serveur
      refresh();
    },
    aiStop() { clearInterval(timer); clearInterval(poll); timer = poll = 0; noteEl = null; }
  };
})();
