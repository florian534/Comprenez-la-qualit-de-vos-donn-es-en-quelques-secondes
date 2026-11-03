"""
qa_eval.py — Évaluation pass@k du chatbot SQL (Priorité P3)

Évalue objectivement la fiabilité du chatbot SQL de qa.py
en utilisant la métrique pass@k.

Références cours :
- Lecture 6, Section 3.2 : The pass@k metric
"""

import json
import re
import time
from math import comb
from typing import Callable, Optional

# ============================================================
# FORMULE PASS@K
# ============================================================


def pass_at_k(n: int, c: int, k: int) -> float:
    """
    Formule exacte de pass@k (Lecture 6, eq. pass@k).

    Probabilité qu'au moins une parmi k tentatives tirées au sort
    parmi n soit correcte, sachant que c sont correctes.

    pass@k = 1 - C(n-c, k) / C(n, k)

    Args:
        n : nombre total de tentatives effectuées
        c : nombre de tentatives correctes parmi n
        k : nombre de tentatives sélectionnées

    Returns:
        float in [0.0, 1.0]

    Exemples :
        pass_at_k(10, 5, 1)  → 0.5   (50% de chance sur 1 essai)
        pass_at_k(10, 5, 3)  → 0.917 (91.7% de chance sur 3 essais)
        pass_at_k(10, 10, 1) → 1.0   (toujours correct)
        pass_at_k(10, 0, 3)  → 0.0   (jamais correct)
    """
    if n <= 0:
        raise ValueError(f"n doit être > 0, reçu : {n}")
    if not (0 <= c <= n):
        raise ValueError(f"c doit être dans [0, n], reçu c={c}, n={n}")
    if k <= 0:
        raise ValueError(f"k doit être > 0, reçu : {k}")

    # Si k > n-c, toute sélection de k inclut au moins 1 correct
    if k > n - c:
        return 1.0

    # Formule exacte avec combinaisons
    numerator = comb(n - c, k)
    denominator = comb(n, k)

    if denominator == 0:
        return 0.0

    return 1.0 - numerator / denominator


def consistency_at_k(n: int, c: int, k: int) -> float:
    """
    cons@k = probabilité que TOUTES les k tentatives soient correctes.

    cons@k = C(c, k) / C(n, k)

    Complémentaire de pass@k : mesure la robustesse (pas juste la chance).

    Args:
        n : nombre total de tentatives
        c : nombre de tentatives correctes
        k : nombre de tentatives sélectionnées

    Returns:
        float in [0.0, 1.0]
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c < k:
        return 0.0  # impossible d'avoir k corrects si c < k

    denominator = comb(n, k)
    if denominator == 0:
        return 0.0

    return comb(c, k) / denominator


# ============================================================
# ÉVALUATION D'UN CAS DE TEST
# ============================================================


def _run_single_case(
    question: str,
    verify_fn: Callable[[str], bool],
    n_attempts: int,
    model: Optional[str],
    delay_between_attempts: float = 0.5,
) -> dict:
    """
    Exécute n_attempts appels à ask_data() pour une question donnée.

    Args:
        question               : question en langage naturel
        verify_fn              : fonction qui retourne True si la réponse est correcte
        n_attempts             : nombre de tentatives
        model                  : modèle Ollama à utiliser
        delay_between_attempts : délai en secondes entre chaque appel

    Returns:
        dict avec les résultats détaillés
    """
    try:
        from qa import ask_data
    except ImportError as e:
        return {"error": f"Impossible d'importer qa.py : {e}"}

    correct = 0
    attempts = []
    errors = []

    for i in range(n_attempts):
        attempt_result = {
            "attempt": i + 1,
            "correct": False,
            "answer": "",
            "error": None,
        }

        try:
            result = ask_data(question, model=model)
            answer = result.get("answer", "")
            attempt_result["answer"] = answer[:500]  # tronque pour le log

            if verify_fn(answer):
                correct += 1
                attempt_result["correct"] = True

        except Exception as e:
            attempt_result["error"] = str(e)
            errors.append(str(e))

        attempts.append(attempt_result)

        # Délai entre les appels pour éviter la surcharge
        if i < n_attempts - 1:
            time.sleep(delay_between_attempts)

    # Toutes les tentatives ont planté (Ollama arrêté, modèle absent...) :
    # ce n'est pas « 0 % de réussite », c'est une mesure impossible
    if errors and len(errors) == n_attempts:
        return {"error": f"Toutes les tentatives ont échoué : {errors[0]}"}

    return {
        "question": question,
        "n_attempts": n_attempts,
        "correct": correct,
        "attempts": attempts,
        "errors": errors,
    }


# ============================================================
# ÉVALUATION COMPLÈTE
# ============================================================


def evaluate_qa_passk(
    test_cases: list,
    k: int = 3,
    n_attempts: Optional[int] = None,
    model: Optional[str] = None,
    verbose: bool = False,
    delay: float = 0.5,
) -> dict:
    """
    Évalue le chatbot SQL sur un ensemble de cas de test.

    Args:
        test_cases : liste de dicts :
            [
                {
                    "question":  "Combien de clients ont un email NULL ?",
                    "verify_fn": lambda answer: "42" in answer,
                    "description": "Test valeurs manquantes email"  # optionnel
                },
                ...
            ]
        k          : nombre de tentatives à sélectionner pour pass@k
        n_attempts : nombre total de tentatives par question (>= k, défaut = k)
        model      : modèle Ollama à utiliser
        verbose    : affiche la progression
        delay      : délai en secondes entre les appels

    Returns:
        dict avec les résultats détaillés et les moyennes globales
    """
    # n_attempts >= k (on a besoin d'au moins k tentatives)
    n = n_attempts if n_attempts and n_attempts >= k else k

    results = []

    for idx, case in enumerate(test_cases):
        question = case["question"]
        verify_fn = case["verify_fn"]
        description = case.get("description", question[:50])

        if verbose:
            print(f"[{idx+1}/{len(test_cases)}] {description}...")

        # Exécution des tentatives
        run = _run_single_case(
            question=question,
            verify_fn=verify_fn,
            n_attempts=n,
            model=model,
            delay_between_attempts=delay,
        )

        if "error" in run:
            results.append(
                {
                    "question": question,
                    "description": description,
                    "error": run["error"],
                    "pass@1": 0.0,
                    f"pass@{k}": 0.0,
                    f"cons@{k}": 0.0,
                }
            )
            continue

        c = run["correct"]

        # Calcul des métriques
        p1 = pass_at_k(n=n, c=c, k=1)
        pk = pass_at_k(n=n, c=c, k=k)
        ck = consistency_at_k(n=n, c=c, k=k)

        case_result = {
            "question": question,
            "description": description,
            "n_attempts": n,
            "correct": c,
            "pass@1": round(p1, 4),
            f"pass@{k}": round(pk, 4),
            f"cons@{k}": round(ck, 4),
            "attempts_detail": run["attempts"],
            "errors": run["errors"],
            "expected": case.get("expected"),
        }
        results.append(case_result)

        if verbose:
            print(
                f"  ✓ {c}/{n} corrects — "
                f"pass@1={p1:.3f}  pass@{k}={pk:.3f}  cons@{k}={ck:.3f}"
            )

    # --- Moyennes globales ---
    valid_results = [r for r in results if "error" not in r]

    if not valid_results:
        return {"error": "Aucun cas de test valide", "results": results}

    mean_p1 = sum(r["pass@1"] for r in valid_results) / len(valid_results)
    mean_pk = sum(r[f"pass@{k}"] for r in valid_results) / len(valid_results)
    mean_ck = sum(r[f"cons@{k}"] for r in valid_results) / len(valid_results)

    summary = {
        "n_test_cases": len(test_cases),
        "n_valid": len(valid_results),
        "k": k,
        "n_attempts": n,
        "mean_pass@1": round(mean_p1, 4),
        f"mean_pass@{k}": round(mean_pk, 4),
        f"mean_cons@{k}": round(mean_ck, 4),
        "results": results,
    }

    return summary


# ============================================================
# HELPERS — FONCTIONS DE VÉRIFICATION PRÊTES À L'EMPLOI
# ============================================================


def _numbers_in(text: str) -> list:
    """
    Extrait les nombres d'un texte en tenant compte des formats français et anglais :
    « 1 234 », « 1 234 » (espace insécable), « 1,234 », « 12,5 », « 12.5 ».
    Un nombre ambigu comme « 1,234 » produit deux lectures (1234 et 1.234).
    """
    # Retire tous les types d'espaces (dont l'espace fine insécable \u202f utilisée par toLocaleString('fr-FR'))
    compact = re.sub(r"[\s\u00a0\u202f]+", "", text)
    values = []
    for token in re.findall(r"\d+(?:[.,]\d+)*", compact):
        # Lecture 1 : séparateurs = milliers (tous supprimés)
        values.append(float(re.sub(r"[.,]", "", token)))
        # Lecture 2 : dernier séparateur = virgule décimale
        m = re.match(r"^(.*?)[.,](\d+)$", token)
        if m:
            values.append(float(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(2)))
    return values


def verify_contains_number(expected: float, tolerance: float = 0.01):
    """
    Retourne une verify_fn qui vérifie qu'un nombre attendu
    apparaît dans la réponse.

    tolerance est une tolérance RELATIVE (0.01 = 1 %). Pour un comptage exact
    (nombre de lignes, de valeurs manquantes...), utiliser tolerance=0.
    """

    def fn(answer: str) -> bool:
        return any(
            abs(v - expected) <= tolerance * max(1, abs(expected))
            for v in _numbers_in(answer)
        )

    return fn


def verify_contains_any(keywords: list):
    """
    Retourne une verify_fn qui vérifie qu'au moins un mot-clé
    apparaît dans la réponse (insensible à la casse).
    """

    def fn(answer: str) -> bool:
        answer_lower = answer.lower()
        return any(kw.lower() in answer_lower for kw in keywords)

    return fn


def verify_contains_all(keywords: list):
    """
    Retourne une verify_fn qui vérifie que TOUS les mots-clés
    apparaissent dans la réponse.
    """

    def fn(answer: str) -> bool:
        answer_lower = answer.lower()
        return all(kw.lower() in answer_lower for kw in keywords)

    return fn


# ============================================================
# CAS DE TEST GÉNÉRÉS DEPUIS L'AUDIT
# ============================================================
#
# pass@k exige une réponse de référence. L'audit calculé par DuckDB en fournit :
# nombre de lignes, de valeurs manquantes (NULL), de valeurs distinctes.
# Chaque cas pose la question en français au chatbot SQL ; la réponse est jugée
# correcte si elle contient le nombre exact calculé par l'audit.


def build_auto_cases(audit: dict, max_cases: int = 4) -> list:
    """
    Construit des cas de test à partir du dict d'audit (voir audit.py).

    Les tables en erreur sont ignorées. Les cas sont répartis : lignes d'abord,
    puis valeurs manquantes, puis valeurs distinctes.
    """
    rows_cases, missing_cases, distinct_cases = [], [], []

    for table, data in audit.items():
        if not isinstance(data, dict) or data.get("error"):
            continue

        n_rows = (data.get("structure") or {}).get("rows")
        if isinstance(n_rows, int) and n_rows > 0:
            rows_cases.append(
                {
                    "question": f"Combien de lignes contient la table {table} ?",
                    "verify_fn": verify_contains_number(n_rows, tolerance=0),
                    "description": f"Lignes de {table} (attendu : {n_rows})",
                    "expected": n_rows,
                }
            )

        # Colonne avec le plus de valeurs manquantes (au moins une)
        missing = [m for m in data.get("missing_values", []) if m.get("missing", 0) > 0]
        if missing:
            m = max(missing, key=lambda x: x["missing"])
            missing_cases.append(
                {
                    "question": (
                        f"Combien de valeurs NULL (manquantes) contient la colonne "
                        f"\"{m['column']}\" de la table {table} ?"
                    ),
                    "verify_fn": verify_contains_number(m["missing"], tolerance=0),
                    "description": f"NULL de {table}.{m['column']} (attendu : {m['missing']})",
                    "expected": m["missing"],
                }
            )

        # Colonne la plus diversifiée (COUNT DISTINCT ignore les NULL)
        card = [
            c for c in data.get("cardinality", []) if c.get("distinct_values", 0) > 1
        ]
        if card:
            c = max(card, key=lambda x: x["distinct_values"])
            distinct_cases.append(
                {
                    "question": (
                        f"Combien de valeurs distinctes (hors NULL) contient la colonne "
                        f"\"{c['column']}\" de la table {table} ?"
                    ),
                    "verify_fn": verify_contains_number(
                        c["distinct_values"], tolerance=0
                    ),
                    "description": f"Distincts de {table}.{c['column']} (attendu : {c['distinct_values']})",
                    "expected": c["distinct_values"],
                }
            )

    # Alternance pour varier les types de questions avant d'atteindre max_cases
    pools = [rows_cases, missing_cases, distinct_cases]
    cases = []
    while len(cases) < max_cases and any(pools):
        for pool in pools:
            if pool and len(cases) < max_cases:
                cases.append(pool.pop(0))
    return cases


# ============================================================
# CLI — TEST RAPIDE
# ============================================================

if __name__ == "__main__":
    # Test des formules mathématiques
    print("=== Test des formules pass@k ===\n")

    test_cases_math = [
        (10, 5, 1, 0.5),
        (10, 10, 1, 1.0),
        (10, 0, 3, 0.0),
        (10, 9, 3, 1.0),
    ]

    for n, c, k, expected in test_cases_math:
        result = pass_at_k(n, c, k)
        status = "✓" if abs(result - expected) < 0.001 else "✗"
        print(
            f"  {status} pass_at_k(n={n}, c={c}, k={k}) = {result:.4f} "
            f"(attendu {expected})"
        )

    print("\n=== Test de consistency@k ===\n")
    print(f"  cons@3(n=10, c=5, k=3) = {consistency_at_k(10, 5, 3):.4f}")
    print(f"  cons@3(n=10, c=10, k=3) = {consistency_at_k(10, 10, 3):.4f}")
    print(f"  cons@3(n=10, c=2, k=3) = {consistency_at_k(10, 2, 3):.4f}")

    print("\n=== Test des helpers de vérification ===\n")
    fn1 = verify_contains_number(42)
    print(f"  '42 clients manquants' contient 42 : {fn1('42 clients manquants')}")
    print(f"  'aucun résultat' contient 42       : {fn1('aucun résultat')}")

    fn2 = verify_contains_any(["NULL", "manquant", "missing"])
    print(f"  'valeurs NULL détectées' match     : {fn2('valeurs NULL détectées')}")
    print(f"  'tout est correct' match           : {fn2('tout est correct')}")

    print("\n=== Exemple de cas de test SQL (sans qa.py) ===\n")
    sample_test_cases = [
        {
            "question": "Combien de lignes contient la table clients ?",
            "verify_fn": verify_contains_number(1000),
            "description": "Comptage lignes clients",
        },
        {
            "question": "Quelles colonnes ont des valeurs manquantes ?",
            "verify_fn": verify_contains_any(["email", "NULL", "manquant"]),
            "description": "Détection valeurs manquantes",
        },
    ]
    print("Cas de test définis :")
    for tc in sample_test_cases:
        print(f"  - {tc['description']}")
    print(
        "\nLancer evaluate_qa_passk(sample_test_cases, k=3) "
        "pour exécuter avec qa.py."
    )
