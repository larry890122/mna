# Bloomberg US Market Wrap Automation

This folder generates a daily US market wrap from Bloomberg Desktop API data on the same machine where Bloomberg Terminal is logged in.

## Files

- `generate_us_market_wrap.ps1`: Pulls Bloomberg data and writes a Chinese market-wrap summary.
- `market_wrap_config.json`: Editable watchlists for indices, macro assets, sectors, and megacaps.
- `register_daily_task.ps1`: Registers a Windows scheduled task for daily runs.

## Run Once

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\generate_us_market_wrap.ps1
```

Outputs are written to `.\output` as both Markdown and JSON.

## Set a Daily Schedule

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\register_daily_task.ps1 -Time 08:00
```

`08:00` is local machine time. A morning Taiwan schedule usually works well because the prior US cash session has already closed.

## Important Notes

- Bloomberg Terminal must be logged in on this machine when the task runs.
- This automation recreates the market wrap from Bloomberg data instead of scraping the Terminal news page.
- If you want to change the basket of sectors or megacaps, edit `market_wrap_config.json`.

## Terminal News Harvest

Use `harvest_bloomberg_terminal_news.ps1` when you want visible Bloomberg Terminal news headlines or article text from the current screen instead of API sentiment fields.

Dry run against a screenshot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\harvest_bloomberg_terminal_news.ps1 -ImagePath C:\path\to\screenshot.png
```

Live harvest from the current foreground Bloomberg window:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\harvest_bloomberg_terminal_news.ps1 -ArticleCount 3 -KeepScreenshots
```

Before the live run, open Bloomberg Terminal to the desired news list and keep it in the foreground.

## Reuters Headline Brief

Use `generate_reuters_market_brief.py` to build a Reuters-oriented morning brief from Google News RSS results filtered to Reuters headlines.

```powershell
python .\generate_reuters_market_brief.py
```

Outputs are written to `.\output\reuters_news`.

Notes:

- This path is more reliable than scraping Reuters directly in this environment because Reuters blocks direct automated requests here.
- The brief currently includes Reuters headlines, timestamps, and Google News links.
- Reuters full article bodies are not directly harvested in this version.

## S&P 500 M&A Monitor

Use `generate_sp500_ma_monitor.py` to:

- refresh the live S&P 500 constituent list from Wikipedia,
- scan Google News RSS for prior-day M&A headlines from Yahoo Finance, Seeking Alpha, WSJ, and Financial Times,
- and attach the same-day stock move for each matched S&P 500 company using Yahoo Finance price history.

Run once:

```powershell
python .\generate_sp500_ma_monitor.py --target-date 2026-06-23
```

If `--target-date` is omitted, the script defaults to the previous U.S. Eastern calendar day.

Outputs are written to `.\output` as dated and `latest_*.{md,json}` files.

## S&P 500 M&A Monitor

Use `generate_sp500_ma_monitor.py` to:

- refresh the S&P 500 constituent list from Wikipedia,
- scan Yahoo Finance, Seeking Alpha, WSJ, and Financial Times M&A headlines via Google News RSS,
- and attach same-day Yahoo Finance price performance for matched S&P 500 companies.

Run:

```powershell
python .\generate_sp500_ma_monitor.py --target-date 2026-06-23
```

Outputs are written to `.\output` as both Markdown and JSON.

## GitHub Daily Email

This repo now includes:

- `generate_sp500_ma_monitor.py` to build the daily monitor
- `send_sp500_ma_monitor_email.py` to turn the latest JSON into an email and send it through Gmail SMTP
- `.github/workflows/sp500-ma-monitor.yml` to run the job automatically on GitHub Actions

### Local preview

```powershell
python .\generate_sp500_ma_monitor.py --target-date 2026-06-23
python .\send_sp500_ma_monitor_email.py --print-only
```

### Push to GitHub

1. Create a new GitHub repository.
2. Push this folder to that repository.
3. Make sure the workflow file exists on the default branch, because scheduled GitHub Actions only run from the default branch.

### Add GitHub Actions secrets

In GitHub: `Settings` -> `Secrets and variables` -> `Actions`, add:

- `EMAIL_TO`: `larry890122@gmail.com`
- `GMAIL_SENDER`: the Gmail address that will send the email
- `GMAIL_APP_PASSWORD`: a Gmail app password for the sender account

### Gmail setup

For the sender Gmail account:

1. Turn on Google 2-Step Verification.
2. Create an App Password for Mail.
3. Put that 16-character app password into `GMAIL_APP_PASSWORD` on GitHub.

### Schedule

The workflow is set to run every day at `08:00` Taiwan time via GitHub Actions.

```yaml
schedule:
  - cron: "0 8 * * *"
    timezone: "Asia/Taipei"
```

GitHub notes that scheduled workflows can still run a few minutes late during heavy load, so `08:00` means the target schedule, not a strict guaranteed delivery second.
