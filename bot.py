import os
import sqlite3
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

REGISTRATION_FEE = os.getenv("REGISTRATION_FEE", "50")

GROUP_GRADE9 = int(os.getenv("GROUP_GRADE9", "-1004297148096"))
GROUP_EXAM_CENTER = int(os.getenv("GROUP_EXAM_CENTER", "-1004465600412"))

EBIRR_ACCOUNT = os.getenv("EBIRR_ACCOUNT", "")
MPESA_ACCOUNT = os.getenv("MPESA_ACCOUNT", "")

ABOUT_URL = "https://keyraddiin-media.onrender.com"

GROUP_GRADE9_NAME = "GRADE 9 SMART STUDENTS | 2019 E.C"
GROUP_EXAM_CENTER_NAME = "🛑 KEYRADDIIN EXAM CENTER"

DB_FILE = "students.db"

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# CONVERSATION STATES
# ============================================================

(
    FULL_NAME,
    SCHOOL_NAME,
    GRADE,
    REGISTRATION_NUMBER,
    TELEGRAM_USERNAME,
    PHONE_NUMBER,
    REVIEW,
    PAYMENT_METHOD,
    PAYMENT_SCREENSHOT,
) = range(9)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            telegram_username TEXT,
            full_name TEXT NOT NULL,
            school_name TEXT NOT NULL,
            grade TEXT NOT NULL,
            registration_number TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            amount TEXT NOT NULL,
            screenshot_file_id TEXT,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(application_id) REFERENCES applications(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS access_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            invite_link TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(application_id) REFERENCES applications(id)
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def escape_text(text):
    if text is None:
        return ""
    return str(text)


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📝 New Registration", callback_data="new_registration")
        ],
        [
            InlineKeyboardButton("📋 My Applications", callback_data="my_applications"),
            InlineKeyboardButton("💳 Payment History", callback_data="payment_history"),
        ],
        [
            InlineKeyboardButton("🔐 My Access", callback_data="my_access"),
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎓 <b>KEYRADDIIN STUDENT REGISTRATION</b>\n\n"
        "Baga nagaan dhuftan! 👋\n\n"
        "Bot kanaan:\n"
        "• 📝 Registration haaraa gochuu\n"
        "• 💳 Kaffaltii mirkaneessuu\n"
        "• 📸 Payment screenshot erguu\n"
        "• 🔐 Private group access argachuu\n"
        "• 📋 Application kee hordofuu\n\n"
        f"💰 Registration Fee: <b>{REGISTRATION_FEE} ETB</b>\n\n"
        "👇 Filannoo kee keessaa tokko filadhu."
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )


def get_application(application_id):
    conn = get_db()

    row = conn.execute("""
        SELECT
            a.*,
            s.telegram_id,
            s.telegram_username,
            s.full_name,
            s.school_name,
            s.grade,
            s.registration_number,
            s.phone_number,
            p.id AS payment_id,
            p.method AS payment_method,
            p.amount AS payment_amount,
            p.screenshot_file_id,
            p.status AS payment_status,
            p.rejection_reason
        FROM applications a
        JOIN students s ON a.student_id = s.id
        LEFT JOIN payments p ON p.application_id = a.id
        WHERE a.id = ?
        ORDER BY p.id DESC
        LIMIT 1
    """, (application_id,)).fetchone()

    conn.close()
    return row


def create_application(data, telegram_id):
    conn = get_db()
    cur = conn.cursor()

    created = now()

    cur.execute("""
        INSERT INTO students (
            telegram_id,
            telegram_username,
            full_name,
            school_name,
            grade,
            registration_number,
            phone_number,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        telegram_id,
        data["telegram_username"],
        data["full_name"],
        data["school_name"],
        data["grade"],
        data["registration_number"],
        data["phone_number"],
        created,
    ))

    student_id = cur.lastrowid

    cur.execute("""
        INSERT INTO applications (
            student_id,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        student_id,
        "WAITING_PAYMENT",
        created,
        created,
    ))

    application_id = cur.lastrowid

    conn.commit()
    conn.close()

    return application_id


def create_payment(application_id, method):
    conn = get_db()
    cur = conn.cursor()

    created = now()

    cur.execute("""
        INSERT INTO payments (
            application_id,
            method,
            amount,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        application_id,
        method,
        REGISTRATION_FEE,
        "WAITING_SCREENSHOT",
        created,
        created,
    ))

    payment_id = cur.lastrowid

    cur.execute("""
        UPDATE applications
        SET status = ?, updated_at = ?
        WHERE id = ?
    """, (
        "WAITING_SCREENSHOT",
        created,
        application_id,
    ))

    conn.commit()
    conn.close()

    return payment_id


def update_payment_screenshot(payment_id, file_id):
    conn = get_db()

    conn.execute("""
        UPDATE payments
        SET screenshot_file_id = ?,
            status = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        file_id,
        "PENDING_ADMIN",
        now(),
        payment_id,
    ))

    conn.commit()
    conn.close()


def set_payment_rejected(application_id, reason):
    conn = get_db()

    conn.execute("""
        UPDATE payments
        SET status = ?,
            rejection_reason = ?,
            updated_at = ?
        WHERE application_id = ?
          AND id = (
              SELECT MAX(id)
              FROM payments
              WHERE application_id = ?
          )
    """, (
        "REJECTED",
        reason,
        now(),
        application_id,
        application_id,
    ))

    conn.execute("""
        UPDATE applications
        SET status = ?, updated_at = ?
        WHERE id = ?
    """, (
        "REJECTED",
        now(),
        application_id,
    ))

    conn.commit()
    conn.close()


def set_application_approved(application_id):
    conn = get_db()

    conn.execute("""
        UPDATE payments
        SET status = ?,
            updated_at = ?
        WHERE application_id = ?
          AND id = (
              SELECT MAX(id)
              FROM payments
              WHERE application_id = ?
          )
    """, (
        "APPROVED",
        now(),
        application_id,
        application_id,
    ))

    conn.execute("""
        UPDATE applications
        SET status = ?, updated_at = ?
        WHERE id = ?
    """, (
        "APPROVED",
        now(),
        application_id,
    ))

    conn.commit()
    conn.close()


def save_access_link(application_id, group_id, group_name, invite_link):
    conn = get_db()

    conn.execute("""
        INSERT INTO access_links (
            application_id,
            group_id,
            group_name,
            invite_link,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        application_id,
        group_id,
        group_name,
        invite_link,
        now(),
    ))

    conn.commit()
    conn.close()


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    text = (
        "🎓 <b>WELCOME TO KEYRADDIIN STUDENT REGISTRATION BOT</b>\n\n"
        "Baga nagaan dhuftan! 👋\n\n"
        "Bot kun barattoota Grade 9 fi Grade 10 "
        "registration fi private group access isaaniif qophaa'e.\n\n"
        "💰 Registration Fee: "
        f"<b>{REGISTRATION_FEE} ETB</b>\n\n"
        "👇 Continue gochuuf button armaan gadii tuqi."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# NEW REGISTRATION
# ============================================================

async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.message.edit_text(
        "📝 <b>NEW REGISTRATION</b>\n\n"
        "Mee <b>maqaa kee guutuu</b> barreessi.\n\n"
        "Fakkeenya:\n"
        "<code>Keyraddiin Abdella</code>",
        parse_mode=ParseMode.HTML,
    )

    return FULL_NAME


async def get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if len(text) < 3:
        await update.message.reply_text(
            "⚠️ Maqaan kee sirrii miti.\n"
            "Maqaa guutuu kee barreessi."
        )
        return FULL_NAME

    context.user_data["full_name"] = text

    await update.message.reply_text(
        "🏫 <b>School Name</b>\n\n"
        "Maqaa mana barumsaa kee barreessi.\n\n"
        "Fakkeenya:\n"
        "<code>Bisidimo Secondary School</code>",
        parse_mode=ParseMode.HTML,
    )

    return SCHOOL_NAME


async def get_school_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Maaloo maqaa mana barumsaa sirrii galchi."
        )
        return SCHOOL_NAME

    context.user_data["school_name"] = text

    keyboard = [
        [
            InlineKeyboardButton("9️⃣ Grade 9", callback_data="grade_9"),
            InlineKeyboardButton("🔟 Grade 10", callback_data="grade_10"),
        ]
    ]

    await update.message.reply_text(
        "🎓 <b>Grade kee filadhu:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return GRADE


async def get_grade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "grade_9":
        grade = "Grade 9"
    elif query.data == "grade_10":
        grade = "Grade 10"
    else:
        return GRADE

    context.user_data["grade"] = grade

    await query.message.edit_text(
        "🔢 <b>Registration Number</b>\n\n"
        "Registration Number kee galchi.\n\n"
        "Fakkeenya:\n"
        "<code>G9-2026-001</code>",
        parse_mode=ParseMode.HTML,
    )

    return REGISTRATION_NUMBER


async def get_registration_number(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text.strip()

    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Registration Number sirrii galchi."
        )
        return REGISTRATION_NUMBER

    context.user_data["registration_number"] = text

    username = update.effective_user.username

    if username:
        context.user_data["telegram_username"] = f"@{username}"

        await update.message.reply_text(
            "📱 <b>Phone Number</b>\n\n"
            "Lakkoofsa bilbilaa kee galchi.\n\n"
            "Fakkeenya:\n"
            "<code>09XXXXXXXX</code>",
            parse_mode=ParseMode.HTML,
        )

        return PHONE_NUMBER

    await update.message.reply_text(
        "👤 <b>Telegram Username</b>\n\n"
        "Username kee galchi.\n\n"
        "Fakkeenya:\n"
        "<code>@Key05r</code>\n\n"
        "Yoo username hin qabne:\n"
        "<code>None</code>",
        parse_mode=ParseMode.HTML,
    )

    return TELEGRAM_USERNAME


async def get_telegram_username(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    username = update.message.text.strip()

    if username.lower() == "none":
        username = "None"
    elif not username.startswith("@"):
        username = "@" + username

    context.user_data["telegram_username"] = username

    await update.message.reply_text(
        "📱 <b>Phone Number</b>\n\n"
        "Lakkoofsa bilbilaa kee galchi.\n\n"
        "Fakkeenya:\n"
        "<code>09XXXXXXXX</code>",
        parse_mode=ParseMode.HTML,
    )

    return PHONE_NUMBER


async def get_phone_number(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    phone = update.message.text.strip()

    cleaned = phone.replace(" ", "").replace("-", "")

    if len(cleaned) < 9:
        await update.message.reply_text(
            "⚠️ Phone Number sirrii fakkaatu galchi."
        )
        return PHONE_NUMBER

    context.user_data["phone_number"] = phone

    data = context.user_data

    text = (
        "🔎 <b>REVIEW YOUR REGISTRATION</b>\n\n"
        f"👤 <b>Full Name:</b> {escape_text(data['full_name'])}\n"
        f"🏫 <b>School:</b> {escape_text(data['school_name'])}\n"
        f"🎓 <b>Grade:</b> {escape_text(data['grade'])}\n"
        f"🔢 <b>Registration No:</b> {escape_text(data['registration_number'])}\n"
        f"💬 <b>Telegram:</b> {escape_text(data.get('telegram_username', 'None'))}\n"
        f"📱 <b>Phone:</b> {escape_text(data['phone_number'])}\n\n"
        f"💰 <b>Fee:</b> {REGISTRATION_FEE} ETB\n\n"
        "Odeeffannoon kun sirrii yoo ta'e <b>CONFIRM</b> tuqi."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ CONFIRM",
                callback_data="confirm_registration"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ CANCEL",
                callback_data="cancel_registration"
            )
        ],
    ]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return REVIEW


# ============================================================
# CONFIRM REGISTRATION
# ============================================================

async def confirm_registration(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    data = context.user_data

    required = [
        "full_name",
        "school_name",
        "grade",
        "registration_number",
        "phone_number",
    ]

    if not all(key in data for key in required):
        await query.message.edit_text(
            "❌ Registration data guutuu miti.\n"
            "Mee registration haaraa jalqabi."
        )
        return ConversationHandler.END

    application_id = create_application(
        data,
        update.effective_user.id
    )

    context.user_data["application_id"] = application_id

    keyboard = [
        [
            InlineKeyboardButton(
                "🟢 E-Birr",
                callback_data="payment_ebirr"
            )
        ],
        [
            InlineKeyboardButton(
                "🔵 M-Pesa",
                callback_data="payment_mpesa"
            )
        ],
    ]

    await query.message.edit_text(
        "💳 <b>PAYMENT METHOD</b>\n\n"
        f"Registration Fee: <b>{REGISTRATION_FEE} ETB</b>\n\n"
        "Kaffaltii gochuuf karaa tokko filadhu:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return PAYMENT_METHOD


# ============================================================
# PAYMENT METHOD
# ============================================================

async def choose_payment_method(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    application_id = context.user_data.get("application_id")

    if not application_id:
        await query.message.edit_text(
            "❌ Application hin argamne.\n"
            "Mee registration haaraa jalqabi."
        )
        return ConversationHandler.END

    if query.data == "payment_ebirr":
        method = "E-Birr"
        account = EBIRR_ACCOUNT

    elif query.data == "payment_mpesa":
        method = "M-Pesa"
        account = MPESA_ACCOUNT

    else:
        return PAYMENT_METHOD

    payment_id = create_payment(application_id, method)

    context.user_data["payment_id"] = payment_id
    context.user_data["payment_method"] = method

    await query.message.edit_text(
        f"💳 <b>{method} PAYMENT</b>\n\n"
        f"💰 Amount: <b>{REGISTRATION_FEE} ETB</b>\n"
        f"📱 Account: <code>{escape_text(account)}</code>\n\n"
        "1️⃣ Kaffaltii godhi.\n"
        "2️⃣ Receipt/payment screenshot qabadhu.\n"
        "3️⃣ Screenshot kana asitti ergi.\n\n"
        "📸 <b>Amma payment screenshot ergi.</b>",
        parse_mode=ParseMode.HTML,
    )

    return PAYMENT_SCREENSHOT


# ============================================================
# PAYMENT SCREENSHOT
# ============================================================

async def receive_payment_screenshot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    payment_id = context.user_data.get("payment_id")
    application_id = context.user_data.get("application_id")

    if not payment_id or not application_id:
        await update.message.reply_text(
            "❌ Payment session hin argamne.\n"
            "Mee registration haaraa jalqabi."
        )
        return ConversationHandler.END

    file_id = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id

    elif update.message.document:
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text(
            "⚠️ Maaloo payment screenshot akka "
            "<b>photo</b> ykn <b>document</b> ergi.",
            parse_mode=ParseMode.HTML,
        )
        return PAYMENT_SCREENSHOT

    update_payment_screenshot(payment_id, file_id)

    application = get_application(application_id)

    await update.message.reply_text(
        "✅ <b>PAYMENT SUBMITTED</b>\n\n"
        f"Application ID: <code>#{application_id}</code>\n"
        f"💳 Method: <b>{escape_text(application['payment_method'])}</b>\n"
        f"💰 Amount: <b>{REGISTRATION_FEE} ETB</b>\n\n"
        "📸 Payment screenshot kee adminitti ergameera.\n"
        "⏳ Mee approval eegi.",
        parse_mode=ParseMode.HTML,
    )

    await notify_admin_payment(
        context.application,
        application_id
    )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# ADMIN PAYMENT NOTIFICATION
# ============================================================

async def notify_admin_payment(
    application: Application,
    application_id: int
):
    row = get_application(application_id)

    if not row:
        return

    username = row["telegram_username"] or "None"

    text = (
        "🔔 <b>NEW PAYMENT VERIFICATION</b>\n\n"
        f"🆔 <b>Application:</b> #{row['id']}\n\n"
        f"👤 <b>Full Name:</b> {escape_text(row['full_name'])}\n"
        f"🏫 <b>School:</b> {escape_text(row['school_name'])}\n"
        f"🎓 <b>Grade:</b> {escape_text(row['grade'])}\n"
        f"🔢 <b>Registration No:</b> {escape_text(row['registration_number'])}\n"
        f"💬 <b>Telegram:</b> {escape_text(username)}\n"
        f"📱 <b>Phone:</b> {escape_text(row['phone_number'])}\n\n"
        f"💳 <b>Payment:</b> {escape_text(row['payment_method'])}\n"
        f"💰 <b>Amount:</b> {REGISTRATION_FEE} ETB\n\n"
        "👇 Payment screenshot ilaaliitii murtii kenni."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=f"admin_approve:{application_id}"
            ),
            InlineKeyboardButton(
                "❌ REJECT",
                callback_data=f"admin_reject:{application_id}"
            ),
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    screenshot_id = row["screenshot_file_id"]

    try:
        if screenshot_id:
            await application.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=screenshot_id,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        else:
            await application.bot.send_message(
                chat_id=ADMIN_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )

    except Exception as e:
        logger.exception("Failed to notify admin: %s", e)


# ============================================================
# ADMIN APPROVE
# ============================================================

async def admin_approve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "⛔ You are not authorized.",
            show_alert=True,
        )
        return

    await query.answer("Processing approval...")

    try:
        application_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.message.reply_text(
            "❌ Invalid application ID."
        )
        return

    row = get_application(application_id)

    if not row:
        await query.message.reply_text(
            "❌ Application hin argamne."
        )
        return

    if row["payment_status"] == "APPROVED":
        await query.answer(
            "Already approved.",
            show_alert=True,
        )
        return

    if row["payment_status"] != "PENDING_ADMIN":
        await query.message.reply_text(
            "⚠️ Payment kun approvalaf hin eegin.\n"
            f"Current status: {row['payment_status']}"
        )
        return

    # Mark approved first.
    set_application_approved(application_id)

    # Remove old access links if any.
    conn = get_db()
    old_links = conn.execute("""
        SELECT * FROM access_links
        WHERE application_id = ?
    """, (application_id,)).fetchall()

    conn.close()

    # Create fresh links.
    links = []

    if row["grade"] == "Grade 9":
        groups = [
            (GROUP_GRADE9, GROUP_GRADE9_NAME),
            (GROUP_EXAM_CENTER, GROUP_EXAM_CENTER_NAME),
        ]
    else:
        groups = [
            (GROUP_EXAM_CENTER, GROUP_EXAM_CENTER_NAME),
        ]

    for group_id, group_name in groups:
        try:
            expire_at = datetime.now() + timedelta(hours=24)

            invite = await context.bot.create_chat_invite_link(
                chat_id=group_id,
                name=f"Application #{application_id}",
                expire_date=expire_at,
                member_limit=1,
            )

            save_access_link(
                application_id,
                group_id,
                group_name,
                invite.invite_link,
            )

            links.append(
                (group_name, invite.invite_link)
            )

        except Exception as e:
            logger.exception(
                "Could not create invite link for %s: %s",
                group_name,
                e,
            )

    # Admin result
    await query.edit_message_reply_markup(
        reply_markup=None
    )

    await query.message.reply_text(
        f"✅ <b>APPROVED</b>\n\n"
        f"Application <b>#{application_id}</b> approved.\n"
        f"Student: <b>{escape_text(row['full_name'])}</b>\n"
        f"Grade: <b>{escape_text(row['grade'])}</b>\n\n"
        f"🔐 Created links: <b>{len(links)}</b>",
        parse_mode=ParseMode.HTML,
    )

    # Student approval message.
    student_text = (
        "🎉 <b>PAYMENT APPROVED!</b>\n\n"
        "Congratulations! 🎓\n\n"
        f"👤 <b>Name:</b> {escape_text(row['full_name'])}\n"
        f"🏫 <b>School:</b> {escape_text(row['school_name'])}\n"
        f"🎓 <b>Grade:</b> {escape_text(row['grade'])}\n"
        f"🔢 <b>Registration No:</b> {escape_text(row['registration_number'])}\n\n"
        f"💳 <b>Payment:</b> {escape_text(row['payment_method'])}\n"
        f"💰 <b>Amount:</b> {REGISTRATION_FEE} ETB\n\n"
        "🔐 <b>PRIVATE ACCESS LINKS</b>\n\n"
    )

    if links:
        for index, (group_name, link) in enumerate(links, start=1):
            student_text += (
                f"{index}. <b>{escape_text(group_name)}</b>\n"
                f"👉 {link}\n\n"
            )
    else:
        student_text += (
            "⚠️ Invite link uumuu hin dandeenye.\n"
            "Admin qunnami."
        )

    student_text += (
        "\n⚠️ <b>IMPORTANT</b>\n"
        "• Link kun limited/one-time access qaba.\n"
        "• Namni biraa waliin hin qoodin.\n"
        "• Link yeroo muraasa keessatti expire ta'a.\n"
        "• Group keessa seenuuf link sirrii fayyadami."
    )

    try:
        await context.bot.send_message(
            chat_id=row["telegram_id"],
            text=student_text,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(
            "Could not send approval message to student: %s",
            e,
        )


# ============================================================
# ADMIN REJECT
# ============================================================

async def admin_reject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "⛔ You are not authorized.",
            show_alert=True,
        )
        return

    await query.answer()

    try:
        application_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.message.reply_text(
            "❌ Invalid application ID."
        )
        return

    row = get_application(application_id)

    if not row:
        await query.message.reply_text(
            "❌ Application hin argamne."
        )
        return

    if row["payment_status"] == "APPROVED":
        await query.answer(
            "Payment already approved.",
            show_alert=True,
        )
        return

    reason = "Payment screenshot ykn payment detail sirrii hin mirkanoofne."

    set_payment_rejected(application_id, reason)

    await query.edit_message_reply_markup(
        reply_markup=None
    )

    await query.message.reply_text(
        f"❌ <b>PAYMENT REJECTED</b>\n\n"
        f"Application: <b>#{application_id}</b>\n"
        f"Student: <b>{escape_text(row['full_name'])}</b>",
        parse_mode=ParseMode.HTML,
    )

    student_text = (
        "❌ <b>PAYMENT REJECTED</b>\n\n"
        f"👤 <b>Name:</b> {escape_text(row['full_name'])}\n"
        f"🆔 <b>Application:</b> #{application_id}\n"
        f"💳 <b>Method:</b> {escape_text(row['payment_method'])}\n"
        f"💰 <b>Amount:</b> {REGISTRATION_FEE} ETB\n\n"
        "📌 <b>Reason:</b>\n"
        f"{escape_text(reason)}\n\n"
        "Kaffaltii kee sirreessitee screenshot haaraa erguu "
        "dandeessa. Registration guutuu irra deebi'uu hin qabdu."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 RESUBMIT PAYMENT",
                callback_data=f"resubmit_payment:{application_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="main_menu"
            )
        ],
    ]

    try:
        await context.bot.send_message(
            chat_id=row["telegram_id"],
            text=student_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.exception(
            "Could not send rejection message: %s",
            e,
        )


# ============================================================
# RESUBMIT PAYMENT
# ============================================================

async def resubmit_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    try:
        application_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.message.reply_text(
            "❌ Application ID sirrii miti."
        )
        return ConversationHandler.END

    row = get_application(application_id)

    if not row:
        await query.message.reply_text(
            "❌ Application hin argamne."
        )
        return ConversationHandler.END

    if row["telegram_id"] != update.effective_user.id:
        await query.answer(
            "⛔ This application is not yours.",
            show_alert=True,
        )
        return ConversationHandler.END

    if row["payment_status"] == "APPROVED":
        await query.message.reply_text(
            "✅ Application kun duraan approved dha."
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["application_id"] = application_id

    keyboard = [
        [
            InlineKeyboardButton(
                "🟢 E-Birr",
                callback_data="resubmit_ebirr"
            )
        ],
        [
            InlineKeyboardButton(
                "🔵 M-Pesa",
                callback_data="resubmit_mpesa"
            )
        ],
    ]

    await query.message.reply_text(
        "🔄 <b>RESUBMIT PAYMENT</b>\n\n"
        f"Application: <b>#{application_id}</b>\n"
        f"Amount: <b>{REGISTRATION_FEE} ETB</b>\n\n"
        "Payment method filadhu:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return PAYMENT_METHOD


async def choose_resubmit_method(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    application_id = context.user_data.get("application_id")

    if not application_id:
        await query.message.reply_text(
            "❌ Application ID hin argamne."
        )
        return ConversationHandler.END

    if query.data == "resubmit_ebirr":
        method = "E-Birr"
        account = EBIRR_ACCOUNT

    elif query.data == "resubmit_mpesa":
        method = "M-Pesa"
        account = MPESA_ACCOUNT

    else:
        return PAYMENT_METHOD

    payment_id = create_payment(application_id, method)

    context.user_data["payment_id"] = payment_id
    context.user_data["payment_method"] = method

    await query.message.edit_text(
        f"💳 <b>{method} PAYMENT</b>\n\n"
        f"💰 Amount: <b>{REGISTRATION_FEE} ETB</b>\n"
        f"📱 Account: <code>{escape_text(account)}</code>\n\n"
        "Kaffaltii godhi, achiis screenshot haaraa asitti ergi.",
        parse_mode=ParseMode.HTML,
    )

    return PAYMENT_SCREENSHOT


# ============================================================
# CANCEL
# ============================================================

async def cancel_registration(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if query:
        await query.answer()
        await query.message.edit_text(
            "❌ Registration cancelled.\n\n"
            "Yeroo barbaadde registration haaraa jalqabi.",
            reply_markup=main_menu(),
        )
    else:
        await update.message.reply_text(
            "❌ Registration cancelled.",
            reply_markup=main_menu(),
        )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# MY APPLICATIONS
# ============================================================

async def my_applications(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id

    conn = get_db()

    rows = conn.execute("""
        SELECT
            a.id,
            a.status,
            a.created_at,
            s.full_name,
            s.school_name,
            s.grade,
            s.registration_number,
            p.method,
            p.amount,
            p.status AS payment_status
        FROM applications a
        JOIN students s ON a.student_id = s.id
        LEFT JOIN payments p ON p.id = (
            SELECT MAX(id)
            FROM payments
            WHERE application_id = a.id
        )
        WHERE s.telegram_id = ?
        ORDER BY a.id DESC
        LIMIT 20
    """, (telegram_id,)).fetchall()

    conn.close()

    if not rows:
        await query.message.edit_text(
            "📋 <b>MY APPLICATIONS</b>\n\n"
            "Ati application tokko illee hin qabdu.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return

    text = "📋 <b>MY APPLICATIONS</b>\n\n"

    for row in rows:
        text += (
            f"🆔 <b>#{row['id']}</b>\n"
            f"👤 {escape_text(row['full_name'])}\n"
            f"🎓 {escape_text(row['grade'])}\n"
            f"🏫 {escape_text(row['school_name'])}\n"
            f"💳 {escape_text(row['payment_status'] or 'NO PAYMENT')}\n"
            f"📅 {escape_text(row['created_at'])}\n"
            "──────────────\n"
        )

    await query.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# PAYMENT HISTORY
# ============================================================

async def payment_history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id

    conn = get_db()

    rows = conn.execute("""
        SELECT
            p.id,
            p.application_id,
            p.method,
            p.amount,
            p.status,
            p.rejection_reason,
            p.created_at
        FROM payments p
        JOIN applications a ON p.application_id = a.id
        JOIN students s ON a.student_id = s.id
        WHERE s.telegram_id = ?
        ORDER BY p.id DESC
        LIMIT 30
    """, (telegram_id,)).fetchall()

    conn.close()

    if not rows:
        await query.message.edit_text(
            "💳 <b>PAYMENT HISTORY</b>\n\n"
            "Payment history hin argamne.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return

    text = "💳 <b>PAYMENT HISTORY</b>\n\n"

    for row in rows:
        status = row["status"]

        if status == "APPROVED":
            icon = "✅"
        elif status == "REJECTED":
            icon = "❌"
        elif status == "PENDING_ADMIN":
            icon = "⏳"
        else:
            icon = "🕐"

        text += (
            f"{icon} <b>Payment #{row['id']}</b>\n"
            f"Application: #{row['application_id']}\n"
            f"Method: {escape_text(row['method'])}\n"
            f"Amount: {escape_text(row['amount'])} ETB\n"
            f"Status: {escape_text(status)}\n"
            f"Date: {escape_text(row['created_at'])}\n"
        )

        if row["rejection_reason"]:
            text += (
                f"Reason: {escape_text(row['rejection_reason'])}\n"
            )

        text += "──────────────\n"

    await query.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# MY ACCESS
# ============================================================

async def my_access(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id

    conn = get_db()

    rows = conn.execute("""
        SELECT
            al.application_id,
            al.group_name,
            al.invite_link,
            al.created_at
        FROM access_links al
        JOIN applications a ON al.application_id = a.id
        JOIN students s ON a.student_id = s.id
        WHERE s.telegram_id = ?
        ORDER BY al.id DESC
        LIMIT 30
    """, (telegram_id,)).fetchall()

    conn.close()

    if not rows:
        await query.message.edit_text(
            "🔐 <b>MY ACCESS</b>\n\n"
            "Ammaaf private access link hin qabdu.\n\n"
            "Payment kee approved yoo ta'e link argatta.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return

    text = "🔐 <b>MY ACCESS</b>\n\n"

    for row in rows:
        text += (
            f"🆔 Application: <b>#{row['application_id']}</b>\n"
            f"👥 <b>{escape_text(row['group_name'])}</b>\n"
            f"🔗 {escape_text(row['invite_link'])}\n"
            f"📅 {escape_text(row['created_at'])}\n"
            "──────────────\n"
        )

    await query.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


# ============================================================
# ABOUT
# ============================================================

async def about(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    text = (
        "ℹ️ <b>ABOUT KEYRADDIIN MEDIA</b>\n\n"
        "🎓 <b>KEYRADDIIN MEDIA BARNOOTA</b>\n\n"
        "Barattoota Grade 9 fi Grade 10'f "
        "barnoota, preparation, notes fi qabeenyaalee "
        "barnootaa dhiyeessa.\n\n"
        "🌐 <b>Website</b>\n"
        "https://keyraddiin-media.onrender.com\n\n"
        "📚 Barnoota har'aa — Milkaa'ina boruu."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🌐 Open Website",
                url=ABOUT_URL
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="main_menu"
            )
        ],
    ]

    await query.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=False,
    )


# ============================================================
# MAIN MENU CALLBACK
# ============================================================

async def main_menu_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    await send_main_menu(update, context)


# ============================================================
# /ID
# ============================================================

async def show_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    await update.message.reply_text(
        f"🆔 <b>Your Telegram ID:</b>\n"
        f"<code>{user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADMIN STATS
# ============================================================

async def admin_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Unauthorized."
        )
        return

    conn = get_db()

    students = conn.execute(
        "SELECT COUNT(*) AS count FROM students"
    ).fetchone()["count"]

    applications = conn.execute(
        "SELECT COUNT(*) AS count FROM applications"
    ).fetchone()["count"]

    pending = conn.execute("""
        SELECT COUNT(*) AS count
        FROM payments
        WHERE status = 'PENDING_ADMIN'
    """).fetchone()["count"]

    approved = conn.execute("""
        SELECT COUNT(*) AS count
        FROM payments
        WHERE status = 'APPROVED'
    """).fetchone()["count"]

    rejected = conn.execute("""
        SELECT COUNT(*) AS count
        FROM payments
        WHERE status = 'REJECTED'
    """).fetchone()["count"]

    conn.close()

    await update.message.reply_text(
        "📊 <b>ADMIN DASHBOARD</b>\n\n"
        f"👨‍🎓 Students: <b>{students}</b>\n"
        f"📝 Applications: <b>{applications}</b>\n"
        f"⏳ Pending Payments: <b>{pending}</b>\n"
        f"✅ Approved: <b>{approved}</b>\n"
        f"❌ Rejected: <b>{rejected}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.exception(
        "Unhandled exception:",
        exc_info=context.error
    )


# ============================================================
# APPLICATION
# ============================================================

def build_application():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing in .env"
        )

    init_db()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Registration Conversation
    # --------------------------------------------------------

    registration_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                start_registration,
                pattern=r"^new_registration$"
            ),
            CallbackQueryHandler(
                resubmit_payment,
                pattern=r"^resubmit_payment:\d+$"
            ),
        ],

        states={

            FULL_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_full_name
                )
            ],

            SCHOOL_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_school_name
                )
            ],

            GRADE: [
                CallbackQueryHandler(
                    get_grade,
                    pattern=r"^grade_(9|10)$"
                )
            ],

            REGISTRATION_NUMBER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_registration_number
                )
            ],

            TELEGRAM_USERNAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_telegram_username
                )
            ],

            PHONE_NUMBER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_phone_number
                )
            ],

            REVIEW: [
                CallbackQueryHandler(
                    confirm_registration,
                    pattern=r"^confirm_registration$"
                ),
                CallbackQueryHandler(
                    cancel_registration,
                    pattern=r"^cancel_registration$"
                ),
            ],

            PAYMENT_METHOD: [
                CallbackQueryHandler(
                    choose_payment_method,
                    pattern=r"^payment_(ebirr|mpesa)$"
                ),
                CallbackQueryHandler(
                    choose_resubmit_method,
                    pattern=r"^resubmit_(ebirr|mpesa)$"
                ),
            ],

            PAYMENT_SCREENSHOT: [
                MessageHandler(
                    filters.PHOTO | filters.Document.ALL,
                    receive_payment_screenshot
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_registration
            ),
        ],

        allow_reentry=True,
    )

    application.add_handler(
        registration_conversation
    )

    # --------------------------------------------------------
    # General Commands
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("id", show_id)
    )

    application.add_handler(
        CommandHandler("admin", admin_stats)
    )

    # --------------------------------------------------------
    # Admin callbacks
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            admin_approve,
            pattern=r"^admin_approve:\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_reject,
            pattern=r"^admin_reject:\d+$"
        )
    )

    # --------------------------------------------------------
    # Main menu callbacks
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            my_applications,
            pattern=r"^my_applications$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            payment_history,
            pattern=r"^payment_history$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            my_access,
            pattern=r"^my_access$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            about,
            pattern=r"^about$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            main_menu_callback,
            pattern=r"^main_menu$"
        )
    )

    application.add_error_handler(error_handler)

    return application


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    print("==============================================")
    print(" KEYRADDIIN STUDENT REGISTRATION BOT")
    print(" Starting...")
    print("==============================================")

    app = build_application()

    print("✅ Database ready")
    print("✅ Bot is running...")
    print("🛑 Press CTRL+C to stop")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )
