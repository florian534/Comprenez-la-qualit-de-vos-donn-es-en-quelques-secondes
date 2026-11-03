# Importation de math pour détecter NaN et Inf (incompatibles avec JSON)
import math

# Importation de re pour les expressions régulières (nettoyage des noms de fichiers)
import re

# Importation de unicodedata pour normaliser les caractères accentués
import unicodedata

# Importation de traceback pour afficher les erreurs complètes dans le terminal
import traceback

# Importation de shutil pour supprimer des dossiers entiers (upload)
import shutil

# Importation de threading pour l'ouverture du navigateur en arrière-plan
import threading

# Importation de webbrowser pour ouvrir automatiquement le navigateur au démarrage
import webbrowser

# Importation de Path pour manipuler les chemins de fichiers
from pathlib import Path

# Importation de requests pour détecter les erreurs de connexion Ollama
import requests

# Importation de HTTPException pour gérer les erreurs HTTP de werkzeug
from werkzeug.exceptions import HTTPException

# Importation des composants Flask nécessaires
from flask import Flask, Response, jsonify, request, send_from_directory

# Importation du module config pour accéder à OLLAMA_URL
import config

# Importation des paramètres et fonctions de configuration
from config import BASE_DIR, FILES, MODEL, SUPPORTED_EXTENSIONS, discover_files

# Importation des fonctions d'audit
from audit import audit_all_tables, column_distribution

# Importation de la fonction d'analyse IA
from agent import analyze_audit

# Importation des fonctions du chatbot Q&A
from qa import ask_data, export_result

# Importation du module RAG (documents PDF : lecture, découpage, recherche)
import rag

# Chemin du dossier contenant les fichiers statiques (HTML, CSS, JS)
STATIC_DIR = BASE_DIR / "static"
# Chemin du dossier où seront stockés les fichiers uploadés via l'interface web
UPLOAD_DIR = BASE_DIR / "uploads"
# Dossier où l'on dépose les présentations PowerPoint (.pptx) affichées par le robot
PRESENTATIONS_DIR = STATIC_DIR / "presentations"

# Création de l'application Flask sans dossier static automatique
# static_folder=None : on gère les fichiers statiques manuellement
app = Flask(__name__, static_folder=None)

# Étape en cours de l'analyse IA, lue par l'interface (GET /api/progress)
# Outil local mono-utilisateur : un simple dictionnaire partagé suffit
PROGRESS = {"step": "idle", "pdf": False}

# Verrou threading : garantit qu'un seul audit s'exécute à la fois
# Évite les conflits si plusieurs utilisateurs lancent un audit simultanément
lock = threading.Lock()


def clean(value):
    """Rend le résultat de l'audit compatible JSON (NaN, dates, Decimal...)."""

    # Si c'est un dict, nettoie récursivement chaque clé et valeur
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}

    # Si c'est une liste ou un tuple, nettoie récursivement chaque élément
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]

    # JSON ne supporte pas NaN et Inf : les convertit en null
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None

    # Ces types sont nativement supportés par JSON : retourne tel quel
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    # Pour tout autre type (datetime, Decimal, Path...) : convertit en string
    return str(value)


def error(message, status=400):
    # Raccourci pour retourner une réponse d'erreur JSON avec un code HTTP

    # jsonify crée une réponse Flask avec Content-Type: application/json
    return jsonify({"error": message}), status


@app.errorhandler(Exception)
def on_error(e):
    # Gestionnaire global d'erreurs : intercepte toutes les exceptions non gérées

    # Si c'est une erreur HTTP standard (404, 405...), retourne son message
    if isinstance(e, HTTPException):
        return error(e.description, e.code)

    # Pour les autres erreurs : affiche la stack trace complète dans le terminal
    traceback.print_exc()

    # Retourne une erreur 500 avec le message de l'exception
    return error(f"Erreur serveur : {e}", 500)


# ============================================================
# PAGES
# ============================================================


@app.get("/")
def index():
    # Route GET / : sert la page principale de l'interface web

    # Construit le chemin vers index.html dans le dossier static/
    page = STATIC_DIR / "index.html"

    # Si le fichier n'existe pas, retourne un message d'erreur explicite
    if not page.exists():
        return (
            "Fichier introuvable : " + str(page) + "\n\n"
            "Créez un dossier 'static' à côté de server.py et placez-y "
            "index.html, style.css et app.js.",
            404,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    # Envoie le fichier index.html depuis le dossier STATIC_DIR
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/<path:name>")
def static_files(name):
    # Route GET pour tous les autres fichiers statiques (CSS, JS, images...)
    # <path:name> capture tout le chemin, y compris les sous-dossiers

    # Envoie le fichier demandé depuis le dossier STATIC_DIR
    return send_from_directory(STATIC_DIR, name)


@app.get("/api/presentations")
def api_presentations():
    # Route GET /api/presentations : liste les fichiers .pptx du dossier static/presentations

    # Crée le dossier s'il n'existe pas encore (premier lancement)
    PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Liste les fichiers .pptx (hors fichiers temporaires "~$..." d'Office), triés par nom
    files = sorted(
        (
            p.name
            for p in PRESENTATIONS_DIR.glob("*.pptx")
            if not p.name.startswith("~$")
        ),
        key=str.lower,
    )

    # Retourne la liste des noms ; le navigateur télécharge ensuite le fichier choisi
    return jsonify({"files": files})


@app.get("/api/config")
def get_config():
    # Route GET /api/config : retourne la configuration publique du serveur

    # Retourne le nom du modèle Ollama configuré (utile pour l'interface web)
    return jsonify({"model": MODEL})


# ============================================================
# AUDIT
# ============================================================


@app.post("/api/audit")
def api_audit():
    """
    Lance l'audit sur les fichiers téléversés ou un dossier local.

    Retourne :
    - audit : résultats normaux et résultats d'erreur table par table ;
    - ignored : fichiers non supportés ;
    - errors : erreurs détectées par table.
    """

    # Fichiers dont l'extension n'est pas supportée
    ignored = []

    # --------------------------------------------------------
    # CAS 1 : fichiers envoyés depuis l'interface
    # --------------------------------------------------------
    if request.files.getlist("files"):

        # Supprime les anciens imports
        if UPLOAD_DIR.exists():
            shutil.rmtree(UPLOAD_DIR, ignore_errors=True)

        # Recrée le dossier d'import
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Sauvegarde les fichiers supportés
        for f in request.files.getlist("files"):

            # Évite les chemins envoyés par certains navigateurs
            name = Path(f.filename or "").name

            # Ignore les fichiers sans nom
            if not name:
                continue

            # Vérifie l'extension
            if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                f.save(UPLOAD_DIR / name)
            else:
                ignored.append(name)

        # Dossier analysé
        data_dir = UPLOAD_DIR

    # --------------------------------------------------------
    # CAS 2 : dossier local fourni
    # --------------------------------------------------------
    else:
        raw_path = request.form.get("data_dir", "").strip().strip('"')

        if not raw_path:
            return error("Aucun fichier ni dossier fourni.")

        data_dir = Path(raw_path).expanduser()

        if not data_dir.is_dir():
            return error(f"Dossier introuvable : {data_dir}")

    # Un seul audit à la fois
    with lock:

        # Met à jour les tables globales connues
        FILES.clear()
        FILES.update(discover_files(data_dir))

        # Aucun fichier exploitable
        if not FILES:
            return error(
                "Aucune table trouvée (formats supportés : "
                + ", ".join(SUPPORTED_EXTENSIONS)
                + ")."
            )

        try:
            # Lance les audits.
            # Grâce à la modification de audit_all_tables(), les erreurs
            # par table sont conservées dans le résultat.
            audit = audit_all_tables()

        except Exception as e:
            traceback.print_exc()
            return error(f"Erreur pendant l'audit : {e}", 500)

    # Construit une liste claire des erreurs par table
    table_errors = {
        table_name: data["error"]
        for table_name, data in audit.items()
        if isinstance(data, dict) and data.get("error")
    }

    # Réponse finale JSON
    return jsonify({"audit": clean(audit), "ignored": ignored, "errors": table_errors})


@app.get("/api/column")
def api_column():
    # Route GET /api/column?table=X&column=Y : calcule la distribution d'une colonne

    # Récupère les paramètres de la requête URL
    table = request.args.get("table", "")
    column = request.args.get("column", "")

    # Vérifie que la table existe dans le dict FILES
    if table not in FILES:
        return error("Table inconnue : relancez l'audit.", 404)

    # Calcule la distribution sous verrou pour éviter les conflits
    with lock:
        result = column_distribution(table, column)

    # Retourne le résultat nettoyé (compatible JSON)
    return jsonify(clean(result))


# ============================================================
# DOCUMENTS PDF (RAG)
# ============================================================


@app.get("/api/docs")
def api_docs():
    # Route GET /api/docs : liste les PDF en mémoire et le mode de recherche
    return jsonify(rag.docs_info())


@app.post("/api/docs")
def api_docs_upload():
    # Route POST /api/docs : reçoit un ou plusieurs PDF, les découpe et les indexe

    errors = []
    warnings = []

    for f in request.files.getlist("files"):

        # Garde uniquement le nom du fichier (pas le chemin)
        name = Path(f.filename or "").name

        # Seuls les PDF sont acceptés ici
        if Path(name).suffix.lower() != ".pdf":
            errors.append(f"{name} : format non pris en charge (PDF uniquement).")
            continue

        try:
            # Lit, découpe et indexe le PDF
            info = rag.ingest(name, f.read())
            if info["warning"]:
                warnings.append(f"{name} : {info['warning']}")

        except Exception as e:
            errors.append(f"{name} : {e}")

    # Retourne l'état complet pour que la page se mette à jour
    result = rag.docs_info()
    result["errors"] = errors
    result["warnings"] = warnings
    return jsonify(result)


@app.post("/api/docs/delete")
def api_docs_delete():
    # Route POST /api/docs/delete : retire un PDF (ou tous si aucun nom n'est donné)
    body = request.get_json(silent=True) or {}
    rag.remove(body.get("name") or None)
    return jsonify(rag.docs_info())


# ============================================================
# ANALYSE OLLAMA
# ============================================================


@app.get("/api/progress")
def api_progress():
    # Route GET /api/progress : étape actuelle de l'analyse IA (search, write ou idle)
    return jsonify(PROGRESS)


@app.post("/api/analyze")
def api_analyze():
    # Route POST /api/analyze : génère le rapport IA à partir des résultats d'audit

    # Parse le corps de la requête JSON (silent=True : retourne {} si erreur)
    body = request.get_json(silent=True) or {}

    # Récupère les résultats d'audit depuis le corps de la requête
    audit = body.get("audit")

    # Erreur si aucun audit n'est fourni
    if not audit:
        return error("Aucun résultat d'audit fourni.")

    # Contexte métier saisi par l'utilisateur (peut être vide)
    context = body.get("context") or ""

    # Étape 1 : recherche dans les PDF (s'il y en a)
    PROGRESS.update(step="search", pdf=bool(rag.DOCS))

    # RAG : recherche les passages de PDF utiles pour cet audit
    # Une erreur ici ne doit jamais empêcher l'analyse : on continue sans les PDF
    sources = []
    search_mode = None
    try:
        passages = rag.retrieve_for_audit(audit, context)
        if passages:
            search_mode = passages[0].get("mode")
            # Ajoute les extraits (et leurs règles d'usage) au contexte métier
            context = (context + "\n\n" if context.strip() else "") + rag.format_block(
                passages
            )
            sources = rag.sources_summary(passages)
    except Exception:
        traceback.print_exc()

    # Étape 2 : rédaction du rapport par Ollama
    PROGRESS["step"] = "write"

    try:
        # Appelle la fonction d'analyse IA avec les paramètres fournis
        analysis = analyze_audit(
            audit,
            project_name=body.get("name") or None,  # nom du projet (optionnel)
            context=context,  # contexte métier + extraits PDF
            model=body.get("model") or None,  # modèle Ollama (optionnel)
        )

    except requests.exceptions.ConnectionError:
        # Erreur si Ollama n'est pas lancé ou inaccessible
        return error(
            f"Ollama est inaccessible ({config.OLLAMA_URL}). "
            "Vérifiez qu'il est lancé.",
            502,
        )

    except requests.exceptions.RequestException as e:
        # Erreur pour tout autre problème HTTP avec Ollama
        return error(f"Erreur Ollama : {e}", 502)

    finally:
        # Quoi qu'il arrive (succès ou erreur), l'analyse n'est plus en cours
        PROGRESS["step"] = "idle"

    # Retourne le rapport Markdown généré par l'IA et la liste des sources PDF utilisées
    return jsonify(
        {"analysis": analysis, "sources": sources, "search_mode": search_mode}
    )


@app.post("/api/evaluate")
def api_evaluate():
    # Route POST /api/evaluate : évalue la qualité du rapport IA généré

    body = request.get_json(silent=True) or {}

    # Récupère l'audit et l'analyse depuis le corps de la requête
    audit = body.get("audit")
    analysis = body.get("analysis")

    if not audit:
        return error("Aucun résultat d'audit fourni.")
    if not analysis:
        return error("Aucune analyse à évaluer.")

    try:
        # Import de la fonction d'évaluation
        from evaluator import evaluate_analysis

        # Lance l'évaluation
        evaluation = evaluate_analysis(
            audit=audit, analysis=analysis, model=body.get("model") or None
        )

    except requests.exceptions.ConnectionError:
        return error(
            f"Ollama est inaccessible ({config.OLLAMA_URL}). "
            "Vérifiez qu'il est lancé.",
            502,
        )

    except Exception as e:
        traceback.print_exc()
        return error(f"Erreur pendant l'évaluation : {e}", 500)

    return jsonify({"evaluation": evaluation})


# ============================================================
# EVALUATION DE LA RECHERCHE (RAG) : P@k, R@k, NDCG@k, RR@k
# ============================================================


@app.post("/api/eval/rag")
def api_eval_rag():
    # Route POST /api/eval/rag : compare recherche sémantique, BM25 et hybride
    # sur un jeu de test construit automatiquement à partir des PDF indexés
    body = request.get_json(silent=True) or {}

    try:
        k = max(1, min(int(body.get("k") or config.RAG_TOP_K), 20))
        n_queries = max(1, min(int(body.get("n_queries") or 8), 30))
    except (TypeError, ValueError):
        return error("Paramètres invalides.")

    from rag_eval import build_auto_cases, evaluate_modes

    try:
        built = build_auto_cases(
            n_queries=n_queries,
            use_llm=bool(body.get("use_llm", True)),
            model=body.get("model") or None,
        )
        if "error" in built:
            return error(built["error"])

        result = evaluate_modes(built["cases"], k=k)
        if "error" in result:
            return error(result["error"])

    except requests.exceptions.ConnectionError:
        return error(
            f"Ollama est inaccessible ({config.OLLAMA_URL}). "
            "Vérifiez qu'il est lancé.",
            502,
        )

    # Origine des requêtes : générées par le modèle ou extraites du passage
    result["query_sources"] = {
        src: sum(1 for c in built["cases"] if c["source"] == src)
        for src in {c["source"] for c in built["cases"]}
    }
    return jsonify(clean(result))


# ============================================================
# EVALUATION DU TEXT-TO-SQL : pass@k et cons@k
# ============================================================


@app.post("/api/eval/sql")
def api_eval_sql():
    # Route POST /api/eval/sql : mesure la fiabilité du chatbot SQL.
    # Les questions et les réponses attendues viennent de l'audit (valeurs calculées par DuckDB).
    body = request.get_json(silent=True) or {}
    audit = body.get("audit")

    if not audit:
        return error("Aucun résultat d'audit fourni.")
    if not FILES:
        return error("Importez d'abord des fichiers.")

    try:
        k = max(1, min(int(body.get("k") or 3), 5))
        n_attempts = max(k, min(int(body.get("n_attempts") or k), 8))
        max_cases = max(1, min(int(body.get("max_cases") or 3), 6))
    except (TypeError, ValueError):
        return error("Paramètres invalides.")

    from qa_eval import build_auto_cases, evaluate_qa_passk

    cases = build_auto_cases(audit, max_cases=max_cases)
    if not cases:
        return error("Impossible de construire des cas de test à partir de cet audit.")

    try:
        result = evaluate_qa_passk(
            cases,
            k=k,
            n_attempts=n_attempts,
            model=body.get("model") or None,
            delay=0.2,
        )
    except requests.exceptions.ConnectionError:
        return error(
            f"Ollama est inaccessible ({config.OLLAMA_URL}). "
            "Vérifiez qu'il est lancé.",
            502,
        )

    if "error" in result and not result.get("results"):
        return error(result["error"])

    return jsonify(clean(result))


@app.post("/api/ask")
def api_ask():
    # Route POST /api/ask : répond à une question en langage naturel sur les données

    # Parse le corps de la requête JSON
    body = request.get_json(silent=True) or {}

    # Récupère et nettoie la question
    question = (body.get("question") or "").strip()

    # Erreur si la question est vide
    if not question:
        return error("Question vide.")

    # Erreur si aucun fichier n'a encore été importé
    if not FILES:
        return error("Importez d'abord des fichiers.")

    try:
        # Appelle le chatbot Q&A avec la question et les paramètres optionnels
        result = ask_data(
            question,
            model=body.get("model") or None,  # modèle Ollama (optionnel)
            history=body.get("history") or [],  # historique des échanges précédents
            context=body.get("context") or "",  # contexte métier (optionnel)
        )

    except requests.exceptions.ConnectionError:
        # Erreur si Ollama n'est pas lancé
        return error(
            f"Ollama est inaccessible ({config.OLLAMA_URL}). "
            "Vérifiez qu'il est lancé.",
            502,
        )

    except requests.exceptions.RequestException as e:
        # Erreur pour tout autre problème HTTP avec Ollama
        return error(f"Erreur Ollama : {e}", 502)

    # Retourne la réponse nettoyée (réponse + étapes SQL + état du verrou)
    return jsonify(clean(result))


@app.post("/api/export")
def api_export():
    # Route POST /api/export : exporte le résultat d'une requête SQL en fichier

    # Parse le corps de la requête JSON
    body = request.get_json(silent=True) or {}

    # Erreur si aucun fichier n'a encore été importé
    if not FILES:
        return error("Importez d'abord des fichiers.")

    # Récupère et normalise le format d'export demandé
    fmt = (body.get("format") or "csv").lower()

    try:
        # Exécute la requête SQL et génère le fichier dans le format demandé
        data, mime, count, truncated = export_result(
            body.get("sql") or "",  # requête SQL à exécuter
            fmt,  # format : csv, xlsx ou parquet
        )

    except ValueError as e:
        # Retourne l'erreur de validation ou d'exécution
        return error(str(e))

    # Nettoie le nom de fichier pour l'en-tête HTTP Content-Disposition
    # unicodedata.normalize("NFKD") : décompose les caractères accentués (é → e + accent)
    base = unicodedata.normalize("NFKD", str(body.get("name") or ""))
    # encode("ascii", "ignore") : supprime les caractères non-ASCII (accents...)
    base = base.encode("ascii", "ignore").decode()
    # Remplace tout caractère non alphanumérique par _ et limite à 50 caractères
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")[:50] or "resultat"

    # Retourne le fichier comme réponse HTTP avec les en-têtes appropriés
    return Response(
        data,  # octets du fichier (CSV, Excel ou Parquet)
        mimetype=mime,  # type MIME pour que le navigateur sache comment traiter le fichier
        headers={
            # Indique au navigateur de télécharger le fichier avec ce nom
            "Content-Disposition": f'attachment; filename="{base}.{fmt}"',
            # En-tête personnalisé : nombre de lignes dans l'export
            "X-Row-Count": str(count),
            # En-tête personnalisé : "1" si l'export a été tronqué, "0" sinon
            "X-Truncated": "1" if truncated else "0",
            # Autorise le JavaScript côté navigateur à lire ces en-têtes personnalisés
            "Access-Control-Expose-Headers": "Content-Disposition, X-Row-Count, X-Truncated",
        },
    )


# Point d'entrée : exécuté seulement si le fichier est lancé directement
# (pas si importé comme module)
if __name__ == "__main__":

    # URL locale du serveur Flask
    url = "http://127.0.0.1:5000"

    # Affiche l'URL et les instructions dans le terminal
    print(f"\nAudit de données : {url}\n(Ctrl+C pour arrêter)\n")

    # Ouvre le navigateur automatiquement 1 seconde après le démarrage
    # threading.Timer : exécute la lambda après 1 seconde sans bloquer le démarrage
    # lambda : fonction anonyme qui appelle webbrowser.open(url)
    threading.Timer(1, lambda: webbrowser.open(url)).start()

    # Lance le serveur Flask sur localhost port 5000
    # debug=False : pas de rechargement automatique (stabilité en production)
    app.run(host="127.0.0.1", port=5000, debug=False)
