# Importation de re pour les expressions régulières (nettoyage des noms de fichiers)
import re

# Importation de matplotlib avec le backend "Agg" (sans interface graphique)
import matplotlib

# "Agg" = moteur de rendu sans fenêtre : indispensable sur un serveur sans écran
matplotlib.use("Agg")

# Importation du module de tracé de matplotlib
import matplotlib.pyplot as plt

# Importation du chemin du dossier de sortie des graphiques
from config import GRAPH_DIR


def safe_name(name):
    # Convertit un nom de table en nom de fichier sûr (sans caractères spéciaux)
    # Ex: "ma table/2024" → "ma_table_2024"

    # Remplace tout caractère non alphanumérique, non tiret, non underscore par "_"
    return re.sub(r"[^\w\-]+", "_", str(name))


def clean_graph_dir():
    """
    Supprime les anciens graphiques pour qu'ils ne se mélangent
    pas avec ceux d'un audit précédent (autre base de données).
    """

    # Itère sur tous les fichiers PNG du dossier graphs/
    for file in GRAPH_DIR.glob("*.png"):
        # Supprime le fichier PNG
        file.unlink()


# ============================================================
# NOMBRE DE LIGNES
# ============================================================


def chart_table_sizes(audit):
    # Génère un graphique en barres du nombre de lignes par table

    # Listes qui recevront les noms et les valeurs pour le graphique
    names = []
    values = []

    # Parcourt chaque table de l'audit pour récupérer son nombre de lignes
    for table, data in audit.items():
        # Ajoute le nom de la table à la liste des labels
        names.append(table)
        # Ajoute le nombre de lignes à la liste des valeurs
        values.append(data["structure"]["rows"])

    # Crée une figure avec une largeur adaptée au nombre de tables
    # max(10, ...) garantit une largeur minimale de 10 pouces
    plt.figure(figsize=(max(10, len(names) * 0.6), 6))

    # Trace le graphique en barres verticales
    plt.bar(names, values)

    # Titre du graphique
    plt.title("Nombre de lignes par table")

    # Label de l'axe Y
    plt.ylabel("Nombre de lignes")

    # Rotation des labels de l'axe X pour éviter les chevauchements
    # ha="right" : aligne les labels à droite de leur position
    plt.xticks(rotation=45, ha="right")

    # Ajuste automatiquement les marges pour éviter les coupures
    plt.tight_layout()

    # Chemin de sortie du fichier PNG
    output = GRAPH_DIR / "01_volume_tables.png"

    # Sauvegarde le graphique en PNG avec une résolution de 150 DPI
    plt.savefig(output, dpi=150)

    # Ferme la figure pour libérer la mémoire
    plt.close()

    # Retourne le chemin du fichier créé
    return output


# ============================================================
# VALEURS MANQUANTES
# ============================================================


def chart_missing_values(audit):
    # Génère un graphique de valeurs manquantes pour chaque table concernée

    # Itère sur chaque table de l'audit
    for table, data in audit.items():

        # Filtre les colonnes qui ont au moins une valeur manquante
        missing = [x for x in data["missing_values"] if x["missing"] > 0]

        # Si aucune colonne n'a de manquants, passe à la table suivante
        if not missing:
            continue

        # Trie par pourcentage décroissant et garde les 20 pires colonnes
        # Évite les graphiques illisibles avec trop de colonnes
        missing = sorted(
            missing,
            key=lambda x: x["missing_percent"],  # tri par pourcentage
            reverse=True,  # décroissant : le pire en premier
        )[
            :20
        ]  # maximum 20 colonnes affichées

        # Extrait les noms de colonnes pour l'axe Y
        names = [x["column"] for x in missing]
        # Extrait les pourcentages pour l'axe X
        values = [x["missing_percent"] for x in missing]

        # Crée une figure de taille fixe
        plt.figure(figsize=(12, 7))

        # Trace le graphique en barres horizontales (barh = horizontal)
        plt.barh(names, values)

        # Label de l'axe X
        plt.xlabel("% de valeurs manquantes")

        # Titre avec le nom de la table
        plt.title(f"Valeurs manquantes - {table}")

        # Inverse l'axe Y pour afficher la colonne la plus critique en haut
        plt.gca().invert_yaxis()

        # Ajuste les marges automatiquement
        plt.tight_layout()

        # Sauvegarde le graphique avec un nom basé sur le nom de la table
        plt.savefig(GRAPH_DIR / f"missing_{safe_name(table)}.png", dpi=150)

        # Ferme la figure pour libérer la mémoire
        plt.close()


# ============================================================
# CARDINALITE
# ============================================================


def chart_cardinality(audit):
    # Génère un graphique de cardinalité (nb valeurs distinctes) pour chaque table

    # Itère sur chaque table de l'audit
    for table, data in audit.items():

        # Trie les colonnes par cardinalité décroissante et garde les 20 premières
        values = sorted(
            data["cardinality"],
            key=lambda x: x["distinct_values"],  # tri par nb de valeurs distinctes
            reverse=True,  # décroissant : le plus de valeurs en premier
        )[
            :20
        ]  # maximum 20 colonnes affichées

        # Si aucune colonne, passe à la table suivante
        if not values:
            continue

        # Extrait les noms de colonnes pour l'axe Y
        names = [x["column"] for x in values]
        # Extrait les nombres de valeurs distinctes pour l'axe X
        counts = [x["distinct_values"] for x in values]

        # Crée une figure de taille fixe
        plt.figure(figsize=(12, 7))

        # Trace le graphique en barres horizontales
        plt.barh(names, counts)

        # Label de l'axe X
        plt.xlabel("Nombre de valeurs distinctes")

        # Titre avec le nom de la table
        plt.title(f"Cardinalité - {table}")

        # Inverse l'axe Y pour afficher la colonne avec le plus de distincts en haut
        plt.gca().invert_yaxis()

        # Ajuste les marges automatiquement
        plt.tight_layout()

        # Sauvegarde le graphique avec un nom basé sur le nom de la table
        plt.savefig(GRAPH_DIR / f"cardinality_{safe_name(table)}.png", dpi=150)

        # Ferme la figure pour libérer la mémoire
        plt.close()


# ============================================================
# GRAPHIQUES
# ============================================================


def generate_all_charts(audit):
    # Orchestre la génération de tous les graphiques dans l'ordre

    # Affiche un message de progression dans le terminal
    print("\nCréation des graphiques...")

    # Supprime les anciens graphiques pour repartir d'un dossier propre
    clean_graph_dir()

    # Génère le graphique du volume (nb lignes par table)
    chart_table_sizes(audit)

    # Génère les graphiques de valeurs manquantes (un par table concernée)
    chart_missing_values(audit)

    # Génère les graphiques de cardinalité (un par table)
    chart_cardinality(audit)

    # Affiche un message de fin dans le terminal
    print("Graphiques terminés.")
