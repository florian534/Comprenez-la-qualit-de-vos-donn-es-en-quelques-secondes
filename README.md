# Data Audit AI — DuckDB, Ollama et RAG

Application web d’audit, d’exploration et d’interrogation de données.  
Elle combine **Flask**, **DuckDB** et **Ollama** pour analyser des fichiers de données, générer des rapports assistés par IA et répondre à des questions en langage naturel via un agent **Text-to-SQL** sécurisé.

## Fonctionnalités

### Audit de qualité des données

- Import de fichiers **CSV**, **TSV**, **JSON** et **Parquet** ;
- Détection automatique du schéma et des types de colonnes ;
- Comptage des valeurs manquantes ;
- Détection des lignes entièrement dupliquées ;
- Calcul de la cardinalité par colonne ;
- Statistiques descriptives sur les variables numériques :
  - minimum ;
  - maximum ;
  - moyenne ;
  - médiane ;
  - écart-type ;
- Détection des valeurs numériques négatives ;
- Visualisations de volumétrie, valeurs manquantes et cardinalité.

### Analyse assistée par IA

- Génération d’un rapport d’audit technique avec **Ollama** ;
- Ajout d’un contexte métier fourni par l’utilisateur ;
- Réduction du volume de données envoyé au modèle grâce à un audit compacté ;
- Contrôle des affirmations chiffrées et de la couverture des anomalies ;
- Évaluation hybride du rapport : vérifications Python déterministes + LLM-as-a-Judge.

### Questions sur les données : Text-to-SQL

- Questions en langage naturel sur les fichiers importés ;
- Agent de type **ReAct** :
  1. le modèle propose une requête SQL ;
  2. l’application valide la requête ;
  3. DuckDB exécute la requête ;
  4. le résultat est renvoyé au modèle ;
  5. le modèle produit une réponse finale ;
- Limite du nombre d’étapes SQL pour éviter les boucles ;
- Export des résultats en **CSV**, **Excel** ou **Parquet**.

### Sécurité SQL

Les requêtes générées par le modèle sont limitées à la lecture :

- `SELECT`, `WITH` et `DESCRIBE` ;
- interdiction des requêtes d’écriture ou de modification :
  `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc. ;
- interdiction de l’accès direct à des fichiers externes ;
- limite du nombre de lignes retournées ;
- timeout des requêtes ;
- création de vues DuckDB limitées aux tables importées.

### RAG sur documents PDF

- Import de documents PDF ;
- Extraction et découpage du texte en passages ;
- Création d’embeddings via Ollama ;
- Recherche hybride :
  - recherche sémantique par similarité cosinus ;
  - recherche lexicale BM25 ;
  - fusion des scores normalisés ;
- Ajout des passages PDF pertinents au contexte de l’analyse ;
- Citation des sources utilisées dans le rapport.

### Évaluation

Le projet inclut des modules d’évaluation pour mesurer :

- la qualité factuelle des rapports générés ;
- la couverture des anomalies détectées ;
- l’actionnabilité des recommandations ;
- les éventuelles affirmations non justifiées ;
- la fiabilité du Text-to-SQL avec `pass@k` et `cons@k` ;
- la qualité du RAG avec :
  - Precision@k ;
  - Recall@k ;
  - NDCG@k ;
  - Reciprocal Rank@k.

---

## Architecture

```text
data-audit-ai/
projet/
├── server.py        serveur web (Flask) : point d'entrée de l'interface
├── main.py          mode ligne de commande (sans interface web)
├── config.py        paramètres et découverte automatique des tables
├── database.py      connexion DuckDB et lecture des fichiers
├── audit.py         calcul de l'audit et des distributions
├── agent.py         analyse rédigée par Ollama
├── qa.py            questions en langage naturel (texte → SQL → réponse)
├── rag.py           recherche dans les PDF (passages, embeddings, BM25, hybride)
├── rag_eval.py      qualité de la recherche : P@k, R@k, NDCG@k, RR@k
├── qa_eval.py       fiabilité du Text-to-SQL : pass@k, cons@k
├── evaluator.py     juge du rapport rédigé par l'IA
├── charts.py        graphiques PNG (mode ligne de commande)
├── report.py        rapport HTML statique (mode ligne de commande)
└── static/
    ├── index.html           structure de la page
    ├── style.css            apparence et animations (thèmes clair et sombre)
    ├── app.js               logique de la page
    ├── bg.js                fond animé 3D (décor de la page)
    ├── deck.js              visionneuse de présentation (robot endormi)
    ├── ux.js                confort : repli, retour en haut, accessibilité
    ├── fx.js                apparition des sections en fondu
    ├── flow.js              parcours animé « Du fichier au rapport »
    ├── pptx-preview.umd.js  bibliothèque tierce de lecture des .pptx
    └── presentations/       présentation .pptx affichée par le robot
```

## Prérequis

- Python **3.10** ou version plus récente ;
- Ollama installé et démarré ;
- Un modèle conversationnel Ollama ;
- Un modèle d’embeddings pour le RAG.

Exemple d’installation des modèles Ollama :

```bash
ollama pull gpt-oss:120b-cloud
ollama pull nomic-embed-text
```

> Le nom du modèle conversationnel peut être modifié avec la variable d’environnement `OLLAMA_MODEL`.

---

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/VOTRE-IDENTIFIANT/NOM-DU-DEPOT.git
cd NOM-DU-DEPOT
```

### 2. Créer un environnement virtuel

```bash
python -m venv .venv
```

Sous Windows :

```bash
.venv\Scripts\activate
```

Sous macOS ou Linux :

```bash
source .venv/bin/activate
```

### 3. Installer les dépendances Python

```bash
pip install -r requirements.txt
```
---

## Lancement de l’application web

Démarrer Ollama dans un terminal :

```bash
ollama serve
```

Puis, dans le dossier du projet :

```bash
python server.py
```

L’application est accessible à l’adresse :

```text
http://127.0.0.1:5000
```

Le navigateur est normalement ouvert automatiquement au démarrage.

---

## Utilisation

1. Ouvrir l’application dans le navigateur ;
2. Importer un ou plusieurs fichiers CSV, TSV, JSON ou Parquet ;
3. Lancer l’audit ;
4. Consulter :
   - la structure des tables ;
   - les valeurs manquantes ;
   - les doublons ;
   - les statistiques ;
   - les graphiques ;
5. Ajouter éventuellement un contexte métier ;
6. Importer des PDF de référence si nécessaire ;
7. Générer l’analyse IA ;
8. Poser des questions sur les données ;
9. Exporter les résultats d’une requête SQL.

---

## Utilisation en ligne de commande

Le script `main.py` permet de produire un audit, des graphiques et un rapport HTML sans utiliser l’interface web.

Exemple :

```bash
python main.py --data-dir "./data/parquet" --name "Audit ventes"
```

Avec un contexte métier :

```bash
python main.py ^
  --data-dir "./data/parquet" ^
  --name "Audit ventes" ^
  --context "Les montants sont exprimés en euros et ne doivent pas être négatifs."
```

Sans appel à Ollama :

```bash
python main.py --data-dir "./data/parquet" --no-ai
```

Les résultats sont générés dans :

```text
reports/
graphs/
```

---

## Configuration

La configuration peut être modifiée avec des variables d’environnement.

| Variable | Description | Valeur par défaut |
|---|---|---|
| `OLLAMA_URL` | URL de l’API Ollama | `http://localhost:11434/api/chat` |
| `OLLAMA_MODEL` | Modèle conversationnel utilisé | `gpt-oss:120b-cloud` |
| `OLLAMA_EMBED_MODEL` | Modèle d’embeddings pour le RAG | `nomic-embed-text` |
| `AUDIT_DATA_DIR` | Dossier de données par défaut | `data/parquet` |
| `AUDIT_NAME` | Nom du projet | `Audit de données` |
| `AUDIT_CONTEXT` | Contexte métier | vide |
| `DUCKDB_MEMORY` | Mémoire maximale DuckDB | `8GB` |
| `DUCKDB_THREADS` | Nombre de threads DuckDB | `4` |
| `RAG_TOP_K` | Nombre de passages RAG retenus | `4` |
| `RAG_HYBRID_ALPHA` | Poids du score sémantique | `0.4` |

Exemple sous Windows PowerShell :

```powershell
$env:OLLAMA_MODEL="gpt-oss:120b-cloud"
python server.py
```

Exemple sous macOS/Linux :

```bash
OLLAMA_MODEL="gpt-oss:120b-cloud" python server.py
```

---

## API principale

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Interface web principale |
| `POST` | `/api/audit` | Import et audit des fichiers |
| `GET` | `/api/column` | Distribution d’une colonne |
| `POST` | `/api/analyze` | Génération du rapport IA |
| `POST` | `/api/ask` | Question en langage naturel sur les données |
| `POST` | `/api/export` | Export d’un résultat SQL |
| `GET/POST` | `/api/docs` | Gestion des PDF pour le RAG |
| `POST` | `/api/evaluate` | Évaluation du rapport IA |
| `POST` | `/api/eval/rag` | Évaluation de la recherche RAG |
| `POST` | `/api/eval/sql` | Évaluation du chatbot Text-to-SQL |

---

## Limites actuelles

- L’application est conçue principalement pour un usage local ;
- Ollama doit être installé et accessible sur la machine ou le serveur ;
- Les PDF scannés sans texte exploitable nécessitent un traitement OCR préalable ;
- Les données importées et les documents RAG sont conservés en mémoire pendant l’exécution ;
- Les contrôles d’audit actuels couvrent surtout la structure, les valeurs manquantes, les doublons, la cardinalité, les statistiques numériques et les valeurs négatives.

---


---

## Technologies utilisées

- **Python**
- **Flask**
- **DuckDB**
- **Pandas**
- **NumPy**
- **Matplotlib**
- **Ollama**
- **RAG hybride** : embeddings + BM25
- **HTML / CSS / JavaScript**
- **PyPDF**
- **OpenPyXL**

---




static/
