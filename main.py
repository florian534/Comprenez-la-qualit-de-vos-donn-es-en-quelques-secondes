# Importation de argparse pour parser les arguments de la ligne de commande
import argparse

# Importation de os pour définir les variables d'environnement
import os


def parse_args():
    # Définit et parse les arguments acceptés par le script en ligne de commande

    # Crée le parser avec une description affichée avec --help
    parser = argparse.ArgumentParser(
        description="Audit automatisé de la qualité d'une base de données "
        "(parquet, csv, tsv, json) avec DuckDB + Ollama."
    )

    # Argument optionnel --data-dir : chemin du dossier de données
    parser.add_argument(
        "--data-dir",
        help="Dossier contenant les fichiers à auditer " "(1 fichier = 1 table).",
    )

    # Argument optionnel --name : nom du projet affiché dans le rapport
    parser.add_argument(
        "--name", help="Nom de la base / du projet affiché dans le rapport."
    )

    # Argument optionnel --context : description métier pour aider l'IA
    parser.add_argument(
        "--context", help="Description métier de la base (aide l'IA à interpréter)."
    )

    # Argument optionnel --model : nom du modèle Ollama à utiliser
    parser.add_argument("--model", help="Modèle Ollama à utiliser.")

    # Argument optionnel --no-ai : désactive l'appel à Ollama
    # action="store_true" : args.no_ai vaut True si --no-ai est présent
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Ne pas appeler Ollama (audit + graphiques + rapport seulement).",
    )

    # Parse les arguments de sys.argv et retourne l'objet Namespace
    return parser.parse_args()


def main():
    # Fonction principale : orchestre les 4 étapes de l'audit

    # Parse les arguments de la ligne de commande
    args = parse_args()

    # ⚠️ IMPORTANT : les variables d'environnement doivent être définies
    # AVANT d'importer config.py (qui les lit au chargement du module)
    # C'est pourquoi les imports des autres modules sont faits APRÈS

    # Si --data-dir est fourni, définit la variable d'environnement correspondante
    if args.data_dir:
        os.environ["AUDIT_DATA_DIR"] = args.data_dir

    # Si --name est fourni, définit le nom du projet
    if args.name:
        os.environ["AUDIT_NAME"] = args.name

    # Si --context est fourni, définit le contexte métier
    if args.context:
        os.environ["AUDIT_CONTEXT"] = args.context

    # Si --model est fourni, définit le modèle Ollama
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    # Imports différés : maintenant que les variables d'env sont définies,
    # config.py peut les lire correctement au moment de son import
    from config import REPORT_DIR, GRAPH_DIR, DATA_DIR, FILES, PROJECT_NAME
    from audit import audit_all_tables, save_audit
    from charts import generate_all_charts
    from agent import analyze_audit
    from report import generate_report

    # Affiche l'en-tête du rapport d'audit dans le terminal
    print("=" * 70)
    print(f"AUDIT AUTOMATISE - {PROJECT_NAME.upper()}")
    print("=" * 70)

    # Affiche les informations de configuration
    print(f"\nDossier de données : {DATA_DIR}")
    print(f"Tables détectées ({len(FILES)}) : {', '.join(FILES) or 'aucune'}")

    # ETAPE 1 : Lance l'audit DuckDB sur toutes les tables
    print("\n[1/4] Analyse des données...")
    audit = audit_all_tables()

    # ETAPE 2 : Sauvegarde les résultats d'audit en JSON
    print("\n[2/4] Sauvegarde des résultats...")
    audit_file = REPORT_DIR / "audit.json"
    save_audit(audit, audit_file)

    # ETAPE 3 : Génère les graphiques matplotlib
    print("\n[3/4] Génération des graphiques...")
    generate_all_charts(audit)

    # ETAPE 4 : Analyse IA (sauf si --no-ai est présent)
    if args.no_ai:
        # Si --no-ai : saute l'analyse IA et utilise une chaîne vide
        print("\n[4/4] Analyse IA désactivée (--no-ai).")
        analysis = ""
    else:
        # Lance l'analyse IA via Ollama
        print("\n[4/4] Analyse par Ollama...")
        analysis = analyze_audit(audit)

        # Sauvegarde le rapport Markdown généré par l'IA
        analysis_file = REPORT_DIR / "analyse_ollama.txt"
        analysis_file.write_text(analysis, encoding="utf-8")

    # Génère le rapport HTML final avec tous les résultats
    report_file = REPORT_DIR / "audit_report.html"

    generate_report(
        audit,  # résultats de l'audit DuckDB
        analysis,  # rapport texte généré par l'IA (ou "")
        report_file,  # chemin de sortie du rapport HTML
        project_name=PROJECT_NAME,  # nom du projet pour le titre
    )

    # Affiche le récapitulatif final dans le terminal
    print("\n" + "=" * 70)
    print("AUDIT TERMINE")
    print("=" * 70)

    # Affiche les chemins des fichiers générés
    print(f"\nRapport : {report_file}")
    print(f"JSON : {audit_file}")
    print(f"Graphiques : {GRAPH_DIR}")


# Exécute main() seulement si le script est lancé directement
# (pas si importé comme module par un autre script)
if __name__ == "__main__":
    main()
