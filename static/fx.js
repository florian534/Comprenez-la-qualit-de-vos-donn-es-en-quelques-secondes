/* Transitions : les sections du rapport apparaissent en fondu au défilement
   (les animations de contenu sont dans style.css).
   Respecte « réduire les animations » du système.
   Pour désactiver : retirer la ligne <script src="/fx.js"> de index.html. */
(() => {
  // Utilisateur qui a demandé moins d'animations : on n'ajoute rien (le CSS les coupe aussi)
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let io = null;
  if ('IntersectionObserver' in window) {
    io = new IntersectionObserver(entries => entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('fx-in'); io.unobserve(e.target); }
    }), {rootMargin: '0px 0px -6% 0px'});   // déclenche dès que le haut de la section entre dans l'écran
  }

  function prepare() {
    if (!io) return;   // sans IntersectionObserver : aucune section n'est masquée
    document.querySelectorAll('#report > section').forEach(s => {
      if (s.dataset.fx) return;
      s.dataset.fx = '1';
      s.classList.add('fxrev');
      io.observe(s);
    });
  }

  const report = document.getElementById('report');
  if (report) { new MutationObserver(prepare).observe(report, {childList: true}); prepare(); }

  // Impression : tout doit être visible
  addEventListener('beforeprint', () => document.querySelectorAll('.fxrev').forEach(s => s.classList.add('fx-in')));
})();
