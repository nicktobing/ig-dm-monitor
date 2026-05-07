# Instagram DM Response Monitor

Monitors Instagram inbox for replies from PT contacts in the Peakspan outreach pipeline. Sends a Slack notification and tags the contact `ig-dm-replied` in GHL when a reply is detected.

## Setup

```bash
pip install -r requirements.txt
cp env.example .env
# Fill in your values in .env
python dm_monitor.py
```

## Environment Variables

| Variable | Description |
|---|---|
| `IG_SESSION_ID` | Instagram session ID from browser cookies |
| `GHL_API_TOKEN` | GHL Private Integration API token |
| `SLACK_WEBHOOK` | Slack incoming webhook URL for #outreach-pt |
| `GHL_LOCATION_ID` | GHL location ID (default: KM3KkAQFgG3bByTZmWLL) |

## Slack Webhook Setup

1. Go to your Slack workspace → Apps → Incoming Webhooks
2. Add to `#outreach-pt` channel
3. Copy the webhook URL into `.env`

## Schedule (run every 4 hours)

Add to crontab (`crontab -e`):

```
0 */4 * * * cd /path/to/ig-dm-monitor && python dm_monitor.py >> monitor.log 2>&1
```

## How it works

1. Fetches GHL contacts tagged `ig-dm-sent` but not `ig-dm-replied`
2. Logs into Instagram using session ID
3. Reads last 50 DM threads
4. For any reply from a watched contact, sends Slack alert and tags `ig-dm-replied` in GHL
5. Tracks seen message IDs in `seen_dm_messages.json` to avoid duplicate alerts
