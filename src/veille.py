import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
import yaml


BASE_DIR = Path(__file__).resolve().parents[1]
QUERIES_FILE = BASE_DIR / "queries.yml"
KEYWORDS_FILE = BASE_DIR / "keywords.yml"
SEEN_FILE = BASE_DIR / "seen_articles.json"
REPORTS_DIR = BASE_DIR / "reports"

EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen_articles() -> set:
    if not SEEN_FILE.exists():
        return set()
    try:
        with SEEN_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data)
    except json.JSONDecodeError:
        return set()


def save_seen_articles(seen: set) -> None:
    with SEEN_FILE.open("w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def normalize_text(text: str) -> str:
    text = text or ""
    return text.lower()


def article_identifier(article: dict) -> str:
    doi = article.get("doi")
    pmid = article.get("pmid")
    pmcid = article.get("pmcid")
    title = article.get("title", "")

    if doi:
        return f"doi:{doi.lower()}"
    if pmid:
        return f"pmid:{pmid}"
    if pmcid:
        return f"pmcid:{pmcid}"
    return "title:" + re.sub(r"\s+", " ", title.lower()).strip()


def clean_abstract(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_europe_pmc(query: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Recherche Europe PMC.
    On ajoute une contrainte de date pour limiter la veille aux publications récentes.
    """
    start_date = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    final_query = f"({query}) AND FIRST_PDATE:[{start_date} TO {date.today().strftime('%Y-%m-%d')}]"

    params = {
        "query": final_query,
        "format": "json",
        "pageSize": page_size,
        "sort": "FIRST_PDATE_D desc",
        "resultType": "core",
    }

    response = requests.get(EUROPE_PMC_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    results = data.get("resultList", {}).get("result", [])
    articles = []

    for item in results:
        article = {
            "title": item.get("title", "").strip(),
            "authors": item.get("authorString", "").strip(),
            "journal": item.get("journalTitle", "").strip(),
            "year": item.get("pubYear", "").strip(),
            "publication_date": item.get("firstPublicationDate", "").strip(),
            "doi": item.get("doi", "").strip(),
            "pmid": item.get("pmid", "").strip(),
            "pmcid": item.get("pmcid", "").strip(),
            "abstract": clean_abstract(item.get("abstractText", "")),
            "source": "Europe PMC",
            "url": build_article_url(item),
        }
        if article["title"]:
            articles.append(article)

    return articles


def build_article_url(item: dict) -> str:
    doi = item.get("doi")
    pmid = item.get("pmid")
    pmcid = item.get("pmcid")

    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmcid:
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
    title = quote(item.get("title", ""))
    return f"https://europepmc.org/search?query={title}"


def score_article(article: dict, keyword_config: dict) -> tuple[int, dict]:
    text = normalize_text(
        " ".join(
            [
                article.get("title", ""),
                article.get("abstract", ""),
                article.get("journal", ""),
            ]
        )
    )

    total_score = 0
    matched = {}

    scoring = keyword_config.get("scoring", {})

    for category, config in scoring.items():
        points = int(config.get("points", 0))
        keywords = config.get("keywords", [])

        category_matches = []
        for kw in keywords:
            kw_norm = normalize_text(kw)
            if kw_norm in text:
                total_score += points
                category_matches.append(kw)

        if category_matches:
            matched[category] = category_matches

    return total_score, matched


def classify_article(score: int, keyword_config: dict) -> str:
    rules = keyword_config.get("decision_rules", {})

    high = int(rules.get("high_priority_threshold", 12))
    watch = int(rules.get("watch_threshold", 8))
    peripheral = int(rules.get("peripheral_threshold", 5))

    if score >= high:
        return "Haute priorité"
    if score >= watch:
        return "À surveiller"
    if score >= peripheral:
        return "Périphérique"
    return "Faible priorité"


def propose_tags(matched: dict, article: dict, keyword_config: dict) -> list[str]:
    tags_config = keyword_config.get("tags", {})
    tags = set()

    text = normalize_text(article.get("title", "") + " " + article.get("abstract", ""))

    if matched.get("high_priority"):
        tags.update(tags_config.get("high_priority", []))

    if matched.get("education"):
        tags.update(tags_config.get("education", []))

    if any(term in text for term in ["concordance", "script concordance"]):
        tags.update(tags_config.get("concordance", []))

    if any(term in text for term in ["clinical reasoning", "uncertainty", "diagnostic uncertainty"]):
        tags.update(tags_config.get("reasoning", []))

    if matched.get("spine_msk"):
        tags.update(tags_config.get("spine", []))

    if any(term in text for term in ["manual therapy", "orthopaedic manual therapy", "orthopedic manual therapy", "omt"]):
        tags.update(tags_config.get("manual_therapy", []))

    if matched.get("clinical_tests"):
        tags.update(tags_config.get("tests", []))

    if matched.get("active_treatments") or matched.get("passive_treatments"):
        tags.update(tags_config.get("treatments", []))

    if matched.get("case_reports"):
        tags.update(tags_config.get("cases", []))

    return sorted(tags)


def format_article_md(article: dict, score: int, decision: str, matched: dict, tags: list[str]) -> str:
    title = article.get("title", "Titre absent")
    authors = article.get("authors", "Auteurs non renseignés")
    journal = article.get("journal", "Journal non renseigné")
    year = article.get("year", "")
    pub_date = article.get("publication_date", "")
    doi = article.get("doi", "")
    pmid = article.get("pmid", "")
    url = article.get("url", "")
    abstract = article.get("abstract", "")

    if len(abstract) > 1200:
        abstract = abstract[:1200].rstrip() + "..."

    matched_lines = []
    for category, kws in matched.items():
        matched_lines.append(f"  - **{category}** : {', '.join(kws)}")

    matched_md = "\n".join(matched_lines) if matched_lines else "  - Aucun mot-clé fort détecté"
    tags_md = ", ".join([f"`#{tag}`" for tag in tags]) if tags else "Aucun tag proposé"

    return f"""
### {title}

- **Auteurs** : {authors}
- **Revue** : {journal}
- **Année** : {year}
- **Date de publication** : {pub_date}
- **DOI** : {doi or "Non renseigné"}
- **PMID** : {pmid or "Non renseigné"}
- **Lien** : {url}
- **Score** : {score}
- **Décision** : **{decision}**
- **Tags proposés** : {tags_md}

**Mots-clés détectés :**

{matched_md}

**Résumé / abstract :**

> {abstract if abstract else "Abstract non disponible."}

---
"""


def generate_report(new_articles: list[dict]) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today().isoformat()
    report_path = REPORTS_DIR / f"veille_{today}.md"

    groups = {
        "Haute priorité": [],
        "À surveiller": [],
        "Périphérique": [],
        "Faible priorité": [],
    }

    for item in new_articles:
        groups[item["decision"]].append(item)

    lines = []
    lines.append(f"# Veille scientifique automatisée — {today}")
    lines.append("")
    lines.append(f"Rapport généré automatiquement le {datetime.now().strftime('%Y-%m-%d à %H:%M')}.")
    lines.append("")
    lines.append("## Synthèse")
    lines.append("")
    lines.append(f"- Articles nouveaux détectés : **{len(new_articles)}**")
    lines.append(f"- Haute priorité : **{len(groups['Haute priorité'])}**")
    lines.append(f"- À surveiller : **{len(groups['À surveiller'])}**")
    lines.append(f"- Périphérique : **{len(groups['Périphérique'])}**")
    lines.append(f"- Faible priorité : **{len(groups['Faible priorité'])}**")
    lines.append("")

    for decision in ["Haute priorité", "À surveiller", "Périphérique", "Faible priorité"]:
        lines.append(f"## {decision}")
        lines.append("")

        if not groups[decision]:
            lines.append("_Aucun article dans cette catégorie._")
            lines.append("")
            continue

        sorted_items = sorted(groups[decision], key=lambda x: x["score"], reverse=True)

        for item in sorted_items:
            lines.append(
                format_article_md(
                    item["article"],
                    item["score"],
                    item["decision"],
                    item["matched"],
                    item["tags"],
                )
            )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    print("Chargement des fichiers de configuration...")

    queries_config = load_yaml(QUERIES_FILE)
    keyword_config = load_yaml(KEYWORDS_FILE)

    queries = queries_config.get("queries", [])
    if not queries:
        print("Aucune requête trouvée dans queries.yml")
        return 1

    seen = load_seen_articles()
    new_seen = set(seen)
    collected = []
    already_collected = set()

    print(f"{len(queries)} requêtes chargées.")
    print("Recherche des nouveaux articles...")

    for q in queries:
        name = q.get("name", "Requête sans nom")
        query = q.get("query", "")

        if not query:
            continue

        print(f"- Recherche : {name}")

        try:
            articles = fetch_europe_pmc(query=query, days_back=14, page_size=25)
        except Exception as e:
            print(f"  Erreur pendant la recherche {name}: {e}", file=sys.stderr)
            continue

        for article in articles:
            identifier = article_identifier(article)

            if identifier in seen or identifier in already_collected:
                continue

            score, matched = score_article(article, keyword_config)
            decision = classify_article(score, keyword_config)
            tags = propose_tags(matched, article, keyword_config)

            collected.append(
                {
                    "query_name": name,
                    "identifier": identifier,
                    "article": article,
                    "score": score,
                    "decision": decision,
                    "matched": matched,
                    "tags": tags,
                }
            )

            new_seen.add(identifier)
            already_collected.add(identifier)

        time.sleep(0.5)

    report_path = generate_report(collected)
    save_seen_articles(new_seen)

    print(f"Rapport généré : {report_path}")
    print(f"Articles nouveaux détectés : {len(collected)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
