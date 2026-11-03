# Importation de DuckDB, le moteur SQL analytique utilisé pour lire les fichiers
import duckdb

# Importation des paramètres de connexion et de la liste des fichiers connus
from config import FILES, DUCKDB_MEMORY, DUCKDB_THREADS


def create_connection():
    """
    Crée et retourne une nouvelle connexion DuckDB en mémoire.
    """

    # Ouvre une connexion DuckDB en mémoire
    con = duckdb.connect()

    # Limite la mémoire utilisable par DuckDB
    con.execute(f"SET memory_limit = '{DUCKDB_MEMORY}'")

    # Limite le nombre de threads CPU utilisés par DuckDB
    con.execute(f"SET threads = {DUCKDB_THREADS}")

    # Autorise DuckDB à utiliser ce dossier temporaire en cas de dépassement mémoire
    con.execute("SET temp_directory = 'duckdb_tmp'")

    # Réduit la mémoire consommée par DuckDB sur les gros fichiers
    con.execute("SET preserve_insertion_order = false")

    return con


def get_table_path(table_name):
    """
    Retourne le chemin absolu du fichier correspondant à une table.
    """

    if table_name not in FILES:
        raise ValueError(f"Table inconnue : {table_name}")

    return FILES[table_name].as_posix()


def get_source(table_name):
    """
    Retourne l'expression SQL DuckDB permettant de lire une table.

    Exemples :
        SELECT * FROM {get_source("clients")}
        DESCRIBE SELECT * FROM {get_source("clients")}
    """

    # Récupère le chemin et échappe les apostrophes SQL éventuelles
    path = get_table_path(table_name).replace("'", "''")

    # Extension du fichier
    extension = FILES[table_name].suffix.lower()

    # ---------------- PARQUET ----------------
    if extension == ".parquet":
        return f"read_parquet('{path}')"

    # ---------------- CSV ----------------
    if extension == ".csv":
        """
        Options importantes :
        - sample_size=-1 :
          DuckDB analyse tout le fichier afin de mieux déterminer les types.
          Utile lorsqu'une colonne contient par exemple des nombres puis du texte.

        - null_padding=true :
          Si une ligne contient moins de colonnes que l'en-tête, DuckDB complète
          les colonnes manquantes avec NULL au lieu de faire échouer complètement
          l'import.

        - ignore_errors=true :
          Ignore les lignes réellement illisibles (guillemets mal fermés, etc.).
          Attention : les lignes ignorées ne participent pas à l'audit.
        """
        return (
            f"read_csv_auto("
            f"'{path}', "
            f"sample_size=-1, "
            f"null_padding=true, "
            f"ignore_errors=true"
            f")"
        )

    # ---------------- TSV ----------------
    if extension == ".tsv":
        return (
            f"read_csv_auto("
            f"'{path}', "
            f"delim='\\t', "
            f"sample_size=-1, "
            f"null_padding=true, "
            f"ignore_errors=true"
            f")"
        )

    # ---------------- JSON ----------------
    if extension == ".json":
        return f"read_json_auto('{path}')"

    raise ValueError(f"Format non supporté : {extension}")


def query(sql):
    """
    Exécute une requête SQL et retourne un DataFrame pandas.
    """

    con = create_connection()

    try:
        return con.execute(sql).fetchdf()

    finally:
        con.close()


def execute(sql):
    """
    Exécute une requête SQL et retourne une liste de tuples.
    """

    con = create_connection()

    try:
        return con.execute(sql).fetchall()

    finally:
        con.close()


def table_exists(table_name):
    """
    Vérifie qu'une table est référencée et que son fichier existe.
    """

    return table_name in FILES and FILES[table_name].exists()
