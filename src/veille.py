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

PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
ERIC_URL = "https://api.ies.ed.gov/eric/"

NCBI_TOOL_NAME = "veille_scientifique_physio"
NCBI_EMAIL = "antoine.roche.mk@gmail.com"


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


def clean_abstract(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_doi(doi: str) -> str:
    doi = doi or ""
    doi = doi.strip()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://dx.doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def openalex_abstract_from_inverted_index(index: dict) -> str:
    """
    OpenAlex fournit parfois les abstracts sous forme d'index inversé.
    Cette fonction reconstruit l'abstract si disponible.
    """
    if not index:
        return ""

    positions = []

    for word, word_positions in index.items():
        for position in word_positions:
            positions.append((position, word))

    if not positions:
        return ""

    positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in positions)


def article_identifier(article: dict) -> str:
    doi = clean_doi(article.get("doi", ""))
    pmid = article.get("pmid", "")
    pmcid = article.get("pmcid", "")
    title = article.get("title", "")

    if doi:
        return f"doi:{doi.lower().strip()}"
    if pmid:
        return f"pmid:{str(pmid).strip()}"
    if pmcid:
        return f"pmcid:{str(pmcid).strip()}"

    clean_title = re.sub(r"\s+", " ", title.lower()).strip()
    return f"title:{clean_title}"


def build_article_url(item: dict) -> str:
    doi = clean_doi(item.get("doi", ""))
    pmid = item.get("pmid", "")
    pmcid = item.get("pmcid", "")

    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmcid:
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"

    title = quote(item.get("title", ""))
    return f"https://europepmc.org/search?query={title}"


def fetch_europe_pmc(query: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Recherche Europe PMC.
    Europe PMC couvre une grande partie du biomédical, dont PubMed/MEDLINE et PubMed Central.
    """
    start_date = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = date.today().strftime("%Y-%m-%d")

    final_query = f"({query}) AND FIRST_PDATE:[{start_date} TO {end_date}]"

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
        doi = clean_doi(item.get("doi", ""))

        article = {
            "title": item.get("title", "").strip(),
            "authors": item.get("authorString", "").strip(),
            "journal": item.get("journalTitle", "").strip(),
            "year": item.get("pubYear", "").strip(),
            "publication_date": item.get("firstPublicationDate", "").strip(),
            "doi": doi,
            "pmid": item.get("pmid", "").strip(),
            "pmcid": item.get("pmcid", "").strip(),
            "abstract": clean_abstract(item.get("abstractText", "")),
            "source": "Europe PMC",
            "url": build_article_url(item),
        }

        if article["title"]:
            articles.append(article)

    return articles


def fetch_pubmed(query: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Recherche directe dans PubMed via NCBI E-utilities.
    Récupère titre, auteurs, revue, année, date, DOI, PMID, PMCID et lien PubMed.
    """
    start_date = (date.today() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    end_date = date.today().strftime("%Y/%m/%d")

    search_params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": page_size,
        "sort": "pub_date",
        "datetype": "pdat",
        "mindate": start_date,
        "maxdate": end_date,
        "tool": NCBI_TOOL_NAME,
        "email": NCBI_EMAIL,
    }

    search_response = requests.get(PUBMED_ESEARCH_URL, params=search_params, timeout=30)
    search_response.raise_for_status()
    search_data = search_response.json()

    ids = search_data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    summary_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "json",
        "tool": NCBI_TOOL_NAME,
        "email": NCBI_EMAIL,
    }

    summary_response = requests.get(PUBMED_ESUMMARY_URL, params=summary_params, timeout=30)
    summary_response.raise_for_status()
    summary_data = summary_response.json()

    articles = []

    for pmid in ids:
        item = summary_data.get("result", {}).get(pmid, {})
        if not item:
            continue

        title = item.get("title", "").strip()
        authors_list = item.get("authors", [])
        authors = ", ".join(
            [author.get("name", "") for author in authors_list if author.get("name")]
        )

        doi = ""
        pmcid = ""

        for article_id in item.get("articleids", []):
            id_type = article_id.get("idtype", "")
            value = article_id.get("value", "")

            if id_type == "doi":
                doi = clean_doi(value)
            elif id_type == "pmc":
                pmcid = value.strip()

        pubdate = item.get("pubdate", "").strip()
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", pubdate)
        year = year_match.group(1) if year_match else ""

        article = {
            "title": title,
            "authors": authors,
            "journal": item.get("fulljournalname", "").strip(),
            "year": year,
            "publication_date": pubdate,
            "doi": doi,
            "pmid": pmid,
            "pmcid": pmcid,
            "abstract": "",
            "source": "PubMed",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }

        if title:
            articles.append(article)

    return articles


def fetch_openalex(query: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Recherche OpenAlex.
    Utile pour élargir la veille au-delà du biomédical :
    sciences de l'éducation, sciences sociales, santé, DOI, revues hors PubMed.
    """
    start_date = (date.today() - timedelta(days=days_back)).isoformat()
    end_date = date.today().isoformat()

    params = {
        "search": query,
        "filter": f"from_publication_date:{start_date},to_publication_date:{end_date}",
        "per-page": page_size,
        "sort": "publication_date:desc",
        "mailto": NCBI_EMAIL,
    }

    response = requests.get(OPENALEX_WORKS_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    articles = []

    for item in results:
        title = item.get("title") or ""

        doi_url = item.get("doi") or ""
        doi = clean_doi(doi_url)

        authorships = item.get("authorships", [])
        authors = ", ".join(
            [
                authorship.get("author", {}).get("display_name", "")
                for authorship in authorships
                if authorship.get("author", {}).get("display_name")
            ]
        )

        primary_location = item.get("primary_location") or {}
        source_obj = primary_location.get("source") or {}
        journal = source_obj.get("display_name", "") if source_obj else ""

        pub_date = item.get("publication_date") or ""
        year = str(item.get("publication_year") or "")

        abstract = clean_abstract(
            openalex_abstract_from_inverted_index(
                item.get("abstract_inverted_index") or {}
            )
        )

        article = {
            "title": title.strip(),
            "authors": authors.strip(),
            "journal": journal.strip(),
            "year": year,
            "publication_date": pub_date,
            "doi": doi,
            "pmid": "",
            "pmcid": "",
            "abstract": abstract,
            "source": "OpenAlex",
            "url": f"https://doi.org/{doi}" if doi else item.get("id", ""),
        }

        if article["title"]:
            articles.append(article)

    return articles


def fetch_crossref(query: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Recherche Crossref.
    Utile pour repérer des DOI récents et des métadonnées éditeur.
    Peut être plus bruyant qu'Europe PMC ou PubMed.
    """
    start_date = (date.today() - timedelta(days=days_back)).isoformat()
    end_date = date.today().isoformat()

    params = {
        "query.bibliographic": query,
        "filter": f"from-pub-date:{start_date},until-pub-date:{end_date},type:journal-article",
        "rows": page_size,
        "sort": "published",
        "order": "desc",
        "mailto": NCBI_EMAIL,
    }

    response = requests.get(CROSSREF_WORKS_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    items = data.get("message", {}).get("items", [])
    articles = []

    for item in items:
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""

        doi = clean_doi(item.get("DOI", ""))

        authors_list = item.get("author", [])
        authors_parts = []

        for author in authors_list:
            given = author.get("given", "")
            family = author.get("family", "")
            full_name = f"{family} {given}".strip()
            if full_name:
                authors_parts.append(full_name)

        authors = ", ".join(authors_parts)

        container = item.get("container-title", [])
        journal = container[0] if container else ""

        published = (
            item.get("published-print")
            or item.get("published-online")
            or item.get("published")
            or {}
        )

        date_parts = published.get("date-parts", [[]])[0]
        year = str(date_parts[0]) if len(date_parts) >= 1 else ""
        month = str(date_parts[1]).zfill(2) if len(date_parts) >= 2 else "01"
        day = str(date_parts[2]).zfill(2) if len(date_parts) >= 3 else "01"
        publication_date = f"{year}-{month}-{day}" if year else ""

        abstract = clean_abstract(item.get("abstract", ""))

        article = {
            "title": title.strip(),
            "authors": authors.strip(),
            "journal": journal.strip(),
            "year": year,
            "publication_date": publication_date,
            "doi": doi,
            "pmid": "",
            "pmcid": "",
            "abstract": abstract,
            "source": "Crossref",
            "url": f"https://doi.org/{doi}" if doi else item.get("URL", ""),
        }

        if article["title"]:
            articles.append(article)

    return articles


def fetch_eric(query: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Recherche ERIC.
    Utile pour sciences de l'éducation, pédagogie, curriculum, feedback,
    assessment et formation des professionnels.
    """
    start_year = (date.today() - timedelta(days=days_back)).year
    end_year = date.today().year

    params = {
        "search": query,
        "format": "json",
        "rows": page_size,
        "start": 0,
    }

    response = requests.get(ERIC_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    records = data.get("response", {}).get("docs", [])
    articles = []

    for item in records:
        title = item.get("title", "")

        authors_data = item.get("author", [])
        if isinstance(authors_data, list):
            authors = ", ".join(authors_data)
        else:
            authors = str(authors_data)

        year = str(item.get("publicationdateyear", "") or "")
        if year and year.isdigit():
            year_int = int(year)
            if year_int < start_year or year_int > end_year:
                continue

        journal = item.get("source", "")
        abstract = clean_abstract(item.get("description", ""))

        eric_id = item.get("id", "")
        doi = clean_doi(item.get("doi", ""))

        article = {
            "title": title.strip(),
            "authors": authors.strip(),
            "journal": journal.strip(),
            "year": year,
            "publication_date": year,
            "doi": doi,
            "pmid": "",
            "pmcid": "",
            "abstract": abstract,
            "source": "ERIC",
            "url": f"https://eric.ed.gov/?id={eric_id}" if eric_id else "",
        }

        if article["title"]:
            articles.append(article)

    return articles


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

        for keyword in keywords:
            keyword_norm = normalize_text(keyword)

            if keyword_norm in text:
                total_score += points
                category_matches.append(keyword)

        if category_matches:
            matched[category] = category_matches

    return total_score, matched


def classify_article(score: int, keyword_config: dict) -> str:
    rules = keyword_config.get("decision_rules", {})

    high = int(rules.get("high_priority_threshold", 22))
    watch = int(rules.get("watch_threshold", 14))
    peripheral = int(rules.get("peripheral_threshold", 8))

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

    if matched.get("education") or matched.get("education_anchor") or matched.get("education_methods"):
        tags.update(tags_config.get("education", []))

    if any(term in text for term in ["concordance", "script concordance"]):
        tags.update(tags_config.get("concordance", []))

    if any(
        term in text
        for term in [
            "clinical reasoning",
            "diagnostic reasoning",
            "clinical uncertainty",
            "diagnostic uncertainty",
            "therapeutic uncertainty",
            "tolerance of uncertainty",
            "intolerance of uncertainty",
        ]
    ):
        tags.update(tags_config.get("reasoning", []))

    if matched.get("spine_msk") or matched.get("spine_core"):
        tags.update(tags_config.get("spine", []))

    if any(
        term in text
        for term in [
            "manual therapy",
            "orthopaedic manual therapy",
            "orthopedic manual therapy",
            "omt",
            "ompt",
            "spinal manipulation",
            "spinal mobilization",
            "spinal mobilisation",
        ]
    ):
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
    pmcid = article.get("pmcid", "")
    source = article.get("source", "")
    url = article.get("url", "")
    abstract = article.get("abstract", "")

    if len(abstract) > 1200:
        abstract = abstract[:1200].rstrip() + "..."

    matched_lines = []

    for category, keywords in matched.items():
        matched_lines.append(f"  - **{category}** : {', '.join(keywords)}")

    matched_md = "\n".join(matched_lines) if matched_lines else "  - Aucun mot-clé fort détecté"
    tags_md = ", ".join([f"`#{tag}`" for tag in tags]) if tags else "Aucun tag proposé"

    return f"""
### {title}

- **Auteurs** : {authors}
- **Revue** : {journal}
- **Année** : {year}
- **Date de publication** : {pub_date}
- **Source** : {source}
- **DOI** : {doi or "Non renseigné"}
- **PMID** : {pmid or "Non renseigné"}
- **PMCID** : {pmcid or "Non renseigné"}
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


def should_use_source_for_query(source_name: str, query_name: str, query: str) -> bool:
    """
    Filtrage léger pour éviter trop de bruit.
    - ERIC est surtout utile pour éducation, pédagogie, feedback, assessment, simulation.
    - Crossref est gardé en complément, mais peut être bruyant.
    """
    text = normalize_text(query_name + " " + query)

    education_terms = [
        "education",
        "teaching",
        "learning",
        "feedback",
        "assessment",
        "simulation",
        "curriculum",
        "pedagogy",
        "osce",
        "ecos",
        "competency",
        "concordance",
    ]

    if source_name == "ERIC":
        return any(term in text for term in education_terms)

    return True


def fetch_from_all_sources(query: str, name: str, days_back: int = 14, page_size: int = 25) -> list[dict]:
    """
    Interroge plusieurs sources bibliographiques gratuites.

    Sources :
    - Europe PMC : biomédical large, PubMed-like
    - PubMed : biomédical direct, NCBI
    - OpenAlex : interdisciplinaire, éducation, sciences sociales, DOI
    - Crossref : métadonnées DOI éditeurs
    - ERIC : sciences de l'éducation
    """
    all_articles = []

    sources = [
        ("Europe PMC", fetch_europe_pmc),
        ("PubMed", fetch_pubmed),
        ("OpenAlex", fetch_openalex),
        ("Crossref", fetch_crossref),
        ("ERIC", fetch_eric),
    ]

    for source_name, fetcher in sources:
        if not should_use_source_for_query(source_name, name, query):
            print(f"  Source : {source_name} ignorée pour cette requête")
            continue

        try:
            print(f"  Source : {source_name}")
            articles = fetcher(query=query, days_back=days_back, page_size=page_size)
            print(f"  {len(articles)} article(s) trouvé(s) via {source_name}")
            all_articles.extend(articles)
        except Exception as e:
            print(f"  Erreur {source_name} pour {name}: {e}", file=sys.stderr)
            continue

        time.sleep(0.5)

    return all_articles


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

    for query_item in queries:
        name = query_item.get("name", "Requête sans nom")
        query = query_item.get("query", "")

        if not query:
            continue

        print(f"- Recherche : {name}")

        articles = fetch_from_all_sources(
            query=query,
            name=name,
            days_back=14,
            page_size=25,
        )

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

    report_path = generate_report(collected)
    save_seen_articles(new_seen)

    print(f"Rapport généré : {report_path}")
    print(f"Articles nouveaux détectés : {len(collected)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
