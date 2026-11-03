# Importation de json pour la sauvegarde de l'audit en fichier JSON
import json

# Importation de FILES (dict des tables connues) depuis config.py
from config import FILES

# Importation des fonctions d'accès à DuckDB
from database import create_connection, get_source

# Liste des noms de types numériques reconnus par DuckDB
# Utilisée pour savoir si une colonne contient des nombres
NUMERIC_TYPES = [
    "TINYINT",  # entier 8 bits signé
    "SMALLINT",  # entier 16 bits signé
    "INTEGER",  # entier 32 bits signé
    "BIGINT",  # entier 64 bits signé
    "HUGEINT",  # entier 128 bits signé
    "UTINYINT",  # entier 8 bits non signé
    "USMALLINT",  # entier 16 bits non signé
    "UINTEGER",  # entier 32 bits non signé
    "UBIGINT",  # entier 64 bits non signé
    "FLOAT",  # flottant 32 bits
    "DOUBLE",  # flottant 64 bits
    "DECIMAL",  # nombre décimal précis (ex: monétaire)
]


def quote(column):
    # Entoure un nom de colonne de guillemets doubles pour le SQL DuckDB
    # Échappe les guillemets doubles déjà présents dans le nom (norme SQL)
    # Ex: quote('ma colonne') → '"ma colonne"'
    # Ex: quote('col"nom') → '"col""nom"'
    return '"' + column.replace('"', '""') + '"'


def is_numeric(dtype):
    # Retourne True si le type DuckDB passé est un type numérique

    # Convertit en majuscules pour une comparaison insensible à la casse
    dtype = str(dtype).upper()

    # Exclut les types complexes comme LIST[INTEGER], STRUCT, MAP, UNION
    # qui peuvent contenir les mots-clés numériques mais ne sont pas numériques
    if dtype.endswith("]") or dtype.startswith(("STRUCT", "MAP", "UNION")):
        return False

    # Retourne True si au moins un type numérique est présent dans la chaîne
    # Ex: "DECIMAL(10,2)" → contient "DECIMAL" → True
    return any(t in dtype for t in NUMERIC_TYPES)


def describe(con, table_name):
    # Exécute DESCRIBE sur la table et retourne un DataFrame avec le schéma
    # Colonnes retournées : column_name, column_type, null, key, default, extra

    return con.execute(
        # DESCRIBE retourne les métadonnées des colonnes de la table
        f"DESCRIBE SELECT * FROM {get_source(table_name)}"
    ).fetchdf()  # Convertit le résultat en DataFrame pandas


# ============================================================
# STRUCTURE
# ============================================================


def inspect_table(table_name):
    # Retourne la structure complète d'une table : nb lignes, colonnes, schéma

    # Crée une connexion DuckDB dédiée à cette fonction
    con = create_connection()

    try:

        # Récupère l'expression SQL pour lire la table (read_parquet, read_csv_auto...)
        source = get_source(table_name)

        # Récupère le schéma (noms et types des colonnes) sous forme de DataFrame
        columns = describe(con, table_name)

        # Compte le nombre total de lignes dans la table
        count = con.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[
            0
        ]  # fetchone() retourne un tuple, [0] prend le premier élément

        # Retourne un dict avec toutes les informations structurelles
        return {
            "table": table_name,  # nom de la table
            "rows": int(count),  # nombre de lignes (int pour JSON)
            "columns": int(len(columns)),  # nombre de colonnes
            "schema": columns.to_dict(
                "records"
            ),  # liste de dicts {column_name, column_type...}
        }

    finally:
        # Ferme la connexion dans tous les cas (succès ou erreur)
        con.close()


# ============================================================
# VALEURS MANQUANTES
# ============================================================


def missing_values(table_name):
    # Compte les valeurs NULL pour chaque colonne de la table
    # Optimisé : une seule passe sur la table pour toutes les colonnes

    # Crée une connexion DuckDB dédiée
    con = create_connection()

    try:

        # Expression DuckDB pour lire la table
        source = get_source(table_name)

        # Récupère la liste des noms de colonnes
        columns = describe(con, table_name)["column_name"].tolist()

        # Construit une liste de SELECT :
        # - COUNT(*) compte toutes les lignes (y compris NULL)
        # - COUNT(colonne) ne compte que les valeurs NON NULL
        # Les alias c0, c1... permettent de différencier les colonnes
        selects = ["COUNT(*) AS total"] + [
            f"COUNT({quote(c)}) AS c{i}" for i, c in enumerate(columns)
        ]

        # Exécute une seule requête qui calcule tout en une passe
        # Plus efficace que N requêtes séparées
        row = con.execute(
            f"SELECT {', '.join(selects)} FROM {source}"
        ).fetchone()  # fetchone() car on attend exactement une ligne de résultat

        # Premier élément = COUNT(*) = nombre total de lignes
        total = row[0]

        # Liste qui contiendra les résultats pour chaque colonne
        results = []

        # Itère sur chaque colonne pour calculer les manquants
        for i, column in enumerate(columns):

            # row[i+1] = COUNT(colonne) = nombre de valeurs NON NULL
            # (+1 car row[0] est le total)
            non_null = row[i + 1]

            # Nombre de NULL = total - non_null
            missing = total - non_null

            # Pourcentage de NULL, arrondi à 3 décimales
            # Évite la division par zéro si la table est vide
            percentage = missing / total * 100 if total else 0

            # Ajoute le résultat pour cette colonne
            results.append(
                {
                    "column": column,
                    "missing": int(missing),  # nb de NULL
                    "missing_percent": round(percentage, 3),  # % de NULL
                }
            )

        # Retourne la liste complète des résultats par colonne
        return results

    finally:
        # Ferme la connexion dans tous les cas
        con.close()


# ============================================================
# DOUBLONS
# ============================================================


def duplicate_rows(table_name):
    # Détecte les lignes entièrement identiques (toutes colonnes confondues)

    # Crée une connexion DuckDB dédiée
    con = create_connection()

    try:

        # Expression DuckDB pour lire la table
        source = get_source(table_name)

        # Compte le nombre total de lignes (avec doublons)
        total = con.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0]

        # Compte le nombre de lignes distinctes (sans doublons)
        # SELECT DISTINCT * supprime les doublons exacts avant de compter
        distinct = con.execute(f"""
            SELECT COUNT(*)
            FROM (SELECT DISTINCT * FROM {source})
            """).fetchone()[0]

        # Retourne les 3 indicateurs de doublons
        return {
            "total_rows": int(total),  # toutes les lignes
            "distinct_rows": int(distinct),  # lignes uniques
            "duplicates": int(total - distinct),  # lignes en double
        }

    finally:
        # Ferme la connexion dans tous les cas
        con.close()


# ============================================================
# STATISTIQUES NUMERIQUES
# ============================================================


def numeric_statistics(table_name):
    # Calcule min, max, moyenne, médiane, écart-type pour chaque colonne numérique

    # Crée une connexion DuckDB dédiée
    con = create_connection()

    try:

        # Expression DuckDB pour lire la table
        source = get_source(table_name)

        # Récupère le schéma complet (noms + types de toutes les colonnes)
        schema = describe(con, table_name)

        # Liste qui contiendra les stats pour chaque colonne numérique
        results = []

        # Itère sur chaque ligne du schéma (= chaque colonne de la table)
        for _, row in schema.iterrows():

            # Nom de la colonne courante
            column = row["column_name"]

            # Saute les colonnes non numériques (texte, date, booléen...)
            if not is_numeric(row["column_type"]):
                continue

            # Entoure le nom de colonne de guillemets doubles pour le SQL
            c = quote(column)

            # Calcule les 5 statistiques en une seule requête SQL
            stats = con.execute(f"""
                SELECT
                    MIN({c}),        -- valeur minimale
                    MAX({c}),        -- valeur maximale
                    AVG({c}),        -- moyenne arithmétique
                    MEDIAN({c}),     -- médiane (valeur centrale)
                    STDDEV_SAMP({c}) -- écart-type (échantillon)
                FROM {source}
                """).fetchone()  # Une seule ligne de résultat attendue

            # Ajoute les stats pour cette colonne
            results.append(
                {
                    "column": column,
                    "min": stats[0],  # minimum
                    "max": stats[1],  # maximum
                    "mean": stats[2],  # moyenne
                    "median": stats[3],  # médiane
                    "stddev": stats[4],  # écart-type
                }
            )

        # Retourne la liste des stats pour toutes les colonnes numériques
        return results

    finally:
        # Ferme la connexion dans tous les cas
        con.close()


# ============================================================
# VALEURS DISTINCTES
# ============================================================


def cardinality(table_name):
    # Compte le nombre de valeurs uniques pour chaque colonne

    # Crée une connexion DuckDB dédiée
    con = create_connection()

    try:

        # Expression DuckDB pour lire la table
        source = get_source(table_name)

        # Récupère la liste des noms de colonnes
        columns = describe(con, table_name)["column_name"].tolist()

        # Construit une liste de COUNT(DISTINCT col) pour chaque colonne
        # Optimisé : une seule requête pour toutes les colonnes
        selects = [f"COUNT(DISTINCT {quote(c)})" for c in columns]

        # Exécute la requête unique qui compte les distincts pour toutes les colonnes
        row = con.execute(
            f"SELECT {', '.join(selects)} FROM {source}"
        ).fetchone()  # Une seule ligne de résultat

        # Construit la liste de résultats en associant chaque colonne à son compte
        return [
            {
                "column": column,
                "distinct_values": int(row[i]),  # int() pour compatibilité JSON
            }
            for i, column in enumerate(columns)
        ]

    finally:
        # Ferme la connexion dans tous les cas
        con.close()


# ============================================================
# VALEURS NEGATIVES
# ============================================================


def negative_values(table_name):
    # Compte les valeurs strictement négatives dans chaque colonne numérique
    # Retourne uniquement les colonnes qui ont au moins une valeur négative

    # Crée une connexion DuckDB dédiée
    con = create_connection()

    try:

        # Expression DuckDB pour lire la table
        source = get_source(table_name)

        # Récupère le schéma de la table
        schema = describe(con, table_name)

        # Filtre uniquement les colonnes numériques
        columns = [
            row["column_name"]
            for _, row in schema.iterrows()
            if is_numeric(row["column_type"])  # garde seulement les numériques
        ]

        # Si aucune colonne numérique, retourne une liste vide
        if not columns:
            return []

        # Construit les COUNT avec filtre < 0 pour chaque colonne numérique
        # FILTER (WHERE col < 0) est une syntaxe DuckDB/SQL standard
        selects = [f"COUNT(*) FILTER (WHERE {quote(c)} < 0)" for c in columns]

        # Exécute la requête unique qui compte les négatifs pour toutes les colonnes
        row = con.execute(f"SELECT {', '.join(selects)} FROM {source}").fetchone()

        # Retourne uniquement les colonnes qui ont au moins une valeur négative
        # if row[i] > 0 : filtre les colonnes sans aucun négatif
        return [
            {"column": column, "negative_values": int(row[i])}
            for i, column in enumerate(columns)
            if row[i] > 0  # exclut les colonnes sans valeur négative
        ]

    finally:
        # Ferme la connexion dans tous les cas
        con.close()


# ============================================================
# AUDIT GLOBAL
# ============================================================


def audit_table(table_name):
    # Lance tous les contrôles sur une table et retourne un dict consolidé

    # Affiche le nom de la table en cours d'audit dans le terminal
    print(f"Audit : {table_name}")

    # Exécute les 6 contrôles et les regroupe dans un seul dictionnaire
    return {
        "structure": inspect_table(table_name),  # nb lignes, colonnes, schéma
        "missing_values": missing_values(table_name),  # valeurs NULL par colonne
        "duplicates": duplicate_rows(table_name),  # lignes entièrement identiques
        "numeric_statistics": numeric_statistics(table_name),  # min/max/moyenne...
        "cardinality": cardinality(table_name),  # nb valeurs distinctes
        "negative_values": negative_values(table_name),  # valeurs < 0
    }


def audit_all_tables():
    """
    Audite toutes les tables connues.

    Une table qui pose problème reste présente dans le résultat :
    elle contient un champ "error" ainsi qu'une structure vide valide.

    Cela évite que l'interface web tente d'accéder à :
        audit[table]["structure"]["schema"]
    alors que la table est absente.
    """

    # Si aucune table n'a été trouvée, arrête le programme avec un message clair
    if not FILES:
        raise SystemExit(
            "Aucune table trouvée. Vérifiez le dossier de données "
            "(formats supportés : parquet, csv, tsv, json)."
        )

    # Résultats de toutes les tables
    results = {}

    # Parcourt toutes les tables détectées
    for table_name in FILES:

        try:
            # Audit normal de la table
            results[table_name] = audit_table(table_name)

        except Exception as error:
            # Affiche l'erreur réelle dans le terminal
            print(f"\n  ! ERREUR sur la table '{table_name}'")
            print(f"    {type(error).__name__} : {error}\n")

            # Important :
            # On conserve une entrée pour la table, avec tous les champs attendus
            # par les graphiques, le rapport HTML et l'interface JavaScript.
            results[table_name] = {
                # Le front-end pourra afficher cette erreur
                "error": str(error),
                # Structure minimale valide :
                # schema existe toujours, même en cas d'erreur.
                "structure": {
                    "table": table_name,
                    "rows": 0,
                    "columns": 0,
                    "schema": [],
                },
                # Résultats vides mais structurellement corrects
                "missing_values": [],
                "duplicates": {"total_rows": 0, "distinct_rows": 0, "duplicates": 0},
                "numeric_statistics": [],
                "cardinality": [],
                "negative_values": [],
            }

    return results


# ============================================================
# SAUVEGARDE JSON
# ============================================================


def save_audit(audit, output_file):
    # Sauvegarde le dict d'audit complet dans un fichier JSON

    # Ouvre le fichier en écriture avec encodage UTF-8
    with open(output_file, "w", encoding="utf-8") as f:

        # Écrit le JSON avec :
        # - ensure_ascii=False : garde les accents (é, à, ç...)
        # - indent=2 : indentation pour la lisibilité humaine
        # - default=str : convertit les types non-JSON (datetime, Decimal...) en string
        json.dump(audit, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# DISTRIBUTION D'UNE COLONNE (calculée à la demande)
# ============================================================


def column_distribution(table_name, column, bins=20, top=10):
    """
    Retourne de quoi tracer un graphique pour une colonne :
    - numérique  -> histogramme (bins intervalles)
    - date       -> répartition par année ou par mois
    - autre      -> top N valeurs les plus fréquentes
    """

    # Crée une connexion DuckDB dédiée
    con = create_connection()

    try:

        # Expression DuckDB pour lire la table
        source = get_source(table_name)

        # Récupère le schéma de la table
        schema = describe(con, table_name)

        # Cherche la colonne dans le schéma
        match = schema[schema["column_name"] == column]

        # Si la colonne n'existe pas, lève une erreur explicite
        if match.empty:
            raise ValueError(f"Colonne inconnue : {column}")

        # Récupère le type DuckDB de la colonne en majuscules
        dtype = str(match.iloc[0]["column_type"]).upper()

        # Entoure le nom de colonne de guillemets pour le SQL
        c = quote(column)

        # Compte les valeurs non-NULL pour vérifier si la colonne est vide
        non_null = con.execute(f"SELECT COUNT({c}) FROM {source}").fetchone()[0]

        # Initialise le résultat avec les informations communes
        result = {
            "column": column,  # nom de la colonne
            "type": dtype,  # type DuckDB
            "non_null": int(non_null),  # nb de valeurs non-NULL
        }

        # Si la colonne est entièrement vide, retourne un résultat "empty"
        if non_null == 0:
            result["kind"] = "empty"
            return result

        # ---------------- numérique ----------------

        # Si la colonne est numérique, calcule un histogramme
        if is_numeric(dtype):

            # Cast en DOUBLE pour uniformiser les calculs (DECIMAL, INTEGER...)
            x = f"CAST({c} AS DOUBLE)"

            # Condition WHERE : exclut les NULL et les infinis (isfinite)
            where = f"{c} IS NOT NULL AND isfinite({x})"

            # Calcule min, max et nombre de valeurs finies
            lo, hi, n = con.execute(f"""
                SELECT MIN({x}), MAX({x}), COUNT(*)
                FROM {source}
                WHERE {where}
                """).fetchone()

            # Si toutes les valeurs sont NULL après filtrage, retourne "empty"
            if lo is None:
                result["kind"] = "empty"
                return result

            # Indique que ce graphique est un histogramme
            result["kind"] = "histogram"

            # Cas particulier : toutes les valeurs sont identiques (un seul bin)
            if lo == hi:
                result["bins"] = [{"from": lo, "to": hi, "count": int(n)}]
                return result

            # Calcule la largeur de chaque intervalle
            width = (hi - lo) / bins

            # Calcule dans quel bin tombe chaque valeur
            # FLOOR((x - lo) / width) = numéro du bin (0 à bins-1)
            # LEAST(..., bins-1) : s'assure que le max tombe dans le dernier bin
            rows = con.execute(f"""
                SELECT
                    LEAST(
                        CAST(FLOOR(({x} - {lo!r}) / {width!r}) AS INTEGER),
                        {bins - 1}
                    ) AS b,
                    COUNT(*)
                FROM {source}
                WHERE {where}
                GROUP BY b
                ORDER BY b
                """).fetchall()

            # Convertit le résultat en dict {numéro_bin: count}
            counts = {int(b): int(k) for b, k in rows}

            # Construit la liste complète des bins (avec 0 pour les bins vides)
            result["bins"] = [
                {
                    "from": lo + i * width,  # borne inférieure du bin
                    "to": lo + (i + 1) * width,  # borne supérieure du bin
                    "count": counts.get(i, 0),  # 0 si aucune valeur dans ce bin
                }
                for i in range(bins)
            ]

            return result

        # ---------------- dates ----------------

        # Si la colonne est une date ou un timestamp, calcule une timeline
        if dtype == "DATE" or dtype.startswith("TIMESTAMP"):

            # Récupère l'année minimale et maximale pour choisir la granularité
            y0, y1 = con.execute(f"""
                SELECT
                    date_part('year', MIN({c})),
                    date_part('year', MAX({c}))
                FROM {source}
                """).fetchone()

            # Si l'écart est >= 2 ans : regroupement par année
            if y1 - y0 >= 2:
                expr = f"CAST(date_part('year', {c}) AS INTEGER)"
                unit = "year"
            else:
                # Sinon : regroupement par mois (format "YYYY-MM")
                expr = f"strftime({c}, '%Y-%m')"
                unit = "month"

            # Compte les enregistrements par période (année ou mois)
            rows = con.execute(f"""
                SELECT {expr} AS k, COUNT(*)
                FROM {source}
                WHERE {c} IS NOT NULL
                GROUP BY k
                ORDER BY k
                """).fetchall()

            # Indique que ce graphique est une timeline
            result["kind"] = "timeline"
            # Indique si les points sont des années ou des mois
            result["unit"] = unit
            # Liste des points {label: "2023", count: 150}
            result["points"] = [{"label": str(k), "count": int(n)} for k, n in rows]

            return result

        # ---------------- texte / autres ----------------

        # Pour les colonnes texte, booléen, etc. : top N valeurs les plus fréquentes
        rows = con.execute(f"""
            SELECT CAST({c} AS VARCHAR) AS v, COUNT(*) AS n
            FROM {source}
            WHERE {c} IS NOT NULL
            GROUP BY v
            ORDER BY n DESC, v   -- tri par fréquence décroissante, puis alphabétique
            LIMIT {int(top)}     -- garde seulement les top N valeurs
            """).fetchall()

        # Construit la liste des valeurs fréquentes (tronquées à 80 caractères)
        values = [{"value": str(v)[:80], "count": int(n)} for v, n in rows]

        # Indique que ce graphique est un top de valeurs
        result["kind"] = "top"
        # Liste des top N valeurs avec leur fréquence
        result["values"] = values
        # Nombre de valeurs non-NULL non représentées dans le top N
        result["others"] = int(non_null - sum(v["count"] for v in values))

        return result

    finally:
        # Ferme la connexion dans tous les cas
        con.close()
