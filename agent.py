# Importation de json pour sérialiser le dict d'audit en chaîne JSON
import json

# Importation de requests pour faire des appels HTTP vers l'API Ollama
import requests

# Importation des paramètres de configuration
from config import OLLAMA_URL, MODEL, PROJECT_NAME, PROJECT_CONTEXT

# ============================================================
# PROMPT SYSTEME
# ============================================================


def build_system_prompt(table_names, project_name=None, context=None):
    # Construit le prompt système qui définit le rôle et les règles de l'IA

    # Utilise le nom du projet passé en argument, ou la valeur par défaut de config.py
    project_name = project_name or PROJECT_NAME

    # Utilise le contexte passé en argument, ou la valeur par défaut de config.py
    if context is None:
        context = PROJECT_CONTEXT

    # Formate la liste des tables en une liste à puces Markdown
    # Ex: "- table1\n- table2\n- table3"
    tables = "\n".join(f"- {name}" for name in table_names)

    # Initialise le bloc de contexte métier à vide par défaut
    context_block = ""

    # Si un contexte métier non-vide est fourni, construit le bloc de texte
    if context.strip():
        context_block = f"""
CONTEXTE METIER FOURNI PAR L'UTILISATEUR :

{context.strip()}

Ce contexte peut t'aider à interpréter les résultats, mais
il ne remplace pas les résultats fournis par Python.
"""

    # Retourne le prompt système complet avec toutes les informations
    # f-string multilignes : injecte les variables dans le texte
    return f"""
Tu es un expert de la qualité des données.

Tu analyses la base de données « {project_name} ».

Tu analyses exclusivement les résultats calculés par Python
et DuckDB.

Les données brutes ne sont pas à analyser directement.
{context_block}
REGLES IMPORTANTES :

1. Ne jamais inventer une donnée.
2. Ne jamais inventer une statistique.
3. Ne jamais modifier les données.
4. Ne jamais présenter une hypothèse comme un fait.
5. Toujours distinguer :
   - anomalie certaine ;
   - point nécessitant une vérification ;
   - absence de problème détecté.
6. Lorsque tu cites une valeur, elle doit être présente
   dans les résultats fournis par Python.
7. Lorsque tu identifies un problème, indique toujours
   la table concernée.
8. Lorsque c'est possible, indique également la colonne.
9. Ne répète pas plusieurs fois la même anomalie.
10. Ne reformule pas inutilement plusieurs fois le même résultat.
11. N'utilise pas de connaissances métier que le contexte
    ou les résultats ne permettent pas de justifier.

Les tables auditées sont :

{tables}

Ton objectif est de produire une analyse technique utile
à un expert de la donnée.
"""


# ============================================================
# APPEL OLLAMA
# ============================================================


def ask_ollama(prompt, system_prompt, model=None):
    # Envoie les prompts à Ollama via HTTP POST et retourne la réponse texte

    # Construit le corps de la requête HTTP au format attendu par l'API Ollama
    payload = {
        # Nom du modèle : utilise l'argument ou la valeur par défaut de config.py
        "model": model or MODEL,
        # Liste des messages de la conversation (format ChatML)
        "messages": [
            {
                # Message système : définit le rôle et les règles de l'IA
                "role": "system",
                # Contenu = prompt système construit par build_system_prompt()
                "content": system_prompt,
            },
            {
                # Message utilisateur : contient les données à analyser
                "role": "user",
                # Contenu = le JSON de l'audit + les instructions du rapport
                "content": prompt,
            },
        ],
        # False = attend la réponse complète avant de retourner
        # True = streaming (envoi progressif), non utilisé ici
        "stream": False,
    }

    # Envoie la requête POST vers l'API Ollama
    # C'est Python (côté serveur) qui appelle Ollama, pas le navigateur
    response = requests.post(
        OLLAMA_URL,  # "http://localhost:11434/api/chat"
        json=payload,  # sérialise automatiquement le dict en JSON
        timeout=1800,  # timeout de 30 minutes (les gros modèles sont lents)
    )

    # Lève une exception HTTPError si le code de statut est >= 400
    response.raise_for_status()

    # Désérialise la réponse JSON d'Ollama en dict Python
    data = response.json()

    # Extrait et retourne uniquement le texte généré par le modèle
    # Structure de la réponse Ollama : {"message": {"role": "assistant", "content": "..."}}
    return data["message"]["content"]


# ============================================================
# ALLEGEMENT DE L'AUDIT (grosses bases)
# ============================================================


def compact_audit(audit):
    """
    Réduit la taille du JSON envoyé à l'IA sans perdre d'information :
    les colonnes sans valeur manquante sont résumées par un simple
    compteur au lieu d'être listées une par une.
    """

    # Dict qui contiendra la version compactée de l'audit
    compact = {}

    # Itère sur chaque table de l'audit
    for table, data in audit.items():

        # Récupère la liste des valeurs manquantes, liste vide si absente
        missing = data.get("missing_values", [])

        # Garde uniquement les colonnes qui ont au moins une valeur manquante
        with_missing = [m for m in missing if m.get("missing", 0) > 0]

        # Construit la version compacte de cette table :
        # - **data : copie tous les autres champs (structure, doublons, stats...)
        # - missing_values : remplace la liste par un dict plus compact
        compact[table] = {
            **data,  # décompresse tous les champs existants
            "missing_values": {
                # Détaille uniquement les colonnes avec des manquants
                "columns_with_missing_values": with_missing,
                # Résume les colonnes sans manquants par un simple compteur
                "columns_without_missing_values": len(missing) - len(with_missing),
            },
        }

    # Retourne l'audit compacté
    return compact


# ============================================================
# INSTRUCTIONS DE REDACTION DU RAPPORT
# ============================================================

# Chaîne de texte statique qui définit la structure et les règles du rapport
# Modifiable pour changer le style ou la structure sans toucher au code
INSTRUCTIONS_RAPPORT = """
# Instructions de rédaction du rapport d'audit de qualité des données
[... contenu identique ...]
"""


# ============================================================
# ANALYSE DE L'AUDIT
# ============================================================


def analyze_audit(audit, project_name=None, context=None, model=None):
    # Orchestre l'analyse complète : construit les prompts et appelle Ollama

    # Utilise le nom du projet passé en argument, ou la valeur par défaut
    project_name = project_name or PROJECT_NAME

    # Construit le prompt système avec la liste des tables et le contexte métier
    system_prompt = build_system_prompt(
        list(audit.keys()),  # extrait les noms des tables du dict d'audit
        project_name,
        context,
    )

    # Sérialise l'audit compacté en JSON lisible (indentation 2 espaces)
    # ensure_ascii=False : conserve les accents
    # default=str : convertit les types non-JSON en string (datetime, Decimal...)
    audit_json = json.dumps(
        compact_audit(audit),  # version allégée pour réduire la taille du prompt
        ensure_ascii=False,
        default=str,
        indent=2,
    )

    # Nombre de tables pour l'affichage dans le prompt
    n_tables = len(audit)

    # Construit le prompt utilisateur complet qui sera envoyé à Ollama
    # Contient : explication du contexte + JSON de l'audit + instructions du rapport
    prompt = f"""
Tu disposes ci-dessous des résultats d'un audit automatique
réalisé par Python/DuckDB sur les {n_tables} tables de la base
« {project_name} ».

[... contenu des instructions ...]

{audit_json}

[... instructions du rapport ...]
"""

    # Appelle Ollama et retourne le rapport Markdown généré
    return ask_ollama(prompt, system_prompt, model)
