from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


USER_AGENT = "Mozilla/5.0"
WIKIPEDIA_RAW_URL = (
    "https://en.wikipedia.org/w/index.php?title=List_of_S%26P_500_companies&action=raw"
)
UTC = dt.timezone.utc
EASTERN_STANDARD = dt.timezone(dt.timedelta(hours=-5), "EST")
EASTERN_DAYLIGHT = dt.timezone(dt.timedelta(hours=-4), "EDT")

SOURCE_BUCKETS = [
    {
        "key": "yahoo_finance",
        "label": "Yahoo Finance",
        "site_clause": "site:finance.yahoo.com OR site:uk.finance.yahoo.com",
        "accepted_sources": {"Yahoo Finance", "Yahoo Finance UK"},
    },
    {
        "key": "seeking_alpha",
        "label": "Seeking Alpha",
        "site_clause": "site:seekingalpha.com",
        "accepted_sources": {"Seeking Alpha"},
    },
    {
        "key": "wsj",
        "label": "WSJ",
        "site_clause": "site:wsj.com",
        "accepted_sources": {"WSJ", "The Wall Street Journal"},
    },
    {
        "key": "financial_times",
        "label": "Financial Times",
        "site_clause": "site:ft.com",
        "accepted_sources": {"Financial Times"},
    },
]

MNA_KEYWORDS = [
    "acquisition",
    "acquire",
    "acquires",
    "acquired",
    "acquiring",
    "buyout",
    "buys",
    "buy",
    "merger",
    "merge",
    "merges",
    "spin off",
    "spinoff",
    "split-off",
    "split off",
    "takeover",
    "take over",
    "divestiture",
    "divest",
    "sale",
    "deal",
]

EXPLICIT_MNA_PATTERN = re.compile(
    r"\b("
    r"acquisition|acquire|acquires|acquired|acquiring|buyout|"
    r"merger|merge|merges|spin\s+off|spinoff|split[-\s]off|"
    r"takeover|take\s+over|divestiture|divest"
    r")\b",
    re.IGNORECASE,
)

BUY_TRANSACTION_PATTERNS = [
    re.compile(
        r"\bbuys?\b\s+.+\b("
        r"company|companies|firm|business|unit|units|stake|assets?|rival|"
        r"drugmaker|startup|platform|ad(?:vertising)?\s+tech\s+firm"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^[A-Z0-9][A-Za-z0-9&.'-]*(?:\s+[A-Z0-9][A-Za-z0-9&.'-]*){0,5}\s+to\s+buy\s+[A-Z0-9]",
    ),
]

COMMON_NAME_OVERRIDES = {
    "Alphabet Inc. Class A": {"Alphabet", "Google"},
    "Alphabet Inc. Class C": {"Alphabet", "Google"},
    "Berkshire Hathaway Class B": {"Berkshire Hathaway", "Berkshire"},
    "Brown & Brown": {"Brown and Brown"},
    "Capital One": {"Capital One Financial"},
    "Cboe Global Markets": {"CBOE"},
    "Charles River Laboratories": {"Charles River"},
    "Chipotle Mexican Grill": {"Chipotle"},
    "Constellation Energy": {"Constellation"},
    "Corteva": {"Corteva Agriscience"},
    "D. R. Horton": {"DR Horton"},
    "Dollar Tree": {"Dollar Tree Inc"},
    "EOG Resources": {"EOG"},
    "Ford Motor Company": {"Ford"},
    "Fox Corporation Class A": {"Fox"},
    "Fox Corporation Class B": {"Fox"},
    "GE Aerospace": {"General Electric", "GE"},
    "Hewlett Packard Enterprise": {"HPE"},
    "Howmet Aerospace": {"Howmet"},
    "International Business Machines": {"IBM"},
    "J. B. Hunt": {"JB Hunt"},
    "JPMorgan Chase": {"JP Morgan", "J.P. Morgan"},
    "Kimberly-Clark": {"Kimberly Clark"},
    "L3Harris": {"L3 Harris"},
    "LKQ Corporation": {"LKQ"},
    "M&T Bank": {"MT Bank", "M and T Bank"},
    "McDonald's": {"McDonalds"},
    "Merck & Co.": {"Merck"},
    "News Corp Class A": {"News Corp"},
    "News Corp Class B": {"News Corp"},
    "Norfolk Southern Railway": {"Norfolk Southern"},
    "Procter & Gamble": {"Procter and Gamble", "P&G"},
    "S&P Global": {"SP Global"},
    "Simon Property Group": {"Simon Property"},
    "Walmart": {"Wal-Mart"},
    "Warner Bros. Discovery": {"Warner Bros Discovery"},
}


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> dt.date:
    first_day = dt.date(year, month, 1)
    offset = (weekday - first_day.weekday()) % 7
    day = 1 + offset + (occurrence - 1) * 7
    return dt.date(year, month, day)


def eastern_timezone_for_utc(moment_utc: dt.datetime) -> dt.timezone:
    year = moment_utc.year
    dst_start_date = nth_weekday_of_month(year, 3, 6, 2)
    dst_end_date = nth_weekday_of_month(year, 11, 6, 1)
    dst_start_utc = dt.datetime(year, 3, dst_start_date.day, 7, 0, tzinfo=UTC)
    dst_end_utc = dt.datetime(year, 11, dst_end_date.day, 6, 0, tzinfo=UTC)

    if dst_start_utc <= moment_utc < dst_end_utc:
        return EASTERN_DAYLIGHT
    return EASTERN_STANDARD


def to_eastern(moment_utc: dt.datetime) -> dt.datetime:
    normalized = moment_utc.astimezone(UTC)
    return normalized.astimezone(eastern_timezone_for_utc(normalized))


def clean_wikitext(value: str) -> str:
    text = value.strip()
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\{[^|{}]+\|([^{}]+)\}\}", r"\1", text)
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = text.replace("&nbsp;", " ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_symbol_cell(value: str) -> str:
    match = re.search(r"\{\{(?:NyseSymbol|NasdaqSymbol)\|([^}|]+)", value)
    if match:
        return match.group(1).strip()
    return clean_wikitext(value)


def parse_constituent_row(row_lines: list[str]) -> dict | None:
    cells: list[str] = []
    for line in row_lines:
        content = line[1:].strip()
        cells.extend(part.strip() for part in content.split("||"))

    if len(cells) < 8:
        return None

    return {
        "symbol": parse_symbol_cell(cells[0]),
        "security": clean_wikitext(cells[1]),
        "sector": clean_wikitext(cells[2]),
        "sub_industry": clean_wikitext(cells[3]),
        "headquarters": clean_wikitext(cells[4]),
        "date_added": clean_wikitext(cells[5]),
        "cik": clean_wikitext(cells[6]),
        "founded": clean_wikitext(cells[7]),
    }


def parse_sp500_constituents() -> list[dict]:
    raw = fetch_text(WIKIPEDIA_RAW_URL)
    lines = raw.splitlines()

    in_table = False
    current_row: list[str] = []
    constituents: list[dict] = []

    for line in lines:
        if not in_table and line.startswith("{|") and 'id="constituents"' in line:
            in_table = True
            continue

        if not in_table:
            continue

        if line.startswith("|}"):
            if current_row:
                row = parse_constituent_row(current_row)
                if row:
                    constituents.append(row)
            break

        if line.startswith("|-"):
            if current_row:
                row = parse_constituent_row(current_row)
                if row:
                    constituents.append(row)
            current_row = []
            continue

        if line.startswith("!"):
            continue

        if line.startswith("|"):
            current_row.append(line)

    if not constituents:
        raise RuntimeError("Unable to parse the S&P 500 constituents table.")

    return constituents


def generate_aliases(security: str, symbol: str) -> set[str]:
    aliases = {("name", security)}

    security_without_class = normalize_company_name(security)
    if security_without_class:
        aliases.add(("name", security_without_class))

    security_without_suffix = re.sub(
        (
            r",?\s+("
            r"Inc\.?|Corporation|Corp\.?|Company|Companies|Co\.?|Group|"
            r"Holdings?|Limited|Ltd\.?|plc|N\.V\.|S\.A\.|Class\s+[A-Z0-9]+"
            r")$"
        ),
        "",
        security,
        flags=re.IGNORECASE,
    ).strip()
    if security_without_suffix and len(security_without_suffix) >= 3:
        aliases.add(("name", security_without_suffix))

    if "&" in security:
        aliases.add(("name", security.replace("&", "and")))

    if re.fullmatch(r"[A-Z0-9.\-]{2,6}", security):
        aliases.add(("name", security))

    if len(symbol) >= 3:
        aliases.add(("symbol", symbol))

    for alias in COMMON_NAME_OVERRIDES.get(security, set()):
        aliases.add(("name", alias))

    return {
        (alias_type, alias.strip())
        for alias_type, alias in aliases
        if alias.strip() and len(alias.strip()) >= 2
    }


def build_alias_records(constituents: list[dict]) -> list[dict]:
    records: list[dict] = []
    seen_aliases: set[tuple[str, str]] = set()

    for row in constituents:
        aliases = generate_aliases(row["security"], row["symbol"])
        for alias_type, alias in aliases:
            key = (row["symbol"], alias_type, alias.casefold())
            if key in seen_aliases:
                continue
            seen_aliases.add(key)
            records.append(
                {
                    "symbol": row["symbol"],
                    "security": row["security"],
                    "sector": row["sector"],
                    "alias_type": alias_type,
                    "alias": alias,
                    "sort_key": (len(alias), row["security"], alias_type, alias),
                }
            )

    records.sort(key=lambda item: item["sort_key"], reverse=True)
    return records


def parse_target_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)

    now_et = to_eastern(dt.datetime.now(UTC))
    return latest_completed_us_market_date(now_et)


def previous_weekday(day: dt.date) -> dt.date:
    current = day
    while current.weekday() >= 5:
        current -= dt.timedelta(days=1)
    return current


def latest_completed_us_market_date(now_et: dt.datetime) -> dt.date:
    today_et = now_et.date()

    if today_et.weekday() >= 5:
        return previous_weekday(today_et - dt.timedelta(days=1))

    market_close_buffer = dt.time(17, 0)
    if now_et.time() >= market_close_buffer:
        return today_et

    return previous_weekday(today_et - dt.timedelta(days=1))


def normalize_company_name(value: str) -> str:
    return re.sub(
        r"\s*\(?Class\s+[A-Z0-9]+\)?$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def build_query(site_clause: str, target_date: dt.date) -> str:
    after_date = target_date - dt.timedelta(days=1)
    before_date = target_date + dt.timedelta(days=1)
    keyword_query = " OR ".join(f'"{keyword}"' if " " in keyword else keyword for keyword in MNA_KEYWORDS)
    return (
        f"({site_clause}) ({keyword_query}) "
        f"after:{after_date.isoformat()} before:{before_date.isoformat()}"
    )


def build_google_news_rss_url(query: str) -> str:
    encoded = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def clean_title(title: str) -> str:
    cleaned = html.unescape(title or "").strip()
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_pub_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def strip_source_suffix(title: str, source: str) -> str:
    if not source:
        return title
    return re.sub(rf"\s*-\s*{re.escape(source)}$", "", title, flags=re.IGNORECASE).strip()


def match_companies(title: str, alias_records: list[dict]) -> list[dict]:
    matched: list[dict] = []
    seen_symbols: set[str] = set()

    for record in alias_records:
        alias = record["alias"]
        if record["alias_type"] == "symbol":
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])")
        else:
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", re.IGNORECASE)
        if not pattern.search(title):
            continue
        if record["symbol"] in seen_symbols:
            continue
        if should_skip_alias_match(title, record):
            continue

        seen_symbols.add(record["symbol"])
        matched.append(
            {
                "symbol": record["symbol"],
                "security": record["security"],
                "sector": record["sector"],
                "matched_alias": alias,
            }
        )

    matched.sort(key=lambda row: row["security"])
    return matched


def should_skip_alias_match(title: str, record: dict) -> bool:
    if record["symbol"] != "NDAQ":
        return False

    if record["alias_type"] != "name":
        return False

    if record["alias"].casefold() != "nasdaq":
        return False

    # Skip exchange suffixes like "(ADBE:NASDAQ)" that are not references to Nasdaq, Inc.
    if re.search(r"\([A-Z0-9.\-]+:NASDAQ\)", title):
        return True

    return False


def is_mna_title(title: str) -> bool:
    if EXPLICIT_MNA_PATTERN.search(title):
        return True
    return any(pattern.search(title) for pattern in BUY_TRANSACTION_PATTERNS)


def fetch_bucket_articles(bucket: dict, target_date: dt.date, alias_records: list[dict]) -> list[dict]:
    url = build_google_news_rss_url(build_query(bucket["site_clause"], target_date))
    root = ET.fromstring(fetch_text(url))

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for item in root.findall("./channel/item"):
        source = clean_title(item.findtext("source") or "")
        if bucket["accepted_sources"] and source not in bucket["accepted_sources"]:
            continue

        raw_title = clean_title(item.findtext("title") or "")
        if not raw_title:
            continue

        title = strip_source_suffix(raw_title, source)
        if not is_mna_title(title):
            continue

        published_utc = parse_pub_datetime(item.findtext("pubDate"))
        if not published_utc:
            continue

        published_et = to_eastern(published_utc)
        if published_et.date() != target_date:
            continue

        matched_companies = match_companies(title, alias_records)
        if not matched_companies:
            continue

        dedupe_key = (source.lower(), title.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        items.append(
            {
                "source_key": bucket["key"],
                "source_label": bucket["label"],
                "source": source,
                "title": title,
                "google_news_link": (item.findtext("link") or "").strip(),
                "published_at_utc": published_utc.isoformat(),
                "published_at_et": published_et.isoformat(),
                "matched_companies": matched_companies,
            }
        )

    items.sort(key=lambda row: row["published_at_et"], reverse=True)
    return items


def fetch_price_performance(symbol: str, target_date: dt.date) -> dict:
    start = target_date - dt.timedelta(days=10)
    end = target_date + dt.timedelta(days=3)
    period1 = int(dt.datetime.combine(start, dt.time.min, tzinfo=UTC).timestamp())
    period2 = int(dt.datetime.combine(end, dt.time.min, tzinfo=UTC).timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?period1={period1}&period2={period2}&interval=1d&includePrePost=false&events=div%2Csplits"
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    result = payload.get("chart", {}).get("result")
    if not result:
        return {
            "symbol": symbol,
            "price_date": None,
            "close": None,
            "previous_close": None,
            "change": None,
            "change_pct": None,
            "note": "Yahoo Finance price history unavailable.",
        }

    row = result[0]
    timestamps = row.get("timestamp") or []
    closes = (row.get("indicators") or {}).get("quote", [{}])[0].get("close") or []

    series: list[tuple[dt.date, float]] = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        price_date = dt.datetime.fromtimestamp(timestamp, UTC).date()
        series.append((price_date, float(close)))

    series.sort(key=lambda item: item[0])
    target_index = next((idx for idx, item in enumerate(series) if item[0] == target_date), None)
    if target_index is None or target_index == 0:
        return {
            "symbol": symbol,
            "price_date": None,
            "close": None,
            "previous_close": None,
            "change": None,
            "change_pct": None,
            "note": "No same-day regular-session price found for the target date.",
        }

    current_date, current_close = series[target_index]
    _, previous_close = series[target_index - 1]
    change = current_close - previous_close
    change_pct = (change / previous_close) * 100 if previous_close else None

    return {
        "symbol": symbol,
        "price_date": current_date.isoformat(),
        "close": round(current_close, 4),
        "previous_close": round(previous_close, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "note": None,
    }


def enrich_with_prices(articles: list[dict], target_date: dt.date) -> None:
    cache: dict[str, dict] = {}

    for article in articles:
        for company in article["matched_companies"]:
            symbol = company["symbol"]
            if symbol not in cache:
                cache[symbol] = fetch_price_performance(symbol, target_date)
            company["price_performance"] = cache[symbol]


def summarize_articles(articles: list[dict]) -> list[str]:
    if not articles:
        return ["No M&A headlines tied to S&P 500 constituents were found in the four target sources."]

    lines = [f"Found {len(articles)} M&A headlines tied to S&P 500 constituents."]
    unique_symbols = sorted({company["symbol"] for article in articles for company in article["matched_companies"]})
    if unique_symbols:
        lines.append(f"Impacted S&P 500 tickers: {', '.join(unique_symbols)}.")
    return lines


def format_iso_for_display(value: str) -> str:
    parsed = dt.datetime.fromisoformat(value)
    return parsed.strftime("%Y-%m-%d %H:%M %Z")


def format_company_line(company: dict) -> str:
    perf = company.get("price_performance") or {}
    if perf.get("change_pct") is None:
        return f"{company['security']} ({company['symbol']}, no same-day price)"

    change_pct = perf["change_pct"]
    direction = "+" if change_pct >= 0 else ""
    return f"{company['security']} ({company['symbol']}, {direction}{change_pct:.2f}%, close {perf['close']})"


def format_company_header(company: dict) -> str:
    return f"{company['security']} ({company['symbol']})"


def render_markdown(
    *,
    generated_at_local: str,
    target_date: dt.date,
    constituent_count: int,
    unique_company_count: int,
    articles: list[dict],
) -> str:
    lines: list[str] = []
    lines.append(f"# S&P 500 M&A Monitor | {target_date.isoformat()}")
    lines.append("")
    lines.append(f"- Generated at: {generated_at_local}")
    lines.append(f"- Prior-day definition: {target_date.isoformat()} in U.S. Eastern time")
    lines.append(f"- S&P 500 verification: {constituent_count} securities / {unique_company_count} companies")
    lines.append("- Constituents source: Wikipedia `List of S&P 500 companies` fetched live")
    lines.append("- News sources scanned: Yahoo Finance, Seeking Alpha, WSJ, Financial Times")
    lines.append("")
    lines.append("## Summary")
    for line in summarize_articles(articles):
        lines.append(f"- {line}")

    lines.append("")
    lines.append("## Constituents Check")
    lines.append(f"- Parsed {constituent_count} constituent securities representing {unique_company_count} companies.")

    lines.append("")
    lines.append("## M&A Headlines")
    if not articles:
        lines.append("- No qualifying headlines.")
        return "\n".join(lines)

    for article in articles:
        company_headers = [format_company_header(company) for company in article["matched_companies"]]
        company_bits = [format_company_line(company) for company in article["matched_companies"]]
        lines.append(f"- Companies: {'; '.join(company_headers)}")
        lines.append(f"  Headline: [{article['source_label']}] {article['title']}")
        lines.append(f"  Published (ET): {format_iso_for_display(article['published_at_et'])}")
        lines.append(f"  Stock move: {'; '.join(company_bits)}")
        lines.append(f"  Google News: {article['google_news_link']}")

    return "\n".join(lines)


def write_constituent_files(output_dir: pathlib.Path, target_date: dt.date, constituents: list[dict]) -> None:
    text = json.dumps(constituents, ensure_ascii=False, indent=2)
    dated_path = output_dir / f"{target_date.isoformat()}_sp500_constituents.json"
    latest_path = output_dir / "latest_sp500_constituents.json"
    dated_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target-date",
        help="Target news date in America/New_York, format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(pathlib.Path(__file__).resolve().parent / "output"),
    )
    args = parser.parse_args()

    target_date = parse_target_date(args.target_date)
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    constituents = parse_sp500_constituents()
    alias_records = build_alias_records(constituents)

    articles: list[dict] = []
    for bucket in SOURCE_BUCKETS:
        articles.extend(fetch_bucket_articles(bucket, target_date, alias_records))

    articles.sort(key=lambda row: row["published_at_et"], reverse=True)
    enrich_with_prices(articles, target_date)

    generated_at_local = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    unique_company_count = len({normalize_company_name(row["security"]) for row in constituents})

    payload = {
        "generated_at_local": generated_at_local,
        "target_date_et": target_date.isoformat(),
        "sp500_constituent_securities": len(constituents),
        "sp500_unique_companies": unique_company_count,
        "news_sources": [bucket["label"] for bucket in SOURCE_BUCKETS],
        "summary": summarize_articles(articles),
        "articles": articles,
    }

    markdown = render_markdown(
        generated_at_local=generated_at_local,
        target_date=target_date,
        constituent_count=len(constituents),
        unique_company_count=unique_company_count,
        articles=articles,
    )

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    dated_json_path = output_dir / f"{target_date.isoformat()}_sp500_ma_monitor.json"
    dated_md_path = output_dir / f"{target_date.isoformat()}_sp500_ma_monitor.md"
    latest_json_path = output_dir / "latest_sp500_ma_monitor.json"
    latest_md_path = output_dir / "latest_sp500_ma_monitor.md"

    dated_json_path.write_text(json_text, encoding="utf-8")
    dated_md_path.write_text(markdown, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    latest_md_path.write_text(markdown, encoding="utf-8")
    write_constituent_files(output_dir, target_date, constituents)

    print("Generated:")
    print(dated_md_path)
    print(dated_json_path)


if __name__ == "__main__":
    main()
