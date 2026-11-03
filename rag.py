# Module RAG : lit les PDF, les découpe en passages, les indexe et retrouve les passages utiles.
# Recherche HYBRIDE : chaque passage reçoit simultanément
#   - un score sémantique : embeddings Ollama (modèle EMBED_MODEL) + similarité cosinus ;
#   - un score lexical    : BM25 simplifié ;
# les deux scores sont normalisés (min-max, entre 0 et 1) puis combinés :
#   score = alpha * sémantique + (1 - alpha) * lexical        (alpha = RAG_HYBRID_ALPHA)
# Si les embeddings sont indisponibles, la recherche retombe sur le score lexical seul (mode "keywords").

# Importation de io pour lire un PDF depuis des octets en mémoire
import io

# Importation de re pour les expressions régulières (nettoyage, découpage, mots)
import re

# Importation de threading pour protéger la mémoire partagée entre requêtes
import threading

# Importation de unicodedata pour retirer les accents (recherche par mots-clés)
import unicodedata

# Importation de Counter pour compter les mots
from collections import Counter

# Importation de numpy pour les calculs de similarité sur les vecteurs
import numpy as np

# Importation de requests pour appeler l'API d'embeddings d'Ollama
import requests

# Importation de PdfReader pour extraire le texte des PDF
from pypdf import PdfReader

# Importation des paramètres de configuration
import config as _config
from config import (
    OLLAMA_EMBED_URL,
    EMBED_MODEL,
    RAG_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
    RAG_TOP_K,
    RAG_MAX_CHARS,
)

# Réglages de la recherche hybride et des requêtes : lus dans config.py s'ils y sont,
# sinon valeurs par défaut ci-dessous (config.py n'a donc pas besoin d'être modifié)
# Poids du score sémantique dans la fusion (1.0 = sémantique seul, 0.0 = BM25 seul)
RAG_HYBRID_ALPHA = float(getattr(_config, "RAG_HYBRID_ALPHA", 0.6))
# Score hybride minimal (0-1) pour retenir un passage
RAG_MIN_HYBRID_SCORE = float(getattr(_config, "RAG_MIN_HYBRID_SCORE", 0.35))
# Nombre maximal de requêtes par table, plafond global, colonnes citées par requête de structure
RAG_QUERIES_PER_TABLE = int(getattr(_config, "RAG_QUERIES_PER_TABLE", 8))
RAG_MAX_QUERIES = int(getattr(_config, "RAG_MAX_QUERIES", 80))
RAG_QUERY_COLUMNS = int(getattr(_config, "RAG_QUERY_COLUMNS", 10))

# Nombre maximal de passages conservés par document (évite des embeddings interminables)
MAX_CHUNKS_PER_DOC = 4000
# Nombre de passages envoyés à Ollama en une seule requête d'embeddings
EMBED_BATCH = 16
# Similarité minimale (cosinus) pour garder un passage en mode sémantique
MIN_SEMANTIC_SCORE = 0.30

# Verrou : un seul accès à la fois à la mémoire des documents
lock = threading.RLock()

# Mémoire des documents : {nom: {"pages": n, "chunks": [...], "vectors": matrice ou None}}
# Chaque passage : {"page": numéro, "text": texte, "tf": Counter, "len": nb de mots}
DOCS = {}


# ============================================================
# EXTRACTION ET DECOUPAGE
# ============================================================


def normalize_text(text):
    # Nettoie le texte brut d'une page PDF
    text = text.replace("\r", "")
    # Recolle les mots coupés par un tiret en fin de ligne
    text = re.sub(r"-\n(?=\w)", "", text)
    # Réduit les espaces et tabulations multiples
    text = re.sub(r"[ \t]+", " ", text)
    # Un retour à la ligne simple devient un espace (les paragraphes sont conservés)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # Réduit les lignes vides multiples
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _flush(chunks, current, unit, size, overlap):
    # Ajoute une unité (phrase) au passage courant ; clôt le passage s'il dépasse la taille
    if current and len(current) + 1 + len(unit) > size:
        chunks.append(current.strip())
        # Le passage suivant reprend la fin du précédent (chevauchement) à partir d'un mot entier
        tail = current[-overlap:] if overlap else ""
        if " " in tail:
            tail = tail[tail.find(" ") + 1 :]
        current = tail
    return (current + " " + unit).strip()


def split_text(text, size, overlap):
    # Découpe un texte en passages d'environ `size` caractères, avec chevauchement
    units = [u.strip() for u in re.split(r"(?<=[.!?;:])\s+|\n{2,}", text) if u.strip()]
    chunks, current = [], ""
    for unit in units:
        # Une phrase plus longue qu'un passage est coupée à un espace
        while len(unit) > size:
            cut = unit.rfind(" ", 0, size)
            cut = cut if cut > size * 0.5 else size
            piece, unit = unit[:cut], unit[cut:].strip()
            current = _flush(chunks, current, piece, size, overlap)
        current = _flush(chunks, current, unit, size, overlap)
    if current.strip():
        chunks.append(current.strip())
    return chunks


# Mots très fréquents ignorés par la recherche par mots-clés
STOP = set(
    "le la les un une des du de d l et ou en au aux a est sont dans pour par sur avec que qui "
    "ne pas ce cette ces se sa son ses leur leurs il elle ils elles on plus où the of and to in is".split()
)


def tokens(text):
    # Découpe un texte en mots sans accents, en minuscules, sans mots vides
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-z0-9]{2,}", t) if w not in STOP]


# ============================================================
# EMBEDDINGS OLLAMA
# ============================================================


def embed(texts, kind):
    # Transforme des textes en vecteurs normalisés via Ollama
    # kind = "document" (passages) ou "query" (questions de recherche)

    # Le modèle nomic-embed-text donne de meilleurs résultats avec ces préfixes
    prefix = ""
    if "nomic" in EMBED_MODEL.lower():
        prefix = "search_document: " if kind == "document" else "search_query: "

    vectors = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = [prefix + t for t in texts[i : i + EMBED_BATCH]]
        response = requests.post(
            OLLAMA_EMBED_URL, json={"model": EMBED_MODEL, "input": batch}, timeout=600
        )
        response.raise_for_status()
        vectors.extend(response.json()["embeddings"])

    matrix = np.array(vectors, dtype="float32")
    # Normalise chaque vecteur : le produit scalaire devient alors la similarité cosinus
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms


def embed_error(e):
    # Traduit une erreur d'embeddings en message clair
    if isinstance(e, requests.exceptions.ConnectionError):
        return "Ollama est inaccessible"
    if (
        isinstance(e, requests.exceptions.HTTPError)
        and e.response is not None
        and e.response.status_code == 404
    ):
        return f"modèle d'embeddings absent (ollama pull {EMBED_MODEL})"
    return str(e)[:150]


# ============================================================
# AJOUT / SUPPRESSION DE DOCUMENTS
# ============================================================


def ingest(name, data):
    # Lit un PDF (octets), le découpe, calcule les embeddings et l'enregistre en mémoire

    try:
        reader = PdfReader(io.BytesIO(data))
        # PDF protégé : tente un mot de passe vide, sinon refuse
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF protégé par un mot de passe.")
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except ValueError:
        raise
    except Exception:
        # Fichier qui n'est pas un vrai PDF, tronqué ou corrompu
        raise ValueError("PDF illisible ou corrompu.")

    chunks = []
    for number, raw_text in enumerate(pages_text, start=1):
        text = normalize_text(raw_text)
        for piece in split_text(text, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP):
            words = tokens(piece)
            chunks.append(
                {
                    "page": number,
                    "text": piece,
                    "tf": Counter(words),
                    "len": max(1, len(words)),
                }
            )

    # Aucun texte : PDF scanné (image) ou vide
    if not chunks:
        raise ValueError(
            "Aucun texte exploitable (PDF scanné ou vide ? il faudrait de l'OCR)."
        )

    # Limite le nombre de passages d'un document très volumineux
    chunks = chunks[:MAX_CHUNKS_PER_DOC]

    # Calcule les embeddings ; en cas d'échec, le document reste utilisable en mode mots-clés
    vectors, warning = None, None
    try:
        vectors = embed([c["text"] for c in chunks], "document")
    except Exception as e:
        warning = (
            "Embeddings indisponibles ("
            + embed_error(e)
            + ") : recherche par mots-clés."
        )

    with lock:
        DOCS[name] = {"pages": len(reader.pages), "chunks": chunks, "vectors": vectors}

    return {
        "name": name,
        "pages": len(reader.pages),
        "chunks": len(chunks),
        "warning": warning,
    }


def remove(name=None):
    # Retire un document (ou tous si name est vide)
    with lock:
        if name:
            DOCS.pop(name, None)
        else:
            DOCS.clear()


def docs_info():
    # Résumé des documents en mémoire pour l'interface
    with lock:
        docs = [
            {
                "name": n,
                "pages": d["pages"],
                "chunks": len(d["chunks"]),
                "semantic": d["vectors"] is not None,
            }
            for n, d in DOCS.items()
        ]
        mode = None
        if docs:
            mode = "hybrid" if all(d["semantic"] for d in docs) else "keywords"
    return {
        "docs": docs,
        "mode": mode,
        "embed_model": EMBED_MODEL,
        "alpha": RAG_HYBRID_ALPHA,
    }


# ============================================================
# RECHERCHE
# ============================================================


def table_queries(table, data):
    # Requêtes d'UNE table, de la plus importante à la moins importante.
    # Toutes les rubriques de l'audit sont exploitées :
    #   structure, statistiques numériques, valeurs manquantes, doublons,
    #   valeurs négatives, cardinalité (colonnes constantes, identifiants).
    # Seuls des noms (tables, colonnes) et des mots-clés servent de requête, jamais les valeurs chiffrées :
    # les chiffres servent uniquement à DECIDER quelles requêtes créer.
    # Une rubrique absente ou vide ne produit aucune requête.
    queries = []
    structure = data.get("structure") or {}

    # 1. Structure : nom de la table et de ses colonnes
    columns = [c.get("column_name", "") for c in structure.get("schema", [])]
    columns = [c for c in columns if c]
    if columns:
        queries.append(f"{table} : " + ", ".join(columns[:RAG_QUERY_COLUMNS]))

    # 2. Colonnes numériques : cherche unités, plages et seuils attendus
    stats = [x for x in data.get("numeric_statistics") or [] if x.get("column")]
    if stats:
        names = ", ".join(x["column"] for x in stats[:RAG_QUERY_COLUMNS])
        queries.append(
            f"{table} colonnes numériques : {names} unité plage de valeurs minimum maximum seuil"
        )

    # Colonnes avec valeurs manquantes (les pires d'abord)
    missing = [m for m in data.get("missing_values") or [] if m.get("missing", 0) > 0]
    missing.sort(key=lambda m: m.get("missing_percent", 0), reverse=True)
    missing = [f"{m.get('column')} {table} valeurs manquantes" for m in missing]

    # Doublons
    duplicates = []
    if (data.get("duplicates") or {}).get("duplicates", 0):
        duplicates.append(f"{table} doublons lignes en double")

    # Valeurs négatives (les plus nombreuses d'abord)
    negatives = [
        n for n in data.get("negative_values") or [] if n.get("negative_values", 0) > 0
    ]
    negatives.sort(key=lambda n: n.get("negative_values", 0), reverse=True)
    negatives = [f"{n.get('column')} {table} valeurs négatives" for n in negatives]

    # Valeurs aberrantes probables : extrêmes très éloignés de la moyenne (plus de 5 écarts-types)
    outliers = []
    for x in stats:
        mean, std = x.get("mean"), x.get("stddev")
        if None in (mean, std) or not std:
            continue
        spread = (
            max(abs((x.get("max") or mean) - mean), abs(mean - (x.get("min") or mean)))
            / std
        )
        if spread > 5:
            outliers.append(
                (
                    spread,
                    f"{x['column']} {table} valeurs aberrantes extrêmes plage attendue",
                )
            )
    outliers = [q for _, q in sorted(outliers, reverse=True)]

    # Cardinalité : colonnes constantes (une seule valeur) et identifiants (toutes les valeurs différentes)
    n_rows = structure.get("rows") or 0
    cardinality = data.get("cardinality") or []
    constants = [
        f"{c['column']} {table} valeur constante unique"
        for c in cardinality
        if c.get("distinct_values") == 1
    ]
    identifiers = [
        f"{c['column']} {table} identifiant unique clé"
        for c in cardinality
        if n_rows > 1 and c.get("distinct_values") == n_rows
    ]

    # Alternance entre types d'anomalies : une table qui cumule tout n'est pas
    # réduite à un seul type de problème quand la place manque
    groups = (missing, duplicates, negatives, outliers, constants, identifiers)
    for i in range(max(len(g) for g in groups)):
        for group in groups:
            if i < len(group):
                queries.append(group[i])

    return queries[:RAG_QUERIES_PER_TABLE]


def build_queries(audit, context=""):
    # Construit les questions de recherche à partir de l'audit et du contexte saisi.
    #   1. requêtes fixes : contexte métier, règles de qualité générales (jamais sacrifiées) ;
    #   2. requêtes des tables en TOUR DE ROLE : la 1re de chaque table (sa structure),
    #      puis la 2e de chaque table, etc. Aucune table n'est favorisée, quel que soit leur nombre.
    fixed = []
    if context and context.strip():
        fixed.append(context.strip()[:400])
    fixed.append(
        "règles de qualité des données, seuils, valeurs attendues, définitions des variables"
    )

    per_table = [table_queries(table, data) for table, data in audit.items()]
    rounds = [
        q[i] for i in range(RAG_QUERIES_PER_TABLE) for q in per_table if len(q) > i
    ]

    # Plafond proportionnel au nombre de tables, borné par RAG_MAX_QUERIES,
    # mais jamais en dessous d'une requête par table : toutes les tables sont toujours couvertes
    cap = min(RAG_MAX_QUERIES, len(fixed) + RAG_QUERIES_PER_TABLE * len(audit))
    cap = max(cap, len(fixed) + len(audit))
    return (fixed + rounds)[:cap]


def _flat():
    # Aplatit tous les passages de tous les documents (copie sous verrou)
    with lock:
        items, matrices, complete = [], [], True
        for name, d in DOCS.items():
            for i, c in enumerate(d["chunks"]):
                items.append(
                    {
                        "doc": name,
                        "page": c["page"],
                        "text": c["text"],
                        "tf": c["tf"],
                        "len": c["len"],
                    }
                )
            if d["vectors"] is None:
                complete = False
            else:
                matrices.append(d["vectors"])
        matrix = np.vstack(matrices) if complete and matrices else None
    return items, matrix


def _bm25(query_tokens, items):
    # Score BM25 simplifié de chaque passage pour une requête
    n = len(items)
    avg = sum(i["len"] for i in items) / n
    df = Counter()
    for i in items:
        df.update(i["tf"].keys())
    scores = np.zeros(n, dtype="float32")
    for t in set(query_tokens):
        if t not in df:
            continue
        idf = np.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
        for k, i in enumerate(items):
            tf = i["tf"].get(t, 0)
            if tf:
                scores[k] += (
                    idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * i["len"] / avg))
                )
    return scores


def minmax(scores):
    # Normalise un vecteur de scores entre 0 et 1 (le pire passage = 0, le meilleur = 1)
    # Si tous les scores sont égaux (ex : aucun mot en commun), tout vaut 0 : pas de faux signal
    s = np.asarray(scores, dtype="float32")
    if s.size == 0:
        return s
    low, high = float(s.min()), float(s.max())
    if high - low < 1e-9:
        return np.zeros_like(s)
    return (s - low) / (high - low)


def score_queries(queries, items, matrix, mode="hybrid", alpha=None):
    # Calcule, pour chaque requête, un score par passage.
    # mode : "hybrid" (défaut), "semantic" ou "bm25" (les deux derniers servent à l'évaluation).
    # Retourne un dict :
    #   scores : matrice (requêtes x passages) des scores finaux, entre 0 et 1
    #   cos    : similarités cosinus brutes (ou None si les embeddings sont indisponibles)
    #   bm25   : scores BM25 bruts
    #   mode   : mode réellement utilisé ("hybrid", "semantic", "bm25" ou "keywords" en repli)
    alpha = RAG_HYBRID_ALPHA if alpha is None else min(1.0, max(0.0, float(alpha)))

    # Score lexical brut, puis normalisé (une requête = une ligne)
    bm25 = np.array([_bm25(tokens(q), items) for q in queries])
    lexical = np.array([minmax(row) for row in bm25])

    # Score sémantique brut (cosinus) si tous les documents ont des vecteurs
    cos = None
    if mode != "bm25" and matrix is not None and len(matrix) == len(items):
        try:
            cos = embed(queries, "query") @ matrix.T
        except Exception as e:
            print(
                "RAG : embeddings indisponibles pour la recherche (",
                embed_error(e),
                ") -> mots-clés",
            )

    # Repli : sans embeddings (ou mode bm25 demandé), seul le score lexical compte
    if cos is None:
        return {
            "scores": lexical,
            "cos": None,
            "bm25": bm25,
            "mode": "bm25" if mode == "bm25" else "keywords",
        }

    semantic = np.array([minmax(row) for row in cos])

    if mode == "semantic":
        return {"scores": semantic, "cos": cos, "bm25": bm25, "mode": "semantic"}

    # Fusion : combinaison linéaire des deux scores normalisés
    return {
        "scores": alpha * semantic + (1 - alpha) * lexical,
        "cos": cos,
        "bm25": bm25,
        "mode": "hybrid",
    }


def retrieve_for_audit(audit, context=""):
    # Retourne les passages de PDF les plus utiles pour interpréter cet audit
    items, matrix = _flat()
    if not items:
        return []

    queries = build_queries(audit, context)
    sc = score_queries(queries, items, matrix, "hybrid")
    scores, cos, bm25, used = sc["scores"], sc["cos"], sc["bm25"], sc["mode"]

    # Garde les meilleurs passages de chaque requête, puis le meilleur score par passage
    best = {}
    for q, row in enumerate(scores):
        for idx in np.argsort(row)[::-1][:RAG_TOP_K]:
            score = float(row[idx])
            if used == "hybrid":
                # Garde-fou : le score est relatif (min-max), il faut aussi un vrai signal absolu :
                # une similarité cosinus suffisante OU au moins un mot en commun
                keep = score >= RAG_MIN_HYBRID_SCORE and (
                    cos[q, idx] >= MIN_SEMANTIC_SCORE or bm25[q, idx] > 0
                )
            else:
                keep = bm25[q, idx] >= 0.01
            if keep:
                best[idx] = max(best.get(idx, 0), score)

    # Respecte la taille maximale, en gardant d'abord les plus pertinents
    chosen, total = [], 0
    for idx in sorted(best, key=best.get, reverse=True):
        size = len(items[idx]["text"])
        if total + size > RAG_MAX_CHARS and chosen:
            continue
        chosen.append(idx)
        total += size

    # Remet les passages dans l'ordre document / page pour une lecture naturelle
    chosen.sort(key=lambda i: (items[i]["doc"], items[i]["page"], i))
    return [
        {
            "doc": items[i]["doc"],
            "page": items[i]["page"],
            "text": items[i]["text"],
            "score": best[i],
            "mode": used,
        }
        for i in chosen
    ]


# ============================================================
# MISE EN FORME POUR LE PROMPT
# ============================================================


def format_block(passages):
    # Texte ajouté au contexte métier : extraits numérotés + règles d'utilisation
    lines = [
        "EXTRAITS DE DOCUMENTS PDF FOURNIS PAR L'UTILISATEUR (recherche automatique, RAG) :",
        "",
    ]
    for n, p in enumerate(passages, start=1):
        lines.append(f"[{n}] {p['doc']}, p. {p['page']} :\n{p['text']}\n")
    lines.append(
        "Règles d'usage de ces extraits :\n"
        "- Ils servent à interpréter les résultats de l'audit (définitions, seuils, règles métier, objectifs).\n"
        "- Quand tu t'appuies sur un extrait, cite-le entre crochets, par exemple [1] ou [nom.pdf, p. 3].\n"
        "- Les valeurs chiffrées d'un extrait peuvent être citées avec leur source ; les résultats de l'audit "
        "restent la seule source pour les valeurs calculées sur les données.\n"
        "- Si un extrait contredit un résultat de l'audit, signale-le explicitement au lieu de choisir.\n"
        "- Si les extraits ne contiennent rien de pertinent, dis-le et analyse uniquement les résultats.\n"
        "- N'invente rien qui ne figure ni dans les extraits ni dans les résultats."
    )
    return "\n".join(lines)


def sources_summary(passages):
    # Liste lisible des sources utilisées : "fichier.pdf (p. 2, 5)"
    pages = {}
    for p in passages:
        pages.setdefault(p["doc"], set()).add(p["page"])
    return [
        f"{doc} (p. {', '.join(str(n) for n in sorted(nums))})"
        for doc, nums in pages.items()
    ]
