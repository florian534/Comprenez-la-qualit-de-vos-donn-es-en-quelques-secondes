const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => n == null ? '—' : typeof n === 'number' ? n.toLocaleString('fr-FR', {maximumFractionDigits: 3}) : esc(n);
const pct = n => {
  const value = Number(n);

  if (!Number.isFinite(value)) {
    return '—';
  }

  return value.toLocaleString('fr-FR', {
    maximumFractionDigits: 1
  }) + ' %';
};

/* ---------- Icônes ---------- */
const ICONS = {
  db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  rows: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  cols: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
  miss: '<circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/><path d="M12 8v4M12 16h.01"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  minus: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  spark: '<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
  down: '<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  logo: '<path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/>'
};
const ic = n => `<svg class="i" viewBox="0 0 24 24">${ICONS[n]}</svg>`;
$('#logo').innerHTML = ic('logo');
$('#upIco').innerHTML = ic('upload');
$('#dlJson').innerHTML = ic('down') + 'JSON';
$('#dlHtml').innerHTML = ic('down') + 'Rapport HTML';

/* ---------- Thème ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  $('#theme').innerHTML = ic(t === 'dark' ? 'sun' : 'moon');
  try { localStorage.setItem('theme', t); } catch (e) {}
}
let saved = null; try { saved = localStorage.getItem('theme'); } catch (e) {}
setTheme(saved || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light'));
$('#theme').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');

/* ---------- État ---------- */
let raw = {};
let view = {};
let importErrors = {};
let aiText = '';
let ollamaModel = '';

fetch('/api/config')
  .then(r => r.json())
  .then(c => {
    ollamaModel = c.model || '';
  })
  .catch(() => {});
fetch('/api/config').then(r => r.json()).then(c => { ollamaModel = c.model; }).catch(() => {});

async function readJson(r) {
  const text = await r.text();
  try { return JSON.parse(text); }
  catch (e) {
    throw new Error('Réponse invalide du serveur (HTTP ' + r.status + '). ' +
      (text.trim() ? text.trim().slice(0, 200) : 'Réponse vide : regardez le terminal où tourne server.py et vérifiez que la page est ouverte sur http://127.0.0.1:5000'));
  }
}

/* ---------- Import ---------- */
const drop = $('#drop'), fileInput = $('#file');
drop.onclick = () => fileInput.click();
fileInput.onchange = () => sendFiles([...fileInput.files]);
['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', ev => sendFiles([...ev.dataTransfer.files]));

const size = b => b > 1e9 ? (b / 1e9).toFixed(1) + ' Go' : b > 1e6 ? (b / 1e6).toFixed(1) + ' Mo' : Math.max(1, Math.round(b / 1e3)) + ' Ko';

function setStatus(msg, err = false, busy = false) {
  const st = $('#status');
  st.className = 'status ' + (err ? 'err' : 'muted');
  st.innerHTML = (busy ? '<span class="spin"></span>' : '') + esc(msg);
  $('#progress').classList.toggle('hide', !busy);
}

async function sendFiles(files) {
  // Les PDF servent de documents de référence (RAG).
  // Les autres fichiers supportés sont envoyés pour l'audit.
  const pdfs = files.filter(f => /\.pdf$/i.test(f.name));

  if (pdfs.length) {
    uploadDocs(pdfs);
    files = files.filter(f => !/\.pdf$/i.test(f.name));
  }

  // Cas : uniquement des PDF sélectionnés
  if (!files.length) {
    return;
  }

  // Affiche la liste des fichiers à importer
  $('#files').innerHTML = files
    .map(f => `<span class="file">${esc(f.name)} <small>${size(f.size)}</small></span>`)
    .join('');

  // Prépare les fichiers pour l'API Flask
  const fd = new FormData();

  files.forEach(f => {
    fd.append('files', f, f.name);
  });

  // Réinitialise l'analyse IA et les erreurs précédentes
  aiText = '';
  importErrors = {};

  setStatus('Audit en cours avec DuckDB…', false, true);

  try {
    const r = await fetch('/api/audit', {
      method: 'POST',
      body: fd
    });

    const j = await readJson(r);

    if (!r.ok) {
      throw new Error(j.error || 'Erreur serveur pendant l’audit.');
    }

    // Sécurise les valeurs reçues de l'API
    raw = j.audit && typeof j.audit === 'object' ? j.audit : {};
    importErrors = j.errors && typeof j.errors === 'object' ? j.errors : {};

    // Transforme les données audit.py en structure utilisée par l'interface
    view = mergeAudit(raw);

    // Vide le cache des graphiques de colonnes
    for (const k in cache) {
      delete cache[k];
    }

    const tableCount = Object.keys(view).length;
    const ignored = Array.isArray(j.ignored) ? j.ignored : [];
    const errorNames = Object.keys(importErrors);

    // Message normal + avertissements éventuels
    let message = `${tableCount} table(s) analysée(s).`;

    if (ignored.length) {
      message += ` Fichiers ignorés : ${ignored.join(', ')}.`;
    }

    if (errorNames.length) {
      message += ` ${errorNames.length} table(s) en erreur : ${errorNames.join(', ')}.`;
    }

    // Si aucune table n'est exploitable, on affiche une erreur lisible
    if (!tableCount) {
      setStatus(
        'Aucune table exploitable après import. Vérifiez le format du CSV et le terminal Python.',
        true
      );

      $('#report').innerHTML = `
        <div class="card err" style="margin-top:20px">
          <h3>Import impossible</h3>
          <p>Aucune table n’a pu être analysée.</p>
          <p>Consultez le terminal dans lequel <code>server.py</code> est lancé pour voir l’erreur DuckDB exacte.</p>
        </div>
      `;

      $('#result').classList.remove('hide');
      return;
    }

    // Une erreur de table ne bloque plus tout le rendu
    setStatus(message, errorNames.length > 0, false);

    render();

  } catch (e) {
    console.error('Erreur import/audit :', e);
    setStatus(e.message || 'Erreur inconnue pendant l’import.', true);
  }
}

/* ---------- Documents PDF (RAG) ---------- */
const docBtn = $('#docBtn'), docFile = $('#docFile');
docBtn.onclick = () => docFile.click();
docFile.onchange = () => { uploadDocs([...docFile.files]); docFile.value = ''; };
$('#docList').addEventListener('click', e => {
  const b = e.target.closest('.x');
  if (b) removeDoc(b.dataset.name);
});

function showDocs(j, extra = []) {
  const docs = j.docs || [];
  $('#docList').innerHTML = docs.map(d =>
    `<span class="file doc">📄 ${esc(d.name)} <small>${d.pages} p. · ${d.chunks} passages</small>` +
    `<button type="button" class="x" data-name="${esc(d.name)}" aria-label="Retirer ${esc(d.name)}">✕</button></span>`).join('');
  const st = $('#docStatus');
  if (!docs.length && !extra.length) { st.className = 'status muted'; st.textContent = ''; return; }
  const mode = j.mode === 'hybrid' ? 'recherche hybride : sémantique (' + esc(j.embed_model) + ') + mots-clés BM25, scores normalisés'
    : j.mode === 'keywords' ? 'recherche par mots-clés seulement (modèle d’embeddings indisponible)' : '';
  st.className = 'status ' + (extra.length ? 'err' : 'muted');
  st.innerHTML = [docs.length ? docs.length + ' document(s) · ' + mode : '', ...extra.map(esc)].filter(Boolean).join('<br>');
  if (docs.length) document.querySelector('details.ctxbox').open = true;
}

async function loadDocs() {
  try { showDocs(await readJson(await fetch('/api/docs'))); } catch (e) { /* serveur sans RAG : on ignore */ }
}

async function uploadDocs(files) {
  if (!files.length) return;
  const fd = new FormData();
  files.forEach(f => fd.append('files', f, f.name));
  const st = $('#docStatus');
  st.className = 'status muted';
  st.innerHTML = '<span class="spin"></span>Lecture et indexation des PDF…';
  try {
    const j = await readJson(await fetch('/api/docs', {method: 'POST', body: fd}));
    showDocs(j, [...(j.errors || []), ...(j.warnings || [])]);
  } catch (e) { st.className = 'status err'; st.textContent = e.message; }
}

async function removeDoc(name) {
  try {
    const j = await readJson(await fetch('/api/docs/delete', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})}));
    showDocs(j);
  } catch (e) { $('#docStatus').textContent = e.message; }
}

loadDocs();

/* ---------- Fusion des résultats de audit.py ---------- */
function mergeAudit(audit) {
  const out = {};

  // Sécurité : évite Object.entries(null), Object.entries(undefined), etc.
  if (!audit || typeof audit !== 'object') {
    return out;
  }

  for (const [tableName, data] of Object.entries(audit)) {
    // Une table invalide ne doit jamais casser tout le rendu
    if (!data || typeof data !== 'object') {
      out[tableName] = {
        error: 'Résultat d’audit invalide ou absent.',
        rows: 0,
        columns: 0,
        duplicates: {
          total_rows: 0,
          distinct_rows: 0,
          duplicates: 0
        },
        schema: []
      };

      continue;
    }

    // Structure sécurisée, même si l'audit de la table a échoué
    const structure = data.structure && typeof data.structure === 'object'
      ? data.structure
      : {};

    const duplicates = data.duplicates && typeof data.duplicates === 'object'
      ? data.duplicates
      : {};

    // Transforme une liste [{column: "..."}] en objet indexé par colonne
    const byColumn = arr => {
      if (!Array.isArray(arr)) {
        return {};
      }

      return Object.fromEntries(
        arr
          .filter(item => item && typeof item === 'object' && item.column)
          .map(item => [item.column, item])
      );
    };

    const missingByColumn = byColumn(data.missing_values);
    const cardinalityByColumn = byColumn(data.cardinality);
    const numericByColumn = byColumn(data.numeric_statistics);
    const negativeByColumn = byColumn(data.negative_values);

    // schema est impérativement un tableau
    const rawSchema = Array.isArray(structure.schema)
      ? structure.schema
      : [];

    out[tableName] = {
      // L'erreur est conservée si audit.py l'a ajoutée
      error: data.error || null,

      // Valeurs numériques sécurisées
      rows: Number(structure.rows) || 0,
      columns: Number(structure.columns) || 0,

      duplicates: {
        total_rows: Number(duplicates.total_rows) || 0,
        distinct_rows: Number(duplicates.distinct_rows) || 0,
        duplicates: Number(duplicates.duplicates) || 0
      },

      // Le schéma existe TOUJOURS, même si vide
      schema: rawSchema.map(columnInfo => {
        const columnName = columnInfo.column_name || 'Colonne inconnue';

        const numericStats = numericByColumn[columnName] || {};
        const missingStats = missingByColumn[columnName] || {};
        const cardinalityStats = cardinalityByColumn[columnName] || {};
        const negativeStats = negativeByColumn[columnName] || {};

        return {
          column: columnName,
          type: columnInfo.column_type || 'UNKNOWN',

          missing: Number(missingStats.missing) || 0,
          missing_percent: Number(missingStats.missing_percent) || 0,

          distinct: cardinalityStats.distinct_values ?? null,

          min: numericStats.min ?? null,
          max: numericStats.max ?? null,
          mean: numericStats.mean ?? null,
          median: numericStats.median ?? null,
          stddev: numericStats.stddev ?? null,

          negatives: Number(negativeStats.negative_values) || 0,

          // La colonne est numérique uniquement si des stats existent réellement
          numeric: Object.prototype.hasOwnProperty.call(
            numericByColumn,
            columnName
          )
        };
      })
    };
  }

  return out;
}

const completeness = d => {
  if (!d || d.error) {
    return 0;
  }

  const rows = Number(d.rows) || 0;
  const columns = Number(d.columns) || 0;
  const schema = Array.isArray(d.schema) ? d.schema : [];

  const cells = rows * columns;

  if (!cells) {
    return 100;
  }

  const missingValues = schema.reduce(
    (sum, column) => sum + (Number(column.missing) || 0),
    0
  );

  return 100 * (1 - missingValues / cells);
};
const tone = p => p >= 98 ? 'ok' : p >= 85 ? 'warn' : 'bad';
const typeClass = t => { t = String(t).toUpperCase(); return /INT|DOUBLE|FLOAT|DECIMAL|REAL|HUGE/.test(t) ? 'num' : /DATE|TIME/.test(t) ? 'dt' : /BOOL/.test(t) ? 'bo' : 'tx'; };

function findings() {
  const out = [];

  for (const [tableName, tableData] of Object.entries(view)) {
    // Cas important : table détectée, mais audit impossible
    if (tableData.error) {
      out.push([
        'bad',
        tableName,
        '',
        tableData.error,
        'Erreur de lecture ou d’audit'
      ]);

      continue;
    }

    // Table réellement vide
    if (!tableData.rows) {
      out.push([
        'bad',
        tableName,
        '',
        'La table ne contient aucune ligne.',
        'Table vide'
      ]);

      continue;
    }

    // Protection si schema n'est pas un tableau
    const schema = Array.isArray(tableData.schema)
      ? tableData.schema
      : [];

    schema.forEach(column => {
      if (column.missing === tableData.rows) {
        out.push([
          'bad',
          tableName,
          column.column,
          'Colonne entièrement vide.',
          'Colonne vide'
        ]);
      } else if (column.missing_percent >= 50) {
        out.push([
          'warn',
          tableName,
          column.column,
          `${pct(column.missing_percent)} de valeurs manquantes (${fmt(column.missing)} lignes).`,
          'Valeurs manquantes'
        ]);
      }

      if (
        column.distinct === 1 &&
        tableData.rows > 1 &&
        column.missing === 0
      ) {
        out.push([
          'warn',
          tableName,
          column.column,
          'Une seule valeur distincte sur toute la colonne.',
          'Colonne constante'
        ]);
      }

      if (column.negatives) {
        out.push([
          'warn',
          tableName,
          column.column,
          `${fmt(column.negatives)} valeur(s) négative(s) : à interpréter selon la variable.`,
          'Valeurs négatives'
        ]);
      }
    });

    if (tableData.duplicates?.duplicates) {
      out.push([
        'warn',
        tableName,
        '',
        `${fmt(tableData.duplicates.duplicates)} ligne(s) en doublon exact (peut être légitime selon le modèle).`,
        'Doublons exacts'
      ]);
    }
  }

  return out;
}

/* ---------- Rendu ---------- */
const COLORS = ['#2d6a4f', '#2a9d8f', '#e9c46a', '#52b788', '#8ecae6', '#e76f51', '#b5e48c', '#40916c', '#94a3b8'];

function donut(names) {
  const total = names.reduce((s, n) => s + view[n].rows, 0) || 1;
  let items = names.map(n => [n, view[n].rows]).sort((a, b) => b[1] - a[1]);
  if (items.length > 8) { const rest = items.slice(8).reduce((s, x) => s + x[1], 0); items = items.slice(0, 8).concat([['Autres', rest]]); }
  const R = 70, C = 2 * Math.PI * R; let off = 0;
  const arcs = items.map(([n, v], i) => {
    const len = v / total * C, a = `<circle cx="85" cy="85" r="${R}" stroke="${COLORS[i % COLORS.length]}" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}"/>`;
    off += len; return a;
  }).join('');
  return `<div class="donutwrap"><svg class="donut" viewBox="0 0 170 170"><circle cx="85" cy="85" r="${R}" stroke="var(--soft)"/>${arcs}</svg>
    <div class="legend">${items.map(([n, v], i) => `<div><i style="background:${COLORS[i % COLORS.length]}"></i>${esc(n)}<b>${pct(v / total * 100)}</b></div>`).join('')}</div></div>`;
}

function render() {
  const names = Object.keys(view);
  const sum = f => names.reduce((s, n) => s + f(view[n]), 0);
  const kp = [
    ['Tables', names.length, 'db', '#2d6a4f,#52b788'], ['Lignes', sum(d => d.rows), 'rows', '#2a9d8f,#8ecae6'],
    ['Colonnes', sum(d => d.columns), 'cols', '#52b788,#b5e48c'], ['Valeurs manquantes', sum(d => d.schema.reduce((s, c) => s + c.missing, 0)), 'miss', '#e9c46a,#e76f51'],
    ['Doublons', sum(d => d.duplicates.duplicates), 'copy', '#e76f51,#9c6644'], ['Valeurs négatives', sum(d => d.schema.reduce((s, c) => s + c.negatives, 0)), 'minus', '#6b705c,#3a5a40']
  ];
  const fl = findings(), nb = fl.filter(f => f[0] === 'bad').length, nw = fl.length - nb;
  const sh = (id, t, sub) => `<div class="sh"><span class="bar"></span><h2>${t}</h2></div><p class="sec-sub">${sub}</p>`;

  let h = `<section id="s-over" class="reveal">${sh('', 'Vue d\'ensemble', 'Indicateurs calculés directement par Python / DuckDB.')}
    <div class="kpis">${kp.map(([l, v, i, g]) => `<div class="kpi" style="--g:linear-gradient(135deg,${g})"><div class="ic">${ic(i)}</div><div class="l">${l}</div><div class="v" data-v="${v}">0</div></div>`).join('')}</div>
    <div class="grid2" style="margin-top:16px">
      <div class="card"><h3 class="ct">Répartition des lignes</h3>${donut(names)}</div>
      <div class="card"><h3 class="ct">Complétude par table</h3>${names.map(n => { const p = completeness(view[n]); return `<div class="hbar"><div class="t" title="${esc(n)}">${esc(n)}</div><div class="track"><div class="fill ${tone(p)}" data-w="${p}"></div></div><div class="p">${pct(p)}</div></div>`; }).join('')}</div>
    </div>
    <div class="card" style="margin-top:16px"><h3 class="ct">Comparatif des tables <span class="muted" style="font-weight:400;font-size:13px">· cliquez sur un en-tête pour trier</span></h3>
      <div class="scroll"><table class="dt sortable"><thead><tr>${TH([['Table',0],['Lignes',1],['Colonnes',1],['Complétude',1],['Manquants',1],['Doublons',1],['Négatifs',1]])}</tr></thead><tbody>${names.map((n, k) => {
        const d = view[n], p = completeness(d), mi = d.schema.reduce((s, c) => s + c.missing, 0), ng = d.schema.reduce((s, c) => s + c.negatives, 0);
        return `<tr><td class="c" data-s="${esc(n.toLowerCase())}"><a href="#t-${k}" class="tl" data-go="t-${k}">${esc(n)}</a></td><td class="n" data-s="${d.rows}">${fmt(d.rows)}</td><td class="n" data-s="${d.columns}">${fmt(d.columns)}</td><td class="n" data-s="${p}"><span class="tag ${tone(p)}">${pct(p)}</span></td><td class="n" data-s="${mi}">${fmt(mi)}</td><td class="n" data-s="${d.duplicates.duplicates}">${fmt(d.duplicates.duplicates)}</td><td class="n" data-s="${ng}">${fmt(ng)}</td></tr>`; }).join('')}</tbody></table></div></div>
  </section>`;

  const frows = fl.slice().sort((a, b) => (a[0] === 'bad' ? 0 : 1) - (b[0] === 'bad' ? 0 : 1)).map(([lv, t, c, m, k]) =>
    `<tr><td data-s="${lv === 'bad' ? 0 : 1}"><span class="lv ${lv}">${lv === 'bad' ? 'Anomalie' : 'À vérifier'}</span></td>
      <td class="c" data-s="${esc(t.toLowerCase())}">${esc(t)}</td>
      <td data-s="${esc(c.toLowerCase())}">${c ? '<code>' + esc(c) + '</code>' : '<span class="muted">—</span>'}</td>
      <td data-s="${esc(k.toLowerCase())}">${esc(k)}</td><td class="wrap" data-s="${esc(m.toLowerCase())}">${esc(m)}</td></tr>`).join('');
  h += `<section id="s-find" class="reveal">${sh('', 'Constats automatiques', 'Règles simples appliquées aux résultats : ce sont des points à vérifier, pas des verdicts. Cliquez sur un en-tête pour trier.')}
    <div class="card"><div class="pills">${fl.length ? `<span class="pill bad">${nb} anomalie(s)</span><span class="pill warn">${nw} à vérifier</span>` : `<span class="pill ok">${ic('check')} Aucun point détecté</span>`}</div>
    ${fl.length ? `<div class="scroll"><table class="dt sortable"><thead><tr>${TH([['Niveau', 1], ['Table', 0], ['Colonne', 0], ['Constat', 0], ['Détail', 0]])}</tr></thead><tbody>${frows}</tbody></table></div>` : ''}</div></section>`;

  h += `<section id="s-tables" class="reveal">${sh('', 'Détail par table', 'Cliquez sur une table pour déplier ses colonnes.')}`;
names.forEach((n, k) => {
  const d = view[n] || {
    rows: 0,
    columns: 0,
    duplicates: {
      total_rows: 0,
      distinct_rows: 0,
      duplicates: 0
    },
    schema: [],
    error: 'Table absente du résultat.'
  };

  const p = completeness(d);
  const schema = Array.isArray(d.schema) ? d.schema : [];

  h += `
    <details class="tcard" id="t-${k}"${names.length <= 3 || k === 0 ? ' open' : ''}>
      <summary>
        <span class="tname">${esc(n)}</span>
        <span class="tag">${fmt(d.rows)} lignes</span>
        <span class="tag">${fmt(d.columns)} colonnes</span>
        <span class="tag ${tone(p)}">Complétude ${pct(p)}</span>
        ${d.error
          ? '<span class="tag bad">Erreur d’audit</span>'
          : d.duplicates?.duplicates
            ? `<span class="tag warn">${fmt(d.duplicates.duplicates)} doublons</span>`
            : ''
        }
      </summary>

      <div class="tbody">
  `;

  // Cas : l'audit de cette table a échoué
  if (d.error) {
    h += `
      <div class="err" style="margin:12px 0;padding:12px">
        <strong>Impossible d’auditer cette table.</strong>
        <br>
        ${esc(d.error)}
        <br><br>
        <span class="muted">
          Consultez également le terminal où <code>server.py</code> est lancé.
        </span>
      </div>
    `;

    h += `
      </div>
    </details>
    `;

    return;
  }

  h += `
    <div class="tools">
      <input type="text" class="tsearch" placeholder="Filtrer les colonnes…">
      <span class="muted">
        Lignes distinctes : ${fmt(d.duplicates?.distinct_rows)}
      </span>
      <span class="muted hint">
        Cliquez sur une colonne pour son graphique · sur un en-tête pour trier
      </span>
    </div>

    <div class="scroll">
      <table class="dt sortable">
        <thead>
          <tr>
            ${TH([
              ['Colonne', 0],
              ['Type', 0],
              ['Manquant', 1],
              ['Distincts', 1],
              ['Min', 1],
              ['Max', 1],
              ['Moyenne', 1],
              ['Médiane', 1],
              ['Écart-type', 1],
              ['Négatifs', 1]
            ])}
          </tr>
        </thead>
        <tbody>
  `;

  // Cas rare : la table est lue mais aucune colonne n'est détectée
  if (!schema.length) {
    h += `
      <tr>
        <td colspan="10" class="muted">
          Aucune colonne détectée dans cette table.
        </td>
      </tr>
    `;
  }

  schema.forEach(c => {
    const mt = c.missing_percent >= 50
      ? 'bad'
      : c.missing_percent >= 5
        ? 'warn'
        : 'ok';

    h += `
      <tr
        class="drow"
        data-c="${esc(c.column.toLowerCase())}"
        data-t="${esc(n)}"
        data-col="${esc(c.column)}"
        title="Cliquer pour afficher la distribution"
      >
        <td class="c" data-s="${esc(c.column.toLowerCase())}">
          <span class="ci">${ic('chart')}</span>${esc(c.column)}
        </td>

        <td data-s="${esc(c.type)}">
          <span class="ty ${typeClass(c.type)}">${esc(c.type)}</span>
        </td>

        <td data-s="${c.missing_percent}">
          <div class="mcell">
            <div class="track">
              <div class="fill ${mt}" data-w="${c.missing_percent}"></div>
            </div>
            <small>${fmt(c.missing)} · ${pct(c.missing_percent)}</small>
          </div>
        </td>

        <td class="n" data-s="${c.distinct ?? ''}">${fmt(c.distinct)}</td>
        <td class="n" data-s="${c.min ?? ''}">${fmt(c.min)}</td>
        <td class="n" data-s="${c.max ?? ''}">${fmt(c.max)}</td>
        <td class="n" data-s="${c.mean ?? ''}">${fmt(c.mean)}</td>
        <td class="n" data-s="${c.median ?? ''}">${fmt(c.median)}</td>
        <td class="n" data-s="${c.stddev ?? ''}">${fmt(c.stddev)}</td>
        <td class="n" data-s="${c.numeric ? c.negatives : ''}">
          ${c.numeric ? fmt(c.negatives) : '—'}
        </td>
      </tr>
    `;
  });

  h += `
        </tbody>
      </table>
    </div>
  </div>
</details>
  `;
});
  h += '</section>';

h += `<section id="s-ai" class="reveal">${sh('', 'Analyse IA', 'Interprétation des résultats par votre modèle Ollama, sans accès aux données brutes.')}
    <div class="card"><div class="aihead"><div class="badge">${ic('spark')}</div><div><strong>Analyse technique</strong><div class="muted" style="font-size:13px">Modèle Ollama</div></div><span class="sp"></span>
      <input type="text" id="model" value="${esc(ollamaModel)}" aria-label="Modèle Ollama"><button class="btn" id="aiBtn">${ic('spark')}Lancer l'analyse</button><button class="ghost sm hide" id="cpBtn">${ic('copy')}Copier</button></div>
      <p class="ainote muted" id="aiNote"></p><div class="ai" id="ai"></div>
      
      <div style="margin-top:24px;padding-top:24px;border-top:1px solid var(--soft)">
        <button class="btn" id="evalBtn" style="background:linear-gradient(135deg,#8b5cf6,#a78bfa)">${ic('check')}Évaluer la qualité de cette analyse</button>
        <p class="muted" style="margin:8px 0 0;font-size:13px">Vérifie l'exactitude, la complétude et détecte les hallucinations (LLM-as-a-Judge).</p>
        <div id="evaluation-results"></div>
      </div>
    </div></section>`;

h += `<section id="s-ask" class="reveal">${sh('', 'Poser une question', 'Posez une question en français : le modèle écrit des requêtes SQL en lecture seule sur vos tables importées, puis répond à partir des résultats.')}
    <div class="card"><div class="askbox"><textarea id="q" rows="2" placeholder="Ex : quelle est la valeur maximale de … entre 2020 et 2021 pour … ?"></textarea><div class="askbtns"><button class="btn" id="askBtn">${ic('spark')}Envoyer</button><button class="ghost" id="clrBtn" title="Effacer la question et les réponses">${ic('trash')}Effacer</button></div></div>
      <div class="sugg" id="sugg"></div><div id="thread"></div></div></section>`;

h += `<section id="s-eval" class="reveal">${sh('', 'Évaluation', 'Mesurez objectivement la recherche dans vos PDF (RAG) et la fiabilité du Text-to-SQL.')}
    <div class="card">
      <h3 class="ct">${ic('chart')} Recherche dans les PDF : Precision@k, Recall@k, NDCG@k</h3>
      <p class="muted" style="margin:0 0 12px;font-size:13.5px">Des questions sont générées à partir de passages de vos PDF ; on vérifie si chaque mode de recherche (hybride, sémantique, BM25) retrouve le bon passage. Nécessite au moins un PDF indexé.</p>
      <div class="evalctl"><label>k <input type="number" id="ragK" value="4" min="1" max="20"></label>
        <label>Questions <input type="number" id="ragN" value="8" min="1" max="30"></label>
        <label class="chk"><input type="checkbox" id="ragLlm" checked> Questions reformulées par le modèle</label>
        <button class="btn" id="ragEvalBtn">${ic('check')}Évaluer la recherche</button></div>
      <div id="rag-eval-results"></div>
    </div>
    <div class="card" style="margin-top:18px">
      <h3 class="ct">${ic('spark')} Text-to-SQL : pass@k et cons@k</h3>
      <p class="muted" style="margin:0 0 12px;font-size:13.5px">Le chatbot SQL répond n fois à des questions dont la réponse est connue grâce à l'audit (lignes, valeurs NULL, valeurs distinctes). pass@k : au moins une réponse juste sur k ; cons@k : toutes les k réponses justes. Chaque tentative appelle Ollama : comptez plusieurs minutes.</p>
      <div class="evalctl"><label>k <input type="number" id="sqlK" value="3" min="1" max="5"></label>
        <label>Tentatives (n ≥ k) <input type="number" id="sqlNA" value="3" min="1" max="8"></label>
        <label>Questions <input type="number" id="sqlN" value="3" min="1" max="6"></label>
        <button class="btn" id="sqlEvalBtn">${ic('check')}Évaluer le Text-to-SQL</button></div>
      <div id="sql-eval-results"></div>
    </div></section>`;

  $('#report').innerHTML = h;
  $('#result').classList.remove('hide');
  bind();
  requestAnimationFrame(() => {
    document.querySelectorAll('.fill').forEach(f => f.style.width = Math.min(100, +f.dataset.w) + '%');
    document.querySelectorAll('.kpi .v').forEach(el => countUp(el, +el.dataset.v));
  });
  scrollSpy();
  $('#s-over').scrollIntoView({behavior: 'smooth'});
}

function countUp(el, v) {
  const t0 = performance.now(), D = 800;
  const step = t => { const k = Math.min(1, (t - t0) / D), e = 1 - Math.pow(1 - k, 3); el.textContent = fmt(Math.round(v * e)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}

function bind() {
  bindAsk();
  $('#aiBtn').onclick = runAI;
  $('#cpBtn').onclick = async () => { try { await navigator.clipboard.writeText(aiText); $('#aiNote').textContent = 'Analyse copiée.'; } catch (e) {} };

  // AJOUT : liaison du bouton d'évaluation
  const evalBtn = $('#evalBtn');
  if (evalBtn) evalBtn.onclick = evaluateAnalysis;
  $('#ragEvalBtn').onclick = evalRag;
  $('#sqlEvalBtn').onclick = evalSql;
  
  document.querySelectorAll('.tsearch').forEach(inp => inp.oninput = () => {
    const q = inp.value.trim().toLowerCase();
    inp.closest('.tbody').querySelectorAll('tbody tr.drow').forEach(tr => {
      const hid = !!q && !tr.dataset.c.includes(q);
      tr.classList.toggle('hide', hid);
      const nx = tr.nextElementSibling;
      if (nx && nx.classList.contains('crow')) nx.classList.toggle('hide', hid);
    });
  });
}

let spy;
function scrollSpy() {
  if (spy) spy.disconnect();
  if (!('IntersectionObserver' in window)) return;
  const links = [...document.querySelectorAll('#nav a')];
  spy = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) links.forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + e.target.id));
  }), {rootMargin: '-30% 0px -60% 0px'});
  document.querySelectorAll('#report section').forEach(s => spy.observe(s));
}

/* ---------- Markdown (avec tableaux) ---------- */
function inline(s) {
  return esc(s)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*(?!\s)([^*]+?)\*(?![*\w])/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}
const cells = l => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
const isSep = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l) && l.includes('|');
const isNum = s => /^[-+~≈]?\s*[\d\s\u00a0\u202f.,]+\s*(%|k|M|Mo|Go)?$/.test(s) && /\d/.test(s);

function md(text) {
  const L = String(text).replace(/\r/g, '').split('\n');
  let h = '', list = null, i = 0;
  const close = () => { if (list) { h += `</${list}>`; list = null; } };
  while (i < L.length) {
    const t = L[i].trim();
    if (t.startsWith('|') && i + 1 < L.length && isSep(L[i + 1])) {
      close();
      const head = cells(t), al = cells(L[i + 1]).map(c => c.startsWith(':') && c.endsWith(':') ? 'ctr' : c.endsWith(':') ? 'r' : '');
      i += 2; const rows = [];
      while (i < L.length && L[i].trim().startsWith('|')) { rows.push(cells(L[i])); i++; }
      const cls = (r, k) => al[k] || (rows.length && rows.every(x => !x[k] || isNum(x[k])) ? 'r' : '');
      h += '<div class="tw"><table><thead><tr>' + head.map((c, k) => `<th class="${cls(rows, k)}">${inline(c)}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + head.map((_, k) => `<td class="${cls(rows, k)}">${inline(r[k] ?? '')}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
      continue;
    }
    let m;
    if (!t) { close(); }
    else if ((m = t.match(/^(#{1,4})\s+(.*)/))) { close(); const n = m[1].length + 1; h += `<h${n}>${inline(m[2])}</h${n}>`; }
    else if (/^(-{3,}|\*{3,})$/.test(t)) { close(); h += '<hr>'; }
    else if ((m = t.match(/^>\s?(.*)/))) { close(); h += `<blockquote>${inline(m[1])}</blockquote>`; }
    else if ((m = t.match(/^[-*•]\s+(.*)/))) { if (list !== 'ul') { close(); h += '<ul>'; list = 'ul'; } h += `<li>${inline(m[1])}</li>`; }
    else if ((m = t.match(/^\d+[.)]\s+(.*)/))) { if (list !== 'ol') { close(); h += '<ol>'; list = 'ol'; } h += `<li>${inline(m[1])}</li>`; }
    else if (/^\*[^*\s].*[^*\s]\*$/.test(t) && !t.startsWith('**')) { close(); h += `<p><em>${inline(t.slice(1, -1))}</em></p>`; }
    else { close(); h += `<p>${inline(t)}</p>`; }
    i++;
  }
  close();
  return h;
}

/* ---------- Analyse IA (Ollama via Python) ---------- */
async function runAI() {
  const btn = $('#aiBtn'), note = $('#aiNote'), box = $('#ai');
  btn.disabled = true; box.innerHTML = ''; $('#cpBtn').classList.add('hide');
  note.className = 'ainote muted';
  if (window.UX) UX.aiStart(note);   // étapes de progression (ux.js)
  else note.innerHTML = '<span class="spin"></span>Ollama analyse vos résultats… cela peut prendre plusieurs minutes.';
  box.innerHTML = '<div class="skel"><div style="width:40%"></div><div></div><div style="width:92%"></div><div style="width:80%"></div><div></div><div style="width:65%"></div></div>';
  try {
    const r = await fetch('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({audit: raw, context: $('#ctx').value.trim(), model: $('#model').value.trim()})
    });
    const j = await readJson(r);
    if (!r.ok) throw new Error(j.error || 'Erreur serveur');
    aiText = j.analysis; box.innerHTML = md(aiText);
    note.textContent = 'Analyse terminée.' + (j.sources && j.sources.length ? ' Sources PDF utilisées (' + (j.search_mode === 'hybrid' ? 'recherche hybride' : 'mots-clés') + ') : ' + j.sources.join(' · ') : '');
    $('#cpBtn').classList.remove('hide');
  } catch (e) { box.innerHTML = ''; note.className = 'ainote err'; note.textContent = e.message; }
  finally { if (window.UX) UX.aiStop(); }
  btn.disabled = false;
}

/* ---------- Tableaux triables ---------- */
const TH = cols => cols.map(([t, num], k) => `<th data-k="${k}"${num ? ' data-num="1" class="n"' : ''}>${t}<span class="ar"></span></th>`).join('');

function sortTable(th) {
  const table = th.closest('table'), tb = table.tBodies[0], k = +th.dataset.k, num = !!th.dataset.num;
  const asc = !th.classList.contains('asc');
  table.querySelectorAll('th').forEach(x => x.classList.remove('asc', 'desc'));
  th.classList.add(asc ? 'asc' : 'desc');
  const pairs = [...tb.querySelectorAll('tr:not(.crow)')].map(tr => [tr, tr.nextElementSibling && tr.nextElementSibling.classList.contains('crow') ? tr.nextElementSibling : null]);
  const val = tr => { const v = tr.children[k].dataset.s; return v === undefined || v === '' ? null : num ? +v : v; };
  pairs.sort(([a], [b]) => {
    const x = val(a), y = val(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    const r = num ? x - y : String(x).localeCompare(String(y), 'fr', {numeric: true});
    return asc ? r : -r;
  });
  pairs.forEach(([tr, cr]) => { tb.appendChild(tr); if (cr) tb.appendChild(cr); });
}

/* ---------- Graphique par colonne ---------- */
const cache = {};

function chartHtml(j) {
  const head = t => `<div class="chead"><strong>${t}</strong><span class="muted">${fmt(j.non_null)} valeurs renseignées</span></div>`;
  if (j.kind === 'empty') return head('Colonne sans valeur') + '<p class="muted" style="margin:6px 0 0">Aucun graphique possible.</p>';
  if (j.kind === 'histogram') {
    if (j.bins.length === 1) return head('Valeur unique') + `<p style="margin:6px 0 0">Toutes les valeurs sont égales à <strong>${fmt(j.bins[0].from)}</strong>.</p>`;
    const mx = Math.max(...j.bins.map(b => b.count)) || 1;
    return head(`Distribution (${j.bins.length} classes)`) +
      `<div class="vbars">${j.bins.map(b => `<div title="${esc(fmt(b.from))} → ${esc(fmt(b.to))} : ${esc(fmt(b.count))}" style="height:${Math.max(b.count / mx * 100, b.count ? 2 : 0)}%"></div>`).join('')}</div>
       <div class="axis"><span>${fmt(j.bins[0].from)}</span><span>${fmt(j.bins[j.bins.length - 1].to)}</span></div>`;
  }
  if (j.kind === 'timeline') {
    const mx = Math.max(...j.points.map(p => p.count)) || 1, P = j.points;
    return head('Répartition par ' + (j.unit === 'year' ? 'année' : 'mois')) +
      `<div class="vbars">${P.map(p => `<div title="${esc(p.label)} : ${esc(fmt(p.count))}" style="height:${Math.max(p.count / mx * 100, 2)}%"></div>`).join('')}</div>
       <div class="axis"><span>${esc(P[0].label)}</span>${P.length > 2 ? `<span>${esc(P[Math.floor(P.length / 2)].label)}</span>` : ''}<span>${esc(P[P.length - 1].label)}</span></div>`;
  }
  const mx = Math.max(...j.values.map(v => v.count)) || 1;
  return head(`Valeurs les plus fréquentes (${j.values.length})`) +
    j.values.map(v => `<div class="topv"><div class="t" title="${esc(v.value)}">${esc(v.value) || '<em>(vide)</em>'}</div><div class="track"><div class="fill" style="width:${v.count / mx * 100}%"></div></div><div class="p">${fmt(v.count)} · ${pct(v.count / j.non_null * 100)}</div></div>`).join('') +
    (j.others > 0 ? `<p class="muted" style="margin:8px 0 0">+ ${fmt(j.others)} autres valeurs (hors top ${j.values.length})</p>` : '');
}

async function toggleChart(tr) {
  const nx = tr.nextElementSibling;
  if (nx && nx.classList.contains('crow')) { nx.remove(); tr.classList.remove('open'); return; }
  const cr = document.createElement('tr'), td = document.createElement('td');
  cr.className = 'crow'; td.colSpan = tr.children.length; cr.appendChild(td);
  td.innerHTML = '<div class="cpanel"><span class="spin"></span>Calcul de la distribution…</div>';
  tr.after(cr); tr.classList.add('open');
  const key = tr.dataset.t + '\u0000' + tr.dataset.col;
  try {
    if (!cache[key]) {
      const r = await fetch('/api/column?table=' + encodeURIComponent(tr.dataset.t) + '&column=' + encodeURIComponent(tr.dataset.col));
      const j = await readJson(r);
      if (!r.ok) throw new Error(j.error || 'Erreur serveur');
      cache[key] = j;
    }
    td.innerHTML = '<div class="cpanel">' + chartHtml(cache[key]) + '</div>';
  } catch (e) { td.innerHTML = '<div class="cpanel err">' + esc(e.message) + '</div>'; }
}

document.addEventListener('click', ev => {
  const th = ev.target.closest('table.sortable th');
  if (th) return sortTable(th);
  const xb = ev.target.closest('.xbtn');
  if (xb) return exportStep(xb);
  const xd = ev.target.closest('.xdel');
  if (xd) return removeExchange(+xd.closest('.qa').dataset.id);
  const go = ev.target.closest('a.tl');
  if (go) { ev.preventDefault(); const d = document.getElementById(go.dataset.go); if (d) { d.open = true; d.scrollIntoView({behavior: 'smooth', block: 'start'}); } return; }
  const tr = ev.target.closest('tr.drow');
  if (tr) toggleChart(tr);
});

/* ---------- Questions sur les données ---------- */
const hist = [];                 // {id, q, a} : contexte envoyé au modèle
const exchanges = new Map();     // id -> {id, q, steps, ctl, dead}
let exSeq = 0, pending = null;

function bindAsk() {
  const names = Object.keys(view);

  // Sécurité absolue :
  // si aucune table n'est disponible, on ne tente jamais view[t0].schema.
  if (!names.length) {
    $('#sugg').innerHTML = `
      <p class="muted">
        Aucune table valide n’est disponible pour les questions SQL.
      </p>
    `;

    $('#askBtn').disabled = true;
    $('#q').disabled = true;
    $('#q').placeholder = 'Importez au moins une table valide avant de poser une question.';
    $('#clrBtn').disabled = true;

    return;
  }

  // On privilégie une table sans erreur pour les suggestions
  const validTableName = names.find(name => !view[name].error) || names[0];

  // Protection : même si quelque chose est inattendu, schema sera toujours un tableau
  const currentTable = view[validTableName] || {};
  const schema = Array.isArray(currentTable.schema)
    ? currentTable.schema
    : [];

  // Cherche une première colonne texte pour proposer une question utile
  const textColumn = schema.find(column => typeClass(column.type) === 'tx');

  const suggestions = [
    `Combien de lignes contient la table ${validTableName} ?`
  ];

  if (textColumn) {
    suggestions.push(
      `Quelles sont les 5 valeurs les plus fréquentes de la colonne ${textColumn.column} dans ${validTableName} ?`
    );
  }

  if (names.length > 1) {
    suggestions.push(
      'Quelles colonnes communes permettent de relier mes tables ?'
    );
  }

  // Réactive les champs dans le cas où un import précédent avait échoué
  $('#askBtn').disabled = false;
  $('#q').disabled = false;
  $('#clrBtn').disabled = false;
  $('#q').placeholder = 'Ex : quelle est la valeur maximale de … entre 2020 et 2021 pour … ?';

  $('#sugg').innerHTML = suggestions
    .map(text => `<button class="chip2" type="button">${esc(text)}</button>`)
    .join('');

  $('#sugg').onclick = event => {
    const button = event.target.closest('.chip2');

    if (!button) {
      return;
    }

    $('#q').value = button.textContent;
    $('#q').focus();
  };

  $('#askBtn').onclick = runAsk;
  $('#clrBtn').onclick = clearAsk;

  $('#q').onkeydown = event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      runAsk();
    }
  };

  // Nouvelle session de questions après chaque nouvel import
  hist.length = 0;
  exchanges.clear();
  pending = null;
}

function removeExchange(id) {
  const ex = exchanges.get(id);
  if (ex) { ex.dead = true; ex.ctl.abort(); }
  exchanges.delete(id);
  const i = hist.findIndex(h => h.id === id);
  if (i >= 0) hist.splice(i, 1);
  if (pending && pending.id === id) { pending = null; $('#askBtn').disabled = false; }
  const box = document.querySelector(`.qa[data-id="${id}"]`);
  if (box) box.remove();
}

function clearAsk() {
  [...exchanges.keys()].forEach(removeExchange);
  $('#thread').innerHTML = ''; $('#q').value = ''; $('#q').focus();
}

function miniTable(s) {
  if (!s.rows || !s.rows.length) return '<p class="muted" style="margin:6px 0 0">Aucune ligne.</p>';
  const cell = v => v === null ? '—' : typeof v === 'number' ? fmt(v) : esc(String(v).slice(0, 80));
  return `<div class="scroll" style="max-height:240px"><table class="dt"><thead><tr>${s.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${s.rows.slice(0, 15).map(r => `<tr>${r.map(v => `<td>${cell(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` +
    (s.row_count > 15 ? `<p class="muted" style="margin:6px 0 0;font-size:12.5px">${fmt(s.row_count)}${s.truncated ? '+' : ''} lignes, 15 affichées.</p>` : '');
}

const XF = {csv: 'CSV', xlsx: 'Excel', parquet: 'Parquet'};
const xbtns = (id, st) => Object.keys(XF).map(f => `<button class="ghost sm xbtn" data-ex="${id}" data-st="${st}" data-fmt="${f}">${XF[f]}</button>`).join('');

/* barre d'export du résultat complet de la dernière requête réussie */
function exportBar(ex) {
  const idx = ex.steps.map((s, i) => i).filter(i => !ex.steps[i].error && ex.steps[i].row_count > 0).pop();
  if (idx === undefined) return '';
  const s = ex.steps[idx];
  const size = s.truncated ? 'plus de ' + fmt(s.row_count) + ' lignes' : fmt(s.row_count) + ' ligne(s)';
  return `<div class="xbar"><span class="xl">${ic('down')}Exporter le résultat complet de la requête ${idx + 1} <small>(${s.columns.length} colonnes, ${size})</small></span>${xbtns(ex.id, idx)}<span class="xmsg"></span></div>`;
}

function stepsHtml(steps, id) {
  if (!steps.length) return '';
  return `<details class="qsteps"><summary>Voir les ${steps.length} requête(s) exécutée(s)</summary>${steps.map((s, i) =>
    `<div class="qstep"><div class="qh">Requête ${i + 1} ${s.error ? '<span class="tag bad">erreur</span>' : `<span class="tag ok">${fmt(s.row_count)}${s.truncated ? '+' : ''} ligne(s)</span>`}</div><pre class="sql">${esc(s.sql)}</pre>${s.error ? `<div class="err" style="font-size:13.5px">${esc(s.error)}</div>` : miniTable(s) + (s.row_count > 0 ? `<div class="xbar mini"><span class="xl">${ic('down')}Exporter</span>${xbtns(id, i)}<span class="xmsg"></span></div>` : '')}</div>`).join('')}</details>`;
}

async function runAsk() {
  const q = $('#q').value.trim();
  const th = $('#thread');

  // Évite un appel à l'API si aucune table valide n'est disponible
  const validTables = Object.values(view).filter(table => !table.error);

  if (!validTables.length) {
    alert('Aucune table valide n’est disponible. Corrigez le fichier CSV puis relancez l’import.');
    return;
  }

  if (!q || pending) {
    return;
  }
  const id = ++exSeq, ex = {id, q, steps: [], ctl: new AbortController(), dead: false};
  exchanges.set(id, ex); pending = ex; $('#askBtn').disabled = true; $('#q').value = '';
  const box = document.createElement('div'); box.className = 'qa'; box.dataset.id = id;
  box.innerHTML = `<button class="xdel" title="Supprimer cet échange" aria-label="Supprimer cet échange">${ic('x')}</button>
    <div class="msg me"><div class="bub">${inline(q)}</div></div>
    <div class="msg bot"><div class="bub"><span class="spin"></span>Le modèle explore vos données… cela peut prendre quelques minutes.</div></div>`;
  th.appendChild(box); box.scrollIntoView({behavior: 'smooth', block: 'center'});
  const bot = box.querySelector('.msg.bot');
  try {
    const r = await fetch('/api/ask', {method: 'POST', signal: ex.ctl.signal, headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, model: $('#model').value.trim(), context: $('#ctx').value.trim(), history: hist.slice(-3).map(h => ({q: h.q, a: h.a}))})});
    const j = await readJson(r);
    if (ex.dead) return;
    if (!r.ok) throw new Error(j.error || 'Erreur serveur');
    ex.steps = j.steps; hist.push({id, q, a: j.answer});
    bot.innerHTML = `<div class="bub"><div class="ai">${md(j.answer)}</div>${exportBar(ex)}${stepsHtml(j.steps, id)}</div>`;
  } catch (e) {
    if (ex.dead || e.name === 'AbortError') return;
    bot.innerHTML = `<div class="bub err">${esc(e.message)}</div>`;
  } finally {
    if (pending === ex) { pending = null; $('#askBtn').disabled = false; }
  }
}

/* export du résultat complet d'une requête (CSV, Excel, Parquet) */
async function exportStep(btn) {
  const ex = exchanges.get(+btn.dataset.ex);
  if (!ex) return;
  const step = ex.steps[+btn.dataset.st], f = btn.dataset.fmt, bar = btn.closest('.xbar'), msg = bar.querySelector('.xmsg');
  const all = bar.querySelectorAll('.xbtn'); all.forEach(b => b.disabled = true);
  msg.className = 'xmsg muted'; msg.innerHTML = '<span class="spin"></span>Préparation du fichier…';
  try {
    const r = await fetch('/api/export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({sql: step.sql, format: f, name: ex.q})});
    if (!r.ok) { const j = await readJson(r); throw new Error(j.error || 'Erreur serveur'); }
    const blob = await r.blob(), m = (r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = m ? m[1] : 'resultat.' + f; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    msg.className = 'xmsg muted';
    msg.textContent = fmt(+r.headers.get('X-Row-Count')) + ' ligne(s) exportée(s)' + (r.headers.get('X-Truncated') === '1' ? ' (limité à 1 000 000)' : '') + '.';
  } catch (e) { msg.className = 'xmsg err'; msg.textContent = e.message; }
  all.forEach(b => b.disabled = false);
}

/* ---------- Export ---------- */
function download(filename, data, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([data], {type}));
  a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$('#dlJson').onclick = () => download('audit.json', JSON.stringify(raw, null, 2), 'application/json');
$('#dlHtml').onclick = async () => {
  const css = await (await fetch('/style.css')).text();
  const body = $('#report').cloneNode(true);
  body.querySelectorAll('.kpi .v').forEach(e => e.textContent = fmt(+e.dataset.v));
  body.querySelectorAll('.fill').forEach(e => e.style.width = Math.min(100, +e.dataset.w) + '%');
  body.querySelectorAll('details').forEach(e => e.open = true);
  body.querySelectorAll('.fxrev').forEach(e => e.classList.remove('fxrev', 'fx-in'));   // export : pas d'animation d'entrée
  body.querySelectorAll('.collapsed').forEach(e => e.classList.remove('collapsed'));   // export : toutes les sections dépliées
  body.querySelectorAll('.sh[role=button]').forEach(e => { e.removeAttribute('role'); e.removeAttribute('tabindex'); e.removeAttribute('aria-expanded'); });
  body.querySelectorAll('.evalctl,.askbox,.xbar,.xdel,#sugg,.tools input,#aiBtn,#cpBtn,#moreF,#model,.skel,.aihead input,.aihead .btn').forEach(e => e.remove());
  const theme = document.documentElement.dataset.theme;
  download('rapport_audit.html', `<!DOCTYPE html><html lang="fr" data-theme="${theme}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Rapport d'audit</title><style>${css}</style></head><body><header class="hero"><div class="in"><div class="brand"><div class="logo">${ic('logo')}</div>Audit de données</div><h1>Rapport d'<span>audit</span></h1><p>Généré le ${new Date().toLocaleString('fr-FR')}</p></div></header><main class="wrap" style="margin-top:-60px">${body.innerHTML}</main></body></html>`, 'text/html');
};

/* ---------- Évaluation de la qualité (LLM-as-a-Judge) ---------- */


// ✅ 1. DÉFINIR displayEvaluation() EN PREMIER
function displayEvaluation(ev) {
  const div = $('#evaluation-results');
  
  // Récupération des scores avec fallback
  const fa = ev.factual_accuracy || {};
  const co = ev.completeness || {};
  const ac = ev.actionability || {};
  const overall = ev.overall_score || 0;
  const hallus = ev.hallucinations || [];
  
  // Couleur du score global
  const scoreColor = overall >= 8 ? '#10b981' : overall >= 5 ? '#f59e0b' : '#dc2626';
  
  let html = `
    <div class="card" style="margin-top:24px;border:2px solid ${scoreColor}">
      <h3 class="ct">${ic('check')} Évaluation de la qualité (LLM-as-a-Judge)</h3>
      
      <div class="kpis" style="margin:20px 0">
        <div class="kpi" style="--g:linear-gradient(135deg,#10b981,#34d399)">
          <div class="l">Exactitude factuelle</div>
          <div class="v">${fa.score || 0}<small>/10</small></div>
        </div>
        <div class="kpi" style="--g:linear-gradient(135deg,#3b82f6,#60a5fa)">
          <div class="l">Complétude</div>
          <div class="v">${co.score || 0}<small>/10</small></div>
        </div>
        <div class="kpi" style="--g:linear-gradient(135deg,#f59e0b,#fbbf24)">
          <div class="l">Actionnabilité</div>
          <div class="v">${ac.score || 0}<small>/10</small></div>
        </div>
        <div class="kpi" style="--g:linear-gradient(135deg,${scoreColor},${scoreColor}dd)">
          <div class="l">Score global</div>
          <div class="v" style="font-size:2.5em">${overall.toFixed(1)}<small>/10</small></div>
        </div>
      </div>
      
      <details open>
        <summary><strong>📋 Justifications détaillées</strong></summary>
        <div style="margin-top:12px">
          <p><strong>Exactitude factuelle (poids 50%) :</strong><br>${esc(fa.rationale || 'N/A')}</p>
          <p><strong>Complétude (poids 30%) :</strong><br>${esc(co.rationale || 'N/A')}</p>
          <p><strong>Actionnabilité (poids 20%) :</strong><br>${esc(ac.rationale || 'N/A')}</p>
        </div>
      </details>
      
      <details${hallus.length ? ' open' : ''}>
        <summary><strong>⚠️ Hallucinations détectées : ${hallus.length}</strong></summary>
  `;
  
  if (hallus.length > 0) {
    html += '<div style="margin-top:12px"><ol style="padding-left:20px">';
    hallus.forEach(h => {
      html += `<li style="margin-bottom:12px">
        <strong>Affirmation :</strong> ${esc(h.claim || '')}
        <br><em class="muted">Cherché dans :</em> ${esc(h.source_searched || '')}
      </li>`;
    });
    html += '</ol></div>';
  } else {
    html += '<p style="color:#10b981;margin:12px 0">✅ Aucune hallucination détectée.</p>';
  }
  
  html += `
      </details>
      
      <p class="muted" style="margin:16px 0 0;font-size:13px">
        Méthode : le modèle juge vérifie chaque affirmation du rapport contre l'audit JSON source (vérité de référence).
      </p>
    </div>
  `;
  
  div.innerHTML = html;
}

// ✅ 2. DÉFINIR evaluateAnalysis() APRÈS
async function evaluateAnalysis() {
  if (!raw || Object.keys(raw).length === 0) {
    alert('Aucun audit disponible. Lancez d\'abord un audit sur vos données.');
    return;
  }
  
  if (!aiText || aiText.trim() === '') {
    alert('Aucune analyse IA à évaluer. Lancez d\'abord une analyse avec Ollama.');
    return;
  }
  
  const evalDiv = $('#evaluation-results');
  const evalBtn = $('#evalBtn');
  evalBtn.disabled = true;
  
  evalDiv.innerHTML = `
    <div class="card" style="margin-top:24px;border:2px solid #8b5cf6">
      <p class="muted" style="margin:0">
        <span class="spin"></span>
        Évaluation en cours par le modèle juge… 
        <br><small>Cela peut prendre 1-2 minutes selon la taille du rapport.</small>
      </p>
    </div>
  `;
  evalDiv.scrollIntoView({behavior: 'smooth', block: 'center'});
  
  try {
    console.log('=== DEBUG EVALUATE ===');
    console.log('Audit tables:', Object.keys(raw));
    console.log('Analysis length:', aiText.length);
    console.log('Model:', $('#model').value.trim());
    
    const r = await fetch('/api/evaluate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        audit: raw,
        analysis: aiText,
        model: $('#model').value.trim()
      })
    });
    
    const j = await readJson(r);
    
    console.log('Response:', j);
    
    if (!r.ok) throw new Error(j.error || 'Erreur serveur');
    
    if (!j.evaluation) {
      throw new Error('Réponse invalide du serveur : clé "evaluation" manquante.');
    }
    
    displayEvaluation(j.evaluation);  // ✅ Appelée ICI
    
  } catch (e) {
    console.error('Erreur évaluation:', e);
    evalDiv.innerHTML = `
      <div class="card" style="margin-top:24px;border-left:4px solid #dc2626">
        <h3 style="color:#dc2626;margin:0 0 8px">❌ Erreur d'évaluation</h3>
        <p style="margin:0">${esc(e.message)}</p>
        <details style="margin-top:12px">
          <summary class="muted">Détails techniques</summary>
          <pre style="font-size:12px;overflow:auto">${esc(e.stack || e.toString())}</pre>
        </details>
      </div>
    `;
  } finally {
    evalBtn.disabled = false;
  }
}

/* ---------- Évaluation de la recherche (RAG) : P@k, R@k, NDCG@k, RR@k ---------- */
const evalBox = (id, html) => { $(id).innerHTML = `<div style="margin-top:16px">${html}</div>`; };
const evalErr = (id, e) => evalBox(id, `<p class="err" style="margin:0">${esc(e.message)}</p>`);
const evalWait = (id, txt) => evalBox(id, `<p class="muted" style="margin:0"><span class="spin"></span>${txt}</p>`);
const f3 = v => (v ?? 0).toLocaleString('fr-FR', {minimumFractionDigits: 3, maximumFractionDigits: 3});
const sc01 = v => `<span class="tag ${v >= .75 ? 'ok' : v >= .4 ? 'warn' : 'bad'}">${f3(v)}</span>`;

async function evalRag() {
  const btn = $('#ragEvalBtn');
  btn.disabled = true;
  evalWait('#rag-eval-results', 'Construction du jeu de test et comparaison des modes de recherche…');
  try {
    const r = await fetch('/api/eval/rag', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({k: +$('#ragK').value || 4, n_queries: +$('#ragN').value || 8, use_llm: $('#ragLlm').checked, model: $('#model').value.trim()})});
    const j = await readJson(r);
    if (!r.ok) throw new Error(j.error || 'Erreur serveur');
    showRagEval(j);
  } catch (e) { evalErr('#rag-eval-results', e); }
  btn.disabled = false;
}

function showRagEval(j) {
  const k = j.k, names = {hybrid: 'Hybride (utilisé par l’application)', semantic: 'Sémantique seule', bm25: 'Lexical BM25 seul'};
  const modes = ['hybrid', 'semantic', 'bm25'].filter(m => j.modes[m]);
  const best = key => Math.max(...modes.map(m => j.modes[m][key]));
  const cell = (m, key) => { const v = j.modes[m][key]; return `<td class="n" style="${v === best(key) && modes.length > 1 ? 'font-weight:800' : ''}">${f3(v)}</td>`; };
  const src = Object.entries(j.query_sources || {}).map(([a, n]) => `${n} ${a === 'llm' ? 'reformulée(s) par le modèle' : 'extraite(s) du texte'}`).join(', ');
  let h = `<div class="scroll" style="max-height:none"><table class="dt"><thead><tr><th>Mode de recherche</th><th class="n">Precision@${k}</th><th class="n">Recall@${k}</th><th class="n">NDCG@${k}</th><th class="n">RR@${k}</th></tr></thead><tbody>` +
    modes.map(m => `<tr><td class="c">${names[m]}</td>${cell(m, 'P')}${cell(m, 'R')}${cell(m, 'NDCG')}${cell(m, 'RR')}</tr>`).join('') + '</tbody></table></div>';
  h += `<p class="muted" style="font-size:13px;margin:10px 0 0">${j.n_queries} question(s) sur ${j.n_chunks} passages (${esc(src)}) · poids du sémantique α = ${j.alpha}. Un seul passage est pertinent par question : Precision@${k} ne peut donc pas dépasser ${f3(1 / k)}. Lisez surtout Recall, NDCG et RR. En gras : meilleure valeur.</p>`;
  if (!j.semantic_available) h += '<p class="err" style="font-size:13px;margin:8px 0 0">Embeddings indisponibles : seul le mode BM25 a pu être évalué.</p>';
  h += `<details style="margin-top:10px"><summary>Détail par question (rang du bon passage, 1 = premier)</summary><div class="scroll" style="max-height:320px;margin-top:8px"><table class="dt"><thead><tr><th>Question</th>${modes.map(m => `<th class="n">${m}</th>`).join('')}</tr></thead><tbody>` +
    j.details.map(d => `<tr><td class="wrap">${esc(d.query)}</td>${modes.map(m => `<td class="n">${d.ranks[m] ?? '—'}</td>`).join('')}</tr>`).join('') + '</tbody></table></div></details>';
  evalBox('#rag-eval-results', h);
}

/* ---------- Évaluation du Text-to-SQL : pass@k, cons@k ---------- */
async function evalSql() {
  const btn = $('#sqlEvalBtn');
  if (!raw || !Object.keys(raw).length) { alert('Lancez d’abord un audit.'); return; }
  btn.disabled = true;
  evalWait('#sql-eval-results', 'Le chatbot SQL répond à chaque question plusieurs fois… cela peut prendre plusieurs minutes.');
  try {
    const r = await fetch('/api/eval/sql', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({audit: raw, k: +$('#sqlK').value || 3, n_attempts: +$('#sqlNA').value || 3, max_cases: +$('#sqlN').value || 3, model: $('#model').value.trim()})});
    const j = await readJson(r);
    if (!r.ok) throw new Error(j.error || 'Erreur serveur');
    showSqlEval(j);
  } catch (e) { evalErr('#sql-eval-results', e); }
  btn.disabled = false;
}

function showSqlEval(j) {
  const k = j.k, pk = 'pass@' + k, ck = 'cons@' + k;
  let h = `<div class="kpis" style="margin-bottom:14px">
    <div class="kpi" style="--g:linear-gradient(135deg,#3b82f6,#60a5fa)"><div class="l">pass@1 moyen</div><div class="v">${f3(j['mean_pass@1'])}</div></div>
    <div class="kpi" style="--g:linear-gradient(135deg,#10b981,#34d399)"><div class="l">${pk} moyen</div><div class="v">${f3(j['mean_' + pk])}</div></div>
    <div class="kpi" style="--g:linear-gradient(135deg,#f59e0b,#fbbf24)"><div class="l">${ck} moyen</div><div class="v">${f3(j['mean_' + ck])}</div></div></div>`;
  h += `<div class="scroll" style="max-height:none"><table class="dt"><thead><tr><th>Question testée</th><th class="n">Justes / n</th><th class="n">pass@1</th><th class="n">${pk}</th><th class="n">${ck}</th></tr></thead><tbody>` +
    j.results.map(r => r.error
      ? `<tr><td class="wrap">${esc(r.description || r.question)}</td><td colspan="4" class="err">${esc(r.error)}</td></tr>`
      : `<tr><td class="wrap">${esc(r.description)}</td><td class="n">${r.correct} / ${r.n_attempts}</td><td class="n">${sc01(r['pass@1'])}</td><td class="n">${sc01(r[pk])}</td><td class="n">${sc01(r[ck])}</td></tr>`).join('') + '</tbody></table></div>';
  h += `<p class="muted" style="font-size:13px;margin:10px 0 0">${j.n_valid} question(s) valide(s) sur ${j.n_test_cases}, ${j.n_attempts} tentatives chacune. Une réponse est juste si elle contient le nombre exact calculé par l’audit DuckDB. Ce test mesure des questions simples de comptage : il ne couvre pas les requêtes complexes.</p>`;
  evalBox('#sql-eval-results', h);
}
