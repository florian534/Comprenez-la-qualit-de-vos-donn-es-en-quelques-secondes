# Importation de Path pour manipuler les chemins de fichiers
from pathlib import Path

# Importation de datetime pour horodater le rapport
from datetime import datetime

# Importation de escape pour sécuriser les chaînes insérées dans le HTML
from html import escape

# Importation de la bibliothèque markdown pour convertir le texte Markdown en HTML
import markdown

# ============================================================
# FORMATAGE
# ============================================================


def format_number(value):
    # Formate un nombre avec des espaces comme séparateurs de milliers
    # Ex: 1234567 → "1 234 567"

    # Retourne un tiret si la valeur est None
    if value is None:
        return "—"

    try:

        # Si c'est un float
        if isinstance(value, float):

            # Si c'est un entier déguisé en float (ex: 5.0), formate comme entier
            if value.is_integer():
                return f"{int(value):,}".replace(",", " ")

            # Sinon formate avec 2 décimales et séparateurs de milliers
            return f"{value:,.2f}".replace(",", " ")

        # Pour les entiers : formate avec séparateurs de milliers
        return f"{int(value):,}".replace(",", " ")

    except (ValueError, TypeError):
        # Si la conversion échoue, retourne la valeur convertie en string
        return str(value)


def format_percent(value):
    # Formate un pourcentage avec 2 décimales
    # Ex: 12.3456 → "12.35 %"

    # Retourne un tiret si la valeur est None
    if value is None:
        return "—"

    try:
        # Formate avec 2 décimales et le symbole %
        return f"{float(value):.2f} %"

    except (ValueError, TypeError):
        # Si la conversion échoue, retourne la valeur convertie en string
        return str(value)


def markdown_to_html(text):
    # Convertit un texte Markdown en HTML pour l'affichage dans le rapport

    # Si le texte est vide ou None, retourne un message par défaut
    if not text:
        return """
        <div class="empty-state">
            Aucune analyse IA disponible.
        </div>
        """

    # Convertit le Markdown en HTML avec les extensions :
    # - "tables" : supporte les tableaux Markdown (| col1 | col2 |)
    # - "fenced_code" : supporte les blocs de code ```python ... ```
    return markdown.markdown(str(text), extensions=["tables", "fenced_code"])


# ============================================================
# KPI
# ============================================================


def get_kpis(audit):
    # Calcule les 6 indicateurs clés affichés en haut du rapport HTML

    # Initialise les KPIs à 0
    kpis = {
        "tables": 0,  # nombre de tables auditées
        "rows": 0,  # nombre total de lignes
        "columns": 0,  # nombre total de colonnes
        "missing": 0,  # nombre total de valeurs manquantes
        "duplicates": 0,  # nombre total de doublons
        "negative": 0,  # nombre total de valeurs négatives
    }

    # Vérifie que l'audit est bien un dict
    if not isinstance(audit, dict):
        return kpis

    # Itère sur chaque table de l'audit
    for table_name, data in audit.items():

        # Ignore les tables dont les données ne sont pas un dict
        if not isinstance(data, dict):
            continue

        # Incrémente le compteur de tables
        kpis["tables"] += 1

        # Récupère les informations de structure
        structure = data.get("structure", {})

        if isinstance(structure, dict):

            # Nombre de lignes de cette table
            rows = structure.get("rows", 0)
            # Nombre de colonnes de cette table
            columns = structure.get("columns", 0)

            # Ajoute au total en gérant les erreurs de conversion
            try:
                kpis["rows"] += int(rows or 0)
            except (ValueError, TypeError):
                pass

            try:
                kpis["columns"] += int(columns or 0)
            except (ValueError, TypeError):
                pass

        # ----------------------------------------------------
        # VALEURS MANQUANTES
        # ----------------------------------------------------

        # Récupère la liste des valeurs manquantes
        missing = data.get("missing_values", [])

        if isinstance(missing, list):

            # Itère sur chaque colonne
            for item in missing:

                if not isinstance(item, dict):
                    continue

                # Ajoute le nombre de manquants de cette colonne au total
                count = item.get("missing", 0)

                try:
                    kpis["missing"] += int(count or 0)
                except (ValueError, TypeError):
                    pass

        # ----------------------------------------------------
        # DOUBLONS
        # ----------------------------------------------------

        # Récupère le dict des doublons
        duplicates = data.get("duplicates", {})

        if isinstance(duplicates, dict):

            # Ajoute le nombre de doublons de cette table au total
            count = duplicates.get("duplicates", 0)

            try:
                kpis["duplicates"] += int(count or 0)
            except (ValueError, TypeError):
                pass

        # ----------------------------------------------------
        # NEGATIFS
        # ----------------------------------------------------

        # Récupère la liste des valeurs négatives
        negative = data.get("negative_values", [])

        if isinstance(negative, list):

            # Itère sur chaque colonne avec des valeurs négatives
            for item in negative:

                if not isinstance(item, dict):
                    continue

                # Ajoute le nombre de valeurs négatives au total
                count = item.get("negative_values", 0)

                try:
                    kpis["negative"] += int(count or 0)
                except (ValueError, TypeError):
                    pass

    # Retourne le dict des KPIs calculés
    return kpis


# ============================================================
# TABLE HTML
# ============================================================


def simple_table(headers, rows):
    # Génère une table HTML à partir d'une liste d'en-têtes et de lignes de données

    # Si pas d'en-têtes, retourne un message "aucune donnée"
    if not headers:

        return """
        <div class="empty-state">
            Aucune donnée disponible.
        </div>
        """

    # Ouvre le div wrapper avec défilement horizontal si la table est large
    html = '<div class="table-wrapper">'
    # Ouvre la balise table avec la classe CSS
    html += '<table class="app-table">'

    # Génère l'en-tête de la table (thead)
    html += "<thead><tr>"

    # Ajoute une cellule d'en-tête pour chaque colonne
    for header in headers:
        # escape() empêche les injections HTML dans les noms de colonnes
        html += f"<th>{escape(str(header))}</th>"

    html += "</tr></thead>"

    # Ouvre le corps de la table (tbody)
    html += "<tbody>"

    # Si pas de données, affiche un message centré sur toute la largeur
    if not rows:

        html += f"""
        <tr>
            <td colspan="{len(headers)}" class="empty-table">
                Aucune donnée.
            </td>
        </tr>
        """

    else:

        # Génère une ligne HTML pour chaque ligne de données
        for row in rows:

            html += "<tr>"

            # Génère une cellule pour chaque valeur de la ligne
            for value in row:

                # Remplace None par un tiret pour l'affichage
                if value is None:
                    value = "—"

                # escape() empêche les injections HTML dans les valeurs
                html += f"<td>{escape(str(value))}</td>"

            html += "</tr>"

    # Ferme le tbody, la table et le wrapper
    html += "</tbody>"
    html += "</table>"
    html += "</div>"

    return html


# ============================================================
# RAPPORT
# ============================================================


def generate_report(audit, analysis, output_file, project_name="Base de données"):
    # Génère le rapport HTML complet et l'écrit sur disque

    # Convertit en objet Path si ce n'est pas déjà le cas
    output_file = Path(output_file)

    # Nombre de tables auditées (0 si audit n'est pas un dict)
    n_tables = len(audit) if isinstance(audit, dict) else 0

    # Crée le dossier de sortie s'il n'existe pas
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Calcule les 6 KPIs pour les afficher en haut du rapport
    kpis = get_kpis(audit)

    # Convertit le rapport Markdown de l'IA en HTML
    analysis_html = markdown_to_html(analysis)

    # Formate la date et l'heure de génération du rapport
    generated_at = datetime.now().strftime(
        "%d/%m/%Y à %H:%M"  # Ex: "19/10/2026 à 14:32"
    )

    # Début du document HTML avec le DOCTYPE, head, styles CSS et début du body
    # __PROJECT__ et __N_TABLES__ sont des placeholders remplacés à la fin
    html = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Audit automatisé - __PROJECT__</title>
<style>
/* [... styles CSS identiques ...] */
</style>
</head>
<body>
[... structure HTML identique ...]
"""

    # ========================================================
    # VUE GENERALE
    # ========================================================

    # Ajoute la section "Vue générale" avec l'ancre #overview
    html += """
<section class="section" id="overview">
<h2>Vue générale</h2>
"""

    # Ouvre la grille de KPIs (6 colonnes)
    html += '<div class="kpi-grid">'

    # Définit les 6 KPIs à afficher avec leurs labels et valeurs
    kpi_items = [
        ("Tables", kpis["tables"]),  # nombre de tables
        ("Lignes", kpis["rows"]),  # nombre total de lignes
        ("Colonnes", kpis["columns"]),  # nombre total de colonnes
        ("Valeurs manquantes", kpis["missing"]),  # total de NULL
        ("Doublons", kpis["duplicates"]),  # total de doublons
        ("Valeurs négatives", kpis["negative"]),  # total de valeurs < 0
    ]

    # Génère une carte KPI pour chaque indicateur
    for label, value in kpi_items:

        html += f"""
<div class="kpi">
<div class="kpi-label">{escape(label)}</div>
<div class="kpi-value">{format_number(value)}</div>
</div>
"""

    # Ferme la grille de KPIs
    html += "</div>"

    # Ajoute la carte "Résumé de l'audit" avec les placeholders
    html += """
<div class="card">
<div class="card-title">Résumé de l'audit</div>
<div class="card-subtitle">Indicateurs calculés directement par Python / DuckDB.</div>
<p>L'audit porte sur <strong>__N_TABLES__ table(s)</strong> de la base <strong>__PROJECT__</strong>.</p>
</div>
"""

    # Génère le tableau des tables avec leur volumétrie
    table_rows = []

    # Itère sur chaque table pour extraire nom, lignes, colonnes
    for table_name, data in audit.items():

        if not isinstance(data, dict):
            continue

        structure = data.get("structure", {})

        if not isinstance(structure, dict):
            continue

        # Ajoute une ligne au tableau avec le nom, nb lignes et nb colonnes
        table_rows.append(
            [
                table_name,
                format_number(structure.get("rows", 0)),
                format_number(structure.get("columns", 0)),
            ]
        )

    # Génère le tableau HTML des tables
    html += simple_table(["Table", "Lignes", "Colonnes"], table_rows)

    # ========================================================
    # QUALITE
    # ========================================================

    # Ajoute la section "Qualité des données" avec l'ancre #quality
    html += """
<section class="section" id="quality">
<h2>Qualité des données</h2>
"""

    # Génère une carte par table avec ses contrôles qualité
    for table_name, data in audit.items():

        if not isinstance(data, dict):
            continue

        # En-tête de la carte avec le nom de la table
        html += f"""
<div class="card">
<div class="card-title">{escape(table_name)}</div>
<div class="card-subtitle">Contrôles qualité</div>
"""

        # ---- VALEURS MANQUANTES ----

        # Récupère la liste des valeurs manquantes pour cette table
        missing = data.get("missing_values", [])

        html += "<h3>Valeurs manquantes</h3>"

        # Filtre les colonnes avec au moins une valeur manquante
        missing_rows = []

        for item in missing:

            if not isinstance(item, dict):
                continue

            missing_count = item.get("missing", 0)

            # Ignore les colonnes sans valeur manquante
            if missing_count == 0:
                continue

            # Ajoute la ligne : [nom_colonne, nb_manquants, pourcentage]
            missing_rows.append(
                [
                    item.get("column", "—"),
                    format_number(missing_count),
                    format_percent(item.get("missing_percent", 0)),
                ]
            )

        # Affiche le tableau ou un message "aucune valeur manquante"
        if missing_rows:
            html += simple_table(
                ["Colonne", "Valeurs manquantes", "Pourcentage"], missing_rows
            )
        else:
            html += '<div class="empty-state">Aucune valeur manquante détectée.</div>'

        # ---- DOUBLONS ----

        # Récupère le dict des doublons pour cette table
        duplicates = data.get("duplicates", {})

        html += "<h3>Doublons</h3>"

        # Affiche un tableau avec les 3 indicateurs de doublons
        if isinstance(duplicates, dict):
            html += simple_table(
                ["Lignes totales", "Lignes distinctes", "Doublons"],
                [
                    [
                        format_number(duplicates.get("total_rows", 0)),
                        format_number(duplicates.get("distinct_rows", 0)),
                        format_number(duplicates.get("duplicates", 0)),
                    ]
                ],
            )

        # ---- VALEURS NEGATIVES ----

        # Récupère la liste des valeurs négatives pour cette table
        negative = data.get("negative_values", [])

        html += "<h3>Valeurs négatives</h3>"

        # Construit les lignes du tableau des valeurs négatives
        negative_rows = []

        for item in negative:

            if not isinstance(item, dict):
                continue

            # Ajoute la ligne : [nom_colonne, nb_valeurs_négatives]
            negative_rows.append(
                [item.get("column", "—"), format_number(item.get("negative_values", 0))]
            )

        # Affiche le tableau ou un message "aucune valeur négative"
        if negative_rows:
            html += simple_table(["Colonne", "Valeurs négatives"], negative_rows)
        else:
            html += '<div class="empty-state">Aucune valeur négative détectée.</div>'

        # Ferme la carte de cette table
        html += "</div>"

    # ========================================================
    # TABLES (structure détaillée)
    # ========================================================

    # Ajoute la section "Tables" avec l'ancre #tables
    html += """
<section class="section" id="tables">
<h2>Tables</h2>
"""

    # Génère une carte par table avec sa structure détaillée
    for table_name, data in audit.items():

        if not isinstance(data, dict):
            continue

        structure = data.get("structure", {})

        # En-tête de la carte avec le nom de la table
        html += f'<div class="card"><div class="card-title">{escape(table_name)}</div>'

        if isinstance(structure, dict):

            # Récupère le nombre de lignes et de colonnes
            rows = structure.get("rows", 0)
            columns_count = structure.get("columns", 0)

            # Affiche 3 métriques dans une grille (lignes, colonnes, statut)
            html += '<div class="structure-grid">'
            html += f'<div class="structure-item"><div class="structure-label">Lignes</div><div class="structure-value">{format_number(rows)}</div></div>'
            html += f'<div class="structure-item"><div class="structure-label">Colonnes</div><div class="structure-value">{format_number(columns_count)}</div></div>'
            html += '<div class="structure-item"><div class="structure-label">Statut</div><div class="structure-value">Analysée</div></div>'
            html += "</div>"

            # Récupère le schéma (liste de dicts avec column_name, column_type, null)
            schema = structure.get("schema", [])

            # Construit les lignes du tableau de schéma
            schema_rows = []

            for column in schema:

                if not isinstance(column, dict):
                    continue

                # Ajoute la ligne : [nom_colonne, type, nullable]
                schema_rows.append(
                    [
                        column.get("column_name", "—"),
                        column.get("column_type", "—"),
                        column.get("null", "—"),
                    ]
                )

            # Affiche le tableau de schéma ou un message si indisponible
            if schema_rows:
                html += simple_table(["Colonne", "Type", "Nullable"], schema_rows)
            else:
                html += (
                    '<div class="empty-state">Structure détaillée indisponible.</div>'
                )

        # Ferme la carte de cette table
        html += "</div>"

    # ========================================================
    # GRAPHIQUES
    # ========================================================

    # Ajoute la section "Graphiques" avec l'ancre #graphs
    html += """
<section class="section" id="graphs">
<h2>Graphiques</h2>
"""

    # Calcule le chemin du dossier de graphiques relatif au rapport HTML
    # Le rapport est dans reports/ et les graphiques dans graphs/
    graph_dir = output_file.parent.parent / "graphs"

    # Liste vide par défaut
    graph_files = []

    # Si le dossier graphs/ existe, liste tous les fichiers image
    if graph_dir.exists():

        graph_files = sorted(
            [
                file
                for file in graph_dir.iterdir()
                # Filtre les extensions d'images supportées
                if file.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
            ]
        )

    # Si des graphiques existent, les affiche dans une grille 2 colonnes
    if graph_files:

        html += '<div class="graph-grid">'

        for graph_file in graph_files:

            # Génère un titre lisible à partir du nom de fichier
            # "01_volume_tables" → "01 volume tables"
            title = graph_file.stem.replace("_", " ").replace("-", " ").capitalize()

            # Chemin relatif depuis reports/ vers graphs/
            # Ex: "../graphs/01_volume_tables.png"
            relative_path = Path("..") / "graphs" / graph_file.name

            # Génère la carte image avec titre et balise img
            html += f"""
<div class="graph-card">
<div class="graph-title">{escape(title)}</div>
<img src="{escape(relative_path.as_posix())}" alt="{escape(title)}">
</div>
"""

        html += "</div>"

    else:
        # Message si aucun graphique n'est disponible
        html += '<div class="empty-state">Aucun graphique disponible.</div>'

    # ========================================================
    # ANALYSE IA
    # ========================================================

    # Ajoute la section "Analyse IA" avec l'ancre #ai
    html += """
<section class="section" id="ai">
<h2>Analyse IA</h2>
<div class="card">
<div class="card-title">Analyse technique par Ollama</div>
<div class="card-subtitle">Interprétation des résultats calculés par Python / DuckDB.</div>
<div class="ai-content">
"""

    # Insère le HTML généré à partir du rapport Markdown de l'IA
    html += analysis_html

    html += "</div></div></section>"

    # ========================================================
    # FOOTER
    # ========================================================

    # Ajoute le pied de page avec la date de génération
    html += f"""
<footer class="footer">
Rapport généré automatiquement le {escape(generated_at)}.
<br><br>
Audit Python / DuckDB · Analyse Ollama.
</footer>
"""

    # Ferme les balises main, div.app et body/html
    html += "</main></div></body></html>"

    # ========================================================
    # REMPLACEMENT DES PLACEHOLDERS ET ECRITURE
    # ========================================================

    # Remplace __PROJECT__ par le nom du projet (échappé pour le HTML)
    # Remplace __N_TABLES__ par le nombre de tables
    html = html.replace("__PROJECT__", escape(str(project_name))).replace(
        "__N_TABLES__", str(n_tables)
    )

    # Écrit le HTML final dans le fichier de sortie en UTF-8
    output_file.write_text(html, encoding="utf-8")

    # Confirme la génération dans le terminal
    print(f"Rapport HTML généré : {output_file}")
