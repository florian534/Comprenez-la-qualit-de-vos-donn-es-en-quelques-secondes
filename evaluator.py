"""
evaluator.py — Évaluation hybride d'un rapport d'audit (Python + LLM-as-a-Judge)

Ce qui change par rapport à la version précédente
-------------------------------------------------
1. Plus AUCUNE troncature : le juge reçoit l'audit complet (allégé, pas coupé)
   et le rapport complet.
2. Les CHIFFRES sont vérifiés par Python (déterministe), pas par le LLM :
   chaque nombre du rapport est cherché dans l'audit, avec tolérance d'arrondi,
   et rattaché à la table dont parle la phrase.
3. La COUVERTURE des anomalies (missing >= seuil, doublons, valeurs négatives)
   est calculée par Python : quelles anomalies de l'audit le rapport ne cite pas ?
4. Le LLM ne juge que ce que Python ne sait pas juger : affirmations
   qualitatives, anomalies évidentes non listées, qualité des recommandations.
5. Si le prompt est trop gros, évaluation TABLE PAR TABLE puis agrégation.
6. Les "hallucinations" renvoyées par le LLM sont validées (la phrase doit
   exister dans le rapport) avant d'être affichées.
7. Les extraits de documents de référence (contexte métier + RAG) sont fournis
   au juge, pour qu'une règle venant d'un PDF ne soit pas jugée inventée.

Le format de sortie reste compatible avec app.js (factual_accuracy,
completeness, actionability, hallucinations, overall_score) ; des clés
supplémentaires sont ajoutées (numeric_check, missed_anomalies, mode...).

Variables d'environnement (facultatives)
    JUDGE_NUM_CTX            contexte demandé à Ollama            (32768)
    JUDGE_NUM_PREDICT        tokens max de la réponse du juge     (4096)
    JUDGE_SINGLE_MAX_TOKENS  au-delà : évaluation table par table (14000)
    JUDGE_TIMEOUT            timeout HTTP en secondes             (900)
    JUDGE_MISSING_PCT        seuil d'anomalie "valeurs manquantes" (5)
"""

import json
import os
import re
import sys
import unicodedata
from bisect import bisect_left
from typing import Optional

import requests

# ============================================================
# PARAMÈTRES
# ============================================================

JUDGE_NUM_CTX = int(os.getenv("JUDGE_NUM_CTX", "32768"))
JUDGE_NUM_PREDICT = int(os.getenv("JUDGE_NUM_PREDICT", "4096"))
JUDGE_SINGLE_MAX_TOKENS = int(os.getenv("JUDGE_SINGLE_MAX_TOKENS", "14000"))
JUDGE_TIMEOUT = int(os.getenv("JUDGE_TIMEOUT", "900"))
MISSING_CRITICAL_PCT = float(os.getenv("JUDGE_MISSING_PCT", "5"))

# Pondération du score global
W_FACT, W_COMP, W_ACT = 0.5, 0.3, 0.2

# Part de la vérification Python dans les scores d'exactitude et de complétude
# (le reste vient du jugement qualitatif du LLM)
PY_WEIGHT = 0.6

# Estimation grossière : 1 token ~ 3 caractères (français + JSON)
CHARS_PER_TOKEN = 3


# ============================================================
# OUTILS DE TEXTE
# ============================================================


def _norm(s) -> str:
    """Minuscules sans accents, pour comparer des textes."""
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _is_num(x) -> bool:
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and x == x
        and abs(x) != float("inf")
    )


# ============================================================
# AUDIT ALLÉGÉ POUR LE JUGE
# ============================================================


def audit_for_judge_table(d: dict) -> dict:
    """Version allégée d'UNE table de l'audit : on garde tous les chiffres,
    on retire le bruit (champs du schéma toujours null, colonnes sans manquant)."""
    if not isinstance(d, dict):
        return {"value": d}
    if d.get("error"):
        return {"error": d["error"]}

    s = d.get("structure") or {}
    missing = d.get("missing_values") or []
    with_missing = [m for m in missing if (m.get("missing") or 0) > 0]

    return {
        "rows": s.get("rows"),
        "columns": s.get("columns"),
        "schema": {
            c.get("column_name"): c.get("column_type") for c in (s.get("schema") or [])
        },
        "duplicates": d.get("duplicates"),
        "missing_values": with_missing,
        "columns_without_missing": len(missing) - len(with_missing),
        "numeric_statistics": d.get("numeric_statistics"),
        "cardinality": d.get("cardinality"),
        "negative_values": d.get("negative_values"),
    }


def audit_for_judge(audit: dict, tables: Optional[list] = None) -> str:
    """JSON compact (sans indentation) de tout l'audit, ou de certaines tables."""
    out = {
        t: audit_for_judge_table(d)
        for t, d in audit.items()
        if tables is None or t in tables
    }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str)


# ============================================================
# EXTRACTION DES NOMBRES D'UN TEXTE
# ============================================================

# 1 : entier (avec séparateurs de milliers espaces/insécables) ; 2 : décimales ;
# 3 : suffixe d'échelle (M, k, millions...)
_NUM_RE = re.compile(
    r"(?<![\w.,/#\[])"
    r"(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)"
    r"(?:[.,](\d+))?"
    r"(?:\s?(Md|M|k|K|millions?|milliards?|mille)\b)?"
    r"(?![\w])"
)

_SCALE = {
    "m": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "md": 1e9,
    "milliard": 1e9,
    "milliards": 1e9,
    "k": 1e3,
    "mille": 1e3,
}

# Éléments qui ressemblent à des nombres mais n'en sont pas : numéros de liste,
# citations [1], [fichier.pdf, p. 3], "p. 3"
_NOISE = [
    re.compile(r"^\s*(?:[-*+]\s+)?\d+[.)]\s+"),
    re.compile(r"\[\d+(?:\s*[,;\-–]\s*\d+)*\]"),
    re.compile(r"\[[^\]]*\.pdf[^\]]*\]", re.I),
    re.compile(r"\bpp?\.\s*\d+(?:\s*[-–,]\s*\d+)*", re.I),
]


def _clean_line(line: str) -> str:
    for rx in _NOISE:
        line = rx.sub(" ", line)
    return line


def _find_numbers(line: str):
    """Retourne [(valeur, nb_décimales, échelle, texte_brut)] pour une ligne."""
    found = []
    for m in _NUM_RE.finditer(_clean_line(line)):
        ipart = re.sub(r"[ \u00a0\u202f]", "", m.group(1))
        frac = m.group(2) or ""
        try:
            v = float(ipart + ("." + frac if frac else ""))
        except ValueError:
            continue
        mult = _SCALE.get((m.group(3) or "").lower(), 1.0)
        found.append((v * mult, len(frac), mult, m.group(0).strip()))
    return found


def _skippable(value: float, dec: int, mult: float) -> bool:
    """Nombres trop ambigus pour être vérifiés : petits entiers (3 colonnes,
    étape 2...) et années."""
    if mult == 1.0 and dec == 0:
        if value < 10:
            return True
        if 1900 <= value <= 2100:
            return True
    return False


# ============================================================
# PORTÉE : DE QUELLE TABLE PARLE CHAQUE LIGNE DU RAPPORT ?
# ============================================================

_HEAD_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_BOLD_RE = re.compile(r"^\s*(?:[-*]\s+)?(\*\*|__)(.+?)\1\s*:?\s*$")


def _scopes(text: str, tables: list):
    """Pour chaque ligne : tables nommées dans la ligne, et tables du dernier
    titre rencontré (héritage). Le nom d'une table est cherché tel quel
    (mot entier, sans normaliser les accents) pour ne pas confondre la table
    `resultat` avec le mot « résultat »."""
    pats = {
        t: re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.I) for t in tables
    }
    rows, heading = [], set()
    for line in (text or "").splitlines():
        tl = {t for t, p in pats.items() if p.search(line)}
        is_head = bool(_HEAD_RE.match(line) or _BOLD_RE.match(line))
        if is_head:
            heading = tl
            rows.append({"line": line, "tables": tl, "heading": set(), "head": True})
        else:
            rows.append(
                {"line": line, "tables": tl, "heading": set(heading), "head": False}
            )
    return rows


# ============================================================
# VÉRIFICATION DES CHIFFRES (PYTHON)
# ============================================================


def _walk_numbers(obj, out: set):
    if _is_num(obj):
        out.add(abs(float(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_numbers(v, out)


def _table_numbers(d: dict) -> set:
    """Tous les nombres d'une table de l'audit + les nombres dérivables
    (totaux, comptages, pourcentages recalculés)."""
    out = set()
    if not isinstance(d, dict) or d.get("error"):
        return out
    _walk_numbers(d, out)

    s = d.get("structure") or {}
    rows = s.get("rows")
    missing = d.get("missing_values") or []
    with_m = [m for m in missing if (m.get("missing") or 0) > 0]
    out.update(
        {float(len(missing)), float(len(with_m)), float(len(missing) - len(with_m))}
    )
    out.add(
        float(
            sum((m.get("missing") or 0) for m in missing if _is_num(m.get("missing")))
        )
    )

    dup = d.get("duplicates") or {}
    total = dup.get("total_rows") or rows
    if _is_num(total) and total and _is_num(dup.get("duplicates")):
        out.add(dup["duplicates"] / total * 100)
    if _is_num(rows) and rows:
        for c in d.get("cardinality") or []:
            if _is_num(c.get("distinct_values")):
                out.add(c["distinct_values"] / rows * 100)
    for key in ("numeric_statistics", "cardinality", "negative_values"):
        out.add(float(len(d.get(key) or [])))
    return out


def _global_derived(audit: dict) -> set:
    out = {float(len(audit))}
    rows = cols = dups = miss = 0
    for d in audit.values():
        if not isinstance(d, dict) or d.get("error"):
            continue
        s = d.get("structure") or {}
        rows += s.get("rows") or 0
        cols += s.get("columns") or 0
        dups += (d.get("duplicates") or {}).get("duplicates") or 0
        miss += sum(
            (m.get("missing") or 0)
            for m in (d.get("missing_values") or [])
            if _is_num(m.get("missing"))
        )
    out.update({float(rows), float(cols), float(dups), float(miss)})
    return out


def _pool(values) -> list:
    return sorted(values)


def _has(pool: list, v: float, tol: float) -> bool:
    i = bisect_left(pool, v - tol - 1e-9)
    return i < len(pool) and pool[i] <= v + tol + 1e-9


class _NumberChecker:
    """Cherche des nombres dans les nombres de l'audit (par table et global)."""

    def __init__(self, audit: dict, reference: str = ""):
        self.tables = list(audit.keys())
        self.by_table = {t: _pool(_table_numbers(d)) for t, d in audit.items()}
        glob = set(_global_derived(audit))
        for t in self.tables:
            glob.update(self.by_table[t])
        self.glob = _pool(glob)
        ref = set()
        for line in (reference or "").splitlines():
            for v, _d, _m, _raw in _find_numbers(line):
                ref.add(v)
        self.ref = _pool(ref)

    @staticmethod
    def tol(dec: int, mult: float) -> float:
        # Un nombre arrondi à `dec` décimales est exact à ±0,5 unité de la dernière décimale
        return 0.5 * (10**-dec) * mult

    def in_global(self, v, dec, mult) -> bool:
        tol = self.tol(dec, mult)
        return _has(self.glob, v, tol) or _has(self.ref, v, tol)

    def classify(self, v, dec, mult, scope: set):
        """Retourne ('ok'|'wrong_table'|'absent', tables_qui_contiennent_la_valeur)."""
        tol = self.tol(dec, mult)
        if _has(self.ref, v, tol):
            return "ok", []
        holders = [t for t in self.tables if _has(self.by_table[t], v, tol)]
        if scope:
            if any(t in scope for t in holders):
                return "ok", holders
            # valeur "globale" (total, nombre de tables...) acceptée
            if _has(self.glob, v, tol) and not holders:
                return "ok", []
            return ("wrong_table", holders) if holders else ("absent", [])
        if holders or _has(self.glob, v, tol):
            return "ok", holders
        return "absent", []


def verify_numbers(audit: dict, analysis: str, reference: str = "") -> dict:
    """Vérifie, en Python, chaque nombre du rapport contre l'audit.

    Un nombre est 'vérifié' s'il figure dans l'audit (ou s'en déduit : totaux,
    comptages, pourcentages recalculés) à l'arrondi près, et — quand la phrase
    nomme une table — dans CETTE table. Les petits entiers (< 10) et les années
    sont ignorés (trop ambigus).
    """
    checker = _NumberChecker(audit, reference)
    rows = _scopes(analysis, checker.tables)

    checked, failed, warnings, skipped = 0, [], [], 0
    for r in rows:
        scope = r["tables"] or r["heading"]
        from_line = bool(r["tables"])
        for v, dec, mult, raw in _find_numbers(r["line"]):
            if _skippable(v, dec, mult):
                skipped += 1
                continue
            checked += 1
            status, holders = checker.classify(v, dec, mult, scope)
            if status == "ok":
                continue
            entry = {
                "value": raw,
                "line": r["line"].strip()[:220],
                "table": sorted(scope) if scope else None,
                "found_in_tables": holders,
                "reason": status,
            }
            # Valeur d'une autre table, mais la phrase ne nomme pas la table
            # (elle hérite du titre) : simple avertissement, pas une faute.
            if status == "wrong_table" and not from_line:
                warnings.append(entry)
            else:
                failed.append(entry)

    ratio = None if checked == 0 else (checked - len(failed)) / checked
    return {
        "checked": checked,
        "verified": checked - len(failed),
        "failed": failed,
        "warnings": warnings,
        "skipped_ambiguous": skipped,
        "ratio": None if ratio is None else round(ratio, 4),
        "score": None if ratio is None else round(10 * ratio, 2),
    }


# ============================================================
# COUVERTURE DES ANOMALIES (PYTHON)
# ============================================================

_DUP_RE = re.compile(r"doublon|duplic|dupli|en double|redondan", re.I)


def check_coverage(audit: dict, analysis: str) -> dict:
    """Quelles anomalies objectives de l'audit le rapport mentionne-t-il ?

    Anomalies : colonnes avec valeurs manquantes >= seuil, tables avec
    doublons, colonnes avec valeurs négatives. Une anomalie est « couverte »
    si le rapport la cite dans le périmètre de la table, « partielle » s'il
    cite seulement la colonne ailleurs.
    """
    tables = list(audit.keys())
    rows = _scopes(analysis, tables)
    full_text = analysis or ""

    def col_rx(col):
        return re.compile(r"(?<![\w])" + re.escape(str(col)) + r"(?![\w])", re.I)

    def in_scope(r, t):
        return t in (r["tables"] or r["heading"])

    items = []
    for t, d in audit.items():
        if not isinstance(d, dict) or d.get("error"):
            continue
        for m in d.get("missing_values") or []:
            pct = m.get("missing_percent")
            if _is_num(pct) and pct >= MISSING_CRITICAL_PCT:
                items.append(
                    {
                        "table": t,
                        "kind": "missing",
                        "column": m.get("column"),
                        "detail": f"{pct} % de valeurs manquantes ({m.get('missing')} lignes)",
                    }
                )
        dup = (d.get("duplicates") or {}).get("duplicates")
        if _is_num(dup) and dup > 0:
            items.append(
                {
                    "table": t,
                    "kind": "duplicates",
                    "column": None,
                    "detail": f"{int(dup)} lignes en double",
                }
            )
        for n in d.get("negative_values") or []:
            col = n.get("column") if isinstance(n, dict) else n
            if col:
                items.append(
                    {
                        "table": t,
                        "kind": "negative",
                        "column": col,
                        "detail": "valeurs négatives",
                    }
                )

    full = partial = 0
    missed = []
    for it in items:
        t = it["table"]
        status = "missed"
        if it["kind"] == "duplicates":
            if any(in_scope(r, t) and _DUP_RE.search(r["line"]) for r in rows):
                status = "covered"
        else:
            rx = col_rx(it["column"])
            if any(in_scope(r, t) and rx.search(r["line"]) for r in rows):
                status = "covered"
            elif rx.search(full_text):
                status = "partial"
        if status == "covered":
            full += 1
        elif status == "partial":
            partial += 1
        else:
            missed.append(it)
        it["status"] = status

    total = len(items)
    ratio = None if total == 0 else (full + 0.5 * partial) / total
    return {
        "total": total,
        "covered": full,
        "partial": partial,
        "missed": missed,
        "missing_threshold_pct": MISSING_CRITICAL_PCT,
        "ratio": None if ratio is None else round(ratio, 4),
        "score": None if ratio is None else round(10 * ratio, 2),
    }


# ============================================================
# EXTRAIT DU RAPPORT POUR UNE TABLE
# ============================================================


def report_excerpt_for_table(analysis: str, table: str, tables: list) -> str:
    """Lignes du rapport qui concernent `table` ou aucune table en particulier
    (synthèse, recommandations générales). Écarte celles qui ne parlent que
    d'autres tables."""
    keep = []
    for r in _scopes(analysis, tables):
        eff = r["tables"] or r["heading"]
        if not eff or table in eff:
            keep.append(r["line"])
    return "\n".join(keep).strip()


# ============================================================
# APPEL DU JUGE
# ============================================================

JUDGE_SYSTEM = (
    "Tu es un évaluateur expert en qualité des données. "
    "Tu réponds UNIQUEMENT par un objet JSON valide, sans texte autour, "
    "sans bloc de code. Tu es strict et factuel."
)


def _parse_json(raw: str) -> dict:
    if not raw or not raw.strip():
        raise ValueError("réponse vide")
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i = s.find("{")
    if i < 0:
        raise ValueError("aucun JSON dans la réponse")
    s = s[i:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(s)
        return obj
    except json.JSONDecodeError:
        pass
    # Réponse coupée : on referme chaînes, tableaux et objets ouverts
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    fixed = s + ('"' if in_str else "")
    fixed = re.sub(r",\s*$", "", fixed.rstrip()) + "".join(reversed(stack))
    obj, _ = json.JSONDecoder().raw_decode(fixed)
    return obj


def _call_judge(url: str, model: str, prompt: str) -> dict:
    """Appelle Ollama. 1re tentative avec format=json ; en cas d'échec,
    2e tentative sans contrainte de format et avec plus de tokens de sortie
    (certains modèles « raisonnants » consomment num_predict en réflexion)."""
    last_err = None
    for attempt in range(2):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": JUDGE_NUM_CTX,
                "num_predict": JUDGE_NUM_PREDICT * (2 if attempt else 1),
            },
        }
        if attempt == 0:
            payload["format"] = "json"
        response = requests.post(url, json=payload, timeout=JUDGE_TIMEOUT)
        response.raise_for_status()
        raw = (response.json().get("message") or {}).get("content") or ""
        try:
            return _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = f"{e} — début de la réponse : {raw[:200]!r}"
            print(
                f"⚠️ Juge : réponse inexploitable (tentative {attempt + 1}/2) : {last_err}"
            )
    raise ValueError(f"Le juge n'a pas renvoyé de JSON valide : {last_err}")


def _build_prompt(
    audit_json: str, report: str, reference: str, py_notes: str, scope_note: str
) -> str:
    ref_block = ""
    if reference and reference.strip():
        ref_block = (
            "DOCUMENTS DE RÉFÉRENCE FOURNIS À L'AUTEUR DU RAPPORT "
            "(contexte métier, extraits de PDF). Une règle ou un seuil qui y figure "
            "n'est PAS une invention :\n" + reference.strip() + "\n\n"
        )
    return f"""Tu évalues un rapport d'audit de qualité des données.
{scope_note}
SOURCE DE VÉRITÉ : résultats de l'audit (JSON compact) :
{audit_json}

{ref_block}RAPPORT À ÉVALUER :
{report}

VÉRIFICATIONS DÉJÀ EFFECTUÉES PAR UN PROGRAMME (fiables, ne les refais pas, ne les contredis pas) :
{py_notes}

TA TÂCHE. Les chiffres sont déjà vérifiés : ne juge PAS les chiffres. Juge :
1. qualitative_accuracy (0-10) : les interprétations, causes supposées, règles métier
   et jugements du rapport sont-ils justifiés par l'audit ou par les documents de
   référence ? Une hypothèse présentée comme un fait est une faute. 10 = tout est justifié.
2. unsupported_claims : affirmations QUALITATIVES recopiées MOT POUR MOT du rapport,
   ni justifiées par l'audit ni par les documents de référence. Liste vide si aucune.
   Avant d'ajouter une affirmation, vérifie qu'elle n'est pas dans l'audit ou les références.
3. completeness (0-10) : le rapport mentionne-t-il les anomalies importantes visibles
   dans l'audit (en plus de celles listées dans les vérifications ci-dessus) ?
   Exemples : min/max aberrants, colonne quasi constante, cardinalité suspecte.
4. actionability (0-10) : chaque anomalie a-t-elle une recommandation concrète
   (action précise, table et colonne nommées) ? 0 = aucune recommandation.

Chaque "rationale" fait 1 à 3 phrases courtes.

FORMAT EXACT DE LA RÉPONSE :
{{
  "qualitative_accuracy": {{"score": 0, "rationale": ""}},
  "completeness": {{"score": 0, "rationale": ""}},
  "actionability": {{"score": 0, "rationale": ""}},
  "unsupported_claims": [{{"claim": "", "why": ""}}]
}}
"""


def _py_notes(py: dict, cov: dict, only_table: Optional[str] = None) -> str:
    lines = []
    failed = [
        f
        for f in py["failed"]
        if only_table is None or not f["table"] or only_table in f["table"]
    ]
    lines.append(
        f"- Chiffres du rapport : {py['verified']}/{py['checked']} retrouvés dans l'audit."
    )
    if failed:
        lines.append(
            "- Chiffres introuvables ou attribués à la mauvaise table (déjà comptés comme erreurs) :"
        )
        for f in failed[:15]:
            lines.append(f"    • « {f['value']} » dans : {f['line'][:120]}")
    missed = [
        m for m in cov["missed"] if only_table is None or m["table"] == only_table
    ]
    if missed:
        lines.append(
            f"- Anomalies de l'audit (seuil manquants ≥ {cov['missing_threshold_pct']} %, doublons, négatifs) NON citées dans le rapport :"
        )
        for m in missed[:15]:
            col = f" / {m['column']}" if m.get("column") else ""
            lines.append(f"    • {m['table']}{col} : {m['detail']}")
    else:
        lines.append(
            "- Toutes les anomalies objectives de l'audit sont citées dans le rapport."
        )
    return "\n".join(lines)


# ============================================================
# VALIDATION DES RÉPONSES DU JUGE
# ============================================================


def _score(x) -> Optional[float]:
    try:
        return max(0.0, min(10.0, float(x)))
    except (TypeError, ValueError):
        return None


def _claim_in_report(claim: str, report: str) -> bool:
    """La phrase signalée par le juge existe-t-elle vraiment dans le rapport ?"""
    c, r = _norm(claim).strip(), _norm(report)
    if not c:
        return False
    if c in r:
        return True
    words = [w for w in re.findall(r"[a-z0-9]{3,}", c)]
    if len(words) < 4:
        return False
    for line in r.splitlines():
        if sum(1 for w in words if w in line) / len(words) >= 0.7:
            return True
    return False


def _claim_numbers_all_verified(claim: str, checker: _NumberChecker) -> bool:
    """Si tous les chiffres de l'affirmation contestée existent dans l'audit,
    le juge LLM se trompe (Python fait foi pour les chiffres)."""
    nums = [(v, d, m) for v, d, m, _ in _find_numbers(claim) if not _skippable(v, d, m)]
    return bool(nums) and all(checker.in_global(v, d, m) for v, d, m in nums)


def _clean_claims(claims, report: str, checker: _NumberChecker) -> list:
    out = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        text = str(c.get("claim") or "").strip()
        if not text or not _claim_in_report(text, report):
            continue
        if _claim_numbers_all_verified(text, checker):
            continue
        out.append(
            {
                "claim": text,
                "source_searched": str(
                    c.get("why")
                    or "Ni l'audit ni les documents de référence ne la justifient."
                ),
            }
        )
    return out


# ============================================================
# ÉVALUATION
# ============================================================


def check_without_llm(audit: dict, analysis: str, reference: str = "") -> dict:
    """Parties déterministes seules (pas d'appel à Ollama)."""
    return {
        "numeric_check": verify_numbers(audit, analysis, reference),
        "coverage": check_coverage(audit, analysis),
    }


def evaluate_analysis(
    audit: dict,
    analysis: str,
    model: Optional[str] = None,
    ollama_url: Optional[str] = None,
    reference: str = "",
) -> dict:
    """
    Évalue un rapport d'analyse.

    audit      : dict d'audit complet (celui renvoyé par /api/audit)
    analysis   : texte du rapport généré par l'IA
    reference  : contexte métier + extraits RAG fournis à l'analyse (facultatif)
    """
    try:
        from config import OLLAMA_URL as _URL, MODEL as _MODEL
    except ImportError:
        _URL = "http://localhost:11434/api/chat"
        _MODEL = "gpt-oss:120b-cloud"
    url = ollama_url or _URL
    mdl = model or _MODEL
    reference = reference or ""
    analysis = analysis or ""
    warnings = []

    # ---------- 1. Vérifications déterministes ----------
    py = verify_numbers(audit, analysis, reference)
    cov = check_coverage(audit, analysis)
    checker = _NumberChecker(audit, reference)
    tables = [t for t, d in audit.items() if isinstance(d, dict) and not d.get("error")]
    err_tables = [t for t in audit if t not in tables]
    if err_tables:
        warnings.append(
            "Tables en erreur dans l'audit, non évaluées : " + ", ".join(err_tables)
        )
    if not tables:
        return {"error": "Aucune table exploitable dans l'audit.", "model_used": mdl}

    # ---------- 2. Choix du mode (une requête ou table par table) ----------
    full_json = audit_for_judge(audit, tables)
    est_tokens = (
        len(full_json) + len(analysis) + len(reference) + 2500
    ) // CHARS_PER_TOKEN
    mode = (
        "single"
        if est_tokens <= JUDGE_SINGLE_MAX_TOKENS or len(tables) == 1
        else "per_table"
    )

    print("=" * 60)
    print(f"🤖 ÉVALUATION avec : {mdl} — mode {mode} (~{est_tokens} tokens estimés)")
    print(
        f"📊 Audit : {len(full_json)} car. | 📝 Rapport : {len(analysis)} car. "
        f"| 📎 Références : {len(reference)} car."
    )
    print(
        f"🔢 Chiffres vérifiés : {py['verified']}/{py['checked']} "
        f"| 🧭 Anomalies couvertes : {cov['covered']}/{cov['total']} (+{cov['partial']} partielles)"
    )
    print("=" * 60)

    # ---------- 3. Jugement qualitatif ----------
    judged = []  # [(étiquette, dict_llm, rapport_utilisé)]
    try:
        if mode == "single":
            prompt = _build_prompt(
                full_json, analysis, reference, _py_notes(py, cov), ""
            )
            judged.append(("global", _call_judge(url, mdl, prompt), analysis))
        else:
            for t in tables:
                excerpt = report_excerpt_for_table(analysis, t, tables) or analysis
                note = (
                    f"\nLe JSON ci-dessous ne contient QUE la table « {t} » et le rapport est "
                    f"limité aux passages qui la concernent. Ne juge pas les autres tables.\n"
                )
                prompt = _build_prompt(
                    audit_for_judge(audit, [t]),
                    excerpt,
                    reference,
                    _py_notes(py, cov, only_table=t),
                    note,
                )
                if len(prompt) // CHARS_PER_TOKEN > JUDGE_NUM_CTX * 0.8:
                    warnings.append(
                        f"Prompt très volumineux pour la table {t} : "
                        "augmentez JUDGE_NUM_CTX ou réduisez l'audit."
                    )
                print(f"   → table {t}")
                judged.append((t, _call_judge(url, mdl, prompt), excerpt))
    except requests.exceptions.RequestException:
        raise  # laissé à server.py (message « Ollama est inaccessible »)
    except ValueError as e:
        return {
            "error": str(e),
            "model_used": mdl,
            "numeric_check": py,
            "coverage": cov,
        }

    # ---------- 4. Agrégation ----------
    def avg(key):
        vals = [_score((r.get(key) or {}).get("score")) for _, r, _ in judged]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    def rationale(key):
        parts = []
        for label, r, _ in judged:
            txt = str((r.get(key) or {}).get("rationale") or "").strip()
            if txt:
                parts.append(txt if mode == "single" else f"[{label}] {txt}")
        return " ".join(parts)

    q_llm, c_llm, a_llm = (
        avg("qualitative_accuracy"),
        avg("completeness"),
        avg("actionability"),
    )

    def blend(py_score, llm_score):
        if py_score is None:
            return llm_score
        if llm_score is None:
            return py_score
        return PY_WEIGHT * py_score + (1 - PY_WEIGHT) * llm_score

    fa = blend(py["score"], q_llm)
    co = blend(cov["score"], c_llm)
    ac = a_llm

    # Explications lisibles
    n_fail = len(py["failed"])
    fa_txt = (
        f"Vérification automatique : {py['verified']}/{py['checked']} chiffres du rapport "
        f"retrouvés dans l'audit ({n_fail} introuvable(s) ou attribué(s) à une autre table). "
        if py["checked"]
        else "Aucun chiffre vérifiable dans le rapport. "
    )
    fa_txt += rationale("qualitative_accuracy")

    co_txt = (
        f"Vérification automatique : {cov['covered']} anomalie(s) citée(s) sur {cov['total']} "
        f"(+{cov['partial']} partiellement, seuil {cov['missing_threshold_pct']} %). "
        if cov["total"]
        else "Aucune anomalie objective dans l'audit au seuil retenu. "
    )
    if cov["missed"]:
        co_txt += (
            "Non citées : "
            + "; ".join(
                (
                    f"{m['table']}.{m['column']}"
                    if m.get("column")
                    else f"{m['table']} (doublons)"
                )
                for m in cov["missed"][:10]
            )
            + ". "
        )
    co_txt += rationale("completeness")

    # Hallucinations : chiffres faux (Python) + affirmations qualitatives validées (LLM)
    hallus = []
    for f in py["failed"]:
        if f["reason"] == "wrong_table":
            src = (
                f"Vérification automatique : la valeur {f['value']} existe dans l'audit mais "
                f"pour {', '.join(f['found_in_tables'])}, pas pour {', '.join(f['table'])}."
            )
        else:
            src = (
                f"Vérification automatique : la valeur {f['value']} n'existe nulle part dans l'audit"
                + (f" (table {', '.join(f['table'])})." if f["table"] else ".")
            )
        hallus.append({"claim": f["line"], "source_searched": src})
    for _, r, rep in judged:
        hallus.extend(_clean_claims(r.get("unsupported_claims"), rep, checker))

    result = {
        "factual_accuracy": {
            "score": round(fa, 1) if fa is not None else 0,
            "rationale": fa_txt.strip(),
        },
        "completeness": {
            "score": round(co, 1) if co is not None else 0,
            "rationale": co_txt.strip(),
        },
        "actionability": {
            "score": round(ac, 1) if ac is not None else 0,
            "rationale": rationale("actionability") or "Non évalué.",
        },
        "hallucinations": hallus,
        "numeric_check": py,
        "coverage": cov,
        "missed_anomalies": cov["missed"],
        "mode": mode,
        "model_used": mdl,
        "warnings": warnings,
    }
    result = _ensure_overall_score(result)

    print(
        "✅ Évaluation terminée : "
        f"exactitude {result['factual_accuracy']['score']} | complétude {result['completeness']['score']} "
        f"| actionnabilité {result['actionability']['score']} | global {result['overall_score']} "
        f"| hallucinations {len(hallus)}"
    )
    return result


# ============================================================
# HELPERS
# ============================================================


def _ensure_overall_score(result: dict) -> dict:
    """Score global = 0,5 × exactitude + 0,3 × complétude + 0,2 × actionnabilité
    (toujours recalculé : on ne fait pas confiance au LLM pour l'arithmétique)."""
    try:
        fa = float(result.get("factual_accuracy", {}).get("score", 0))
        co = float(result.get("completeness", {}).get("score", 0))
        ac = float(result.get("actionability", {}).get("score", 0))
        result["overall_score"] = round(W_FACT * fa + W_COMP * co + W_ACT * ac, 2)
    except (TypeError, ValueError, AttributeError):
        result.setdefault("overall_score", 0.0)
    return result


def format_evaluation_report(eval_result: dict) -> str:
    """Formate le résultat de l'évaluation en Markdown lisible."""
    if "error" in eval_result:
        return f"❌ Erreur d'évaluation : {eval_result['error']}"

    lines = ["# Rapport d'évaluation (Python + LLM-as-a-Judge)\n", "## Scores\n"]
    for key, label, weight in [
        ("factual_accuracy", "Exactitude factuelle", "0.5"),
        ("completeness", "Complétude", "0.3"),
        ("actionability", "Actionnabilité", "0.2"),
    ]:
        dim = eval_result.get(key, {})
        lines.append(f"### {label} (poids {weight}) : {dim.get('score', 'N/A')}/10")
        lines.append(f"{dim.get('rationale', '')}\n")
    lines.append(
        f"## Score global pondéré : **{eval_result.get('overall_score', 'N/A')}/10**\n"
    )

    hallus = eval_result.get("hallucinations", [])
    lines.append(f"## Affirmations non vérifiées : {len(hallus)}\n")
    if hallus:
        for i, h in enumerate(hallus, 1):
            lines.append(f"{i}. **Affirmation :** {h.get('claim', '')}")
            lines.append(f"   **Vérification :** {h.get('source_searched', '')}\n")
    else:
        lines.append("✅ Aucune affirmation non vérifiée.\n")

    missed = eval_result.get("missed_anomalies") or []
    if missed:
        lines.append(
            f"## Anomalies de l'audit non citées dans le rapport : {len(missed)}\n"
        )
        for m in missed:
            col = f" / {m['column']}" if m.get("column") else ""
            lines.append(f"- {m['table']}{col} : {m['detail']}")
        lines.append("")
    for w in eval_result.get("warnings") or []:
        lines.append(f"⚠️ {w}")
    return "\n".join(lines)


# ============================================================
# CLI
#   python evaluator.py audit.json analyse.txt            -> évaluation complète
#   python evaluator.py audit.json analyse.txt --no-llm   -> vérifications Python seules
#   options : --model NOM   --reference fichier.txt
# ============================================================

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Évalue un rapport d'audit contre audit.json"
    )
    ap.add_argument("audit", help="fichier audit.json")
    ap.add_argument(
        "analysis", help="fichier texte du rapport (ex. reports/analyse_ollama.txt)"
    )
    ap.add_argument(
        "--reference",
        help="fichier texte : contexte métier / extraits PDF fournis à l'IA",
    )
    ap.add_argument("--model", help="modèle Ollama du juge")
    ap.add_argument(
        "--no-llm", action="store_true", help="vérifications Python seulement"
    )
    args = ap.parse_args()

    with open(args.audit, encoding="utf-8") as f:
        _audit = json.load(f)
    with open(args.analysis, encoding="utf-8") as f:
        _analysis = f.read()
    _ref = ""
    if args.reference:
        with open(args.reference, encoding="utf-8") as f:
            _ref = f.read()

    if args.no_llm:
        res = check_without_llm(_audit, _analysis, _ref)
        py, cv = res["numeric_check"], res["coverage"]
        print(
            f"Chiffres vérifiés : {py['verified']}/{py['checked']} (score {py['score']}/10)"
        )
        for fl in py["failed"]:
            print(f"  ✗ {fl['value']:>14}  [{fl['reason']}] {fl['line'][:110]}")
        for w in py["warnings"]:
            print(
                f"  ? {w['value']:>14}  [héritage du titre → {w['found_in_tables']}] {w['line'][:90]}"
            )
        print(
            f"\nAnomalies citées : {cv['covered']}/{cv['total']} (+{cv['partial']} partielles) "
            f"(score {cv['score']}/10)"
        )
        for m in cv["missed"]:
            print(f"  ✗ {m['table']}.{m.get('column') or '(doublons)'} : {m['detail']}")
        sys.exit(0)

    out = evaluate_analysis(_audit, _analysis, model=args.model, reference=_ref)
    print(format_evaluation_report(out))
