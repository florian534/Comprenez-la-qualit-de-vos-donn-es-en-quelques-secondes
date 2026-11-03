/* « Du fichier au rapport » : animation pilotée par le défilement.
   La section reste épinglée à l'écran pendant que vous défilez ; la progression du défilement
   fait avancer une ligne et allume les 4 étapes l'une après l'autre.
   Respecte « réduire les animations » et passe en affichage fixe une fois le rapport affiché.
   Pour désactiver : retirer la ligne <script src="/flow.js"> de index.html (la section reste lisible). */
(() => {
  const flow = document.getElementById('flow');
  if (!flow) return;

  const steps = [...flow.querySelectorAll('.flow-steps li')];
  const result = document.getElementById('result');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));

  // Progression du défilement (0 à 1) à laquelle chaque étape s'allume
  const TH = [0.04, 0.26, 0.48, 0.70];

  flow.classList.add('js');

  let target = 0, cur = 0, raf = 0;

  // Affichage fixe : « réduire les animations », ou rapport déjà affiché (on ne fait pas redéfiler 3 écrans)
  const isStatic = () => reduce || (result && !result.classList.contains('hide'));

  function applyMode() {
    const stat = isStatic();
    flow.classList.toggle('static', stat);
    if (stat) document.body.classList.remove('in-flow');
    if (stat) {
      steps.forEach(li => li.classList.add('on'));
      flow.style.setProperty('--p', 1);
      flow.style.setProperty('--fill', 1);
      flow.classList.add('done');
    } else {
      kick();
    }
  }

  function measure() {
    const r = flow.getBoundingClientRect();
    const total = flow.offsetHeight - innerHeight;       // distance de défilement pendant laquelle la section est épinglée
    target = total > 0 ? clamp(-r.top / total) : 1;
    document.body.classList.toggle('in-flow', r.top <= 0 && r.bottom >= innerHeight);   // section épinglée à l'écran
  }

  function render() {
    cur += (target - cur) * 0.12;                         // lissage : le mouvement rattrape le défilement en douceur
    if (Math.abs(target - cur) < 0.0005) cur = target;

    const fill = clamp((cur - TH[0]) / (TH[3] - TH[0]));  // la ligne atteint la dernière étape quand elle s'allume
    flow.style.setProperty('--p', cur.toFixed(4));
    flow.style.setProperty('--fill', fill.toFixed(4));
    steps.forEach((li, i) => li.classList.toggle('on', cur >= TH[i]));
    flow.classList.toggle('done', cur > 0.88);

    raf = cur !== target ? requestAnimationFrame(render) : 0;
  }

  function kick() {
    if (flow.classList.contains('static')) return;
    measure();
    if (!raf) raf = requestAnimationFrame(render);
  }

  addEventListener('scroll', kick, {passive: true});
  addEventListener('resize', kick);

  // Le rapport s'affiche : on passe en affichage fixe
  if (result) new MutationObserver(applyMode).observe(result, {attributes: true, attributeFilter: ['class']});

  // Bouton de fin : retour à la zone de dépôt
  const cta = document.getElementById('flowCta');
  if (cta) cta.addEventListener('click', () => {
    const drop = document.getElementById('drop');
    if (drop) { drop.scrollIntoView({behavior: reduce ? 'auto' : 'smooth', block: 'center'}); drop.focus({preventScroll: true}); }
  });

  applyMode();
  if (!isStatic()) kick();
})();
