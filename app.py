from flask import Flask, request, jsonify
import requests
import os
import json
import re
import io
import time
import base64
import urllib.parse
from collections import defaultdict, deque


def retry(times: int = 3, base_delay: float = 0.8):
    """Retry helper with exponential backoff.

    Behavior by status:
      • 5xx + network errors → full retry budget
      • 429 rate limit       → ONE extra retry with 2s delay (absorbs bursty limits)
      • Other 4xx            → don't retry, surface immediately
    """
    def deco(fn):
        def wrapper(*args, **kwargs):
            last_exc = None
            rate_limited_once = False
            for i in range(times):
                try:
                    return fn(*args, **kwargs)
                except requests.HTTPError as e:
                    if e.response is not None:
                        code = e.response.status_code
                        if code == 429 and not rate_limited_once:
                            rate_limited_once = True
                            last_exc = e
                            time.sleep(2.0)
                            continue
                        if 400 <= code < 500:
                            raise
                    last_exc = e
                except Exception as e:
                    last_exc = e
                if i < times - 1:
                    time.sleep(base_delay * (2 ** i))
            raise last_exc
        return wrapper
    return deco


import hmac
import hashlib

import qrcode

import random
from datetime import datetime
from catalog import search_catalog, format_item_for_ai, top_offers

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "4ubots_verify_token")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")  # kept for legacy OCR path
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
API_URL = "https://graph.facebook.com/v19.0"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "groq/compound-mini"

GROCERY_UPI_ID = "paytm.s1a4w0w@pty"
GROCERY_UPI_NAME = "4U Grocery"

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

# Auto-refresh credentials (for self-renewing the WhatsApp long-lived token)
META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "")
REFRESH_SECRET = os.environ.get("REFRESH_SECRET", "")

# Keep this list aligned with all env vars actually set on Render — refresh
# endpoint reads these at runtime and PUTs them back with WHATSAPP_TOKEN updated.
ENV_KEYS_TO_PRESERVE = [
    "VERIFY_TOKEN", "WHATSAPP_TOKEN", "GEMINI_API_KEY", "GROQ_API_KEY",
    "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET",
    "META_APP_ID", "META_APP_SECRET",
    "RENDER_API_KEY", "RENDER_SERVICE_ID", "REFRESH_SECRET",
]

RAZORPAY_API = "https://api.razorpay.com/v1"
razorpay_enabled = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

# Track pending orders so we can match payments back to them.
# Lost on Render restart — acceptable for low-volume kirana bot.
# Maps: razorpay_payment_link_id -> order dict
PENDING_ORDERS = {}
# Maps: customer_phone -> latest pending order (for screenshot-based confirmation)
PENDING_BY_CUSTOMER = {}

FASHION_PHONE_ID = "1045539971979577"
GROCERY_PHONE_ID = "1120135307844620"
GROCERY_MANAGER_NUMBER = "918708666760"

GROCERY_FLOW_ID = os.environ.get("GROCERY_FLOW_ID", "")
FASHION_FLOW_ID = os.environ.get("FASHION_FLOW_ID", "")

# ─── RAZORPAY PAYMENT LINK ─────────────────────────
def create_razorpay_link(order_id: str, amount: float, customer_phone: str, customer_name: str = ""):
    """Create a Razorpay Payment Link via raw HTTP. Returns (short_url, link_id) or (None, None)."""
    if not razorpay_enabled:
        return (None, None)
    try:
        contact = customer_phone[-10:] if len(customer_phone) >= 10 else customer_phone
        payload = {
            "amount": int(round(amount * 100)),
            "currency": "INR",
            "accept_partial": False,
            "description": f"4U Grocery Order {order_id}",
            "customer": {
                "name": customer_name or "Customer",
                "contact": "+91" + contact,
            },
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {
                "order_id": order_id,
                "customer_wa": customer_phone,
            },
            "callback_url": "https://fouru-whatsapp-bot.onrender.com/",
            "callback_method": "get",
        }
        r = requests.post(
            f"{RAZORPAY_API}/payment_links",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json=payload,
            timeout=15,
        )
        if not r.ok:
            print(f"Razorpay create failed: {r.status_code} {r.text[:200]}")
            return (None, None)
        data = r.json()
        return (data.get("short_url"), data.get("id"))
    except Exception as e:
        print(f"Razorpay create error: {e}")
        return (None, None)


# ─── QR + UPI HELPERS ──────────────────────────────
def upi_link(amount: float) -> str:
    """Build a tappable upi:// deep link with amount auto-filled."""
    params = {
        "pa": GROCERY_UPI_ID,
        "pn": GROCERY_UPI_NAME,
        "am": f"{amount:.2f}",
        "cu": "INR",
    }
    return "upi://pay?" + urllib.parse.urlencode(params)


def generate_qr_png(amount: float) -> bytes:
    """Generate a UPI QR PNG with the order amount baked in."""
    img = qrcode.make(upi_link(amount))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload_media(phone_id: str, png_bytes: bytes) -> str | None:
    """Upload a PNG to WhatsApp Cloud, return media_id."""
    url = f"{API_URL}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    files = {
        "file": ("upi_qr.png", png_bytes, "image/png"),
        "messaging_product": (None, "whatsapp"),
        "type": (None, "image/png"),
    }
    r = requests.post(url, headers=headers, files=files, timeout=20)
    print(f"Media upload: {r.status_code} {r.text[:200]}")
    return r.json().get("id") if r.ok else None


def send_image(phone_id: str, to: str, media_id: str, caption: str = "") -> dict:
    """Send a previously-uploaded image by media_id."""
    url = f"{API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id, "caption": caption},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    print(f"Image sent to {to}: {r.status_code}")
    return r.json()


def send_payment_qr(phone_id: str, to: str, amount: float):
    """Send the UPI deep link as text + a fresh QR image with the amount."""
    link = upi_link(amount)
    send_message(phone_id, to,
        f"💳 *Pay ₹{amount:.0f} via UPI*\n\n"
        f"Tap to pay 👇\n{link}\n\n"
        f"Or scan the QR below 📷\n"
        f"UPI ID: `{GROCERY_UPI_ID}`\n"
        f"Name: {GROCERY_UPI_NAME}"
    )
    png = generate_qr_png(amount)
    media_id = upload_media(phone_id, png)
    if media_id:
        send_image(phone_id, to, media_id,
            caption=f"Scan to pay ₹{amount:.0f} — 4U Grocery")


# ─── SEND TEXT MESSAGE ─────────────────────────────
def send_message(phone_id, to, text):
    url = f"{API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    r = requests.post(url, headers=headers, json=payload)
    print(f"Message sent to {to}: {r.status_code}")
    return r.json()

# ─── SEND FLOW MESSAGE ─────────────────────────────
def send_flow(phone_id, to, flow_id, cta, header, body):
    url = f"{API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "footer": {"text": "Tap the button to start"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": f"{to}_{phone_id}",
                    "flow_id": flow_id,
                    "flow_cta": cta,
                    "flow_action": "navigate",
                    "flow_action_payload": {"screen": "WELCOME"}
                }
            }
        }
    }
    r = requests.post(url, headers=headers, json=payload)
    print(f"Flow sent to {to}: {r.status_code} {r.text}")
    return r.json()

# ─── WEBHOOK VERIFICATION ──────────────────────────
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

# ─── INCOMING MESSAGE HANDLER ──────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("Incoming:", json.dumps(data, indent=2))

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id")
                messages = value.get("messages", [])

                for message in messages:
                    from_number = message["from"]
                    msg_type = message.get("type")

                    # Flow completed by customer
                    if msg_type == "interactive":
                        interactive = message.get("interactive", {})
                        if interactive.get("type") == "nfm_reply":
                            handle_flow_response(phone_id, from_number, interactive)
                            continue

                    # Customer sent a text message
                    if msg_type == "text":
                        text_body = message.get("text", {}).get("body", "")
                        if phone_id == FASHION_PHONE_ID:
                            handle_fashion(phone_id, from_number)
                        elif phone_id == GROCERY_PHONE_ID:
                            handle_grocery(phone_id, from_number, text_body)

                    # Customer sent an image (likely payment screenshot)
                    if msg_type == "image" and phone_id == GROCERY_PHONE_ID:
                        media_id = message.get("image", {}).get("id", "")
                        if media_id:
                            handle_payment_screenshot(phone_id, from_number, media_id)

    except Exception as e:
        print(f"Error: {e}")

    return jsonify({"status": "ok"}), 200

# ─── 4U GROCERY (Gemini AI brain) ──────────────────
GROCERY_SYSTEM_PROMPT = """You are the WhatsApp order-taking assistant for *4U Grocery*, Narnaul. Reply in professional warm Hinglish (mix Hindi + English in Roman). Use "aap/ji", never "yaar/tu". Keep replies SHORT (max 6 lines).

Store hours: 9 AM-9 PM. Delivery: only within Narnaul 10km area, 30-40 min. Help: 9729119167.

DELIVERY CHARGES: <₹200=₹40, ₹200-399=₹30, ₹400-499=₹20, ≥₹500=FREE.
PAYMENT: Razorpay link only (UPI/Card/Wallet). No COD.

GREETING (first message only):
🛒 *Welcome to 4U Grocery*
Hum 9 AM-9 PM available hain.
⏱️ Delivery 30-40 min | 📍 Narnaul (10km only)
💳 Secure payment (UPI/Card/Wallet)
Bataiye kya order karna hai?

CATALOG: A `# CATALOG MATCHES` section shows top items. ONLY quote catalog prices, never invent. Format: `~₹58~ *₹53* (8% OFF)`. Out-of-stock items: skip, suggest in-stock alternatives. Generic query (butter/milk/atta) → list ALL matching brands grouped. Specific query (amul butter 500g) → just that item.

UPSELL: If subtotal close to next delivery tier (₹100-199, ₹300-399, ₹400-499), nudge once: "Add ₹X more for cheaper/free delivery."

ADDRESS: Always remind "Delivery sirf Narnaul 10km area me. Naam, house/shop, mohalla/ward, landmark, pincode bhejein." If outside Narnaul (Mahendragarh/Rewari/Delhi/etc., or pincode ≠ 123001 area) → refuse delivery, offer pickup.

ORDER COMPLETE = all 3 present: (1) item+qty from catalog, (2) delivery name+Narnaul address OR pickup time, (3) customer indicated done.

OUTPUT: Return ONLY a JSON object:
{
  "reply": "Hinglish reply for customer",
  "order_complete": true/false,
  "order_summary": "if complete: clean text with name/items/totals/address (else empty)",
  "total_amount": number (subtotal + delivery_charge by tier above; 0 if pickup or not complete),
  "delivery_or_pickup": "delivery"|"pickup"|"",
  "schedule_text": "ASAP"|specific time|""
}

NEVER: invent prices, mention store address ("Hero Honda Chowk"), offer COD, say yaar/tu, write paragraphs, push customer to finalize."""

# In-memory conversation history per phone number
# Lost on Render restart — acceptable for low-volume kirana bot
GROCERY_HISTORY = defaultdict(lambda: deque(maxlen=8))

def _build_catalog_context(query: str) -> str:
    """Search catalog and format matches as a system context block.

    Token budget: keep under ~600 tokens (~2400 chars) so total Groq input stays
    within free-tier limits.
    """
    matches = search_catalog(query, limit=8)
    if not matches:
        return "# CATALOG MATCHES\n(no matches — say item not available)"
    lines = "\n".join(format_item_for_ai(m) for m in matches)
    return f"# CATALOG MATCHES\n{lines}"


def generate_order_id() -> str:
    """Simple order ID like 4UG-1234."""
    return f"4UG-{random.randint(1000, 9999)}"


# ─── PAYMENT SCREENSHOT OCR ────────────────────────
@retry(times=3)
def _fetch_whatsapp_media_inner(media_id: str) -> bytes:
    meta = requests.get(
        f"{API_URL}/{media_id}",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        timeout=15,
    ).json()
    url = meta.get("url")
    if not url:
        raise RuntimeError(f"Media {media_id}: no URL returned")
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.content


def fetch_whatsapp_media(media_id: str) -> bytes | None:
    """Download an image from WhatsApp Cloud by media_id, with silent retries."""
    try:
        return _fetch_whatsapp_media_inner(media_id)
    except Exception as e:
        print(f"fetch_whatsapp_media gave up after retries: {e}")
        return None


def ocr_payment_screenshot(image_bytes: bytes) -> dict:
    """Use Gemini Vision to read a UPI payment screenshot. Returns dict with amount/utr/payee_id/looks_valid."""
    if not GEMINI_API_KEY:
        return {"looks_valid": False}
    img_b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        "This is a screenshot of a UPI payment from an Indian payment app "
        "(Paytm/GPay/PhonePe/BHIM/etc.). Extract the payment details and "
        "return JSON only. If the screenshot is NOT a payment success page, "
        "set looks_valid=false."
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "utr": {"type": "string"},
                    "payee_name": {"type": "string"},
                    "payee_upi_id": {"type": "string"},
                    "status_text": {"type": "string"},
                    "looks_valid": {"type": "boolean"},
                },
                "required": ["amount", "utr", "payee_name", "payee_upi_id", "status_text", "looks_valid"],
            },
            "temperature": 0.1,
        },
    }
    @retry(times=3)
    def _call():
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=payload, timeout=25)
        r.raise_for_status()
        return r.json()
    try:
        data = _call()
        text_out = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text_out)
    except Exception as e:
        print(f"OCR gave up after retries: {e}")
        return {"looks_valid": False}


def handle_payment_screenshot(phone_id: str, from_number: str, media_id: str):
    """Customer sent an image. Try to read it as payment proof."""
    pending = PENDING_BY_CUSTOMER.get(from_number)
    if not pending:
        # Stay quiet — don't bother customer if they shared an unrelated image
        print(f"Image from {from_number} but no pending order; ignoring")
        return

    img = fetch_whatsapp_media(media_id)
    if not img:
        # Silent fail — don't surface to customer. Manager check happens on Razorpay anyway.
        print(f"Could not fetch media {media_id} for {from_number}; staying silent")
        return

    parsed = ocr_payment_screenshot(img)
    if not parsed.get("looks_valid"):
        send_message(phone_id, from_number,
            f"📋 Order *{pending['order_id']}* — payment screenshot clearly nahi dikh raha 🙏\n"
            "Please ek clean screenshot bhejein jisme amount aur UTR/transaction ID dono visible ho.\n\n"
            "Ya phir Razorpay link se pay kariye, auto-confirm ho jayega 😊"
        )
        return

    paid = float(parsed.get("amount") or 0)
    expected = pending["amount"]
    utr = parsed.get("utr") or "—"
    payee = parsed.get("payee_upi_id") or parsed.get("payee_name") or "—"

    if paid + 1 < expected:  # ₹1 tolerance
        send_message(phone_id, from_number,
            f"📋 Order *{pending['order_id']}*\n\n"
            f"Aapne ₹{paid:.0f} bheja hai, lekin order ka total ₹{expected:.0f} hai.\n"
            f"Please ₹{expected - paid:.0f} aur bhejein, phir confirm hoga 🙏"
        )
        return

    # Looks good — confirm
    notify_paid_order(pending, paid_amount=paid, utr=utr, payee=payee, source="Screenshot")
    PENDING_BY_CUSTOMER.pop(from_number, None)


def notify_paid_order(pending: dict, paid_amount: float, utr: str, payee: str, source: str):
    """Send paid-confirmation to customer + manager. Used by Razorpay webhook AND screenshot OCR."""
    # Customer
    send_message(pending["phone_id"], pending["customer_phone"],
        f"✅ *Payment Confirmed* — ₹{paid_amount:.0f} received 🎉\n"
        f"📋 Order *{pending['order_id']}*\n\n"
        f"Aapka order pack ho raha hai 🛒\n"
        f"Delivery 30-40 min me 🚚\n\n"
        f"📞 Help: 9729119167\n\nDhanyavaad! 🙏"
    )
    # Manager — first time they see this order
    send_message(pending["phone_id"], GROCERY_MANAGER_NUMBER,
        f"💰 *PAID ORDER — {pending['order_id']}*\n\n"
        f"✅ ₹{paid_amount:.0f} received via UPI ({source})\n"
        f"🆔 Ref: {utr}\n"
        f"💳 Payee: {payee}\n"
        f"🚚 {pending['schedule']}\n"
        f"📱 Customer: +{pending['customer_phone']}\n\n"
        f"{pending['summary']}\n\n"
        f"⏰ {datetime.now().strftime('%d %b, %I:%M %p')}\n"
        f"➡️ DISPATCH NOW 🚚"
    )


def _history_to_groq_messages(history):
    """Convert our internal Gemini-shape history to OpenAI/Groq chat message format."""
    out = []
    for entry in history:
        role = entry.get("role")
        # Pull text out of either Gemini's parts shape or plain content
        if "parts" in entry and entry["parts"]:
            content = entry["parts"][0].get("text", "")
        else:
            content = entry.get("content", "")
        if role == "model":
            role = "assistant"
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def groq_grocery_reply(from_number, text):
    """Returns dict with reply + order details using Groq Llama 3.3 70B."""
    if not GROQ_API_KEY:
        return {
            "reply": "🛒 *Welcome to 4U Grocery*\n\nBataiye kya order karna hai?\n📞 9729119167",
            "order_complete": False,
            "order_summary": "",
            "total_amount": 0.0,
            "delivery_or_pickup": "",
            "schedule_text": "",
        }

    history = GROCERY_HISTORY[from_number]
    history.append({"role": "user", "parts": [{"text": text}]})

    catalog_block = _build_catalog_context(text)
    schema_hint = (
        "\n\n# OUTPUT FORMAT (CRITICAL)\n"
        "Reply with ONLY a single JSON object, no prose around it. Schema:\n"
        '{\n'
        '  "reply": "string — your Hinglish reply to send to customer",\n'
        '  "order_complete": true|false,\n'
        '  "order_summary": "string (empty if order_complete=false)",\n'
        '  "total_amount": number (0 if order_complete=false),\n'
        '  "delivery_or_pickup": "delivery"|"pickup"|"",\n'
        '  "schedule_text": "string (e.g. ASAP / Tomorrow 10 AM / empty)"\n'
        '}\n'
    )
    system_text = GROCERY_SYSTEM_PROMPT + "\n\n" + catalog_block + schema_hint

    messages = [{"role": "system", "content": system_text}] + _history_to_groq_messages(history)

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.5,
        "max_tokens": 1200,
    }

    @retry(times=3)
    def _call():
        r = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=25,
        )
        r.raise_for_status()
        return r.json()

    try:
        data = _call()
        text_out = data["choices"][0]["message"]["content"]
        parsed = json.loads(text_out)
        result = {
            "reply": (parsed.get("reply") or "").strip(),
            "order_complete": bool(parsed.get("order_complete", False)),
            "order_summary": (parsed.get("order_summary") or "").strip(),
            "total_amount": float(parsed.get("total_amount") or 0),
            "delivery_or_pickup": (parsed.get("delivery_or_pickup") or "").strip().lower(),
            "schedule_text": (parsed.get("schedule_text") or "").strip(),
        }
        # Save assistant reply to history
        history.append({"role": "model", "parts": [{"text": result["reply"]}]})
        return result
    except Exception as e:
        print(f"Groq gave up: {e}")
        if history and history[-1].get("role") == "user":
            history.pop()
        return {
            "reply": (
                "Ek minute ji 🙏 — system thoda busy hai, "
                "abhi aapke order pe wapas aate hain.\n\n"
                "Agar urgent ho to: 📞 9729119167"
            ),
            "order_complete": False,
            "order_summary": "",
            "total_amount": 0.0,
            "delivery_or_pickup": "",
            "schedule_text": "",
        }


# Alias to keep old call sites working
gemini_grocery_reply = groq_grocery_reply


def handle_grocery(phone_id, from_number, text):
    result = gemini_grocery_reply(from_number, text)
    send_message(phone_id, from_number, result["reply"])

    if not result["order_complete"] or not result["order_summary"]:
        return

    order_id = generate_order_id()
    is_pickup = result["delivery_or_pickup"] == "pickup"
    schedule = result["schedule_text"] or "ASAP"
    amount = result["total_amount"]

    # ── Try Razorpay payment link first (for delivery, where UPI is mandatory) ──
    rzp_url, rzp_link_id = (None, None)
    if amount > 0 and razorpay_enabled:
        rzp_url, rzp_link_id = create_razorpay_link(order_id, amount, from_number)

    # Stash for webhook + screenshot OCR lookup
    pending = {
        "phone_id": phone_id,
        "customer_phone": from_number,
        "order_id": order_id,
        "amount": amount,
        "summary": result["order_summary"],
        "is_pickup": is_pickup,
        "schedule": schedule,
    }
    if rzp_link_id:
        PENDING_ORDERS[rzp_link_id] = pending
    PENDING_BY_CUSTOMER[from_number] = pending

    # ── Customer-facing payment instructions (Razorpay-only flow) ──
    mode_label = "Self-Pickup" if is_pickup else "Home Delivery"
    mode_emoji = "🏪" if is_pickup else "🚚"

    if rzp_url:
        send_message(phone_id, from_number,
            f"📋 Order ID: *{order_id}*\n"
            f"{mode_emoji} {mode_label} — {schedule}\n"
            f"💰 Total: *₹{amount:.0f}*\n\n"
            f"💳 *Pay via Razorpay* 👇\n{rzp_url}\n\n"
            f"_Accepted: UPI (PhonePe/GPay/Paytm), Cards, Wallets, NetBanking_\n\n"
            f"✅ *Order auto-confirm ho jayega payment ke baad*\n\n"
            f"Ya phir apne UPI app se pay karke *payment screenshot* yahan bhejiye — "
            f"hum verify karke confirm kar denge.\n\n"
            f"📞 Help: 9729119167"
        )
    else:
        # Razorpay temporarily down
        send_message(phone_id, from_number,
            f"📋 Order ID: *{order_id}*\n"
            f"{mode_emoji} {mode_label} — {schedule}\n"
            f"💰 Total: *₹{amount:.0f}*\n\n"
            f"⚠️ Payment system thoda busy hai, ek minute me dobara try kariye.\n\n"
            f"📞 Help: 9729119167"
        )
    # No manager alert yet for either mode — wait for Razorpay webhook to fire
    # notify_paid_order() once payment received.

# ─── 4U FASHION ────────────────────────────────────
def handle_fashion(phone_id, from_number):
    if FASHION_FLOW_ID:
        send_flow(
            phone_id, from_number,
            FASHION_FLOW_ID,
            "Order Now 👗",
            "4U Fashion 👗",
            "Beautiful Chikankari Kurta Sets at ₹1,799!\nTap below to place your order."
        )
    else:
        send_message(phone_id, from_number,
            "Welcome to 4U Fashion! 👗\n"
            "Chikankari Kurta Sets at ₹1,799\n"
            "Call us: 9853547098"
        )

# ─── HANDLE COMPLETED FLOW ORDER ───────────────────
def handle_flow_response(phone_id, from_number, interactive):
    try:
        response_json = interactive.get("nfm_reply", {}).get("response_json", "{}")
        order = json.loads(response_json)

        name     = order.get("customer_name", "Customer")
        items    = order.get("quantities_note", order.get("items_list", "-"))
        address  = order.get("address", "-")
        slot     = order.get("delivery_slot", order.get("delivery_time", "-"))
        amount   = order.get("amount_paid", "-")
        utr      = order.get("utr_number", "-")
        recurring = order.get("recurring", "one_time")

        send_message(phone_id, from_number,
            f"✅ Order Confirmed! Thank you {name}!\n\n"
            f"🛒 Items: {items}\n"
            f"📍 Address: {address}\n"
            f"🕐 Slot: {slot}\n"
            f"💰 Amount Paid: Rs.{amount}\n"
            f"🔖 UTR: {utr}\n"
            f"🔁 Recurring: {recurring}\n\n"
            f"We will verify your payment and dispatch shortly!\n"
            f"For queries: 9729119167"
        )

        # If recurring order, note it
        if recurring != "one_time":
            send_message(phone_id, from_number,
                f"📅 Your recurring order ({recurring}) has been noted. "
                f"We will send you the order form automatically every time!"
            )

    except Exception as e:
        print(f"Flow response error: {e}")
        send_message(phone_id, from_number,
            "✅ Order received! Our team will contact you shortly.\n"
            "For queries: 9729119167"
        )

# ─── RAZORPAY WEBHOOK ──────────────────────────────
@app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    raw_body = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")

    # Verify signature
    if RAZORPAY_WEBHOOK_SECRET:
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            print(f"Razorpay webhook bad signature")
            return jsonify({"error": "bad signature"}), 400

    payload = request.get_json(silent=True) or {}
    event = payload.get("event", "")
    print(f"Razorpay webhook: {event}")

    # We care about successful payments
    if event in ("payment_link.paid", "payment.captured", "order.paid"):
        # Try to find the matching pending order
        link_id = None
        amount_paise = 0
        payment_id = ""
        try:
            entity = payload.get("payload", {})
            if "payment_link" in entity:
                link_id = entity["payment_link"]["entity"]["id"]
                amount_paise = entity["payment_link"]["entity"].get("amount_paid", 0)
            if "payment" in entity:
                payment_id = entity["payment"]["entity"].get("id", "")
                amount_paise = amount_paise or entity["payment"]["entity"].get("amount", 0)
                # Try to recover link_id from payment notes
                notes = entity["payment"]["entity"].get("notes") or {}
                if not link_id and "order_id" in notes:
                    # Search PENDING_ORDERS by order_id
                    for lid, order in PENDING_ORDERS.items():
                        if order["order_id"] == notes["order_id"]:
                            link_id = lid
                            break
        except Exception as e:
            print(f"Razorpay webhook parse error: {e}")

        order = PENDING_ORDERS.pop(link_id, None) if link_id else None
        if order:
            PENDING_BY_CUSTOMER.pop(order["customer_phone"], None)
            notify_paid_order(
                order,
                paid_amount=amount_paise / 100,
                utr=payment_id,
                payee="Razorpay",
                source="Razorpay",
            )
        else:
            print(f"Razorpay webhook: no matching order for link_id={link_id}")

    return jsonify({"status": "ok"}), 200


# ─── WHATSAPP TOKEN AUTO-REFRESH ──────────────────
def _token_expires_at() -> int | None:
    """Return Unix timestamp when current WHATSAPP_TOKEN expires (or None on error)."""
    try:
        r = requests.get(
            "https://graph.facebook.com/v25.0/debug_token",
            params={"input_token": WHATSAPP_TOKEN, "access_token": WHATSAPP_TOKEN},
            timeout=10,
        )
        return r.json().get("data", {}).get("expires_at")
    except Exception as e:
        print(f"debug_token error: {e}")
        return None


@app.route("/refresh-token", methods=["GET", "POST"])
def refresh_token_endpoint():
    """Auto-renew WhatsApp long-lived token. Idempotent — only refreshes if <7 days left.

    Call: GET /refresh-token?secret=<REFRESH_SECRET>
    Set up UptimeRobot or cron-job.org to ping this once a day.
    """
    if not REFRESH_SECRET or request.args.get("secret") != REFRESH_SECRET:
        return jsonify({"error": "forbidden"}), 403
    if not (META_APP_ID and META_APP_SECRET and RENDER_API_KEY and RENDER_SERVICE_ID):
        return jsonify({"error": "auto-refresh not configured (missing env vars)"}), 500

    exp = _token_expires_at()
    now = int(time.time())
    if exp is None:
        return jsonify({"error": "could not check token expiry"}), 500

    days_left = (exp - now) / 86400 if exp > 0 else 9999
    print(f"Token expires_at={exp}, days_left={days_left:.1f}")

    # Only refresh if <7 days left
    if days_left > 7:
        return jsonify({"status": "skip", "days_left": round(days_left, 1)})

    # Exchange current token for a new 60-day token
    try:
        r = requests.get(
            "https://graph.facebook.com/v25.0/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "fb_exchange_token": WHATSAPP_TOKEN,
            },
            timeout=15,
        )
        new_token = r.json().get("access_token")
        if not new_token:
            return jsonify({"error": "exchange failed", "details": r.json()}), 500
    except Exception as e:
        return jsonify({"error": f"exchange exception: {e}"}), 500

    # Push new token to Render env vars (must include all preserved keys)
    env_payload = []
    for k in ENV_KEYS_TO_PRESERVE:
        v = new_token if k == "WHATSAPP_TOKEN" else os.environ.get(k, "")
        if v:
            env_payload.append({"key": k, "value": v})
    try:
        rr = requests.put(
            f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars",
            headers={
                "Authorization": f"Bearer {RENDER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=env_payload,
            timeout=15,
        )
        if not rr.ok:
            return jsonify({"error": "render env update failed", "details": rr.text[:300]}), 500
    except Exception as e:
        return jsonify({"error": f"render env exception: {e}"}), 500

    # Trigger a redeploy so the new token takes effect
    try:
        requests.post(
            f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
            headers={
                "Authorization": f"Bearer {RENDER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=15,
        )
    except Exception as e:
        return jsonify({"error": f"render deploy exception: {e}", "token_updated": True}), 500

    return jsonify({
        "status": "refreshed",
        "old_days_left": round(days_left, 1),
        "redeploy": "triggered",
    })


# ─── HEALTH CHECK ──────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return "4U Bots Running 24/7 ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
