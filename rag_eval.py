"""
rag_eval.py — Métriques de qualité RAG (Priorité P2)

Calcule P@k, R@k, NDCG@k et RR@k pour évaluer la qualité
du pipeline de retrieval de rag.py, et compare trois modes de recherche :
sémantique, lexical (BM25) et hybride (fusion normalisée, celle utilisée par l'application).

Références cours :
- Lecture 7, Section 3 : How good is the retrieval, really?
"""

import random
import re
from typing import Optional

import numpy as np
import requests

# ============================================================
# MÉTRIQUES INDIVIDUELLES
# ============================================================


def precision_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    """
    P@k = |R ∩ T_k| / k

    Des k chunks retournés, quelle fraction est pertinente ?

    Args:
        retrieved_ids : liste des IDs retournés, ordonnés par score décroissant
        relevant_ids  : ensemble des IDs réellement pertinents
        k             : nombre de résultats à considérer

    Returns:
        float in [0, 1]
    """
    if k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / k


def recall_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    """
    R@k = |R ∩ T_k| / |R|

    Des chunks pertinents existants, quelle fraction a été retrouvée ?

    Args:
        retrieved_ids : liste des IDs retournés, ordonnés par score décroissant
        relevant_ids  : ensemble des IDs réellement pertinents
        k             : nombre de résultats à considérer

    Returns:
        float in [0, 1], 0.0 si relevant_ids est vide
    """
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / len(relevant_ids)


def dcg_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    """
    DCG@k = Σ rel_i / log2(i+2) pour i in range(k)

    (i+2 car i est 0-indexé → position réelle = i+1, log2(i+1+1) = log2(i+2))
    """
    return sum(
        1.0 / np.log2(i + 2)
        for i, doc_id in enumerate(retrieved_ids[:k])
        if doc_id in relevant_ids
    )


def ndcg_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    """
    NDCG@k = DCG@k / IDCG@k

    Récompense les chunks pertinents en tête de liste.
    IDCG@k = DCG du classement idéal (tous les pertinents en premier).

    Args:
        retrieved_ids : liste des IDs retournés, ordonnés par score décroissant
        relevant_ids  : ensemble des IDs réellement pertinents
        k             : nombre de résultats à considérer

    Returns:
        float in [0, 1]
    """
    actual_dcg = dcg_at_k(retrieved_ids, relevant_ids, k)
    # Classement idéal : min(|R|, k) pertinents en tête
    ideal_count = min(len(relevant_ids), k)
    ideal_dcg = sum(1.0 / np.log2(i + 2) for i in range(ideal_count))
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0


def reciprocal_rank_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    """
    RR@k = 1/r si un chunk pertinent apparaît à la position r ≤ k, sinon 0.

    Position du premier chunk pertinent retrouvé.

    Args:
        retrieved_ids : liste des IDs retournés, ordonnés par score décroissant
        relevant_ids  : ensemble des IDs réellement pertinents
        k             : nombre de résultats à considérer

    Returns:
        float in [0, 1]
    """
    for i, doc_id in enumerate(retrieved_ids[:k]):
        if doc_id in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


# ============================================================
# JEU DE TEST AUTOMATIQUE (vérité terrain synthétique)
# ============================================================
#
# Calculer P@k / R@k / NDCG@k exige de savoir quels passages sont pertinents pour
# chaque requête. Sans annotation humaine, on construit un jeu de test synthétique :
# on tire des passages au hasard et, pour chacun, on forme une question à laquelle
# CE passage répond. Le passage d'origine est alors le passage pertinent.
#   - question générée par le modèle Ollama (reformulation : teste surtout le sémantique) ;
#   - à défaut, extrait du passage (teste surtout le lexical : favorise BM25).
# Ces chiffres mesurent donc la capacité à retrouver un passage, pas la qualité
# d'annotations humaines : à lire comme un indicateur de comparaison entre modes.


def _excerpt_query(text: str, max_chars: int = 220) -> str:
    """Requête de repli : une phrase du milieu du passage."""
    sentences = [
        x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if len(x.strip()) > 30
    ]
    if not sentences:
        return text[:max_chars]
    sentence = sentences[len(sentences) // 2]
    return sentence[:max_chars]


def _llm_question(text: str, model: Optional[str]) -> Optional[str]:
    """Demande au modèle Ollama une question à laquelle le passage répond."""
    from config import OLLAMA_URL, MODEL

    prompt = (
        "Voici un passage d'un document :\n\n" + text[:1500] + "\n\n"
        "Écris UNE seule question courte à laquelle ce passage répond. "
        "Ne recopie pas une phrase du passage, reformule avec tes propres mots. "
        "Réponds uniquement par la question."
    )
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": model or MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=180,
        )
        r.raise_for_status()
        q = r.json()["message"]["content"].strip().splitlines()[0].strip(' "«»')
        return q if 10 <= len(q) <= 300 else None
    except Exception:
        return None


def build_auto_cases(
    n_queries: int = 8,
    use_llm: bool = True,
    model: Optional[str] = None,
    seed: int = 42,
) -> dict:
    """
    Construit des cas de test à partir des passages indexés.

    Returns:
        {"cases": [{"query", "relevant_chunk_ids", "source"}], "n_chunks": int}
        ou {"error": "..."} si aucun document n'est indexé.
    """
    try:
        from rag import _flat
    except ImportError as e:
        return {"error": f"Impossible d'importer rag.py : {e}"}

    items, _ = _flat()
    # Passages assez longs pour porter une information précise
    candidates = [i for i, it in enumerate(items) if len(it["text"]) >= 200]
    if not candidates:
        return {
            "error": "Aucun document PDF indexé (ou passages trop courts) : ajoutez des PDF."
        }

    rng = random.Random(seed)
    chosen = rng.sample(candidates, min(n_queries, len(candidates)))

    cases = []
    for idx in chosen:
        text = items[idx]["text"]
        question = _llm_question(text, model) if use_llm else None
        cases.append(
            {
                "query": question or _excerpt_query(text),
                "relevant_chunk_ids": {idx},
                "source": "llm" if question else "excerpt",
            }
        )
    return {"cases": cases, "n_chunks": len(items)}


# ============================================================
# CLASSEMENTS PAR MODE
# ============================================================


def _rankings(queries: list, alpha: float) -> dict:
    """
    Pour chaque mode, retourne la matrice (requêtes x passages) des scores.
    Même calcul que rag.score_queries (normalisation min-max puis fusion),
    mais les trois modes sont calculés en une seule passe d'embeddings.
    """
    from rag import _flat, embed, _bm25, tokens, minmax

    items, matrix = _flat()
    bm25 = np.array([_bm25(tokens(q), items) for q in queries])
    out = {"bm25": bm25}

    if matrix is not None and len(matrix) == len(items):
        cos = embed(queries, "query") @ matrix.T
        out["semantic"] = cos
        out["hybrid"] = alpha * np.array([minmax(r) for r in cos]) + (
            1 - alpha
        ) * np.array([minmax(r) for r in bm25])
    return out


def _order(row) -> list:
    """Indices triés par score décroissant (tri stable : départage reproductible)."""
    return [int(i) for i in np.argsort(-np.asarray(row), kind="stable")]


def _metrics(retrieved: list, relevant: set, k: int) -> dict:
    return {
        "P": precision_at_k(retrieved, relevant, k),
        "R": recall_at_k(retrieved, relevant, k),
        "NDCG": ndcg_at_k(retrieved, relevant, k),
        "RR": reciprocal_rank_at_k(retrieved, relevant, k),
    }


# ============================================================
# ÉVALUATION COMPLÈTE
# ============================================================


def evaluate_modes(cases: list, k: int = 4, alpha: Optional[float] = None) -> dict:
    """
    Évalue les modes semantic / bm25 / hybrid sur des cas annotés.

    Args:
        cases : [{"query": str, "relevant_chunk_ids": set|list, ...}, ...]
        k     : nombre de résultats considérés
        alpha : poids du sémantique dans le mode hybride (défaut : config.RAG_HYBRID_ALPHA)

    Returns:
        {"k", "alpha", "n_queries", "n_chunks", "semantic_available",
         "modes": {mode: {"P", "R", "NDCG", "RR"}},   # moyennes
         "details": [{"query", "relevant", "source", "ranks": {mode: rang du 1er pertinent}}]}
    """
    try:
        from config import RAG_HYBRID_ALPHA
        from rag import _flat
    except ImportError as e:
        return {"error": f"Impossible d'importer rag.py : {e}"}

    alpha = RAG_HYBRID_ALPHA if alpha is None else alpha
    items, _ = _flat()
    if not items:
        return {"error": "Aucun document PDF indexé."}
    if not cases:
        return {"error": "Aucun cas de test."}

    queries = [c["query"] for c in cases]
    scores = _rankings(queries, alpha)

    per_mode = {m: {"P": [], "R": [], "NDCG": [], "RR": []} for m in scores}
    details = []

    for q, case in enumerate(cases):
        relevant = set(case["relevant_chunk_ids"])
        ranks = {}
        for mode, matrix in scores.items():
            retrieved = _order(matrix[q])
            for name, value in _metrics(retrieved, relevant, k).items():
                per_mode[mode][name].append(value)
            # rang (à partir de 1) du premier passage pertinent, quel que soit k
            ranks[mode] = next(
                (r + 1 for r, i in enumerate(retrieved) if i in relevant), None
            )
        details.append(
            {
                "query": case["query"],
                "relevant": sorted(relevant),
                "source": case.get("source", "manuel"),
                "ranks": ranks,
            }
        )

    return {
        "k": k,
        "alpha": alpha,
        "n_queries": len(cases),
        "n_chunks": len(items),
        "semantic_available": "semantic" in scores,
        "modes": {
            mode: {name: round(float(np.mean(vals)), 4) for name, vals in m.items()}
            for mode, m in per_mode.items()
        },
        "details": details,
    }


def evaluate_rag(
    queries_with_ground_truth: list,
    k: int = 4,
    verbose: bool = False,
    mode: str = "hybrid",
) -> dict:
    """
    Évalue un seul mode ("hybrid" par défaut) : moyennes de P@k, R@k, NDCG@k, RR@k.
    Conservée pour compatibilité ; evaluate_modes() compare les trois modes.
    """
    result = evaluate_modes(queries_with_ground_truth, k)
    if "error" in result:
        return result
    mode = mode if mode in result["modes"] else "bm25"
    m = result["modes"][mode]
    if verbose:
        for d in result["details"]:
            print(
                f"Query : {d['query'][:60]}...  rang du 1er pertinent ({mode}) : {d['ranks'].get(mode)}"
            )
    return {
        "mode": mode,
        f"mean_P@{k}": m["P"],
        f"mean_R@{k}": m["R"],
        f"mean_NDCG@{k}": m["NDCG"],
        f"mean_RR@{k}": m["RR"],
        "n_queries": result["n_queries"],
        "k": k,
        "details": result["details"],
    }


def compare_semantic_vs_bm25(queries_with_ground_truth: list, k: int = 4) -> dict:
    """Compare sémantique, BM25 et hybride (nom conservé pour compatibilité)."""
    result = evaluate_modes(queries_with_ground_truth, k)
    if "error" in result:
        return result
    return {
        "k": k,
        "n_queries": result["n_queries"],
        **{
            mode: {
                f"mean_P@{k}": m["P"],
                f"mean_R@{k}": m["R"],
                f"mean_NDCG@{k}": m["NDCG"],
                f"mean_RR@{k}": m["RR"],
            }
            for mode, m in result["modes"].items()
        },
    }


# ============================================================
# CLI — TEST RAPIDE (nécessite des PDF indexés dans le même processus)
# ============================================================

if __name__ == "__main__":
    import json

    # Vérification des métriques sur un exemple connu
    retrieved = [3, 0, 7, 1]
    relevant = {0, 3}
    print("P@4   =", precision_at_k(retrieved, relevant, 4), "(attendu 0.5)")
    print("R@4   =", recall_at_k(retrieved, relevant, 4), "(attendu 1.0)")
    print("RR@4  =", reciprocal_rank_at_k(retrieved, relevant, 4), "(attendu 1.0)")
    print("NDCG@4=", round(ndcg_at_k(retrieved, relevant, 4), 4), "(attendu 1.0)")
    print(
        "\nPour évaluer vos PDF, utilisez le bouton « Évaluer la recherche » de l'application."
    )
