"""
GitHub Trending Newsletter — main.py
Scrapes github.com/trending, summarizes with Claude, sends via Resend.
Run daily via GitHub Actions cron.
"""

import os
import json
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import anthropic
import resend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
RESEND_API_KEY      = os.environ["RESEND_API_KEY"]
FROM_EMAIL          = os.environ.get("FROM_EMAIL", "trending@yourdomain.com")
FROM_NAME           = os.environ.get("FROM_NAME", "GitHub Trending Daily")
TOP_N               = int(os.environ.get("TOP_N", "8"))


# ── 1. Scrape github.com/trending ─────────────────────────────────────────────
def fetch_trending(n: int = 8) -> list[dict]:
    """Scrape GitHub trending page. GitHub is scraper-friendly (no CAPTCHA on /trending)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GH-Trending-Newsletter/1.0)",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = requests.get("https://github.com/trending?since=daily", headers=headers, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    articles = soup.select("article.Box-row")

    repos = []
    for article in articles[:n]:
        # Repo name + owner
        h2 = article.select_one("h2.h3 a")
        if not h2:
            continue
        path = h2["href"].strip("/")  # "owner/repo"
        parts = path.split("/")
        if len(parts) != 2:
            continue
        owner, name = parts

        # Description
        desc_el = article.select_one("p.col-9")
        description = desc_el.get_text(strip=True) if desc_el else "No description"

        # Language
        lang_el = article.select_one("[itemprop='programmingLanguage']")
        language = lang_el.get_text(strip=True) if lang_el else "Unknown"

        # Stars (total)
        star_els = article.select("a.Link--muted")
        total_stars = star_els[0].get_text(strip=True) if star_els else "0"
        total_stars = total_stars.replace(",", "").replace(" ", "")

        # Stars today
        stars_today_el = article.select_one("span.d-inline-block.float-sm-right")
        stars_today = stars_today_el.get_text(strip=True) if stars_today_el else "?"
        # Clean up: "123 stars today" → "123"
        stars_today = stars_today.replace("stars today", "").replace(",", "").strip()

        repos.append({
            "owner": owner,
            "name":  name,
            "full":  f"{owner}/{name}",
            "url":   f"https://github.com/{owner}/{name}",
            "description": description,
            "language":    language,
            "stars":       total_stars,
            "stars_today": stars_today,
        })

    log.info("Scraped %d trending repos", len(repos))
    return repos


# ── 2. Summarize with Claude ───────────────────────────────────────────────────
def summarize_repos(repos: list[dict]) -> list[dict]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt_lines = "\n".join(
        f"{i+1}. {r['full']}: {r['description']} [Language: {r['language']}]"
        for i, r in enumerate(repos)
    )
    system = (
        "You are curating a daily newsletter for senior software engineers. "
        "For each GitHub repo, write ONE sentence (max 20 words) explaining "
        "why developers should care about it today. Focus on what's novel or useful. "
        "Return ONLY a JSON array of strings, in order, no extra text."
    )
    user = f"Write a one-liner for each of these {len(repos)} trending repos:\n\n{prompt_lines}"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    summaries = json.loads(raw)
    for r, summary in zip(repos, summaries):
        r["summary"] = summary
    log.info("Summaries generated")
    return repos


# ── 3. Build email ─────────────────────────────────────────────────────────────
LANG_COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#2b7489",
    "Go": "#00ADD8", "Rust": "#dea584", "Java": "#b07219", "C++": "#f34b7d",
    "C": "#555555", "Ruby": "#701516", "Swift": "#ffac45", "Kotlin": "#F18E33",
}

def lang_badge(lang: str) -> str:
    color = LANG_COLORS.get(lang, "#888")
    return (
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
        f'background:{color};margin-right:4px;vertical-align:middle"></span>'
        f'<span style="font-size:12px;color:#666">{lang}</span>'
    )

def build_email(repos: list[dict], date_str: str) -> tuple[str, str]:
    subject = f"⭐ GitHub Trending — {date_str}: {repos[0]['name']} and {len(repos)-1} more"

    items_html = ""
    for i, r in enumerate(repos, 1):
        items_html += f"""
        <div style="margin-bottom:24px;padding-bottom:20px;border-bottom:1px solid #f4f4f4">
          <div style="font-size:11px;color:#aaa;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px">
            #{i} &nbsp;·&nbsp; ⭐ {r['stars_today']} stars today
          </div>
          <div style="font-size:17px;font-weight:700;margin-bottom:4px">
            <a href="{r['url']}" style="color:#0366d6;text-decoration:none">{r['full']}</a>
          </div>
          <div style="margin-bottom:6px">{lang_badge(r['language'])}</div>
          <div style="font-size:14px;color:#555;line-height:1.5;margin-bottom:7px">{r.get('summary', r['description'])}</div>
          <a href="{r['url']}" style="font-size:12px;color:#0366d6;font-weight:600;text-decoration:none">
            View on GitHub →
          </a>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:30px 20px;color:#1a1a1a">
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:30px">
    <tr>
      <td>
        <span style="font-size:22px;font-weight:800;color:#24292e">⭐ GitHub Trending</span>
        <div style="font-size:13px;color:#888;margin-top:3px">{date_str} &nbsp;·&nbsp; Top {len(repos)} repos blowing up today</div>
      </td>
    </tr>
  </table>
  {items_html}
  <hr style="border:none;border-top:1px solid #eee;margin:30px 0">
  <p style="font-size:11px;color:#bbb;text-align:center;line-height:1.6">
    You're subscribed to GitHub Trending Daily.<br>
    <a href="{{{{unsubscribe_url}}}}" style="color:#bbb">Unsubscribe</a>
  </p>
</body>
</html>"""
    return subject, html


# ── 4 & 5. Subscribers + Send (same helpers as HN digest) ────────────────────
def get_audience_id() -> str:
    r = requests.get(
        "https://api.resend.com/audiences",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        timeout=10,
    )
    r.raise_for_status()
    audiences = r.json().get("data", [])
    if not audiences:
        raise ValueError("No Resend audiences found.")
    log.info("Using audience: %s", audiences[0].get("name", audiences[0]["id"]))
    return audiences[0]["id"]

def get_subscribers() -> list[str]:
    resend.api_key = RESEND_API_KEY
    contacts = resend.Contacts.list(audience_id=get_audience_id())
    return [c["email"] for c in contacts.get("data", []) if not c.get("unsubscribed", False)]


def send_digest(subject: str, html: str, subscribers: list[str]) -> None:
    resend.api_key = RESEND_API_KEY
    if not subscribers:
        log.warning("No subscribers — sending test to FROM_EMAIL")
        subscribers = [FROM_EMAIL]
    BATCH = 100
    for i in range(0, len(subscribers), BATCH):
        batch = subscribers[i:i + BATCH]
        params = resend.Emails.SendParams(
            from_=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=batch,
            subject=subject,
            html=html,
        )
        result = resend.Emails.send(params)
        log.info("Sent batch %d to %d recipients", i // BATCH + 1, len(batch))


# ── Entrypoint ─────────────────────────────────────────────────────────────────
def main():
    date_str = datetime.now(timezone.utc).strftime("%B %-d, %Y")
    log.info("Starting GitHub Trending Newsletter for %s", date_str)
    try:
        repos = fetch_trending(TOP_N)
        if not repos:
            raise ValueError("No trending repos found — GitHub may have changed their HTML structure")
        repos = summarize_repos(repos)
        subject, html = build_email(repos, date_str)
        subscribers = get_subscribers()
        send_digest(subject, html, subscribers)
        log.info("Done ✓")
    except Exception as e:
        log.exception("Fatal: %s", e)
        raise


if __name__ == "__main__":
    main()
