import os
import re
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BASE_DIR / "reports"


def find_latest_report() -> Path:
    reports = sorted(REPORTS_DIR.glob("veille_*.md"), reverse=True)
    if not reports:
        raise FileNotFoundError("Aucun rapport de veille trouvé dans le dossier reports/")
    return reports[0]


def extract_summary(report_text: str) -> str:
    synthesis_match = re.search(
        r"## Synthèse\s+(.*?)(?=\n## Haute priorité)",
        report_text,
        flags=re.DOTALL,
    )
    synthesis = synthesis_match.group(1).strip() if synthesis_match else "Synthèse non trouvée."

    high_priority_match = re.search(
        r"## Haute priorité\s+(.*?)(?=\n## À surveiller)",
        report_text,
        flags=re.DOTALL,
    )
    high_priority_block = high_priority_match.group(1).strip() if high_priority_match else ""

    titles = re.findall(r"^### (.+)$", high_priority_block, flags=re.MULTILINE)

    if titles:
        top_articles = "\n".join(
            [f"{i + 1}. {title}" for i, title in enumerate(titles[:10])]
        )
    else:
        top_articles = "Aucun article en haute priorité cette semaine."

    return f"""Bonjour Antoine,

Voici ta veille scientifique hebdomadaire.

Synthèse :
{synthesis}

Articles haute priorité :
{top_articles}

Le rapport complet est en pièce jointe au format Markdown.

Bonne lecture !
"""


def send_email(report_path: Path) -> None:
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    mail_to = os.environ["MAIL_TO"]

    report_text = report_path.read_text(encoding="utf-8")
    body = extract_summary(report_text)

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
