/* Visionneuse de présentations PowerPoint :
   - robot endormi dans la page ;
   - clic sur le robot ;
   - le robot se réveille ;
   - une copie du robot apparaît en haut à droite des slides ;
   - le diaporama PowerPoint s'affiche au centre.

   Les fichiers .pptx sont lus dans static/presentations/
   La liste des présentations est fournie par /api/presentations.
*/

(() => {
  const DIR = '/presentations/';
  const LIB = '/pptx-preview.umd.js';

  let ov;
  let stage;
  let host;
  let msg;
  let titleEl;
  let dotsEl;
  let countEl;
  let prevB;
  let nextB;
  let closeB;
  let robotEl;

  let pv = null;
  let buf = null;
  let ratio = 16 / 9;
  let total = 0;
  let lastFocus = null;
  let libP = null;
  let job = 0;
  let timer = 0;

  /* ============================================================
     CREATION DE LA FENETRE DE PRESENTATION
     ============================================================ */

  function build() {
    ov = document.createElement('div');

    ov.className = 'deckov';
    ov.hidden = true;

    ov.setAttribute('role', 'dialog');
    ov.setAttribute('aria-modal', 'true');
    ov.setAttribute('aria-label', 'Présentation du projet');

    ov.innerHTML =
      '<div class="decktop">' +
        '<span class="decktitle"></span>' +
        '<button class="deckx" type="button" aria-label="Fermer la présentation">✕</button>' +
      '</div>' +

      '<div class="deckwrap">' +

        '<div class="deckstage">' +

          /* Les slides PowerPoint sont affichées ici */
          '<div class="deckhost"></div>' +

          /* Copie du robot qui apparaît en haut à droite */
          '<div class="deckrobot" aria-hidden="true"></div>' +

          /* Message de chargement / erreur */
          '<p class="deckmsg" hidden></p>' +

        '</div>' +

        '<div class="deckbar">' +
          '<button class="deckb" data-d="prev" type="button" aria-label="Slide précédent">‹</button>' +
          '<div class="deckdots"></div>' +
          '<button class="deckb" data-d="next" type="button" aria-label="Slide suivant">›</button>' +
          '<span class="deckcount"></span>' +
        '</div>' +

      '</div>';

    document.body.appendChild(ov);

    const q = selector => ov.querySelector(selector);

    stage = q('.deckstage');
    host = q('.deckhost');
    msg = q('.deckmsg');
    titleEl = q('.decktitle');

    /* Zone qui contiendra le clone du robot */
    robotEl = q('.deckrobot');

    dotsEl = q('.deckdots');
    countEl = q('.deckcount');

    prevB = q('[data-d=prev]');
    nextB = q('[data-d=next]');
    closeB = q('.deckx');

    prevB.addEventListener('click', () => go(cur() - 1));
    nextB.addEventListener('click', () => go(cur() + 1));
    closeB.addEventListener('click', close);

    /* Ferme si on clique en dehors de la présentation */
    ov.addEventListener('click', event => {
      if (
        event.target === ov ||
        event.target.classList.contains('deckwrap')
      ) {
        close();
      }
    });

    /* Navigation tactile sur mobile */
    let x0 = null;

    ov.addEventListener(
      'touchstart',
      event => {
        x0 = event.touches[0].clientX;
      },
      { passive: true }
    );

    ov.addEventListener(
      'touchend',
      event => {
        if (x0 === null) {
          return;
        }

        const dx = event.changedTouches[0].clientX - x0;
        x0 = null;

        if (Math.abs(dx) > 50) {
          go(cur() + (dx < 0 ? 1 : -1));
        }
      },
      { passive: true }
    );

    /* Redimensionnement de la présentation */
    addEventListener('resize', () => {
      if (ov.hidden) {
        return;
      }

      clearTimeout(timer);

      timer = setTimeout(() => {
        if (buf) {
          render(cur()).catch(fail);
        } else {
          resizeStage();
        }
      }, 250);
    });

    document.addEventListener('keydown', onKey);
  }

  /* ============================================================
     OUTILS
     ============================================================ */

  const cur = () => (pv ? pv.currentIndex : 0);

  const esc = value =>
    String(value).replace(
      /[&<>]/g,
      character =>
        ({
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;'
        })[character]
    );

  function say(html) {
    msg.innerHTML = html;
    msg.hidden = !html;
  }

  function fail(error) {
    console.error(error);

    const message =
      error && error.message
        ? error.message
        : String(error);

    say(
      'Impossible d’afficher cette présentation.<br>' +
      esc(message)
    );

    total = 0;
    pv = null;
    ui();
  }

  function size() {
    let width = Math.min(
      1200,
      innerWidth * 0.92,
      (innerHeight - 170) * ratio
    );

    width = Math.max(260, Math.floor(width));

    return {
      w: width,
      h: Math.round(width / ratio)
    };
  }

  function resizeStage() {
    const dimensions = size();

    stage.style.width = dimensions.w + 'px';
    stage.style.height = dimensions.h + 'px';
  }

  /* ============================================================
     ROBOT DANS LA PRESENTATION
     ============================================================ */

  function wakeRobot() {
    /* Réveille le robot original de la page */
    const originalRobot = document.getElementById('robot');

    if (originalRobot) {
      originalRobot.classList.add('awake');
    }

    /* Le SVG source est celui de la page */
    const sourceSvg = document.getElementById('robotSvg');

    if (!robotEl || !sourceSvg) {
      return;
    }

    /* On vide la zone pour ne pas ajouter plusieurs copies */
    robotEl.innerHTML = '';

    /* Création d'une copie complète du SVG */
    const robotCopy = sourceSvg.cloneNode(true);

    /* Un seul élément doit avoir l'id robotSvg */
    robotCopy.removeAttribute('id');

    /* La copie est décorative */
    robotCopy.setAttribute('aria-hidden', 'true');

    /* Taille du robot dans la présentation */
    robotCopy.setAttribute('width', '118');
    robotCopy.setAttribute('height', '98');

    /* Active les styles du robot réveillé */
    robotEl.classList.add('awake');

    /* Ajoute le robot en haut à droite des slides */
    robotEl.appendChild(robotCopy);
  }

  function sleepRobot() {
    /* Le robot principal redevient endormi */
    const originalRobot = document.getElementById('robot');

    if (originalRobot) {
      originalRobot.classList.remove('awake');
    }

    /* Supprime la copie dans la présentation */
    if (robotEl) {
      robotEl.innerHTML = '';
      robotEl.classList.remove('awake');
    }
  }

  /* ============================================================
     CHARGEMENT DE LA LIBRAIRIE POWERPOINT
     ============================================================ */

  function loadLib() {
    if (window.pptxPreview) {
      return Promise.resolve();
    }

    if (!libP) {
      libP = new Promise((resolve, reject) => {
        const script = document.createElement('script');

        script.src = LIB;

        script.onload = resolve;

        script.onerror = () => {
          libP = null;

          reject(
            new Error(
              'Le fichier pptx-preview.umd.js est introuvable dans le dossier static.'
            )
          );
        };

        document.head.appendChild(script);
      });
    }

    return libP;
  }

  /* ============================================================
     CHARGEMENT DU FICHIER PPTX
     ============================================================ */

  async function loadFile(name) {
    say('Chargement de « ' + esc(name) + ' »…');

    try {
      const response = await fetch(DIR + encodeURIComponent(name));

      if (!response.ok) {
        throw new Error('Fichier introuvable : ' + name);
      }

      const buffer = await response.arrayBuffer();

      await useBuffer(buffer, name);
    } catch (error) {
      fail(error);
    }
  }

  async function useBuffer(buffer, name) {
    buf = buffer;

    titleEl.textContent = name;
    titleEl.title = name;

    say('Préparation des slides…');

    await loadLib();

    await render(0);
  }

  async function render(keep) {
    const currentJob = ++job;

    resizeStage();

    const dimensions = size();
    const width = dimensions.w;
    const height = dimensions.h;

    if (pv) {
      try {
        pv.destroy();
      } catch (error) {
        console.warn(error);
      }

      pv = null;
    }

    host.innerHTML = '';

    const preview = window.pptxPreview.init(host, {
      width,
      height,
      mode: 'slide'
    });

    await preview.preview(buf.slice(0));

    if (currentJob !== job) {
      return;
    }

    const newRatio = preview.pptx.width / preview.pptx.height;

    if (newRatio > 0 && Math.abs(newRatio - ratio) > 0.01) {
      ratio = newRatio;
      return render(keep);
    }

    pv = preview;
    total = preview.slideCount;

    say('');

    /* Retourne à la slide où était l'utilisateur */
    for (let i = 0; i < Math.min(keep, total - 1); i++) {
      preview.renderNextSlide();
    }

    dots();
    ui();
  }

  /* ============================================================
     NAVIGATION ENTRE LES SLIDES
     ============================================================ */

  function go(index) {
    if (!pv) {
      return;
    }

    const target = Math.max(0, Math.min(total - 1, index));

    let guard = total + 2;

    while (pv.currentIndex < target && guard--) {
      pv.renderNextSlide();
    }

    while (pv.currentIndex > target && guard--) {
      pv.renderPreSlide();
    }

    ui();
  }

  function dots() {
    dotsEl.innerHTML = '';

    for (let index = 0; index < total; index++) {
      const button = document.createElement('button');

      button.type = 'button';
      button.setAttribute(
        'aria-label',
        'Slide ' + (index + 1)
      );

      button.addEventListener('click', () => go(index));

      dotsEl.appendChild(button);
    }
  }

  function ui() {
    const index = cur();

    [...dotsEl.children].forEach((dot, position) => {
      dot.setAttribute(
        'aria-current',
        position === index ? 'true' : 'false'
      );
    });

    countEl.textContent = total ? index + 1 + ' / ' + total : '';

    prevB.disabled = !total || index === 0;
    nextB.disabled = !total || index >= total - 1;
  }

  /* ============================================================
     CLAVIER
     ============================================================ */

  function onKey(event) {
    if (!ov || ov.hidden) {
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }

    else if (
      event.key === 'ArrowRight' ||
      event.key === 'PageDown'
    ) {
      event.preventDefault();
      go(cur() + 1);
    }

    else if (
      event.key === 'ArrowLeft' ||
      event.key === 'PageUp'
    ) {
      event.preventDefault();
      go(cur() - 1);
    }

    else if (event.key === 'Home') {
      event.preventDefault();
      go(0);
    }

    else if (event.key === 'End') {
      event.preventDefault();
      go(total - 1);
    }

    /* Garde le focus à l'intérieur de la fenêtre */
    else if (event.key === 'Tab') {
      const focusable = [
        ...ov.querySelectorAll('button:not([disabled])')
      ];

      if (!focusable.length) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }

      else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  /* ============================================================
     OUVERTURE / FERMETURE
     ============================================================ */

  async function open() {
    if (!ov) {
      build();
    }

    lastFocus = document.activeElement;

    ov.hidden = false;

    document.body.style.overflow = 'hidden';

    resizeStage();

    requestAnimationFrame(() => {
      ov.classList.add('open');
    });

    /* Le robot original se réveille,
       puis une copie apparaît sur les slides. */
    wakeRobot();

    closeB.focus();

    /* Présentation déjà chargée : retour à la première slide */
    if (pv) {
      go(0);
      return;
    }

    say('Recherche des présentations…');

    let files = [];

    try {
      const response = await fetch('/api/presentations');
      const data = await response.json();

      files = data.files || [];
    } catch (error) {
      console.warn('Impossible de charger la liste des présentations.', error);
    }

    if (files.length) {
      loadFile(files[0]);
    } else {
      say(
        'Aucune présentation trouvée.<br>' +
        'Déposez un fichier <code>.pptx</code> dans ' +
        '<code>static/presentations</code>.'
      );
    }
  }

  function close() {
    if (!ov) {
      return;
    }

    ov.classList.remove('open');

    document.body.style.overflow = '';

    /* Le robot redevient endormi et disparaît des slides */
    sleepRobot();

    setTimeout(() => {
      ov.hidden = true;
    }, 220);

    if (lastFocus && lastFocus.focus) {
      lastFocus.focus();
    }
  }

  /* ============================================================
     EVENEMENTS : clic sur le robot ou sur la bulle
     ============================================================ */

  document.getElementById('infoBtn')?.addEventListener('click', open);

  document.getElementById('robotSvg')?.addEventListener('click', open);
})();
