import asyncio
import json
import os
import random
from threading import Thread, Lock
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
    return "Ultimate License Manager Shop & Webhook Gateway is running!"

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
            f"🎉 **DEPOSIT SUCCESSFUL & CREDITED!**\n"
            f"═════════════════════════════════\n"
            f"💰 Added to Wallet: `₹{amount:.2f}`\n"
            f"💼 Current Balance: `₹{get_user_balance(user_id):.2f}`\n"
            f"═════════════════════════════════\n"
            f"🚀 You can now buy any panel instantly using your wallet balance with 1-click!"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending deposit notice: {e}")

async def send_key_to_user(user_id, panel_key, plan):
    try:
        success_msg = (
            "🎉 **PAYMENT VERIFIED & AUTO-DELIVERED!**\n"
            "═════════════════════════════════\n"
            f"📦 **Plan:** Free Fire Panel ({plan.replace('_', ' ').title()})\n"
            f"🔑 **Your Secure License Key:** `{panel_key}`\n"
            "═════════════════════════════════\n"
            "🚀 Enjoy your game! Keep this key safe."
        )
        await BOT_APPLICATION.bot.send_message(chat_id=user_id, text=success_msg, parse_mode="Markdown")
        
        admin_alert = (
            "🔔 **SECURE AUTO-SALE SUCCESSFUL**\n"
            "═════════════════════════════════\n"
            f"👤 **User ID:** `{user_id}`\n"
            f"📦 **Plan:** {plan}\n"
            f"🔑 **Key Delivered:** `{panel_key}`\n"
            "═════════════════════════════════"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_alert, parse_mode="Markdown")
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
        f"👋 Hello, {user.first_name}!\n\n"
        f"👑 **License Manager Reseller Hub**\n"
        f"🌐 *Your Business, Your Growth!*\n\n"
        f"💎 **Universal UPI Supported (PhonePe, GPay, Paytm, FamPay)**\n"
        f"⚡ Instant Auto-Add Balance & 1-Click Key Delivery\n"
        f"🇮🇳 Direct deposit to FamPay: `{FAMPAY_UPI}`\n\n"
        f"💼 **Your Wallet Balance:** `₹{balance:.2f}`\n"
        f"═════════════════════════════════\n"
        f"👑 Owner / Support: {ADMIN_USERNAME}"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

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
            "🛍️ **License Shop - Select Product:**\n═════════════════════════════════\nChoose your desired cheat panel below:",
            reply_markup=reply_markup, parse_mode="Markdown"
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
            f"📦 **Product:** `{prod_name}`\n═════════════════════════════════\nSelect your duration plan:",
            reply_markup=reply_markup, parse_mode="Markdown"
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
                [InlineKeyboardButton("📲 Pay via Any UPI App (PhonePe/GPay/FamPay)", callback_data=f"upipay_{prod}_{plan}")],
                [InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod.lower()}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"💳 **CHECKOUT OPTIONS**\n═════════════════════════════════\n"
                f"📦 Product: `{prod}` ({plan.replace('_', ' ').title()})\n"
                f"💰 Price: `₹{base_price:.2f}`\n"
                f"💼 Wallet Balance: `₹{balance:.2f}` (Sufficient!)\n\n"
                f"Choose your payment method:",
                reply_markup=reply_markup, parse_mode="Markdown"
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
            
            checkout_text = (
                f"💳 **UNIVERSAL UPI CHECKOUT**\n═════════════════════════════════\n"
                f"📦 Product: `{prod}` ({plan.replace('_', ' ').title()})\n"
                f"💰 **Exact Amount to Pay:** `₹{unique_amount:.2f}`\n"
                f"📲 **FamPay UPI ID:** `{FAMPAY_UPI}`\n"
                f"👤 Name: Khairul Islam\n\n"
                f"⚠️ **Supported Apps:** PhonePe, Google Pay, Paytm, FamPay & all UPI apps!\n"
                f"1. Pay exact **₹{unique_amount:.2f}** to `{FAMPAY_UPI}`.\n"
                f"2. Key delivers automatically in 1 second! 🚀"
            )
            keyboard = [[InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod.lower()}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(checkout_text, reply_markup=reply_markup, parse_mode="Markdown")

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
                    f"🎉 **1-CLICK PURCHASE SUCCESSFUL!**\n═════════════════════════════════\n"
                    f"📦 Plan: `{prod}` ({plan.replace('_', ' ').title()})\n"
                    f"🔑 **License Key:** `{assigned_key}`\n"
                    f"💼 Remaining Balance: `₹{get_user_balance(user.id):.2f}`\n"
                    f"═════════════════════════════════\n🚀 Enjoy your game!"
                )
                keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
                await query.message.edit_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                update_user_balance(user.id, price)
                await query.message.edit_text("❌ Error: Key Out of Stock! Amount refunded to wallet.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]]))
        else:
            await query.message.edit_text("❌ Insufficient wallet balance!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]]))

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
        
        checkout_text = (
            f"💳 **UNIVERSAL UPI CHECKOUT**\n═════════════════════════════════\n"
            f"📦 Product: `{prod}` ({plan.replace('_', ' ').title()})\n"
            f"💰 **Exact Amount to Pay:** `₹{unique_amount:.2f}`\n"
            f"📲 **FamPay UPI ID:** `{FAMPAY_UPI}`\n"
            f"👤 Name: Khairul Islam\n\n"
            f"⚠️ Pay exact **₹{unique_amount:.2f}** via PhonePe, Google Pay, Paytm, or FamPay!"
        )
        keyboard = [[InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod.lower()}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(checkout_text, reply_markup=reply_markup, parse_mode="Markdown")

    elif data == "deposit_menu":
        keyboard = [
            [InlineKeyboardButton("➕ Add ₹50", callback_data="dep_50"), InlineKeyboardButton("➕ Add ₹100", callback_data="dep_100")],
            [InlineKeyboardButton("➕ Add ₹200", callback_data="dep_200"), InlineKeyboardButton("➕ Add ₹500", callback_data="dep_500")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "💰 **DEPOSIT BALANCE (Auto-Credit via Any UPI App)**\n═════════════════════════════════\nSelect amount to add to your wallet:",
            reply_markup=reply_markup, parse_mode="Markdown"
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
        
        dep_text = (
            f"💳 **ADD BALANCE CHECKOUT**\n═════════════════════════════════\n"
            f"💰 Deposit Amount: `₹{dep_amt:.2f}`\n"
            f"🎯 **Exact Amount to Pay:** `₹{unique_amount:.2f}`\n"
            f"📲 **FamPay UPI ID:** `{FAMPAY_UPI}`\n"
            f"👤 Name: Khairul Islam\n\n"
            f"⚠️ **Instructions:** Pay exact **₹{unique_amount:.2f}** using PhonePe, Google Pay, Paytm, or FamPay. Balance will be credited instantly!"
        )
        keyboard = [[InlineKeyboardButton("« Back to Deposit", callback_data="deposit_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(dep_text, reply_markup=reply_markup, parse_mode="Markdown")

    elif data == "profile":
        balance = get_user_balance(user.id)
        prof_text = (
            f"👤 **RESELLER PROFILE**\n═════════════════════════════════\n"
            f"📛 Name: {user.full_name}\n"
            f"🆔 User ID: `{user.id}`\n"
            f"💼 Wallet Balance: `₹{balance:.2f}`\n"
            f"👑 Status: Verified Reseller 🟢\n"
            f"═════════════════════════════════"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        await query.message.edit_text(prof_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "history":
        balance = get_user_balance(user.id)
        hist_text = (
            f"📊 **TRANSACTION & PURCHASE HISTORY**\n═════════════════════════════════\n"
            f"💼 Current Wallet Balance: `₹{balance:.2f}`\n"
            f"🟢 Status: All systems operational\n"
            f"═════════════════════════════════"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        await query.message.edit_text(hist_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "referral":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"
        ref_text = (
            f"👥 **REFERRAL PROGRAM**\n═════════════════════════════════\n"
            f"Invite your friends and earn rewards!\n\n"
            f"🔗 Your Referral Link:\n`{ref_link}`\n"
            f"═════════════════════════════════"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        await query.message.edit_text(ref_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "low_price":
        await query.message.edit_text(
            "🏷️ **BUY AT LOW PRICE**\n═════════════════════════════════\nWe offer the best wholesale market prices directly in our License Shop!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]], parse_mode="Markdown")
        )
    elif data == "share":
        await query.message.edit_text(
            "🌐 **SHARE WITH FRIENDS**\n═════════════════════════════════\nShare our bot link with your gaming friends and community!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]], parse_mode="Markdown")
        )
    elif data == "vip_seller":
        await query.message.edit_text(
            "🔓 **UNLOCK VIP SELLER**\n═════════════════════════════════\nContact owner to get VIP Reseller status and special discounts!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]], parse_mode="Markdown")
        )
    elif data == "support":
        await query.message.edit_text(
            f"🆘 **HELP LINE SUPPORT**\n═════════════════════════════════\nFor assistance, contact owner: {ADMIN_USERNAME}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]], parse_mode="Markdown")
        )

def main():
    keep_alive()
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
