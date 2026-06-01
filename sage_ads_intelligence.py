#!/usr/bin/env python3
"""Sage Ads Intelligence - Google Ads monitoring, alerting, and AI recommendations."""

import os
import sys
import json
import sqlite3
import datetime
import urllib.request
import urllib.error

from google.ads.googleads.client import GoogleAdsClient

from ads_config import CUSTOMER_ID, build_ads_client_config, get_secret

DB_PATH = "/root/data/ads_history.db"
SLACK_CHANNEL = "C0ARR7Q0QMN"
NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_MODEL = "moonshotai/kimi-k2-instruct"


def build_ads_client():
    """Build a GoogleAdsClient from secrets + constants."""
    return GoogleAdsClient.load_from_dict(build_ads_client_config())


def get_campaigns(days):
    """Query Google Ads API for campaign metrics over the last `days` days."""
    client = build_ads_client()
    ga_service = client.get_service("GoogleAdsService")

    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    date_range = f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"

    query = f"""
        SELECT
            campaign.name,
            campaign.status,
            metrics.cost_micros,
            metrics.clicks,
            metrics.impressions,
            metrics.conversions
        FROM campaign
        WHERE {date_range}
    """

    results = {}
    stream = ga_service.search_stream(customer_id=CUSTOMER_ID, query=query)
    for batch in stream:
        for row in batch.results:
            name = row.campaign.name
            status = row.campaign.status.name
            spend = row.metrics.cost_micros / 1_000_000
            clicks = row.metrics.clicks
            impressions = row.metrics.impressions
            conversions = row.metrics.conversions

            if name in results:
                r = results[name]
                r["spend"] += spend
                r["clicks"] += clicks
                r["impressions"] += impressions
                r["conversions"] += conversions
            else:
                results[name] = {
                    "name": name,
                    "status": status,
                    "spend": spend,
                    "clicks": clicks,
                    "impressions": impressions,
                    "conversions": conversions,
                }

    return list(results.values())


def save_snapshot(campaigns):
    """Persist a snapshot of campaign metrics to SQLite."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS snaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            name TEXT,
            status TEXT,
            spend REAL,
            clicks INTEGER,
            impressions INTEGER,
            conversions REAL
        )
        """
    )
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for c in campaigns:
        cur.execute(
            "INSERT INTO snaps (ts, name, status, spend, clicks, impressions, conversions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                c.get("name"),
                c.get("status"),
                float(c.get("spend", 0)),
                int(c.get("clicks", 0)),
                int(c.get("impressions", 0)),
                float(c.get("conversions", 0)),
            ),
        )
    conn.commit()
    conn.close()


def slack_post(msg):
    """Post a message to the configured Slack channel."""
    token = get_secret("SLACK_TOKEN")
    payload = json.dumps({"channel": SLACK_CHANNEL, "text": msg}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"Slack post failed: {e}", file=sys.stderr)
        return {"ok": False, "error": str(e)}


def ai_recommend(campaigns):
    """Ask NIM/Kimi for 3-5 Google Ads recommendations."""
    api_key = get_secret("NIM_API_KEY")

    summary_lines = []
    for c in campaigns:
        cpc = (c["spend"] / c["clicks"]) if c["clicks"] else 0
        summary_lines.append(
            f"- {c['name']} [{c['status']}] spend=${c['spend']:.2f} "
            f"clicks={c['clicks']} impressions={c['impressions']} "
            f"conversions={c['conversions']:.1f} cpc=${cpc:.2f}"
        )
    summary = "\n".join(summary_lines) if summary_lines else "(no campaigns)"

    user_prompt = (
        "You are an expert Google Ads strategist for a trenchless sewer repair "
        "company based in Delaware County, PA. Given the campaign performance "
        "below, provide 3-5 concrete, actionable recommendations to improve "
        "lead quality, reduce wasted spend, and grow qualified calls. Be "
        "specific to trenchless sewer services (CIPP lining, pipe bursting, "
        "emergency sewer repair) and the Delaware County PA market.\n\n"
        f"Campaign performance:\n{summary}"
    )

    body = json.dumps(
        {
            "model": NIM_MODEL,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4,
            "max_tokens": 1024,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        NIM_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, ValueError) as e:
        return f"(AI recommendations unavailable: {e})"


def format_campaigns(campaigns):
    """Render campaigns as a Slack-friendly text block."""
    if not campaigns:
        return "_No campaigns returned._"
    lines = []
    for c in sorted(campaigns, key=lambda x: x["spend"], reverse=True):
        cpc = (c["spend"] / c["clicks"]) if c["clicks"] else 0
        lines.append(
            f"• *{c['name']}* [{c['status']}] — spend ${c['spend']:.2f}, "
            f"clicks {c['clicks']}, impr {c['impressions']}, "
            f"conv {c['conversions']:.1f}, CPC ${cpc:.2f}"
        )
    return "\n".join(lines)


def cmd_daily():
    campaigns = get_campaigns(7)
    save_snapshot(campaigns)

    alerts = []
    for c in campaigns:
        if c["spend"] > 0 and c["clicks"] == 0:
            alerts.append(
                f":warning: *{c['name']}* spent ${c['spend']:.2f} with *0 clicks* (7d)"
            )
        if c["clicks"] > 0:
            cpc = c["spend"] / c["clicks"]
            if cpc > 25:
                alerts.append(
                    f":rotating_light: *{c['name']}* CPC is *${cpc:.2f}* (>$25, 7d)"
                )

    if alerts:
        msg = "*Daily Google Ads Alerts (7d)*\n" + "\n".join(alerts)
    else:
        msg = "*Daily Google Ads Alerts (7d)*\n:white_check_mark: No zero-click or high-CPC issues detected."

    slack_post(msg)


def cmd_weekly():
    campaigns = get_campaigns(30)
    save_snapshot(campaigns)

    breakdown = format_campaigns(campaigns)
    recs = ai_recommend(campaigns)

    msg = (
        "*Weekly Google Ads Report (30d)*\n"
        f"{breakdown}\n\n"
        "*AI Recommendations*\n"
        f"{recs}"
    )
    slack_post(msg)


def cmd_recommend():
    campaigns = get_campaigns(30)
    recs = ai_recommend(campaigns)
    slack_post(f"*Google Ads AI Recommendations*\n{recs}")


def main():
    if len(sys.argv) < 2:
        print("Usage: sage_ads_intelligence.py [daily|weekly|recommend]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "daily":
        cmd_daily()
    elif cmd == "weekly":
        cmd_weekly()
    elif cmd == "recommend":
        cmd_recommend()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
