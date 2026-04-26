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
    """Tiny retry helper with exponential backoff. Returns last exception's value via fn re-raise."""
    def deco(fn):
        def wrapper(*args, **kwargs):
            last_exc = None
            for i in range(times):
                try:
                    return fn(*args, **kwargs)
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
API_URL = "https://graph.facebook.com/v19.0"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

GROCERY_UPI_ID = "paytm.s1a4w0w@pty"
GROCERY_UPI_NAME = "4U Grocery"

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

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
GROCERY_SYSTEM_PROMPT = """You are the WhatsApp order-taking assistant for *4U Grocery*, a kirana shop in Narnaul, Haryana. Your tone is professional, polite, and Hinglish (Hindi + English in Roman script) — like a real shop owner serving customers, not a casual friend.

# Business rules
- Store hours: 8 AM to 10 PM
- Delivery area: ONLY within Narnaul
- Delivery time: 30-40 minutes
- Help line: 9729119167

## Delivery charges (TIERED)
- Subtotal under ₹200 → ₹40 delivery
- Subtotal ₹200 to ₹399 → ₹30 delivery
- Subtotal ₹400 to ₹499 → ₹20 delivery
- Subtotal ₹500 or above → FREE delivery 🎉

## Payment options
- *Home Delivery*: **UPI ONLY** (no COD). Customer MUST pay first via UPI link/QR you send. Order is NOT confirmed to manager until payment received. Customer can either tap the Razorpay link (auto-confirm) or pay via UPI app and send the payment screenshot to verify.
- *Self Pickup*: **UPI or Cash** at counter. Manager is notified immediately.

# Greeting (use exactly this format on first message)
🛒 *Welcome to 4U Grocery*

Aapki seva me hum 8 AM se 10 PM tak available hain.

⏱️ *Quick delivery* — 30-40 min in Narnaul
💳 UPI / COD accepted

Bataiye, kya order karna hai?

# How to use the CATALOG
You will see a `# CATALOG MATCHES` section with items matching the customer's query. Each line shows: NAME | MRP | 4U price | discount % | stock status.

RULES:
- Quote ONLY prices from the catalog. NEVER invent a price.
- Format prices as: `~₹58~ *₹53* (8% OFF)` — strikethrough MRP, bold 4U price, savings %.

## When customer asks GENERIC product (e.g. "butter", "milk", "bread", "atta")
The catalog will return MANY matches. You MUST list ALL in-stock variants, neatly grouped by brand. Example response for "butter":

> *Butter available* 🧈
>
> *Amul Butter*
> • 100g — ~₹58~ *₹53* (8% OFF)
> • 200g — ~₹118~ *₹109* (8% OFF)
> • 500g — ~₹285~ *₹262* (8% OFF)
>
> *Britannia Butter*
> • 100g — ~₹54~ *₹50* (7% OFF)
> • 500g — ~₹275~ *₹258* (6% OFF)
>
> *Mother Dairy Butter*
> • 200g — ~₹120~ *₹110* (8% OFF)
>
> Kaunsa brand aur kitne packets chahiye?

## When customer asks SPECIFIC product (e.g. "amul butter 500g")
Quote that exact item only with sizes/variants. Don't dump 30 items.

## When item is OUT OF STOCK
Don't show it. Show in-stock alternatives from catalog matches.

## When customer asks brand we DON'T carry (e.g. "Britannia 50% Maska")
"Sorry ye specific item nahi hai. Aapke liye similar options:" — then list 2-3 closest in-stock items from catalog.

## When NO catalog match for the query
"Ye item abhi available nahi hai. Help: 9729119167"

# How to use TOP OFFERS
You will see a `# TOP OFFERS TODAY` section with our 3 best in-stock deals (highest discount %).
- Mid-conversation, after the customer adds their first item, mention 1-2 of these as "Aaj ke top deals" — once per conversation, never repeat. This drives upsell.
- DON'T push offers if customer is in a hurry / clearly wants to finalize.

# Strategic upsell (CRITICAL)
After every cart update, calculate subtotal. Check if customer is close to next delivery tier:
- Subtotal ₹100-199 → "Add ₹X more → ₹30 delivery (save ₹10)"
- Subtotal ₹300-399 → "Add ₹X more → ₹20 delivery (save ₹10)"
- Subtotal ₹400-499 → "Add ₹X more → FREE delivery (save ₹20)" + suggest 1-2 specific items from catalog matching that price range
- Subtotal ≥ ₹500 → celebrate "FREE delivery unlocked! 🎉"

Be subtle and helpful, not pushy. One-line nudge max.

# Conversation flow
1. Greeting → warm welcome
2. Customer asks item → quote from catalog with MRP/4U/% off
3. Customer adds to cart → confirm + show running cart + delivery tier nudge if close
4. Customer says "bas" / "ho gaya" / "done" / "thik hai" → ask Delivery vs Pickup
5. Choice made → ask: ASAP or scheduled (for delivery: schedule = "kal X time" or specific time today)
6. Get name + address (delivery) OR confirm pickup time (pickup)
7. Set order_complete=true with full details

DON'T proactively push customer to "finalize". Let them say when they're done.

# Order completion (CRITICAL)
Set `order_complete: true` ONLY when ALL these are present:
1. At least one item with quantity from catalog
2. Delivery: name + Narnaul address  |  Pickup: pickup time confirmed
3. Customer indicated they're done adding items

When order_complete=true, return:
- `total_amount` = items subtotal + delivery_charge (per tier above; 0 for pickup)
- `delivery_or_pickup` = "delivery" or "pickup"
- `schedule_text` = "ASAP" or specific time like "Tomorrow 10 AM"
- `order_summary` = clean text for manager: items with line totals, subtotal, delivery charge, GRAND TOTAL, customer name + phone + address (or pickup time)

When order_complete=false: total_amount=0, order_summary="", delivery_or_pickup="", schedule_text="".

# Edge cases
- Outside Narnaul address → "Sorry, abhi sirf Narnaul me deliver karte hain. Pickup option available hai if you can come to store."
- Item not in catalog → "Ye item abhi available nahi hai. Help: 9729119167"
- Asks for credit/udhaar → "Sorry udhaar nahi karte. UPI ya cash payment hi accept karte hain."
- Random chit-chat → polite redirect: "Aapko kya order karna hai? 😊"
- Wrong amount paid → "Amount ₹X expected tha. Please ₹Y more bhejiye to complete order."

# What NEVER to do
- NEVER invent prices — only catalog prices
- NEVER mention store address ("Near Hero Honda Chowk") in any message — just say "Narnaul"
- NEVER say "track ya cancel" — instead show "📞 Help: 9729119167"
- NEVER offer COD for home delivery — UPI only for delivery
- NEVER say "yaar/tu/dost" — professional, use "aap/ji"
- NEVER write long paragraphs — concise, max 6-7 lines
- NEVER ask "ya order finalize karein?" — let customer decide when they're done
- NEVER promise delivery outside Narnaul
- NEVER push offers more than once per conversation"""

# In-memory conversation history per phone number
# Lost on Render restart — acceptable for low-volume kirana bot
GROCERY_HISTORY = defaultdict(lambda: deque(maxlen=12))

def _build_catalog_context(query: str) -> str:
    """Search catalog and format matches as a system context block."""
    matches = search_catalog(query, limit=20)
    if not matches:
        catalog_block = "# CATALOG MATCHES\n(no matches in catalog for this query — ask customer to clarify the item, or say item not available)"
    else:
        lines = "\n".join(format_item_for_ai(m) for m in matches)
        catalog_block = f"# CATALOG MATCHES\n{lines}"

    offers = top_offers(limit=3)
    if offers:
        offer_lines = "\n".join(format_item_for_ai(o) for o in offers)
        offers_block = f"\n\n# TOP OFFERS TODAY\n{offer_lines}"
    else:
        offers_block = ""

    return catalog_block + offers_block


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


def gemini_grocery_reply(from_number, text):
    """Returns dict with reply + order details."""
    if not GEMINI_API_KEY:
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
    system_text = GROCERY_SYSTEM_PROMPT + "\n\n" + catalog_block

    payload = {
        "contents": list(history),
        "systemInstruction": {"parts": [{"text": system_text}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "reply": {"type": "string"},
                    "order_complete": {"type": "boolean"},
                    "order_summary": {"type": "string"},
                    "total_amount": {"type": "number"},
                    "delivery_or_pickup": {"type": "string"},
                    "schedule_text": {"type": "string"},
                },
                "required": ["reply", "order_complete", "order_summary", "total_amount", "delivery_or_pickup", "schedule_text"],
            },
            "temperature": 0.5,
            "maxOutputTokens": 1200,
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
        parsed = json.loads(text_out)
        result = {
            "reply": parsed.get("reply", "").strip(),
            "order_complete": bool(parsed.get("order_complete", False)),
            "order_summary": (parsed.get("order_summary") or "").strip(),
            "total_amount": float(parsed.get("total_amount") or 0),
            "delivery_or_pickup": (parsed.get("delivery_or_pickup") or "").strip().lower(),
            "schedule_text": (parsed.get("schedule_text") or "").strip(),
        }
        history.append({"role": "model", "parts": [{"text": result["reply"]}]})
        return result
    except Exception as e:
        print(f"Gemini gave up after retries: {e}")
        # Soft, non-technical fallback
        return {
            "reply": "Namaste! 🙏 Bataiye kya order karna hai aaj? Sugar, atta, dal, oil, dairy — sab available hai 😊\n📞 9729119167",
            "order_complete": False,
            "order_summary": "",
            "total_amount": 0.0,
            "delivery_or_pickup": "",
            "schedule_text": "",
        }


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

    # ── Customer-facing payment instructions ──
    if is_pickup:
        send_message(phone_id, from_number,
            f"📋 Order ID: *{order_id}*\n"
            f"🏪 Self-Pickup — {schedule}\n"
            f"💳 Payment: UPI ya Cash, store par dono accept hain\n\n"
            f"📞 Help: 9729119167"
        )
        # Optional pre-pay link for pickup
        if rzp_url:
            send_message(phone_id, from_number,
                f"💳 Online pay karna hai? (optional)\n"
                f"Tap 👉 {rzp_url}\n"
                f"Amount: ₹{amount:.0f}"
            )
        elif amount > 0:
            send_payment_qr(phone_id, from_number, amount)
    else:
        # Home delivery → UPI mandatory; either Razorpay link OR pay & send screenshot
        if rzp_url:
            send_message(phone_id, from_number,
                f"📋 Order ID: *{order_id}*\n"
                f"🚚 Home Delivery — {schedule}\n"
                f"💰 Total: *₹{amount:.0f}*\n\n"
                f"💳 *Payment options* (choose one):\n\n"
                f"*1)* Tap Razorpay link 👉 {rzp_url}\n   (auto-confirm, easiest)\n\n"
                f"*2)* Pay UPI from QR below + send payment *screenshot* in this chat\n\n"
                f"Order tab confirm hoga jab payment received 🟢\n"
                f"📞 Help: 9729119167"
            )
            if amount > 0:
                send_payment_qr(phone_id, from_number, amount)
        else:
            send_message(phone_id, from_number,
                f"📋 Order ID: *{order_id}*\n"
                f"🚚 Home Delivery — {schedule}\n"
                f"💰 Total: *₹{amount:.0f}*\n\n"
                f"💳 Pay UPI from QR below + send payment *screenshot* in this chat to confirm\n\n"
                f"📞 Help: 9729119167"
            )
            if amount > 0:
                send_payment_qr(phone_id, from_number, amount)

    # ── PICKUP exception: alert manager immediately (no online payment required) ──
    if is_pickup:
        send_message(phone_id, GROCERY_MANAGER_NUMBER,
            f"🛒 *NEW PICKUP ORDER — {order_id}*\n\n"
            f"💰 Total: ₹{amount:.0f} — Cash or UPI at counter\n"
            f"🏪 PICKUP — {schedule}\n"
            f"📱 Customer: +{from_number}\n\n"
            f"{result['order_summary']}\n\n"
            f"⏰ {datetime.now().strftime('%d %b, %I:%M %p')}\n"
            f"➡️ Pack for pickup"
        )
    # For DELIVERY: NO manager alert yet. Wait for payment confirm via Razorpay webhook
    # OR customer payment screenshot. Then notify_paid_order() fires the alert.

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


# ─── HEALTH CHECK ──────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return "4U Bots Running 24/7 ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
