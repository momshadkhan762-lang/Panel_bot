import asyncio
import json
import os
import random
from threading import Thread, Lock
from urllib.parse import quote
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

# --- Flask Server & Webhook API Gateway ---
app = Flask(__name__)

data_lock = Lock()
PENDING_ORDERS = {}
BOT_APPLICATION = None

KEY_FILE = "keys_stock.json"
USER_FILE = "users_db.json"

def load_keys():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    default_stock = {
        "phanthom_1_day": ["PHTM-1DAY-AAAA-1111", "PHTM-1DAY-BBBB-2222"],
        "phanthom_7_days": ["PHTM-7DAY-CCCC-3333"],
        "hex_blade_1_day": ["HEX-1DAY-1111-2222"],
        "rapid_core_1_day": ["RAP-1DAY-3333-4444"],
        "angry_1_day": ["ANGRY-1DAY-5555-6666"],
        "proxy_1_day": ["PROXY-1DAY-7777-8888"]
    }
    save_keys(default_stock)
    return default_stock

def save_keys(stock_data):
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump(stock_data, f, indent=4)

def load_users():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_users(users_data):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, indent=4)

def get_user_balance(user_id):
    users = load_users()
    str_uid = str(user_id)
    if str_uid not in users:
        users[str_uid] = {"balance": 0.0, "purchases": 0}
        save_users(users)
    return users[str_uid]["balance"]

def update_user_balance(user_id, amount):
    with data_lock:
        users = load_users()
        str_uid = str(user_id)
        if str_uid not in users:
            users[str_uid] = {"balance": 0.0, "purchases": 0}
        users[str_uid]["balance"] += amount
        save_users(users)

def get_key_from_stock(plan):
    with data_lock:
        stock = load_keys()
        if stock.get(plan) and len(stock[plan]) > 0:
            assigned_key = stock[plan].pop(0)
            save_keys(stock)
            return assigned_key
        return None

@app.route("/")
def home():
    return "Elite Pro License Manager Shop & Webhook Gateway is running!"

@app.route("/payment-webhook", methods=["POST"])
def payment_webhook():
    try:
        data = request.json
        amount = float(data.get("amount", 0))
        sender = data.get("sender", "Unknown")
        
        print(f"🔔 Universal UPI Payment Received: ₹{amount} from {sender}")
        
        target_user_id = None
        order_type = None
        matched_data = None
        
        with data_lock:
            for uid, order_info in list(PENDING_ORDERS.items()):
                if abs(order_info["amount"] - amount) < 0.001:
                    target_user_id = uid
                    order_type = order_info["type"]
                    matched_data = order_info
                    del PENDING_ORDERS[uid]
                    break
        
        if target_user_id and order_type:
            if order_type == "deposit":
                dep_amount = matched_data["dep_amount"]
                update_user_balance(target_user_id, dep_amount)
                if BOT_APPLICATION:
                    asyncio.run_coroutine_threadsafe(
                        send_deposit_success(target_user_id, dep_amount),
                        BOT_APPLICATION.loop
                    )
                return {"status": "success", "message": "Balance deposited successfully!"}, 200
            
            elif order_type == "product":
                plan = matched_data["plan"]
                assigned_key = get_key_from_stock(plan)
                if assigned_key:
                    if BOT_APPLICATION:
                        asyncio.run_coroutine_threadsafe(
                            send_key_to_user(target_user_id, assigned_key, plan),
                            BOT_APPLICATION.loop
                        )
                    return {"status": "success", "message": "Key delivered automatically!"}, 200
                else:
                    return {"status": "error", "message": "Key Out of Stock!"}, 400
        else:
            return {"status": "not_found", "message": "No matching order found for this amount."}, 404
            
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# -----------------------------------------------------

BOT_TOKEN = "8950060993:AAHGnbt7SjJ944okecPKK_Y10HFGQ3MLj0s"
ADMIN_CHAT_ID = 8380823727
ADMIN_USERNAME = "@Momshad_00"
FAMPAY_UPI = "islam-momshad.khan@fam"

async def send_deposit_success(user_id, amount):
    try:
        msg = (
            f"🎉 <b>DEPOSIT SUCCESSFUL & CREDITED!</b> 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Added to Wallet:</b> <code>₹{amount:.2f}</code>\n"
            f"💼 <b>Current Balance:</b> <code>₹{get_user_balance(user_id):.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <i>You can now buy any panel instantly using your wallet balance with 1-click!</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
    except Exception as e:
        print(f"Error sending deposit notice: {e}")

async def send_key_to_user(user_id, panel_key, plan):
    try:
        success_msg = (
            "🎉 <b>PAYMENT VERIFIED & AUTO-DELIVERED!</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Plan:</b> Free Fire Panel ({plan.replace('_', ' ').title()})\n"
            f"🔑 <b>Your License Key:</b> <code>{panel_key}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <i>Enjoy your game! Keep this key safe.</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=user_id, text=success_msg, parse_mode="HTML")
        
        admin_alert = (
            f"🔔 <b>SECURE AUTO-SALE SUCCESSFUL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📦 <b>Plan:</b> {plan}\n"
            f"🔑 <b>Key Delivered:</b> <code>{panel_key}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_alert, parse_mode="HTML")
    except Exception as e:
        print(f"Error sending auto-key: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🛍️ License Shop", callback_data="shop_menu")],
        [InlineKeyboardButton("💰 Deposit Balance", callback_data="deposit_menu"), InlineKeyboardButton("📊 All History", callback_data="history")],
        [InlineKeyboardButton("👤 Reseller Profile", callback_data="profile"), InlineKeyboardButton("👥 Referral", callback_data="referral")],
        [InlineKeyboardButton("🏷️ Buy at Low Price?", callback_data="low_price"), InlineKeyboardButton("🌐 Share Friends", callback_data="share")],
        [InlineKeyboardButton("🔓 UNLOCK VIP SELLER", callback_data="vip_seller"), InlineKeyboardButton("🆘 Help Line Support", callback_data="support")],
        [InlineKeyboardButton("📂 File Channel", url="https://t.me/Momshad_00")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"⚡ <b>WELCOME TO ELITE STORE</b> ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 Hello <b>{user.first_name}</b>!\n\n"
        f"👑 <b>License Manager Reseller Hub</b>\n"
        f"🌐 <i>Your Business, Your Ultimate Growth!</i>\n\n"
        f"💎 <b>Supported UPI:</b> PhonePe, GPay, Paytm, FamPay\n"
        f"⚡ <b>Instant Auto-Add Balance & 1-Click Delivery</b>\n"
        f"🇮🇳 <b>FamPay UPI:</b> <code>{FAMPAY_UPI}</code>\n\n"
        f"💼 <b>Your Wallet Balance:</b> <code>₹{balance:.2f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>Owner / Support:</b> {ADMIN_USERNAME}"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    
    if data == "shop_menu":
        keyboard = [
            [InlineKeyboardButton("🔥 Phanthom Android + IOS", callback_data="prod_phanthom")],
            [InlineKeyboardButton("⚡ Hex Blade - Root", callback_data="prod_hex")],
            [InlineKeyboardButton("🚀 Rapid Core - Root", callback_data="prod_rapid")],
            [InlineKeyboardButton("🎯 Angry Mod - Root", callback_data="prod_angry")],
            [InlineKeyboardButton("🛡️ Proxy Silent Cheat [Non Root]", callback_data="prod_proxy")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "🛍️ <b>PREMIUM LICENSE SHOP</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your desired cheat panel below:</i>",
            reply_markup=reply_markup, parse_mode="HTML"
        )
        
    elif data == "home":
        await start(update, context)
        
    elif data.startswith("prod_"):
        prod_name = data.replace("prod_", "").upper()
        keyboard = [
            [InlineKeyboardButton("⏱️ 1 Day Plan (₹50)", callback_data=f"buy_{prod_name}_1_day")],
            [InlineKeyboardButton("📅 7 Days Plan (₹200)", callback_data=f"buy_{prod_name}_7_days")],
            [InlineKeyboardButton("🏆 30 Days Plan (₹500)", callback_data=f"buy_{prod_name}_30_days")],
            [InlineKeyboardButton("« Back to Shop", callback_data="shop_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"📦 <b>Product:</b> <code>{prod_name}</code>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your duration plan:</i>",
            reply_markup=reply_markup, parse_mode="HTML"
        )
        
    elif data.startswith("buy_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        
        prices = {"1_day": 50.0, "7_days": 200.0, "30_days": 500.0}
        base_price = prices.get(plan, 50.0)
        
        balance = get_user_balance(user.id)
        if balance >= base_price:
            keyboard = [
                [InlineKeyboardButton("💳 Pay via Wallet Balance (1-Click)", callback_data=f"walletpay_{prod}_{plan}")],
                [InlineKeyboardButton("📲 Pay via Any UPI App (QR / UPI ID)", callback_data=f"upipay_{prod}_{plan}")],
                [InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod.lower()}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"💳 <b>CHECKOUT OPTIONS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
                f"💰 <b>Price:</b> <code>₹{base_price:.2f}</code>\n"
                f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code> (Sufficient!)\n\n"
                f"<i>Choose your payment method:</i>",
                reply_markup=reply_markup, parse_mode="HTML"
            )
        else:
            with data_lock:
                while True:
                    unique_cents = random.randint(1, 99) * 0.01
                    unique_amount = base_price + unique_cents
                    if not any(abs(o["amount"] - unique_amount) < 0.001 for o in PENDING_ORDERS.values()):
                        break
                
                stock_key = f"{prod.lower()}_{plan}"
                PENDING_ORDERS[user.id] = {"type": "product", "plan": stock_key, "amount": unique_amount}
            
            upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Khairul%20Islam&am={unique_amount:.2f}&cu=INR"
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(upi_link, safe='')}"
            
            checkout_text = (
                f"💳 <b>UNIVERSAL UPI CHECKOUT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
                f"🎯 <b>Exact Amount to Pay:</b> <code>₹{unique_amount:.2f}</code>\n"
                f"📲 <b>FamPay UPI ID:</b> <code>{FAMPAY_UPI}</code>\n"
                f"👤 <b>Name:</b> Khairul Islam\n\n"
                f"⚠️ <i>Scan QR code above or pay exact <code>₹{unique_amount:.2f}</code> via PhonePe, GPay, Paytm, FamPay!</i>\n"
                f"⚡ <i>Key delivers automatically in 1 second!</i> 🚀"
            )
            keyboard = [[InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod.lower()}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=qr_url,
                    caption=checkout_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except Exception:
                await query.message.edit_text(checkout_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data.startswith("walletpay_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        prices = {"1_day": 50.0, "7_days": 200.0, "30_days": 500.0}
        price = prices.get(plan, 50.0)
        
        balance = get_user_balance(user.id)
        if balance >= price:
            update_user_balance(user.id, -price)
            stock_key = f"{prod.lower()}_{plan}"
            assigned_key = get_key_from_stock(stock_key)
            if assigned_key:
                success_msg = (
                    f"🎉 <b>1-CLICK PURCHASE SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Plan:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
                    f"🔑 <b>License Key:</b> <code>{assigned_key}</code>\n"
                    f"💼 <b>Remaining Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🚀 <i>Enjoy your game!</i>"
                )
                keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
                await query.message.edit_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            else:
                update_user_balance(user.id, price)
                await query.message.edit_text("❌ <b>Error: Key Out of Stock! Amount refunded to wallet.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]]), parse_mode="HTML")
        else:
            await query.message.edit_text("❌ <b>Insufficient wallet balance!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]]), parse_mode="HTML")

    elif data.startswith("upipay_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        prices = {"1_day": 50.0, "7_days": 200.0, "30_days": 500.0}
        base_price = prices.get(plan, 50.0)
        
        with data_lock:
            while True:
                unique_cents = random.randint(1, 99) * 0.01
                unique_amount = base_price + unique_cents
                if not any(abs(o["amount"] - unique_amount) < 0.001 for o in PENDING_ORDERS.values()):
                    break
            stock_key = f"{prod.lower()}_{plan}"
            PENDING_ORDERS[user.id] = {"type": "product", "plan": stock_key, "amount": unique_amount}
        
        upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Khairul%20Islam&am={unique_amount:.2f}&cu=INR"
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(upi_link, safe='')}"
        
        checkout_text = (
            f"💳 <b>UNIVERSAL UPI CHECKOUT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Product:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
            f"🎯 <b>Exact Amount to Pay:</b> <code>₹{unique_amount:.2f}</code>\n"
            f"📲 <b>FamPay UPI ID:</b> <code>{FAMPAY_UPI}</code>\n"
            f"👤 <b>Name:</b> Khairul Islam\n\n"
            f"⚠️ <i>Pay exact <code>₹{unique_amount:.2f}</code> via PhonePe, Google Pay, Paytm, or FamPay!</i>"
        )
        keyboard = [[InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod.lower()}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=user.id,
                photo=qr_url,
                caption=checkout_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception:
            await query.message.edit_text(checkout_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "deposit_menu":
        keyboard = [
            [InlineKeyboardButton("➕ Add ₹50", callback_data="dep_50"), InlineKeyboardButton("➕ Add ₹100", callback_data="dep_100")],
            [InlineKeyboardButton("➕ Add ₹200", callback_data="dep_200"), InlineKeyboardButton("➕ Add ₹500", callback_data="dep_500")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "💰 <b>DEPOSIT BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select amount to add to your wallet:</i>",
            reply_markup=reply_markup, parse_mode="HTML"
        )
        
    elif data.startswith("dep_"):
        dep_amt = float(data.replace("dep_", ""))
        with data_lock:
            while True:
                unique_cents = random.randint(1, 99) * 0.01
                unique_amount = dep_amt + unique_cents
                if not any(abs(o["amount"] - unique_amount) < 0.001 for o in PENDING_ORDERS.values()):
                    break
            PENDING_ORDERS[user.id] = {"type": "deposit", "dep_amount": dep_amt, "amount": unique_amount}
        
        upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Khairul%20Islam&am={unique_amount:.2f}&cu=INR"
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(upi_link, safe='')}"
        
        dep_text = (
            f"💳 <b>ADD BALANCE CHECKOUT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Deposit Amount:</b> <code>₹{dep_amt:.2f}</code>\n"
            f"🎯 <b>Exact Amount to Pay:</b> <code>₹{unique_amount:.2f}</code>\n"
            f"📲 <b>FamPay UPI ID:</b> <code>{FAMPAY_UPI}</code>\n"
            f"👤 <b>Name:</b> Khairul Islam\n\n"
            f"⚠️ <i>Scan QR code above or pay exact <code>₹{unique_amount:.2f}</code> using PhonePe, GPay, Paytm, or FamPay!</i>"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=user.id,
                photo=qr_url,
                caption=dep_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception:
            await query.message.edit_text(dep_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "profile":
        balance = get_user_balance(user.id)
        prof_text = (
            f"👤 <b>RESELLER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📛 <b>Name:</b> {user.full_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code>\n"
            f"👑 <b>Status:</b> Verified Reseller 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        await query.message.edit_text(prof_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "history":
        balance = get_user_balance(user.id)
        hist_text = (
            f"📊 <b>TRANSACTION & PURCHASE HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code>\n"
            f"🟢 <b>Status:</b> All systems operational\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        await query.message.edit_text(hist_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "referral":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"
        ref_text = (
            f"👥 <b>REFERRAL PROGRAM</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Invite your friends and earn rewards!</i>\n\n"
            f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        await query.message.edit_text(ref_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "low_price":
        await query.message.edit_text(
            "🏷️ <b>BUY AT LOW PRICE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>We offer the best wholesale market prices directly in our License Shop!</i>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]), parse_mode="HTML"
        )
    elif data == "share":
        await query.message.edit_text(
            "🌐 <b>SHARE WITH FRIENDS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Share our bot link with your gaming friends and community!</i>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]), parse_mode="HTML"
        )
    elif data == "vip_seller":
        await query.message.edit_text(
            "🔓 <b>UNLOCK VIP SELLER</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Contact owner to get VIP Reseller status and special discounts!</i>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]), parse_mode="HTML"
        )
    elif data == "support":
        await query.message.edit_text(
            f"🆘 <b>HELP LINE SUPPORT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>For assistance, contact owner:</i> {ADMIN_USERNAME}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]), parse_mode="HTML"
        )

def main():
    keep_alive()
    
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
