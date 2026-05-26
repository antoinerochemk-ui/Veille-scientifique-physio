import html
import os
import re
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BASE_DIR / "reports"


THEMES = {
    "Formation par concordance / TCS": [
        "script concordance test",
        "script concordance tests",
        "script concordance testing",
        "script concordance",
        "learning by concordance",
        "concordance-based learning",
        "formation par concordance",
    ],
    "Raisonnement clinique / éducation": [
        "clinical reasoning",
        "diagnostic reasoning",
        "clinical decision making",
        "clinical decision-making",
        "medical education",
        "health professions education",
        "physical therapist education",
        "simulation-based learning",
        "simulation",
        "assessment",
        "preceptorship",
        "clinical education",
    ],
    "IA / diagnostic / physiothérapie MSK": [
        "artificial intelligence",
        "diagnostic utility",
        "machine learning",
        "musculoskeletal physical therapy",
        "musculoskeletal",
        "physical therapists",
    ],
    "Rachis / OMT / tests / traitements": [
        "whole-spine",
        "spine",
        "low back pain",
        "neck pain",
        "cervical",
        "thoracic",
        "lumbar",
        "sensorimotor",
        "manual therapy",
        "orthopaedic manual physical therapy",
        "orthopedic manual physical therapy",
        "omt",
        "ompt",
    ],
    "Cas cliniques / diagnostic différentiel": [
        "case report",
        "case study",
        "rare case",
        "differential diagnosis",
        "syndrome",
        "dizziness",
    ],
}


THEME_COLORS = {
    "Formation par concordance / TCS": "#7C3AED",
    "Raisonnement clinique / éducation": "#2563EB",
    "IA / diagnostic / physiothérapie MSK": "#059669",
    "Rachis / OMT / tests / traitements": "#EA580C",
    "Cas cliniques / diagnostic différentiel": "#DC2626",
    "Autres articles pertinents": "#4B5563",
}


WHY_READ = {
    "Formation par concordance / TCS": (
        "Directement lié à ton axe Formation par Concordance / TCS et à l’évaluation du raisonnement clinique."
    ),
    "Raisonnement clinique / éducation": (
        "Pertinent pour ta thèse, les ECOS, l’évaluation et l’enseignement du raisonnement clinique."
    ),
    "IA / diagnostic / physiothérapie MSK": (
        "Utile pour suivre l’impact de l’IA sur le diagnostic, la décision clinique et la physiothérapie MSK."
    ),
    "Rachis / OMT / tests / traitements": (
        "Pertinent pour ton axe rachis, thérapie manuelle, tests cliniques et interventions MSK."
    ),
    "Cas cliniques / diagnostic différentiel": (
        "À lire surtout si le cas apporte une réflexion utile sur le diagnostic différentiel ou la prise en charge."
    ),
    "Autres articles pertinents": (
        "Article potentiellement intéressant, mais à vérifier selon ton temps disponible et tes priorités."
    ),
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


def extract_synthesis(report_text: str) -> dict:
    synthesis_match = re.search(
        r"## Synthèse\s+(.*?)(?=\n## Haute priorité)",
        report_text,
        flags=re.DOTALL,
    )

    synthesis = synthesis_match.group(1).strip() if synthesis_match else ""

    def extract_number(label: str) -> str:
        pattern = rf"{re.escape(label)}\s*:\s*\*\*(\d+)\*\*"
        match = re.search(pattern, synthesis)
        return match.group(1) if match else "0"

    return {
        "new_articles": extract_number("Articles nouveaux détectés"),
        "high": extract_number("Haute priorité"),
        "watch": extract_number("À surveiller"),
        "peripheral": extract_number("Périphérique"),
        "low": extract_number("Faible priorité"),
    }


def split_articles(section_text: str) -> list[str]:
    chunks = re.split(r"\n(?=###\s+)", section_text)
    return [chunk.strip() for chunk in chunks if chunk.strip().startswith("### ")]


def first_match(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ""


def clean_markdown(value: str) -> str:
    value = value or ""
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
        link = ""

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
    title = article["title"].lower()
    searchable = f"{article['title']} {article['raw']}".lower()

    if any(
        term in title
        for term in [
            "script concordance",
            "learning by concordance",
            "concordance-based learning",
            "formation par concordance",
        ]
    ):
        return "Formation par concordance / TCS"

    if any(
        term in title
        for term in [
            "clinical reasoning",
            "diagnostic reasoning",
            "clinical decision making",
            "clinical decision-making",
            "preceptorship",
            "simulation",
        ]
    ):
        return "Raisonnement clinique / éducation"

    if any(
        term in title
        for term in [
            "artificial intelligence",
            "diagnostic utility",
            "machine learning",
        ]
    ):
        return "IA / diagnostic / physiothérapie MSK"

    if any(
        term in title
        for term in [
            "spine",
            "whole-spine",
            "low back pain",
            "neck pain",
            "cervical",
            "lumbar",
            "thoracic",
            "sensorimotor",
            "manual therapy",
            "orthopaedic manual physical therapy",
            "orthopedic manual physical therapy",
        ]
    ):
        return "Rachis / OMT / tests / traitements"

    if any(
        term in title
        for term in [
            "case report",
            "case study",
            "rare case",
            "differential diagnosis",
            "syndrome",
            "dizziness",
        ]
    ):
        return "Cas cliniques / diagnostic différentiel"

    best_theme = "Autres articles pertinents"
    best_count = 0

    for theme, keywords in THEMES.items():
        count = sum(1 for keyword in keywords if keyword.lower() in searchable)
        if count > best_count:
            best_count = count
            best_theme = theme

    return best_theme


def escape(value: str) -> str:
    return html.escape(value or "")


def article_card_html(article: dict, rank: int | None = None) -> str:
    theme = article["theme"]
    color = THEME_COLORS.get(theme, THEME_COLORS["Autres articles pertinents"])
    why = WHY_READ.get(theme, WHY_READ["Autres articles pertinents"])

    rank_html = f"<span style='font-weight:700;color:{color};'>#{rank}</span> " if rank else ""
    link_html = (
        f"<a href='{escape(article['link'])}' style='color:{color};text-decoration:none;font-weight:600;'>DOI / lien</a>"
        if article["link"]
        else "<span style='color:#6B7280;'>Lien non trouvé</span>"
    )

    return f"""
    <div style="border:1px solid #E5E7EB;border-left:6px solid {color};border-radius:14px;padding:14px 16px;margin:12px 0;background:#FFFFFF;">
        <div style="font-size:13px;color:{color};font-weight:700;text-transform:uppercase;letter-spacing:0.03em;margin-bottom:6px;">
            {escape(theme)}
        </div>
        <div style="font-size:16px;line-height:1.35;color:#111827;font-weight:700;margin-bottom:6px;">
            {rank_html}{escape(article['first_author'])} ({escape(article['year'])})
        </div>
        <div style="font-size:15px;line-height:1.4;color:#1F2937;margin-bottom:8px;">
            {escape(article['title'])}
        </div>
        <div style="font-size:13px;color:#374151;margin-bottom:8px;">
            {link_html}
        </div>
        <div style="font-size:13px;line-height:1.45;color:#4B5563;background:#F9FAFB;border-radius:10px;padding:10px;">
            <strong>Pourquoi le lire ?</strong> {escape(why)}
        </div>
    </div>
    """


def article_plain_text(article: dict, rank: int | None = None) -> str:
    prefix = f"{rank}. " if rank else "- "
    why = WHY_READ.get(article["theme"], WHY_READ["Autres articles pertinents"])

    return (
        f"{prefix}{article['first_author']} ({article['year']}). {article['title']}\n"
        f"   Thème : {article['theme']}\n"
        f"   DOI/lien : {article['link'] or 'Lien non trouvé'}\n"
        f"   Pourquoi le lire ? {why}"
    )


def build_digest_data(report_text: str) -> dict:
    synthesis = extract_synthesis(report_text)

    high_section = get_section(
        report_text,
        "Haute priorité",
        ["À surveiller", "Périphérique", "Faible priorité"],
    )

    article_blocks = split_articles(high_section)
    high_articles = [extract_article_info(block) for block in article_blocks]

    for article in high_articles:
        article["theme"] = classify_theme(article)

    if any(article["score"] > 0 for article in high_articles):
        high_articles = sorted(
            high_articles,
            key=lambda article: article["score"],
            reverse=True,
        )

    top3_general = high_articles[:3]

    themed_articles = {}
    for article in high_articles:
        theme = article["theme"]
        themed_articles.setdefault(theme, []).append(article)

    top3_by_theme = {
        theme: articles[:3]
        for theme, articles in themed_articles.items()
    }

    return {
        "synthesis": synthesis,
        "top3_general": top3_general,
        "top3_by_theme": top3_by_theme,
    }


def build_plain_body(data: dict) -> str:
    synthesis = data["synthesis"]

    top3_text = "\n\n".join(
        article_plain_text(article, rank=i + 1)
        for i, article in enumerate(data["top3_general"])
    ) or "Aucun article prioritaire cette semaine."

    theme_parts = []
    for theme, articles in data["top3_by_theme"].items():
        lines = [theme]
        for article in articles:
            lines.append(article_plain_text(article))
        theme_parts.append("\n\n".join(lines))

    themes_text = "\n\n".join(theme_parts) or "Aucun article thématique cette semaine."

    return f"""Bonjour Antoine,

Voici ta veille scientifique hebdomadaire.

Synthèse :
- Articles nouveaux détectés : {synthesis['new_articles']}
- Haute priorité : {synthesis['high']}
- À surveiller : {synthesis['watch']}
- Périphérique : {synthesis['peripheral']}
- Faible priorité : {synthesis['low']}

Top 3 général :

{top3_text}

Top 3 par thématique :

{themes_text}

Le rapport complet est en pièce jointe au format Markdown.

Bonne lecture !
"""


def build_html_body(data: dict) -> str:
    synthesis = data["synthesis"]

    top3_cards = "\n".join(
        article_card_html(article, rank=i + 1)
        for i, article in enumerate(data["top3_general"])
    )

    theme_sections = []
    for theme, articles in data["top3_by_theme"].items():
        color = THEME_COLORS.get(theme, THEME_COLORS["Autres articles pertinents"])
        cards = "\n".join(article_card_html(article) for article in articles)

        theme_sections.append(
            f"""
            <div style="margin-top:26px;">
                <h3 style="font-size:18px;color:{color};margin:0 0 10px 0;border-bottom:2px solid {color};padding-bottom:6px;">
                    {escape(theme)}
                </h3>
                {cards}
            </div>
            """
        )

    theme_sections_html = "\n".join(theme_sections)

    return f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#F3F4F6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <div style="max-width:820px;margin:0 auto;padding:24px;">
        <div style="background:#FFFFFF;border-radius:18px;padding:26px;border:1px solid #E5E7EB;">
            <h1 style="font-size:26px;line-height:1.25;margin:0 0 8px 0;color:#111827;">
                Veille scientifique hebdomadaire
            </h1>
            <p style="font-size:15px;color:#4B5563;margin:0 0 24px 0;">
                Bonjour Antoine, voici ta synthèse automatisée de la semaine.
            </p>

            <div style="display:block;background:#F9FAFB;border-radius:14px;padding:16px;margin-bottom:24px;border:1px solid #E5E7EB;">
                <h2 style="font-size:19px;margin:0 0 12px 0;color:#111827;">Synthèse</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr>
                        <td style="padding:6px 0;color:#374151;">Articles nouveaux détectés</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;">{escape(synthesis['new_articles'])}</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 0;color:#374151;">Haute priorité</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;color:#DC2626;">{escape(synthesis['high'])}</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 0;color:#374151;">À surveiller</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;color:#D97706;">{escape(synthesis['watch'])}</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 0;color:#374151;">Périphérique</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;color:#2563EB;">{escape(synthesis['peripheral'])}</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 0;color:#374151;">Faible priorité</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;color:#6B7280;">{escape(synthesis['low'])}</td>
                    </tr>
                </table>
            </div>

            <h2 style="font-size:21px;margin:0 0 14px 0;color:#111827;">
                Top 3 général à lire
            </h2>
            {top3_cards if top3_cards else "<p>Aucun article prioritaire cette semaine.</p>"}

            <h2 style="font-size:21px;margin:30px 0 14px 0;color:#111827;">
                Top 3 par thématique
            </h2>
            {theme_sections_html if theme_sections_html else "<p>Aucun article thématique cette semaine.</p>"}

            <div style="margin-top:28px;padding:14px;border-radius:12px;background:#EFF6FF;color:#1E3A8A;font-size:14px;line-height:1.45;">
                Le rapport complet est en pièce jointe au format Markdown.
            </div>

            <p style="font-size:14px;color:#4B5563;margin-top:22px;">
                Bonne lecture !
            </p>
        </div>
    </div>
</body>
</html>
"""


def send_email(report_path: Path) -> None:
    smtp_username = os.environ["SMTP_USERNAME"].strip()
    smtp_password = os.environ["SMTP_PASSWORD"].strip().replace(" ", "")
    mail_to = os.environ["MAIL_TO"].strip()

    print(f"SMTP_USERNAME détecté : {smtp_username}")
    print(f"MAIL_TO détecté : {mail_to}")
    print(f"Longueur SMTP_PASSWORD : {len(smtp_password)} caractères")

    report_text = report_path.read_text(encoding="utf-8")
    data = build_digest_data(report_text)

    plain_body = build_plain_body(data)
    html_body = build_html_body(data)

    today = date.today().isoformat()

    msg = EmailMessage()
    msg["Subject"] = f"Veille scientifique hebdomadaire — {today}"
    msg["From"] = smtp_username
    msg["To"] = mail_to

    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

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
