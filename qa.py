# Importation de io pour créer des buffers en mémoire (export de fichiers)
import io

# Importation de json pour parser les réponses JSON du modèle
import json

# Importation de re pour les expressions régulières (validation SQL, parsing)
import re

# Importation de threading pour les timeouts de requêtes SQL
import threading

# Importation de Path pour manipuler les chemins de fichiers
from pathlib import Path

# Importation de requests pour les appels HTTP vers l'API Ollama
import requests

# Importation de la liste des tables et des paramètres Ollama
from config import FILES, OLLAMA_URL, MODEL

# Importation des fonctions d'accès à DuckDB
from database import create_connection, get_source

# Importation de la fonction quote pour sécuriser les noms de colonnes en SQL
from audit import quote

# ============================================================
# PARAMETRES
# ============================================================

# Nombre maximum de requêtes SQL que le modèle peut exécuter par question
MAX_STEPS = 6

# Nombre maximal d'instructions SQL exécutées pour une même étape (si le modèle en envoie plusieurs)
MAX_STATEMENTS = 3
# Nombre maximum de lignes retournées par une requête (protège la mémoire)
MAX_ROWS = 200
# Secondes avant d'interrompre une requête SQL trop longue
QUERY_TIMEOUT = 120
# Nombre de lignes de résultat montrées au modèle (les 60 premières)
LLM_ROWS = 60
# Taille maximale en caractères du résultat montré au modèle
LLM_CHARS = 6000

# Nombre maximum de lignes lors d'un export de données
EXPORT_MAX_ROWS = 1_000_000
# Secondes avant d'interrompre un export trop long
EXPORT_TIMEOUT = 600


# ============================================================
# SECURITE : LECTURE SEULE
# ============================================================

# Expression régulière qui liste les mots-clés SQL dangereux (écriture, admin...)
# re.I = insensible à la casse (DROP = drop = Drop)
# \b = word boundary : évite de bloquer "created_at" à cause de "create"
FORBIDDEN = re.compile(
    r"\b("
    r"attach|detach|copy|export|import|install|load|pragma|set|reset|"
    r"create|drop|alter|insert|update|delete|truncate|call|checkpoint|"
    r"vacuum|use|execute|prepare|glob|sniff_csv|getenv|current_setting|"
    r"getvariable|st_read|read_\w+|parquet_\w+|duckdb_\w+|pragma_\w+|"
    r"iceberg_\w+|delta_\w+"
    r")\b",
    re.I,
)

# Expression régulière qui détecte les lectures directes de fichiers dans le SQL
# Ex: FROM 'fichier.csv' ou JOIN "données.parquet"
FILE_SOURCE = re.compile(
    r"\b(from|join)\s+(?:'|\"[^\"]*\.(?:csv|tsv|txt|parquet|json|gz)\")", re.I
)


def scrub(sql):
    """Retire les commentaires et le contenu des chaînes avant contrôle."""

    # Fonction interne qui remplace les correspondances trouvées
    def repl(m):
        t = m.group(0)
        # Remplace le contenu d'une chaîne 'simple' par une chaîne vide ''
        if t[0] == "'":
            return "''"
        # Remplace le contenu d'une chaîne "double" par une chaîne vide ""
        if t[0] == '"':
            return '""'
        # Remplace un commentaire (-- ou /* */) par un espace
        return " "

    # Applique le remplacement sur :
    # - les chaînes entre apostrophes : '...'
    # - les chaînes entre guillemets : "..."
    # - les commentaires inline : -- commentaire
    # - les commentaires blocs : /* commentaire */
    # re.S = le point matche aussi les retours à la ligne (pour /* ... */)
    return re.sub(
        r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", repl, sql, flags=re.S
    )


# Reconnaît une chaîne, un identifiant entre guillemets ou un commentaire (comme scrub)
TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.S)


def strip_tail(sql):
    """Retire à la fin du SQL les « ; » et les commentaires (ex : « ...; -- explication »)."""

    while True:
        # Retire les espaces de fin
        sql = sql.rstrip()

        # Retire un point-virgule final
        if sql.endswith(";"):
            sql = sql[:-1]
            continue

        # Retire un commentaire placé tout à la fin (-- ... ou /* ... */)
        last = None
        for m in TOKEN.finditer(sql):
            last = m
        if last and last.end() == len(sql) and last.group(0)[0] in "-/":
            sql = sql[: last.start()]
            continue

        # Plus rien à retirer
        return sql


def split_statements(sql):
    """Découpe un SQL en instructions séparées par « ; » (hors chaînes et commentaires)."""

    # Remplace chaînes et commentaires par des « x » de même longueur : leurs « ; » sont ignorés
    masked = TOKEN.sub(lambda m: "x" * len(m.group(0)), sql)

    # Coupe le SQL d'origine aux « ; » trouvés dans la version masquée
    parts, start = [], 0
    for m in re.finditer(";", masked):
        parts.append(sql[start : m.start()])
        start = m.end()
    parts.append(sql[start:])

    # Ignore les morceaux vides ou ne contenant que des commentaires
    return [p.strip() for p in parts if scrub(p).strip()]


def validate(sql):
    # Vérifie qu'une requête SQL est sûre (lecture seule) avant exécution

    # Supprime les espaces, les ; finaux et les commentaires de fin
    sql = strip_tail((sql or "").strip()).strip()

    # Rejette les requêtes vides
    if not sql:
        raise ValueError("Requête vide.")

    # Nettoie le SQL des chaînes et commentaires pour l'analyse de sécurité
    clean = scrub(sql)

    # Interdit les requêtes multiples (séparées par ;)
    if ";" in clean:
        # Montre l'endroit du « ; » pour que le modèle (et vous) voient quoi corriger
        i = clean.index(";")
        extrait = " ".join(clean[max(0, i - 30) : i + 30].split())
        raise ValueError(
            "Une seule requête à la fois : un « ; » a été trouvé au milieu du SQL "
            f"(…{extrait}…). Retire-le, ainsi que tout texte après le « ; »."
        )

    # Extrait le premier mot-clé de la requête
    first = re.match(r"\s*(\w+)", clean)

    # Vérifie que la requête commence par un mot-clé de lecture autorisé
    if not first or first.group(1).lower() not in {
        "select",
        "with",
        "describe",
        "summarize",
        "from",
    }:
        raise ValueError(
            "Seules les requêtes de lecture (SELECT / WITH / DESCRIBE) "
            "sont autorisées."
        )

    # Recherche un mot-clé dangereux dans le SQL nettoyé
    bad = FORBIDDEN.search(clean)

    # Si un mot-clé dangereux est trouvé, lève une erreur explicite
    if bad:
        raise ValueError(
            f"Mot-clé ou fonction non autorisé : {bad.group(0)}. "
            "Seules les tables fournies peuvent être interrogées "
            "(si c'est un nom de colonne, mets-le entre guillemets doubles)."
        )

    # Interdit la lecture directe de fichiers dans le SQL
    if FILE_SOURCE.search(sql):
        raise ValueError(
            "La lecture directe de fichiers est interdite : "
            "utilise les tables fournies."
        )

    # Retourne le SQL validé et nettoyé (sans le ; final)
    return sql


# ============================================================
# CONNEXION : UNE VUE PAR TABLE IMPORTEE
# ============================================================


def open_connection():
    """
    Retourne (connexion, verrouillée).
    Si DuckDB le permet, l'accès aux fichiers est fermé, sauf pour
    les fichiers importés : même une requête qui passerait le
    contrôle ne pourrait pas lire autre chose.
    """

    # Copie locale du dict FILES pour éviter les modifications concurrentes
    files = dict(FILES)

    def build(lock):
        # Construit la connexion DuckDB avec ou sans verrouillage des fichiers

        # Crée une connexion DuckDB standard
        con = create_connection()

        # Crée une vue SQL pour chaque table importée
        # Permet d'accéder aux tables par leur nom sans chemin de fichier
        for name in files:
            con.execute(
                f"CREATE VIEW {quote(name)} AS "
                f"SELECT * FROM {get_source(name)}"
                # Ex: CREATE VIEW "clients" AS SELECT * FROM read_parquet('/path/to/clients.parquet')
            )

        # Si lock=True, tente de restreindre l'accès aux fichiers non importés
        if lock:

            # Construit la liste des chemins autorisés (les fichiers importés uniquement)
            paths = ",".join(
                "'" + Path(p).as_posix().replace("'", "''") + "'"
                for p in files.values()
            )

            # Restreint DuckDB aux chemins listés uniquement
            con.execute(f"SET allowed_paths=[{paths}]")
            # Désactive l'accès aux fichiers et URLs externes
            con.execute("SET enable_external_access=false")
            # Verrouille la configuration pour empêcher toute modification ultérieure
            con.execute("SET lock_configuration=true")

            # Teste que les tables importées sont encore lisibles après verrouillage
            first = next(iter(files))
            con.execute(f"SELECT * FROM {quote(first)} LIMIT 1").fetchall()

        return con

    try:
        # Tente de créer une connexion verrouillée (plus sécurisée)
        return build(True), True

    except Exception:
        # Si le verrouillage échoue (ancienne version DuckDB), crée sans verrou
        return build(False), False


# ============================================================
# EXECUTION D'UNE REQUETE
# ============================================================


def run_query(con, sql):
    # Exécute une requête SQL avec timeout et limite de lignes

    # Valide et nettoie la requête avant exécution
    sql = validate(sql)

    # Lance un timer qui interrompra la requête après QUERY_TIMEOUT secondes
    # con.interrupt() est la méthode DuckDB pour interrompre une requête en cours
    timer = threading.Timer(QUERY_TIMEOUT, con.interrupt)
    timer.start()

    try:

        # Encapsule la requête dans un SELECT avec LIMIT pour éviter les résultats géants
        # MAX_ROWS + 1 : récupère une ligne de plus pour détecter si le résultat est tronqué
        cur = con.execute(f"SELECT * FROM (\n{sql}\n) AS q LIMIT {MAX_ROWS + 1}")

        # Extrait les noms des colonnes depuis la description du curseur
        columns = [d[0] for d in cur.description]

        # Récupère toutes les lignes du résultat
        rows = cur.fetchall()

    except Exception as e:

        # Si l'erreur est due au timeout, donne un message clair à l'utilisateur
        if "INTERRUPT" in str(e).upper():
            raise ValueError(
                f"Requête interrompue (plus de {QUERY_TIMEOUT} s). "
                "Filtre davantage ou agrège."
            )

        # Pour toute autre erreur SQL, retourne seulement la première ligne du message
        raise ValueError(str(e).split("\n")[0])

    finally:
        # Annule le timer si la requête s'est terminée avant le timeout
        timer.cancel()

    # True si le résultat contient plus de MAX_ROWS lignes (il a été tronqué)
    truncated = len(rows) > MAX_ROWS

    # Retourne les colonnes, les lignes (limitées à MAX_ROWS) et l'indicateur de troncature
    return columns, rows[:MAX_ROWS], truncated


# ============================================================
# MISE EN FORME POUR LE MODELE
# ============================================================


def short(value, size=40):
    # Tronque une valeur à `size` caractères pour l'affichage dans le prompt

    # Représente NULL comme la chaîne "NULL"
    if value is None:
        return "NULL"

    # Convertit en string et remplace les retours à la ligne par des espaces
    text = str(value).replace("\n", " ")

    # Retourne la valeur telle quelle si elle est courte, sinon tronque avec "…"
    return text if len(text) <= size else text[:size] + "…"


def describe_schema(con, files):
    # Construit une description textuelle du schéma et d'exemples pour le prompt système

    # Liste qui contiendra la description de chaque table
    parts = []

    # Itère sur chaque table importée
    for name in files:

        # Récupère les colonnes et leurs types via DESCRIBE
        columns = con.execute(f"DESCRIBE {quote(name)}").fetchall()

        # Compte le nombre de lignes dans la table
        count = con.execute(f"SELECT COUNT(*) FROM {quote(name)}").fetchone()[0]

        # Récupère 3 exemples de lignes pour aider le modèle à comprendre les données
        sample = con.execute(f"SELECT * FROM {quote(name)} LIMIT 3").fetchall()

        # Construit la description textuelle de cette table
        parts.append(
            # En-tête : nom de la table et nb de lignes
            f'TABLE "{name}" ({count} lignes)\n'
            # Liste des colonnes avec leur type
            "  colonnes : "
            + ", ".join(f'"{c[0]}" {c[1]}' for c in columns)
            # Exemples de lignes (valeurs tronquées à 40 chars)
            + "\n  exemples (3 premières lignes, même ordre) :\n"
            + "\n".join("    " + " | ".join(short(v) for v in row) for row in sample)
        )

    # Joint les descriptions de toutes les tables avec une ligne vide entre elles
    return "\n\n".join(parts)


def result_text(columns, rows, truncated):
    # Formate le résultat d'une requête en texte lisible pour le modèle

    # Première ligne = noms des colonnes séparés par " | "
    lines = [" | ".join(columns)]

    # Ajoute les lignes de données (limitées à LLM_ROWS pour ne pas surcharger le prompt)
    for row in rows[:LLM_ROWS]:
        # Chaque valeur est tronquée à 60 caractères
        lines.append(" | ".join(short(v, 60) for v in row))

    # Joint toutes les lignes et tronque à LLM_CHARS caractères
    text = "\n".join(lines)[:LLM_CHARS]

    # Construit la note de bas de résultat
    note = f"\n({len(rows)} ligne(s)"

    # Indique si le résultat a été tronqué à MAX_ROWS lignes
    if truncated:
        note += f", résultat tronqué à {MAX_ROWS} lignes"

    # Indique si seules les LLM_ROWS premières lignes sont montrées
    if len(rows) > LLM_ROWS:
        note += f", seules les {LLM_ROWS} premières sont montrées ici"

    # Retourne le texte formaté avec l'en-tête "RÉSULTAT :"
    return "RÉSULTAT :\n" + text + note + ")"


# ============================================================
# DIALOGUE AVEC OLLAMA
# ============================================================


def build_system(schema, context):
    # Construit le prompt système pour le chatbot Q&A (différent de l'audit)

    # Initialise le bloc de contexte métier à vide
    extra = ""

    # Si un contexte métier est fourni, le formate pour l'inclure dans le prompt
    if context and context.strip():
        extra = f"\nCONTEXTE DONNÉ PAR L'UTILISATEUR : {context.strip()}\n"

    # ------------------------------------------------------------------
    # RÈGLES DU DIALOGUE
    # Si vous aviez votre propre texte, remplacez le contenu de `rules` par le vôtre
    # (gardez le format JSON {"sql": ...} / {"answer": ...} attendu par parse_reply).
    # ------------------------------------------------------------------
    rules = (
        "Tu es un analyste de données. Tu réponds aux questions de l'utilisateur en "
        "interrogeant des tables avec DuckDB.\n\n"
        "FORMAT DE RÉPONSE (obligatoire) : réponds UNIQUEMENT par un objet JSON, sans aucun "
        "texte autour :\n"
        '- {"sql": "SELECT ..."} pour exécuter UNE requête ;\n'
        '- {"answer": "..."} pour donner la réponse finale.\n\n'
        "RÈGLES SQL :\n"
        "1. Une seule requête par étape : une seule instruction SELECT (ou WITH), sans « ; » "
        "au milieu et sans commentaires (-- ou /* */). Pour plusieurs calculs, fais plusieurs "
        "étapes ou regroupe-les dans un seul SELECT.\n"
        "2. Lecture seule : SELECT ou WITH uniquement. Interroge seulement les tables "
        "listées ci-dessous, avec leur nom exact.\n"
        '3. Mets tous les identifiants (tables, colonnes) entre guillemets doubles, par exemple "Volume (m3)".\n'
        "4. Pour chercher un texte, utilise ILIKE avec strip_accents (recherche insensible aux "
        "accents), par exemple strip_accents(\"col\") ILIKE '%agapetus%'.\n"
        "5. Convertis les nombres et les dates avec TRY_CAST.\n"
        "6. Si une requête renvoie une erreur, corrige-la. Si elle ne renvoie aucune ligne, "
        "élargis la recherche (autre colonne, ILIKE plus large).\n"
        "7. Ne jamais inventer un chiffre : n'utilise que les résultats des requêtes.\n\n"
        f"Tu disposes de {MAX_STEPS} étapes au maximum ; les résultats te sont renvoyés "
        f"limités à {LLM_ROWS} lignes.\n\n"
        "RÉPONSE FINALE : donne d'abord la valeur ou le résultat, puis la méthode (tables, "
        "colonnes, filtres, période) et les limites éventuelles (unité, nombre de mesures, "
        "résultat tronqué)."
    )

    # Retourne le prompt système complet avec les règles, le contexte et le schéma
    return f"""{rules}
{extra}
TABLES DISPONIBLES :

{schema}
"""


def chat(messages, model=None):
    # Envoie une liste de messages à Ollama et retourne la réponse textuelle

    # Envoie la requête POST à l'API Ollama avec la liste complète des messages
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model or MODEL,  # modèle à utiliser
            "messages": messages,  # historique complet de la conversation
            "stream": False,  # attend la réponse complète
        },
        timeout=900,  # timeout de 15 minutes pour les questions complexes
    )

    # Lève une exception si le code HTTP est >= 400
    response.raise_for_status()

    # Extrait et retourne uniquement le texte de la réponse
    return response.json()["message"]["content"]


def clean_sql(sql):
    """
    Retire les échappements en trop ajoutés par certains modèles dans le SQL :
    SELECT \\"Année\\" ... devient SELECT "Année" ... (le backslash provoque
    « Parser Error: syntax error at or near \\ » dans DuckDB).
    """

    # Le modèle double parfois l'échappement JSON : \" au lieu de "
    sql = str(sql).replace('\\"', '"')

    # Découpe le SQL en morceaux : les chaînes entre apostrophes restent intactes
    parts = re.split(r"('(?:[^']|'')*')", sql)

    # Hors des chaînes : \n, \t et \r écrits littéralement deviennent de vrais caractères
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "")

    # Recolle les morceaux et retire les espaces superflus
    return "".join(parts).strip()


def parse_reply(text):
    """Extrait le premier objet JSON de la réponse du modèle."""

    # Crée un décodeur JSON standard
    decoder = json.JSONDecoder()

    # Cherche la position du premier { dans le texte
    start = text.find("{")

    # Boucle tant qu'on trouve un { dans le texte
    while start != -1:

        try:
            # Tente de parser un objet JSON à partir de la position `start`
            # raw_decode retourne (objet, position_fin)
            obj, _ = decoder.raw_decode(text, start)

            # Si c'est bien un dict (pas un tableau ou une valeur simple), le retourne
            if isinstance(obj, dict):
                return obj

        except ValueError:
            # Le JSON n'est pas valide à cette position, cherche le prochain {
            pass

        # Cherche le prochain { après la position courante
        start = text.find("{", start + 1)

    # Fallback 1 : cherche un bloc ```sql ... ``` si pas de JSON trouvé
    match = re.search(r"```sql\s*(.*?)```", text, re.S | re.I)

    # Si un bloc SQL est trouvé, le retourne comme une requête SQL
    if match:
        return {"sql": match.group(1)}

    # Fallback 2 : retourne le texte brut comme réponse finale
    return {"answer": text}


# ============================================================
# QUESTION -> REPONSE
# ============================================================


def ask_data(question, model=None, history=None, context=""):
    # Répond à une question en langage naturel en exécutant des requêtes SQL

    # Copie locale du dict FILES
    files = dict(FILES)

    # Vérifie qu'au moins une table est disponible
    if not files:
        raise ValueError("Aucune table importée.")

    # Ouvre une connexion DuckDB sécurisée avec vues sur les tables importées
    con, locked = open_connection()

    try:

        # Construit la description textuelle du schéma (noms, types, exemples)
        schema = describe_schema(con, files)

        # Initialise l'historique de conversation avec le prompt système
        messages = [{"role": "system", "content": build_system(schema, context)}]

        # La question devient le prompt initial
        prompt = question

        # Si un historique de conversation existe, l'ajoute au prompt
        if history:
            # Prend les 3 derniers échanges pour le contexte (évite les prompts trop longs)
            previous = "\n\n".join(
                f"Question : {h.get('q', '')}\nRéponse : {h.get('a', '')[:1500]}"
                for h in history[-3:]
            )
            # Préfixe le prompt avec l'historique des échanges précédents
            prompt = (
                "Échanges précédents (pour le contexte) :\n"
                f"{previous}\n\nNouvelle question : {question}"
            )

        # Ajoute la question de l'utilisateur à l'historique de messages
        messages.append({"role": "user", "content": prompt})

        # Liste qui enregistre toutes les étapes SQL exécutées
        steps = []

        # Boucle jusqu'à MAX_STEPS requêtes SQL + 1 message de forçage de conclusion
        for i in range(MAX_STEPS + 1):

            # True si on a atteint la limite : force une réponse finale
            final = i == MAX_STEPS

            # Si on a atteint la limite, envoie un message pour forcer la conclusion
            if final:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Limite de requêtes atteinte. Donne maintenant ta "
                            'meilleure réponse finale au format {"answer": ...}, '
                            "sans nouvelle requête, en indiquant ce qui reste "
                            "incertain."
                        ),
                    }
                )

            # Envoie les messages à Ollama et récupère la réponse
            reply = chat(messages, model)

            # Parse la réponse JSON du modèle : {"sql": "..."} ou {"answer": "..."}
            message = parse_reply(reply)

            # Extrait la requête SQL si le modèle en a fourni une
            sql = message.get("sql")

            # Nettoie les échappements en trop (\\" -> ") avant validation et exécution
            if sql:
                sql = clean_sql(sql)

            # Si le modèle propose une requête SQL et qu'on n'a pas atteint la limite
            if sql and not final:

                # Ajoute la requête SQL à l'historique (côté assistant)
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps({"sql": sql}, ensure_ascii=False),
                    }
                )

                # Découpe le SQL en instructions : le modèle en envoie parfois plusieurs d'un coup
                statements = split_statements(sql) or [sql]
                skipped = statements[MAX_STATEMENTS:]
                statements = statements[:MAX_STATEMENTS]

                # Exécute chaque instruction séparément (chacune est validée en lecture seule)
                parts = []
                for statement in statements:

                    # Enregistre cette étape SQL pour la retourner à l'interface
                    step = {"sql": statement.strip()}

                    try:
                        # Exécute la requête SQL sur DuckDB
                        columns, rows, truncated = run_query(con, statement)

                        # Stocke le résultat dans l'étape (50 lignes max pour l'interface)
                        step.update(
                            {
                                "columns": columns,
                                "rows": [list(r) for r in rows[:50]],
                                "row_count": len(rows),
                                "truncated": truncated,
                            }
                        )

                        # Formate le résultat en texte pour le modèle
                        parts.append(result_text(columns, rows, truncated))

                    except Exception as e:
                        # En cas d'erreur SQL, enregistre l'erreur dans l'étape
                        step["error"] = str(e)

                        # Prépare l'erreur pour que le modèle corrige sa requête
                        parts.append(f"ERREUR : {e}")

                    # Ajoute l'étape à la liste des étapes
                    steps.append(step)

                # Message renvoyé au modèle pour la prochaine itération
                if len(parts) == 1 and not skipped:
                    feedback = parts[0]
                else:
                    feedback = "\n\n".join(
                        f"Résultat de la requête {n} :\n{p}"
                        for n, p in enumerate(parts, start=1)
                    )
                    feedback += (
                        "\n\nTes requêtes ont été exécutées séparément. La prochaine fois, "
                        "envoie UNE seule requête par étape, sans commentaires."
                    )
                    if skipped:
                        feedback += f" {len(skipped)} requête(s) en trop n'ont pas été exécutées."

                messages.append({"role": "user", "content": feedback})

                # Continue la boucle pour la prochaine requête SQL
                continue

            # Si le modèle fournit une réponse finale ({"answer": "..."})
            answer = message.get("answer")

            # Si pas de réponse, génère un message d'erreur par défaut
            if not answer:
                answer = (
                    f"Le modèle n'a pas pu conclure après {len(steps)} "
                    "requête(s). Consultez les requêtes exécutées ci-dessous."
                )

            # Convertit la réponse en string si ce n'est pas déjà le cas
            if not isinstance(answer, str):
                answer = json.dumps(answer, ensure_ascii=False)

            # Retourne la réponse finale avec les étapes SQL et l'état du verrou
            return {"answer": answer, "steps": steps, "locked": locked}

    finally:
        # Ferme la connexion dans tous les cas
        con.close()


# ============================================================
# EXPORT DU RESULTAT COMPLET D'UNE REQUETE
# ============================================================


def export_result(sql, fmt="csv"):
    """
    Exécute une requête et retourne le résultat complet sous forme de fichier.
    Formats supportés : csv, xlsx, parquet.
    """

    # Normalise le format en minuscules
    fmt = (fmt or "csv").lower()

    # Vérifie que le format demandé est supporté
    if fmt not in ("csv", "xlsx", "parquet"):
        raise ValueError("Format d'export inconnu (csv, xlsx ou parquet).")

    # Valide la requête SQL (sécurité : lecture seule)
    sql = validate(sql)

    # Initialise la variable pour les caractères illégaux Excel
    illegal = None

    # Si le format est Excel, importe openpyxl pour la gestion des caractères illégaux
    if fmt == "xlsx":

        try:
            # Importe la regex des caractères interdits dans les cellules Excel
            from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE as illegal

        except ImportError:
            # Si openpyxl n'est pas installé, lève une erreur claire
            raise ValueError(
                "Export Excel indisponible : installez openpyxl "
                "(pip install openpyxl)."
            )

    # Ouvre une connexion DuckDB sécurisée
    con, _ = open_connection()

    # Lance un timer pour interrompre l'export si trop long
    timer = threading.Timer(EXPORT_TIMEOUT, con.interrupt)
    timer.start()

    try:

        # Exécute la requête et récupère le résultat complet en DataFrame pandas
        # EXPORT_MAX_ROWS + 1 pour détecter si le résultat est tronqué
        df = con.execute(
            f"SELECT * FROM (\n{sql}\n) AS q LIMIT {EXPORT_MAX_ROWS + 1}"
        ).fetchdf()

    except Exception as e:

        # Si l'erreur est due au timeout, donne un message clair
        if "INTERRUPT" in str(e).upper():
            raise ValueError(
                f"Export interrompu (plus de {EXPORT_TIMEOUT} s). "
                "Filtre davantage la requête."
            )

        # Pour toute autre erreur, retourne la première ligne du message
        raise ValueError(str(e).split("\n")[0])

    finally:
        # Annule le timer si l'export s'est terminé avant le timeout
        timer.cancel()
        # Ferme la connexion dans tous les cas
        con.close()

    # True si le résultat dépasse EXPORT_MAX_ROWS lignes
    truncated = len(df) > EXPORT_MAX_ROWS

    # Si tronqué, garde seulement les EXPORT_MAX_ROWS premières lignes
    if truncated:
        df = df.iloc[:EXPORT_MAX_ROWS]

    # Nettoyage pour la compatibilité Excel
    for column in df.columns:

        # Récupère le type pandas de la colonne
        dtype = str(df[column].dtype)

        # Excel ne supporte pas les datetime avec timezone : supprime le timezone
        if (
            dtype.startswith("datetime64")
            and getattr(df[column].dt, "tz", None) is not None
        ):
            df[column] = df[column].dt.tz_localize(None)

        # Si Excel et colonne texte : supprime les caractères interdits par Excel
        if illegal is not None and dtype == "object":
            df[column] = df[column].map(
                lambda v: illegal.sub("", v) if isinstance(v, str) else v
            )

    # Buffer en mémoire pour écrire le fichier sans créer de fichier temporaire
    buffer = io.BytesIO()

    # Export en CSV UTF-8
    if fmt == "csv":
        df.to_csv(buffer, index=False, encoding="utf-8")
        # Type MIME pour indiquer au navigateur que c'est un fichier CSV
        mime = "text/csv; charset=utf-8"

    # Export en Excel (.xlsx)
    elif fmt == "xlsx":
        df.to_excel(buffer, index=False, sheet_name="Resultat")
        # Type MIME officiel pour les fichiers Excel .xlsx
        mime = "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"

    # Export en Parquet (format colonnaire binaire)
    else:
        df.to_parquet(buffer, index=False)
        # Type MIME générique pour les fichiers binaires
        mime = "application/octet-stream"

    # Retourne les octets du fichier, le type MIME, le nb de lignes et l'indicateur de troncature
    return buffer.getvalue(), mime, len(df), truncated
