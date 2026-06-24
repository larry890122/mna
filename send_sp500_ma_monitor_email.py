from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import smtplib
from email.message import EmailMessage


def load_payload(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_subject(target_date: str, article_count: int) -> str:
    if article_count == 0:
        return f"S&P 500 M&A Monitor | {target_date} | No M&A headlines"
    return f"S&P 500 M&A Monitor | {target_date} | {article_count} headline(s)"


def format_price(company: dict) -> str:
    perf = (company or {}).get("price_performance") or {}
    if perf.get("change_pct") is None:
        return f"{company['security']} ({company['symbol']}): no same-day price"

    change_pct = perf["change_pct"]
    direction = "+" if change_pct >= 0 else ""
    return (
        f"{company['security']} ({company['symbol']}): "
        f"{direction}{change_pct:.2f}% | close {perf['close']} | prev {perf['previous_close']}"
    )


def build_body(payload: dict) -> str:
    target_date = payload["target_date_et"]
    generated_at = payload["generated_at_local"]
    article_count = len(payload.get("articles") or [])

    lines: list[str] = []
    lines.append(f"S&P 500 M&A Monitor")
    lines.append(f"Target date (U.S. Eastern): {target_date}")
    lines.append(f"Generated at: {generated_at}")
    lines.append("")

    for summary_line in payload.get("summary") or []:
        lines.append(f"- {summary_line}")

    if article_count == 0:
        lines.append("")
        lines.append("No qualifying M&A headlines were found in Yahoo Finance, Seeking Alpha, WSJ, or Financial Times.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Headlines")

    for index, article in enumerate(payload["articles"], start=1):
        lines.append("")
        lines.append(f"{index}. Companies")
        for company in article.get("matched_companies") or []:
            lines.append(f"   - {company['security']} ({company['symbol']})")

        lines.append(f"   Headline: [{article['source_label']}] {article['title']}")
        lines.append(f"   Published (ET): {article['published_at_et']}")
        lines.append("   Stock move:")
        for company in article.get("matched_companies") or []:
            lines.append(f"   - {format_price(company)}")
        lines.append(f"   Google News: {article['google_news_link']}")

    return "\n".join(lines)


def send_email(
    *,
    smtp_host: str,
    smtp_port: int,
    sender: str,
    password: str,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(sender, password)
        server.send_message(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--payload-path",
        default=str(pathlib.Path(__file__).resolve().parent / "output" / "latest_sp500_ma_monitor.json"),
    )
    parser.add_argument("--recipient", default=os.environ.get("EMAIL_TO", ""))
    parser.add_argument("--sender", default=os.environ.get("GMAIL_SENDER", ""))
    parser.add_argument("--password", default=os.environ.get("GMAIL_APP_PASSWORD", ""))
    parser.add_argument("--smtp-host", default=os.environ.get("GMAIL_SMTP_HOST", "smtp.gmail.com"))
    parser.add_argument("--smtp-port", type=int, default=int(os.environ.get("GMAIL_SMTP_PORT", "465")))
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the email subject and body without sending.",
    )
    args = parser.parse_args()

    payload = load_payload(pathlib.Path(args.payload_path))
    subject = build_subject(payload["target_date_et"], len(payload.get("articles") or []))
    body = build_body(payload)

    if args.print_only:
        print(subject)
        print("")
        print(body)
        return

    if not args.recipient:
        raise ValueError("Missing recipient. Set --recipient or EMAIL_TO.")
    if not args.sender:
        raise ValueError("Missing sender. Set --sender or GMAIL_SENDER.")
    if not args.password:
        raise ValueError("Missing app password. Set --password or GMAIL_APP_PASSWORD.")

    send_email(
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        sender=args.sender,
        password=args.password,
        recipient=args.recipient,
        subject=subject,
        body=body,
    )

    print(f"Sent email to {args.recipient} for {payload['target_date_et']}.")


if __name__ == "__main__":
    main()
