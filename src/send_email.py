import os
import re
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BASE_DIR / "reports"


THEMES = {
    "Raisonnement clinique / éducation": [
        "clinical reasoning",
        "diagnostic reasoning",
        "medical education",
        "physical therapist education",
        "simulation",
        "assessment",
        "preceptorship",
        "clinical education",
    ],
    "Formation par concordance / TCS": [
        "script concordance",
        "concordance test",
        "learning by concordance",
        "concordance",
    ],
    "IA / diagnostic / physiothérapie MSK": [
        "artificial intelligence",
        "ai",
        "diagnostic utility",
        "musculoskeletal",
        "physical therapy",
        "physical therapist",
    ],
    "Rachis / OMT / tests / traitements": [
        "spine",
        "whole-spine",
        "low back pain",
        "cervical",
        "thoracic",
        "lumbar",
        "sensorimotor",
        "manual therapy",
        "orthopaedic manual physical therapy",
        "orthopedic manual physical therapy",
        "ompt",
        "omt",
    ],
    "Cas cliniques / diagnostic différentiel": [
        "case report",
        "case study",
        "differential diagnosis",
        "management",
        "syndrome",
        "dizziness",
    ],
}


def find_latest_report() -> Path:
    reports = sorted(REPORTS_DIR.glob("veille_*.md"), reverse=True)
    if not reports:
        raise FileNotFoundError("Aucun rapport de veille trouvé dans le dossier reports/")
    return reports[0]


def get_section(text: str, section_title: str, next_titles: list[str]) -> str:
    next_pattern = "|".join([re.escape(title) for title in next_titles])
    pattern = rf"## {re.escape(section_title)}\s+(.*?)(?=\n## ({next_pattern})|\Z)"
    match = re.search(pattern, text, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_synthesis(report_text: str) -> str:
    synthesis_match = re.search(
        r"## Synthèse\s+(.*?)(?=\n## Haute priorité)",
        report_text,
        flags=re.DOTALL,
    )
    return synthesis_match.group(1).strip() if synthesis_match else "Synthèse non trouvée."


def split_articles(section_text: str) -> list[str]:
    """
    Découpe une section Markdown en blocs d'articles.
    Le rapport semble utiliser des titres de niveau ### pour chaque article.
    """
    chunks = re.split(r"\n(?=###\s+)", section_text)
    return [chunk.strip() for chunk in chunks if chunk.strip().startswith("### ")]


def first_match(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ""


def clean_markdown(value: str) -> str:
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return value.strip(" -:\n\t")


def extract_article_info(article_block: str) -> dict:
    title_match = re.search(r"^###\s+(.+)$", article_block, flags=re.MULTILINE)
    title = clean_markdown(title_match.group(1)) if title_match else "Titre non trouvé"

    authors = first_match(
        [
            r"^\s*[-*]\s*\*\*Auteurs?\*\*\s*:\s*(.+)$",
            r"^\s*[-*]\s*Auteurs?\s*:\s*(.+)$",
            r"^\s*[-*]\s*\*\*Authors?\*\*\s*:\s*(.+)$",
            r"^\s*[-*]\s*Authors?\s*:\s*(.+)$",
        ],
        article_block,
    )
    authors = clean_markdown(authors) if authors else "Auteur non trouvé"

    first_author = authors.split(",")[0].strip() if authors else "Auteur non trouvé"

    year = first_match(
        [
            r"^\s*[-*]\s*\*\*Année\*\*\s*:\s*(\d{4})",
            r"^\s*[-*]\s*Année\s*:\s*(\d{4})",
            r"^\s*[-*]\s*\*\*Year\*\*\s*:\s*(\d{4})",
            r"^\s*[-*]\s*Year\s*:\s*(\d{4})",
            r"\b(20\d{2}|19\d{2})\b",
        ],
        article_block,
    )
    year = year if year else "année non trouvée"

    doi = first_match(
        [
            r"^\s*[-*]\s*\*\*DOI\*\*\s*:\s*(.+)$",
            r"^\s*[-*]\s*DOI\s*:\s*(.+)$",
            r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
        ],
        article_block,
    )
    doi = clean_markdown(doi)

    url = first_match(
        [
            r"^\s*[-*]\s*\*\*Lien\*\*\s*:\s*(.+)$",
            r"^\s*[-*]\s*Lien\s*:\s*(.+)$",
            r"^\s*[-*]\s*\*\*URL\*\*\s*:\s*(.+)$",
            r"^\s*[-*]\s*URL\s*:\s*(.+)$",
            r"(https?://[^\s)]+)",
        ],
        article_block,
    )
    url = clean_markdown(url)

    if doi:
        link = f"https://doi.org/{doi}" if doi.startswith("10.") else doi
    elif url:
        link = url
    else:
        link = "Lien non trouvé dans le rapport"

    score = first_match(
        [
            r"^\s*[-*]\s*\*\*Score\*\*\s*:\s*(\d+)",
            r"^\s*[-*]\s*Score\s*:\s*(\d+)",
        ],
        article_block,
    )
    score_int = int(score) if score.isdigit() else 0

    return {
        "title": title,
        "authors": authors,
        "first_author": first_author,
        "year": year,
        "doi": doi,
        "link": link,
        "score": score_int,
        "raw": article_block,
    }


def classify_theme(article: dict) -> str:
    searchable = f"{article['title']} {article['raw']}".lower()

    best_theme = "Autres articles pertinents"
    best_count = 0

    for theme, keywords in THEMES.items():
        count = sum(1 for keyword in keywords if keyword.lower() in searchable)
        if count > best_count:
            best_count = count
            best_theme = theme

    return best_theme


def format_article_line(article: dict, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else "- "
    return (
        f"{prefix}{article['first_author']} ({article['year']}). "
        f"{article['title']}\n"
        f"   DOI/lien : {article['link']}"
    )


def build_digest(report_text: str) -> str:
    synthesis = extract_synthesis(report_text)

    high_section = get_section(
        report_text,
        "Haute priorité",
        ["À surveiller", "Périphérique", "Faible priorité"],
    )

    article_blocks = split_articles(high_section)
    high_articles = [extract_article_info(block) for block in article_blocks]

    # Le rapport est déjà classé par priorité ; on garde l'ordre, puis score si disponible.
    high_articles = sorted(
        high_articles,
        key=lambda article: article["score"],
        reverse=True,
    ) if any(article["score"] > 0 for article in high_articles) else high_articles

    top5 = high_articles[:5]

    themed_articles = {}
    for article in high_articles:
        theme = classify_theme(article)
        themed_articles.setdefault(theme, []).append(article)

    top5_text = "\n\n".join(
        format_article_line(article, index=i + 1)
        for i, article in enumerate(top5)
    ) if top5 else "Aucun article prioritaire cette semaine."

    themes_text_parts = []
    for theme, articles in themed_articles.items():
        theme_lines = [f"### {theme}"]
        for article in articles:
            theme_lines.append(format_article_line(article))
        themes_text_parts.append("\n".join(theme_lines))

    themes_text = "\n\n".join(themes_text_parts) if themes_text_parts else "Aucun article thématique cette semaine."

    return f"""Bonjour Antoine,

Voici ta veille scientifique hebdomadaire.

## Synthèse

{synthesis}

## Top 5 à lire cette semaine

{top5_text}

## Articles haute priorité classés par thèmes

{themes_text}

Le rapport complet est en pièce jointe au format Markdown.

Bonne lecture !
"""


def send_email(report_path: Path) -> None:
    smtp_username = os.environ["SMTP_USERNAME"].strip()
    smtp_password = os.environ["SMTP_PASSWORD"].strip().replace(" ", "")
    mail_to = os.environ["MAIL_TO"].strip()

    print(f"SMTP_USERNAME détecté : {smtp_username}")
    print(f"MAIL_TO détecté : {mail_to}")
    print(f"Longueur SMTP_PASSWORD : {len(smtp_password)} caractères")

    report_text = report_path.read_text(encoding="utf-8")
    body = build_digest(report_text)

    today = date.today().isoformat()

    msg = EmailMessage()
    msg["Subject"] = f"Veille scientifique hebdomadaire — {today}"
    msg["From"] = smtp_username
    msg["To"] = mail_to
    msg.set_content(body)

    msg.add_attachment(
        report_text.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=report_path.name,
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(smtp_username, smtp_password)
        smtp.send_message(msg)

    print(f"Email envoyé à {mail_to} avec le rapport {report_path.name}")


def main() -> int:
    report_path = find_latest_report()
    send_email(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
