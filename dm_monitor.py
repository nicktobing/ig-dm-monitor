"""
Instagram DM Response Monitor
Checks Instagram inbox for replies from PT contacts who were DM'd via Phase 2F.
Sends Slack alert and tags contact ig-dm-replied in GHL.

Setup:
    pip install -r requirements.txt
    cp .env.example .env   # fill in your values
    python dm_monitor.py

Schedule every 4 hours via cron:
    0 */4 * * * cd /path/to/ig-dm-monitor && python dm_monitor.py >> monitor.log 2>&1
"""

import json
import os
import re
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv
from instagrapi import Client

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
IG_SESSION_ID   = os.environ["IG_SESSION_ID"]
GHL_API_TOKEN   = os.environ["GHL_API_TOKEN"]
SLACK_WEBHOOK   = os.environ["SLACK_WEBHOOK"]
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "KM3KkAQFgG3bByTZmWLL")
SEEN_FILE       = os.path.join(os.path.dirname(__file__), "seen_dm_messages.json")
# ─────────────────────────────────────────────────────────────────────────────


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def get_watchlist():
    """Return {instagram_username: ghl_contact} for contacts with ig-dm-sent but not ig-dm-replied."""
    headers = {
        "Authorization": "Bearer " + GHL_API_TOKEN,
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }
    try:
        res = requests.post(
            "https://services.leadconnectorhq.com/contacts/search",
            headers=headers,
            json={
                "locationId": GHL_LOCATION_ID,
                "pageLimit": 100,
                "filters": [{"field": "tags", "operator": "contains", "value": "ig-dm-sent"}],
            },
            timeout=15,
        )
        contacts = res.json().get("contacts", [])
    except Exception as e:
        print("GHL error:", e)
        return {}

    watchlist = {}
    for c in contacts:
        tags = c.get("tags", [])
        if "ig-dm-replied" in tags:
            continue
        website = c.get("website", "")
        match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)", website)
        if match:
            watchlist[match.group(1).lower()] = c
    return watchlist


def tag_replied_in_ghl(contact):
    today = datetime.now().strftime("%Y-%m-%d")
    tags = list(contact.get("tags", []))
    tags.append("ig-dm-replied")
    tags.append("dm-replied-date:" + today)
    headers = {
        "Authorization": "Bearer " + GHL_API_TOKEN,
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }
    try:
        requests.put(
            "https://services.leadconnectorhq.com/contacts/" + contact["id"],
            headers=headers,
            json={"tags": tags},
            timeout=15,
        )
    except Exception as e:
        print("GHL tag error:", e)


def notify_slack(username, contact_name, message_text):
    name_str = (" (" + contact_name + ")") if contact_name.strip() else ""
    text = (
        "*IG DM Reply - Peakspan PT Outreach*\n"
        "@" + username + name_str + " replied to your DM:\n"
        '"' + message_text[:300] + '"\n\n'
        "Contact tagged `ig-dm-replied` in GHL."
    )
    try:
        requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
    except Exception as e:
        print("Slack error:", e)


def main():
    print(datetime.now().isoformat(), "- Starting DM monitor")

    watchlist = get_watchlist()
    if not watchlist:
        print("No contacts to watch")
        return

    print("Watching", len(watchlist), "contacts:", ", ".join(watchlist.keys()))

    cl = Client()
    try:
        cl.login_by_sessionid(IG_SESSION_ID)
        print("Instagram login OK, user_id:", cl.user_id)
    except Exception as e:
        print("Instagram login failed:", e)
        sys.exit(1)

    seen = load_seen()
    new_seen = dict(seen)
    alerts_sent = 0

    try:
        threads = cl.direct_threads(amount=50)
    except Exception as e:
        print("Failed to fetch inbox:", e)
        sys.exit(1)

    for thread in threads:
        for user in thread.users:
            username = user.username.lower()
            if username not in watchlist:
                continue

            contact = watchlist[username]
            contact_name = (
                (contact.get("firstName") or "") + " " + (contact.get("lastName") or "")
            ).strip()

            try:
                messages = cl.direct_messages(thread.id, amount=20)
            except Exception:
                messages = thread.messages or []

            for msg in messages:
                msg_id = str(msg.id)
                if msg_id in seen:
                    continue
                new_seen[msg_id] = True

                if str(msg.user_id) == str(cl.user_id):
                    continue

                msg_text = getattr(msg, "text", None) or "[non-text message]"
                print("New reply from @" + username + ":", msg_text[:80])

                notify_slack(username, contact_name, msg_text)
                tag_replied_in_ghl(contact)
                alerts_sent += 1

    save_seen(new_seen)
    print("Done -", alerts_sent, "new replies found")


if __name__ == "__main__":
    main()
