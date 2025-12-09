# Telegram Bot Setup Guide

This guide walks you through setting up the Telegram bot integration for Ampr.

## Prerequisites

- A Telegram account
- Access to your DigitalOcean deployment URL
- The backend deployed and running on DigitalOcean

## Step 1: Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Start a conversation and send `/newbot`
3. Follow the prompts:
   - Choose a name for your bot (e.g., "Ampr Assistant")
   - Choose a username (must end in "bot", e.g., "ampr_assistant_bot")
4. BotFather will give you a **bot token** - save this, you'll need it

Example token format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

## Step 2: Generate Webhook Secret

Generate a random secret for webhook verification:

```bash
openssl rand -hex 32
```

Save this secret - you'll use it in the next steps.

## Step 3: Configure Environment Variables

Add these environment variables to your DigitalOcean deployment:

```bash
TELEGRAM_BOT_TOKEN=<your_bot_token_from_botfather>
TELEGRAM_WEBHOOK_SECRET=<your_generated_secret>
TELEGRAM_WEBHOOK_PATH=/api/webhooks/telegram  # Optional, this is the default
```

### How to add environment variables in DigitalOcean:

**For App Platform:**
1. Go to your DigitalOcean App Platform dashboard
2. Select your app
3. Go to "Settings" → "App-Level Environment Variables" (or component-level)
4. Click "Edit" and add each variable
5. Click "Save"
6. DigitalOcean will automatically redeploy with the new variables

**For Droplet/VM:**
1. SSH into your droplet
2. Edit your environment file (e.g., `.env` or systemd environment file)
3. Add the variables
4. Restart your application service

## Step 4: Register Webhook with Telegram

After your backend is deployed with the new environment variables, register the webhook:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<YOUR_DIGITALOCEAN_URL>/api/webhooks/telegram",
    "secret_token": "<YOUR_WEBHOOK_SECRET>",
    "allowed_updates": ["message"]
  }'
```

**Replace:**
- `<YOUR_BOT_TOKEN>` with your token from BotFather
- `<YOUR_DIGITALOCEAN_URL>` with your DigitalOcean app URL (e.g., `your-app.ondigitalocean.app` or your custom domain)
- `<YOUR_WEBHOOK_SECRET>` with the secret you generated

**Expected response:**
```json
{
  "ok": true,
  "result": true,
  "description": "Webhook was set"
}
```

## Step 5: Verify Webhook Setup

Check that the webhook is properly configured:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

**Expected response should include:**
```json
{
  "ok": true,
  "result": {
    "url": "https://<YOUR_DIGITALOCEAN_URL>/api/webhooks/telegram",
    "has_custom_certificate": false,
    "pending_update_count": 0,
    "max_connections": 40
  }
}
```

## Step 6: Test the Bot

1. Find your bot on Telegram by searching for the username you chose
2. Start a conversation
3. Send any message
4. The bot should ask you to share your phone number
5. Click the "📱 Share Phone Number" button
6. Once linked, send a message like "Hello!" or "@defianalyst what's the price of bitcoin?"
7. You should receive a response from the bot

## Troubleshooting

### Bot doesn't respond to messages

Check DigitalOcean logs for errors:

**For App Platform:**
```bash
doctl apps logs <app-id> --type RUN
```

Or view logs in the DigitalOcean dashboard under "Runtime Logs"

Look for lines containing "Telegram" to see if webhooks are being received.

### Webhook registration fails

1. Verify your DigitalOcean deployment is running and accessible
2. Check that the URL uses HTTPS (required by Telegram)
3. Ensure environment variables are set correctly in DigitalOcean
4. Try deleting the webhook and setting it again:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook"
   ```

### "Invalid secret token" error

1. Verify `TELEGRAM_WEBHOOK_SECRET` matches in both:
   - DigitalOcean environment variables
   - Webhook registration command
2. Redeploy if you changed the environment variable

### Bot can't link account

1. Verify the user exists in your database with the phone number
2. Check that phone numbers are normalized consistently
3. Look for errors in DigitalOcean logs when sharing contact

## Local Development

For local development without deploying:

1. Use [ngrok](https://ngrok.com/) to expose your local server:
   ```bash
   ngrok http 8000
   ```

2. Set the webhook to your ngrok URL:
   ```bash
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://<YOUR_NGROK_URL>/api/webhooks/telegram",
       "secret_token": "<YOUR_WEBHOOK_SECRET>"
     }'
   ```

3. Run your FastAPI server:
   ```bash
   poetry run uvicorn src.main:fast_api --reload --port 8000
   ```

**Note:** Remember to switch the webhook back to your DigitalOcean URL when done with local testing.

## Webhook Management Commands

### Delete webhook
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook"
```

### Get webhook info
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

### Get bot info
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe"
```

## Security Notes

- Never commit your bot token to git
- Keep your webhook secret secure
- The webhook secret is verified on every incoming request
- Only messages from linked users (with matching phone numbers) are processed
- Telegram only allows webhooks on ports: 443, 80, 88, 8443

## Environment Variables Summary

Add these to your DigitalOcean App Platform environment:

```bash
# Required
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_WEBHOOK_SECRET=<your_32_char_hex_secret>

# Optional
TELEGRAM_WEBHOOK_PATH=/api/webhooks/telegram
```
