# Importation du module os pour lire les variables d'environnement
import os

# Importation de Path pour manipuler les chemins de fichiers de façon portable
from pathlib import Path

# ============================================================
# PARAMETRES GENERAUX
# ============================================================

# Résout le chemin absolu du dossier contenant ce fichier config.py
# __file__ = chemin de ce script, .resolve() = chemin absolu, .parent = dossier parent
BASE_DIR = Path(__file__).resolve().parent

# Lit la variable d'environnement AUDIT_NAME, ou utilise "Audit de données" par défaut
# Ce nom apparaît dans le titre du rapport HTML
PROJECT_NAME = os.getenv("AUDIT_NAME", "Audit de données")

# Lit la variable d'environnement AUDIT_CONTEXT, ou chaîne vide par défaut
# Ce texte décrit le contexte métier et aide l'IA à interpréter les résultats
PROJECT_CONTEXT = os.getenv("AUDIT_CONTEXT", "")


# ============================================================
# CHEMINS
# ============================================================

# Construit le chemin du dossier de données :
# - lit la variable d'environnement AUDIT_DATA_DIR si elle existe
# - sinon utilise BASE_DIR/data/parquet par défaut
# .expanduser() résout le ~ (home), .resolve() donne le chemin absolu
DATA_DIR = (
    Path(os.getenv("AUDIT_DATA_DIR", BASE_DIR / "data" / "parquet"))
    .expanduser()
    .resolve()
)

# Dossier où seront sauvegardés les graphiques PNG générés par charts.py
GRAPH_DIR = BASE_DIR / "graphs"

# Dossier où seront sauvegardés le rapport HTML et le JSON d'audit
REPORT_DIR = BASE_DIR / "reports"

# Crée le dossier graphs/ s'il n'existe pas encore (parents=True = crée aussi les parents)
GRAPH_DIR.mkdir(parents=True, exist_ok=True)

# Crée le dossier reports/ s'il n'existe pas encore
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# DECOUVERTE AUTOMATIQUE DES TABLES
# ============================================================

# Liste des extensions de fichiers supportées, dans l'ordre de priorité
# Si un même nom de fichier existe en .parquet et .csv, le .parquet sera pris
SUPPORTED_EXTENSIONS = [".parquet", ".csv", ".tsv", ".json"]


def discover_files(data_dir):
    # Parcourt le dossier data_dir et retourne un dict {nom_table: chemin_fichier}

    # Initialise le dictionnaire vide qui contiendra les tables trouvées
    files = {}

    # Si le dossier n'existe pas, retourne un dict vide sans erreur
    if not data_dir.exists():
        return files

    # Parcourt les extensions dans l'ordre de priorité défini ci-dessus
    for extension in SUPPORTED_EXTENSIONS:

        # Cherche tous les fichiers correspondant à l'extension dans data_dir
        # sorted() garantit un ordre alphabétique reproductible
        for path in sorted(data_dir.glob(f"*{extension}")):

            # setdefault : n'ajoute le fichier que si le nom (sans extension)
            # n'est pas déjà présent → priorité au premier format rencontré
            files.setdefault(path.stem, path)

    # Retourne le dict trié alphabétiquement par nom de table
    return dict(sorted(files.items()))


# Appelle discover_files au chargement du module pour remplir FILES
# FILES est un dict global utilisé par tous les autres modules
FILES = discover_files(DATA_DIR)


# ============================================================
# OLLAMA
# ============================================================

# URL de l'API Ollama, modifiable via variable d'environnement
# Cette URL est appelée par Python (pas le navigateur) via requests.post()
OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",  # valeur par défaut si la variable n'est pas définie
)

# Nom du modèle Ollama à utiliser, modifiable via variable d'environnement
MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")


# ============================================================
# RAG : DOCUMENTS PDF (embeddings + recherche)
# ============================================================

# Modèle Ollama utilisé pour transformer les passages de PDF en vecteurs (embeddings)
# À installer une fois avec : ollama pull nomic-embed-text
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# URL de l'API d'embeddings d'Ollama (déduite de OLLAMA_URL par défaut)
OLLAMA_EMBED_URL = os.getenv(
    "OLLAMA_EMBED_URL", OLLAMA_URL.replace("/api/chat", "/api/embed")
)

# Taille d'un passage (en caractères) et chevauchement entre deux passages consécutifs
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "900"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))

# Nombre de passages retenus par question de recherche
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))

# Taille maximale (en caractères) de tous les extraits ajoutés au prompt de l'analyse
RAG_MAX_CHARS = int(os.getenv("RAG_MAX_CHARS", "9000"))

# Recherche HYBRIDE : score final = alpha * score sémantique + (1 - alpha) * score lexical (BM25),
# après normalisation min-max des deux scores (sur l'ensemble des passages, pour chaque requête).
# alpha = 1.0 -> sémantique pur ; alpha = 0.0 -> BM25 pur ; 0.6 = léger avantage au sémantique.
RAG_HYBRID_ALPHA = float(os.getenv("RAG_HYBRID_ALPHA", "0.4"))

# Score hybride minimal (0-1) pour retenir un passage
RAG_MIN_HYBRID_SCORE = float(os.getenv("RAG_MIN_HYBRID_SCORE", "0.35"))

# Requêtes de recherche construites à partir de l'audit :
# nombre maximal par table, plafond global, et nombre de colonnes citées dans la requête de structure
RAG_QUERIES_PER_TABLE = int(os.getenv("RAG_QUERIES_PER_TABLE", "4"))
RAG_MAX_QUERIES = int(os.getenv("RAG_MAX_QUERIES", "40"))
RAG_QUERY_COLUMNS = int(os.getenv("RAG_QUERY_COLUMNS", "10"))

# ============================================================
# DUCKDB
# ============================================================

# Limite mémoire allouée à DuckDB, modifiable via variable d'environnement
DUCKDB_MEMORY = os.getenv("DUCKDB_MEMORY", "8GB")

# Nombre de threads alloués à DuckDB, converti en entier
# int() est nécessaire car os.getenv retourne toujours une chaîne
DUCKDB_THREADS = int(os.getenv("DUCKDB_THREADS", "4"))
