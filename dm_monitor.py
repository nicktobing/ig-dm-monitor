"""
Instagram DM Response Monitor
Uses direct HTTP requests with Instagram cookies — no instagrapi.
Checks inbox for replies from PT contacts, alerts Slack, tags GHL.
"""

import json
import os
import re
import sys
import requests
from datetime import datetime
from urllib.parse import unquote
from dotenv import load_dotenv

load_dotenv()

IG_COOKIES_RAW  = os.environ["IG_COOKIES"]
GHL_API_TOKEN   = os.environ["GHL_API_TOKEN"]
SLACK_WEBHOOK   = os.environ["SLACK_WEBHOOK"]
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "KM3KkAQFgG3bByTZmWLL")
SEEN_FILE       = os.path.join(os.path.dirname(__file__), "seen_dm_messages.json")


def build_ig_session():
    cookie_list = json.loads(IG_COOKIES_RAW)
    cookies = {c["name"]: unquote(c["value"]) for c in cookie_list}
    session = requests.Session()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".instagram.com")
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-CSRFToken": cookies.get("csrftoken", ""),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Accept": "*/*",
    })
    return session, cookies.get("ds_user_id", "")


def get_inbox(session):
    try:
        res = session.get(
            "https://www.instagram.com/api/v1/direct_v2/inbox/",
            params={"limit": 20, "thread_message_limit": 10},
            timeout=15,
        )
        data = res.json()
        return data.get("inbox", {}).get("threads", [])
    except Exception as e:
        print("Inbox error:", e)
        return []


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def get_watchlist():
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
    tags = list(contact.get("tags", [])) + ["ig-dm-replied", "dm-replied-date:" + today]
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

    session, my_user_id = build_ig_session()
    threads = get_inbox(session)

    if not threads:
        print("No inbox threads returned - session may be expired or blocked")
        sys.exit(1)

    print("Inbox threads fetched:", len(threads))

    seen = load_seen()
    new_seen = dict(seen)
    alerts_sent = 0

    for thread in threads:
        users = thread.get("users", [])
        for user in users:
            username = (user.get("username") or "").lower()
            if username not in watchlist:
                continue

            contact = watchlist[username]
            contact_name = (
                (contact.get("firstName") or "") + " " + (contact.get("lastName") or "")
            ).strip()

            messages = thread.get("items", [])
            for msg in messages:
                msg_id = str(msg.get("item_id", ""))
                if not msg_id or msg_id in seen:
                    continue
                new_seen[msg_id] = True

                sender_id = str(msg.get("user_id", ""))
                if sender_id == my_user_id:
                    continue

                msg_text = msg.get("text", "") or "[non-text message]"
                print("New reply from @" + username + ":", msg_text[:80])
                notify_slack(username, contact_name, msg_text)
                tag_replied_in_ghl(contact)
                alerts_sent += 1

    save_seen(new_seen)
    print("Done -", alerts_sent, "new replies found")


if __name__ == "__main__":
    main()
