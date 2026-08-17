# WhatsApp AI Suggestion Setup Guide

Connect QuantOS AI BOAT to the **official Meta WhatsApp Business Platform Cloud
API** so AI suggestions (70-89% confidence) are pushed to your phone and can be
approved with a single reply ("1") or rejected ("2").

> Why the official Cloud API? Third-party "WhatsApp web" libraries
> (e.g. `whatsapp-web.js`) automate the consumer WhatsApp app and routinely
> result in account bans. The Cloud API is Meta's supported, production-safe
> path and is what this integration uses.

---

## 1. Create a Meta Developer App

1. Go to <https://developers.facebook.com/apps> and click **Create App**.
2. Select **Business** as the app type, name it (e.g. `QuantOS AI Alerts`), and
   create the app.
3. From the app dashboard, click **Add Product** and select
   **WhatsApp** to enable the WhatsApp Business Platform.

## 2. Get a Test Number

Inside the WhatsApp product configuration:

1. Open **API Setup**.
2. Choose a phone number in **Recipient phone number** — this is the number you
   will receive alerts on (the "admin number").
3. WhatsApp lets you use the **temporary phone number** assigned to your app for
   sending test messages while your own number is being verified.
4. Copy the **Temporary access token** shown in **API Setup**. This is
   `WHATSAPP_TOKEN`. For production you will later swap in a permanent token
   (see [Permanent token](#6-optional-permanent-token-and-production-phone-number)).
5. Copy the **Phone number ID** shown in the same page
   (`WHATSAPP_PHONE_NUMBER_ID`).

## 3. Add the Admin Number to Allowed Recipients

1. In **API Setup** -> **To** field, add your personal WhatsApp number
   (the admin number) as an allowed recipient.
2. That number must first message your test number once
   (click **Test phone number** -> **Send message**) to establish a session,
   otherwise outbound messages to it are rejected by Meta.
3. Only numbers added to the **allowed recipients** list can be messaged by the
   test number. This is the `WHATSAPP_ADMIN_NUMBER`.

## 4. Configure the Webhook (for "1" / "2" replies)

1. In **WhatsApp** -> **Configuration**, click **Edit** next to *Webhook*.
2. **Callback URL**: point it at the running backend's webhook endpoint:

   ```
   https://<your-host>/api/v1/integrations/whatsapp/webhook
   ```

   In local development the callback URL can be exposed via a public tunnel
   (e.g. the platform preview link) that proxies to the backend.
3. **Verify token**: set it to the same value you configure as
   `WHATSAPP_WEBHOOK_SECRET`. The backend returns the `hub.challenge` when the
   token matches.
4. Click **Verify and save**, then **Subscribe** to the **messages** field so
   incoming messages are forwarded.

## 5. Configure the Backend

Set these environment variables (or save them via the Connections Manager API —
see [Connection management](#connection-management)):

```bash
# Required for sending alerts
export WHATSAPP_TOKEN="EAAG...temporary-or-permanent-token"

# The Phone number ID shown in API Setup (the app's business number)
export WHATSAPP_PHONE_NUMBER_ID="101234567890123"

# Your personal number that receives the alerts (E.164 format, with country code)
export WHATSAPP_ADMIN_NUMBER="+15551234567"

# Used both as the webhook verify token and to verify X-Hub-Signature-256
export WHATSAPP_WEBHOOK_SECRET="a-long-random-secret-string"
```

Restart the backend after setting the variables:

```bash
# Start the backend
cd backend-py
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 6. (Optional) Permanent Token and Production Phone Number

For production:

1. Add your business phone number via **Phone numbers** in the WhatsApp product
   and complete its verification (business verification may be required).
2. In **App settings** -> **App roles** -> **WhatsApp**, add a system user
   with **whatsapp_business_messaging** and **whatsapp_business_management**
   permissions.
3. Generate a **permanent** access token for that system user and use it as
   `WHATSAPP_TOKEN`.

---

## How the integration works

1. The AI pipeline evaluates every decision. When confidence lands in the
   **70-89%** band, `AutoTradeController` records a *suggested trade* and emits
   a `suggested:trade-created` event.
2. The WhatsApp listener (subscribed to that event) sends an alert to
   `WHATSAPP_ADMIN_NUMBER`:

   ```
   AI Suggests: BUY XAUUSD. Conf: 85%. Reply '1' to Execute, '2' to Reject.
   ```

3. You reply with a single digit:
   - **1** -> the suggestion is marked **accepted** via
     `auto_trade_controller.approve_suggested(...)`.
   - **2** -> the suggestion is marked **rejected** via
     `auto_trade_controller.reject_suggested(...)`.

4. The webhook replies to confirm the outcome
   (`XAUUSD BUY (approved)` / `XAUUSD BUY (rejected)`).

> Approval never bypasses the risk engine: even an approved suggestion must
> still pass the same pre-trade risk gates at execution time.

---

## Connection management

Credentials can be managed at runtime through the Connections Manager instead
of `.env` files. Tokens are Fernet-encrypted before they are stored.

### List connection statuses

```bash
curl -s http://localhost:8000/api/v1/integrations/connections
```

Response:

```json
{
  "connections": [
    {
      "provider": "whatsapp",
      "name": "WhatsApp",
      "type": "notification",
      "isActive": true,
      "configured": true,
      "updatedAt": 1710000000000
    }
  ]
}
```

### Save a WhatsApp connection

```bash
curl -s -X POST http://localhost:8000/api/v1/integrations/connections \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "whatsapp",
    "api_token": "EAAG...",
    "phone_number_id": "101234567890123",
    "admin_number": "+15551234567",
    "webhook_secret": "a-long-random-secret-string",
    "is_active": true
  }'
```

Once saved, the connection is applied to the live client immediately (and
re-loaded from the store on restart). The same endpoint accepts
`provider=telegram` with `api_token` + `chat_id`, and `provider=mt5`.

### Send a test message

```bash
curl -s -X POST http://localhost:8000/api/v1/integrations/connections/test \
  -H "Content-Type: application/json" -d '{"provider": "whatsapp"}'
```

The admin number receives *"QuantOS AI WhatsApp test: connection OK."*

---

## Security notes

- The webhook rejects any request without a valid `X-Hub-Signature-256`
  header (constant-time HMAC-SHA256 of the raw body using
  `WHATSAPP_WEBHOOK_SECRET`).
- Access tokens and webhook secrets are Fernet-encrypted at rest and returned
  masked (`***`) by the Connections Manager API.
- Incoming numbers are not automatically trusted: only the "1"/"2" reply flow is
  supported, and approvals still pass through the risk engine.

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| No alerts received | Ensure the admin number messaged your test number once, and that it is in the allowed recipient list. |
| `whatsapp-api-rejected` with error 131047 | The recipient is not allowed; add it as an allowed recipient. |
| Webhook verification fails | The `verify_token` must equal `WHATSAPP_WEBHOOK_SECRET` and the callback URL must be reachable over HTTPS. |
| `401` on webhook POST | Check `WHATSAPP_WEBHOOK_SECRET` matches the app secret / verify token configured on Meta. |
| Test message not delivered | Confirm `WHATSAPP_ADMIN_NUMBER` uses E.164 format (e.g. `+15551234567`). |
