#!/usr/bin/env python3
"""
Trading Card Pre-Grader Web App
Flask web application with auth, email verification, and PSA-style grading.
"""

import base64
import datetime
import json
import os
import sqlite3
from pathlib import Path

import stripe
from flask import Flask, render_template, request, Response, stream_with_context, session
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from portkey_ai import Portkey
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

# --- Email config (set these env vars or edit directly) ---
app.config["MAIL_SERVER"]   = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"]     = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"]  = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_USERNAME", "noreply@cardgrade.ai")

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)


# --- Stripe config ---
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")        # e.g. price_xxx from Stripe dashboard
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MEDIA_TYPE_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

PRO_LIFETIME_EMAILS = {
    "alexluongpokemonmaster@gmail.com",
}

PSA_GRADING_SYSTEM = """You are an expert trading card grader with decades of experience grading cards
for PSA (Professional Sports Authenticator) and Beckett (BGS). You evaluate cards with precision
and consistency, using an enhanced grading scale that includes half-point grades and a Pristine tier.

GRADING SCALE:
- Pristine 10: Absolutely flawless. Perfect centering (50/50), razor-sharp corners, flawless edges,
  zero surface defects, full original gloss. Exceptionally rare.
- 10 (Gem Mint): Perfect card. Four sharp corners, no stains, no print defects.
  Virtually perfect centering (55/45 or better). Gloss and original sheen intact.
- 9.5: Between Mint and Gem Mint. Essentially perfect but with one very minor flaw
  not quite meeting PSA 10 standards.
- 9 (Mint): Only one minor flaw allowed. Near-perfect corners, edges, surface.
  Centering 60/40 or better. Very minor printing imperfections allowed.
- 8.5: Between NM-MT and Mint. Strong card with very minor issues on two criteria.
- 8 (NM-MT Near Mint-Mint): Minor imperfections visible only on close inspection.
  75/25 or better centering. Slight surface wear acceptable.
- 7.5: Between NM and NM-MT.
- 7 (NM Near Mint): Minor faults. No major defects. 75/25 centering or better.
  Light surface wear visible. Corners show minor wear.
- 6.5: Between EX-MT and NM.
- 6 (EX-MT Excellent-Mint): Slight surface wear on major surfaces. Slight notching
  on corners. 80/20 centering or better.
- 5.5: Between EX and EX-MT.
- 5 (EX Excellent): Surface wear visible. Corners are slightly rounded. Possible
  minor surface scratches. 85/15 centering or better.
- 4.5: Between VG-EX and EX.
- 4 (VG-EX Very Good-Excellent): Moderate surface wear. Some scuffing. Corner
  rounding. 85/15 centering.
- 3 (VG Very Good): Heavy surface wear, light creases possible. Corners are well
  rounded. Mild staining. 90/10 centering.
- 2 (Good): Heavy wear. Creases. Possibly rounded corners. Heavy staining. Notching on edges.
- 1 (Poor): Heavily worn, badly miscut, altered, or damaged card.

GRADING CRITERIA TO ASSESS:
1. CENTERING: Measure the border ratio front and back (left/right and top/bottom)
2. CORNERS: Examine all four corners for wear, fraying, or damage
3. EDGES: Check all four edges for nicks, chips, or roughness
4. SURFACE: Look for scratches, print lines, stains, creases, or loss of gloss

CRITICAL RULES — follow these exactly:
- There is ONE overall grade for the entire card. Never state two different grades.
- Start the report with exactly this line: "Overall Grade: X" (e.g. "Overall Grade: 9.5" or "Overall Grade: Pristine 10")
- The overall grade must be consistent with sub-grades throughout. Do not contradict yourself.
- Only assign "Pristine 10" if the card is literally perfect in every single way. Any flaw at all means it is a 10 or lower.

Use this exact report structure:

## Overall Grade: [grade]
[One sentence explaining the grade]

## Sub-Grades
- Centering: [grade]
- Corners: [grade]
- Edges: [grade]
- Surface: [grade]

## Observations
[Detailed notes for each category]

## Key Factors
[What determined the final grade]

## Authenticity
[Authentic / concerns]

## Authenticity
[Authentic / concerns]"""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent / "users.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                is_pro INTEGER NOT NULL DEFAULT 0,
                daily_scans INTEGER NOT NULL DEFAULT 0,
                last_scan_date TEXT,
                stripe_customer_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrate existing databases that are missing new columns
        for col, definition in [
            ("is_pro", "INTEGER NOT NULL DEFAULT 0"),
            ("daily_scans", "INTEGER NOT NULL DEFAULT 0"),
            ("last_scan_date", "TEXT"),
            ("stripe_customer_id", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # Column already exists

init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def send_verification_email(email: str):
    token = serializer.dumps(email, salt="email-verify")
    verify_url = f"http://localhost:5000/verify/{token}"
    msg = Message(
        subject="Verify your CardGrade AI account",
        recipients=[email],
        html=f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px;">
          <h2 style="font-weight:900;letter-spacing:-1px;">CardGrade AI</h2>
          <p style="color:#555;margin:16px 0;">Thanks for signing up! Click the button below to verify your email address.</p>
          <a href="{verify_url}" style="display:inline-block;background:#0a0a0a;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700;margin:8px 0;">
            Verify my email →
          </a>
          <p style="color:#aaa;font-size:12px;margin-top:24px;">Link expires in 1 hour. If you didn't sign up, ignore this email.</p>
        </div>
        """
    )
    mail.send(msg)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def _user_is_pro(email, user_row):
    return email in PRO_LIFETIME_EMAILS or (user_row and bool(user_row["is_pro"]))


def _scans_today(user_row):
    if not user_row:
        return 0
    today = datetime.date.today().isoformat()
    return user_row["daily_scans"] if user_row["last_scan_date"] == today else 0


@app.route("/")
def index():
    user_email = session.get("email")
    is_pro = False
    scans_remaining = None
    if user_email:
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (user_email,)).fetchone()
        is_pro = _user_is_pro(user_email, user)
        if not is_pro:
            scans_remaining = max(0, 5 - _scans_today(user))
    return render_template("index.html", user_email=user_email, is_pro=is_pro, scans_remaining=scans_remaining)


@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return {"error": "Email and password are required."}, 400
    if len(password) < 8:
        return {"error": "Password must be at least 8 characters."}, 400

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password))
            )
        try:
            send_verification_email(email)
        except Exception:
            pass  # Don't fail signup if email sending fails
        return {"ok": True, "message": "Account created! Check your email to verify."}
    except sqlite3.IntegrityError:
        return {"error": "An account with that email already exists."}, 409


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return {"error": "Invalid email or password."}, 401
    if not user["verified"]:
        return {"error": "Please verify your email before logging in."}, 403

    session["email"] = email
    is_pro = email in PRO_LIFETIME_EMAILS
    return {"ok": True, "email": email, "pro": is_pro}


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return {"ok": True}


@app.route("/verify/<token>")
def verify_email(token):
    try:
        email = serializer.loads(token, salt="email-verify", max_age=3600)
    except SignatureExpired:
        return render_template("verify.html", status="expired")
    except BadSignature:
        return render_template("verify.html", status="invalid")

    with get_db() as conn:
        conn.execute("UPDATE users SET verified = 1 WHERE email = ?", (email,))
    return render_template("verify.html", status="success", email=email)


@app.route("/resend-verification", methods=["POST"])
def resend_verification():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        return {"error": "No account found."}, 404
    if user["verified"]:
        return {"error": "Already verified."}, 400
    try:
        send_verification_email(email)
        return {"ok": True}
    except Exception as e:
        return {"error": f"Could not send email: {e}"}, 500


@app.route("/me")
def me():
    email = session.get("email")
    if not email:
        return {"logged_in": False}
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    pro = _user_is_pro(email, user)
    scans_used = _scans_today(user)
    return {
        "logged_in": True,
        "email": email,
        "pro": pro,
        "scans_used": scans_used,
        "scans_remaining": None if pro else max(0, 5 - scans_used),
    }


@app.route("/grade", methods=["POST"])
def grade():
    email = session.get("email")
    if not email:
        return {"error": "You must be logged in to grade a card."}, 401

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    pro = _user_is_pro(email, user)
    if not pro:
        if _scans_today(user) >= 5:
            return {"error": "You've used all 5 free scans today. Upgrade to Pro for unlimited grading."}, 429

    if "card_front" not in request.files or "card_back" not in request.files:
        return {"error": "Both front and back images are required."}, 400

    file_front = request.files["card_front"]
    file_back  = request.files["card_back"]
    card_description = request.form.get("card_description", "").strip()

    for f in (file_front, file_back):
        if not f.filename:
            return {"error": "One or both files are missing."}, 400
        if not allowed_file(f.filename):
            return {"error": f"Unsupported format: {f.filename}. Use JPG, PNG, or WebP."}, 400

    def encode(f):
        ext = Path(f.filename).suffix.lower()
        mt = MEDIA_TYPE_MAP[ext]
        data = base64.standard_b64encode(f.read()).decode("utf-8")
        return data, mt

    front_data, front_type = encode(file_front)
    back_data,  back_type  = encode(file_back)

    # Count this scan for free users
    if not pro:
        today = datetime.date.today().isoformat()
        with get_db() as conn:
            row = conn.execute("SELECT daily_scans, last_scan_date FROM users WHERE email = ?", (email,)).fetchone()
            new_count = (row["daily_scans"] + 1) if row["last_scan_date"] == today else 1
            conn.execute(
                "UPDATE users SET daily_scans = ?, last_scan_date = ? WHERE email = ?",
                (new_count, today, email)
            )

    def generate():
        try:
            client = Portkey(
                base_url="https://ai-gateway.apps.cloud.rt.nyu.edu/v1",
                api_key=os.environ.get("PORTKEY_API_KEY", ""),
            )
            user_message = "Please provide a complete PSA-style grading analysis for this trading card. The first image is the front and the second image is the back."
            if card_description:
                user_message += f"\n\nCard details: {card_description}"

            stream = client.chat.completions.create(
                model="@vertexai/anthropic.claude-opus-4-6",
                max_tokens=2048,
                temperature=0,
                stream=True,
                messages=[
                    {"role": "system", "content": PSA_GRADING_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{front_type};base64,{front_data}"}},
                            {"type": "image_url", "image_url": {"url": f"data:{back_type};base64,{back_data}"}},
                            {"type": "text", "text": user_message},
                        ],
                    },
                ],
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield f"data: {json.dumps({'text': delta.content})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': f'Error: {str(e)}'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")



@app.route("/upgrade", methods=["POST"])
def upgrade():
    return {"error": "Pro upgrades are not available yet. Check back soon!"}, 503
    email = session.get("email")
    if not email:
        return {"error": "Not logged in."}, 401
    if not stripe.api_key or not STRIPE_PRICE_ID:
        return {"error": "Stripe is not configured yet."}, 503
    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            customer_email=email,
            success_url=f"{APP_BASE_URL}/?upgraded=1",
            cancel_url=f"{APP_BASE_URL}/",
        )
        return {"url": checkout.url}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return {}, 400

    def set_pro(customer_id, value):
        try:
            customer = stripe.Customer.retrieve(customer_id)
            cust_email = customer.get("email", "")
            if cust_email:
                with get_db() as conn:
                    conn.execute("UPDATE users SET is_pro = ? WHERE email = ?", (value, cust_email))
        except Exception:
            pass

    etype = event["type"]
    cid = event["data"]["object"].get("customer")
    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        status = event["data"]["object"].get("status")
        if status in ("active", "trialing"):
            set_pro(cid, 1)
    elif etype in ("customer.subscription.deleted", "customer.subscription.paused"):
        set_pro(cid, 0)

    return {}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
