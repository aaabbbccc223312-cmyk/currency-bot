import os
import re
import logging
import requests
from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN is missing. Add it in Railway Variables."
    )

API_URL = "https://open.er-api.com/v6/latest/{}"

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ============================================================
# CURRENCY ALIASES
# ============================================================

CURRENCIES = {
    # USD
    "usd": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "$": "USD",

    # NGN
    "ngn": "NGN",
    "nigeria naira": "NGN",
    "nigerian naira": "NGN",
    "nigeria nairas": "NGN",
    "nigerian nairas": "NGN",
    "naira": "NGN",
    "nairas": "NGN",
    "₦": "NGN",

    # EUR
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "€": "EUR",

    # GBP
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "british pound": "GBP",
    "british pounds": "GBP",
    "£": "GBP",

    # CAD
    "cad": "CAD",
    "canadian dollar": "CAD",
    "canadian dollars": "CAD",

    # AUD
    "aud": "AUD",
    "australian dollar": "AUD",
    "australian dollars": "AUD",

    # JPY
    "jpy": "JPY",
    "yen": "JPY",
    "japanese yen": "JPY",
    "¥": "JPY",

    # CNY
    "cny": "CNY",
    "yuan": "CNY",
    "chinese yuan": "CNY",
    "renminbi": "CNY",

    # INR
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "indian rupee": "INR",
    "indian rupees": "INR",
    "₹": "INR",

    # ZAR
    "zar": "ZAR",
    "rand": "ZAR",
    "south african rand": "ZAR",

    # GHS
    "ghs": "GHS",
    "cedi": "GHS",
    "cedis": "GHS",
    "ghanaian cedi": "GHS",
    "ghana cedi": "GHS",

    # KES
    "kes": "KES",
    "kenyan shilling": "KES",
    "kenyan shillings": "KES",

    # CHF
    "chf": "CHF",
    "swiss franc": "CHF",
    "swiss francs": "CHF",

    # BRL
    "brl": "BRL",
    "brazilian real": "BRL",
    "brazilian reals": "BRL",

    # MXN
    "mxn": "MXN",
    "mexican peso": "MXN",
    "mexican pesos": "MXN",
    "peso": "MXN",
    "pesos": "MXN",
}

SYMBOLS = {
    "USD": "$",
    "NGN": "₦",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "INR": "₹",
    "CAD": "C$",
    "AUD": "A$",
    "ZAR": "R",
    "GHS": "GH₵",
    "KES": "KSh",
    "CHF": "CHF",
    "BRL": "R$",
    "MXN": "MX$",
}

# ============================================================
# CURRENCY HELPERS
# ============================================================

def find_currency(text):
    """
    Find a currency mentioned in the text.

    Returns:
        ISO currency code or None
    """

    text = text.lower().strip()

    # Check longer names first
    aliases = sorted(
        CURRENCIES.keys(),
        key=len,
        reverse=True,
    )

    for alias in aliases:

        # Currency symbols
        if alias in ["$", "₦", "€", "£", "¥", "₹"]:
            if alias in text:
                return CURRENCIES[alias]

        else:
            pattern = r"(?<![a-zA-Z])" + re.escape(alias) + r"(?![a-zA-Z])"

            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                return CURRENCIES[alias]

    return None


def clean_text(text):
    text = text.strip().lower()

    # Remove Telegram commands
    text = re.sub(
        r"^/convert(@\w+)?",
        "",
        text,
    )

    text = re.sub(
        r"^/rate(@\w+)?",
        "",
        text,
    )

    # Remove common phrases
    phrases = [
        "how much is",
        "how much are",
        "what is",
        "what's",
        "how many",
        "worth",
        "the",
    ]

    for phrase in phrases:
        text = text.replace(
            phrase,
            " ",
        )

    # Normalize conversion wording
    text = re.sub(
        r"\bfrom\b",
        " ",
        text,
    )

    text = re.sub(
        r"\bto\b",
        " to ",
        text,
    )

    text = re.sub(
        r"\bin\b",
        " to ",
        text,
    )

    text = re.sub(
        r"\bat\b",
        " to ",
        text,
    )

    text = re.sub(
        r"\?",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


# ============================================================
# PARSE CONVERSION
# ============================================================

def parse_conversion(text):
    """
    Parse examples such as:

    50 USD to NGN
    50 dollars to naira
    50$ in naira
    $50 in NGN
    100 euros to dollars
    """

    original = text.strip()

    cleaned = clean_text(original)

    # --------------------------------------------------------
    # Find amount
    # --------------------------------------------------------

    amount_match = re.search(
        r"(?<![A-Za-z])(\d+(?:\.\d+)?)",
        cleaned,
    )

    if not amount_match:
        return None

    try:
        amount = Decimal(
            amount_match.group(1)
        )
    except InvalidOperation:
        return None

    # --------------------------------------------------------
    # Look for currencies
    # --------------------------------------------------------

    # Search all currencies and record their locations
    detected = []

    aliases = sorted(
        CURRENCIES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for alias, code in aliases:

        if alias in ["$", "₦", "€", "£", "¥", "₹"]:

            for match in re.finditer(
                re.escape(alias),
                cleaned,
            ):
                detected.append(
                    (match.start(), code)
                )

        else:

            pattern = (
                r"(?<![A-Za-z])"
                + re.escape(alias)
                + r"(?![A-Za-z])"
            )

            for match in re.finditer(
                pattern,
                cleaned,
                flags=re.IGNORECASE,
            ):
                detected.append(
                    (match.start(), code)
                )

    # --------------------------------------------------------
    # Remove duplicate currencies
    # --------------------------------------------------------

    detected.sort(
        key=lambda item: item[0]
    )

    unique = []

    for position, code in detected:
        if code not in [item[1] for item in unique]:
            unique.append(
                (position, code)
            )

    if len(unique) < 2:
        return None

    # --------------------------------------------------------
    # Determine source / target
    # --------------------------------------------------------

    source_currency = unique[0][1]
    target_currency = unique[1][1]

    return (
        amount,
        source_currency,
        target_currency,
    )


# ============================================================
# GET EXCHANGE RATES
# ============================================================

def get_rates(base_currency):
    url = API_URL.format(
        base_currency
    )

    response = requests.get(
        url,
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("result") != "success":
        raise ValueError(
            data.get(
                "error-type",
                "Currency API error",
            )
        )

    return data


# ============================================================
# CONVERT
# ============================================================

def convert(
    amount,
    source_currency,
    target_currency,
):
    data = get_rates(
        source_currency
    )

    rates = data.get(
        "rates",
        {}
    )

    if target_currency not in rates:
        raise ValueError(
            f"{target_currency} is not available."
        )

    rate = Decimal(
        str(
            rates[target_currency]
        )
    )

    converted = amount * rate

    return {
        "rate": rate,
        "converted": converted,
        "updated": data.get(
            "time_last_update_utc",
            "Unknown",
        ),
    }


# ============================================================
# FORMAT
# ============================================================

def format_money(value):
    if value == value.to_integral_value():
        return f"{value:,.0f}"

    return f"{value:,.2f}"


def currency_symbol(code):
    return SYMBOLS.get(
        code,
        code,
    )


# ============================================================
# PROCESS
# ============================================================

async def process_conversion(
    update: Update,
    text: str,
):

    parsed = parse_conversion(text)

    if not parsed:

        await update.message.reply_text(
            "❌ I couldn't understand that conversion.\n\n"
            "Try:\n"
            "• 50 USD to NGN\n"
            "• 50 dollars to naira\n"
            "• 50$ in naira\n"
            "• How much is 100 euros in dollars?\n"
            "• £200 to Nigerian naira\n"
            "• 5000 NGN to USD"
        )

        return

    amount, source, target = parsed

    waiting = await update.message.reply_text(
        "🔎 Getting the latest exchange rate..."
    )

    try:

        result = convert(
            amount,
            source,
            target,
        )

        converted = result["converted"]
        rate = result["rate"]
        updated = result["updated"]

        source_symbol = currency_symbol(
            source
        )

        target_symbol = currency_symbol(
            target
        )

        message = (
            "💱 *Currency Conversion*\n\n"
            f"{source_symbol}{format_money(amount)} "
            f"{source} = "
            f"{target_symbol}{format_money(converted)} "
            f"{target}\n\n"
            f"📊 *Exchange rate:*\n"
            f"1 {source} = "
            f"{target_symbol}{format_money(rate)} "
            f"{target}\n\n"
            f"🕒 *Rate updated:*\n"
            f"{updated}\n\n"
            "⚠️ This is an indicative exchange rate. "
            "Banks and transfer services may use different "
            "rates and fees.\n\n"
            "📡 Source: ExchangeRate-API"
        )

        await waiting.edit_text(
            message,
            parse_mode="Markdown",
        )

    except requests.RequestException as error:

        logger.error(
            "API request failed: %s",
            error,
        )

        await waiting.edit_text(
            "⚠️ I couldn't connect to the exchange-rate "
            "service right now. Please try again."
        )

    except Exception as error:

        logger.exception(
            "Conversion failed: %s",
            error,
        )

        await waiting.edit_text(
            "⚠️ Something went wrong while converting "
            "the currencies.\n\n"
            "Please try again."
        )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "👋 Welcome to the Currency Bot! 💱\n\n"
        "I can convert money between currencies around "
        "the world.\n\n"
        "Try:\n"
        "• 50 USD to NGN\n"
        "• 50 dollars to naira\n"
        "• 50$ in naira\n"
        "• 100 euros to dollars\n"
        "• £200 to Nigerian naira\n"
        "• 5000 NGN to USD\n\n"
        "Use /help for more examples."
    )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "💱 *Currency Bot*\n\n"
        "Ask me to convert currencies.\n\n"
        "*Examples:*\n"
        "• 50 USD to NGN\n"
        "• 50 dollars to naira\n"
        "• 50$ in naira\n"
        "• $50 to NGN\n"
        "• 100 EUR to USD\n"
        "• £200 to Nigerian naira\n"
        "• 5000 NGN to USD\n\n"
        "You can use currency names, symbols, "
        "or ISO codes.",
        parse_mode="Markdown",
    )


# ============================================================
# CONVERT COMMAND
# ============================================================

async def convert_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = update.message.text or ""

    await process_conversion(
        update,
        text,
    )


# ============================================================
# NORMAL TEXT
# ============================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = update.message.text

    if not text:
        return

    await process_conversion(
        update,
        text,
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Telegram error:",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("💱 Currency bot starting...")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "convert",
            convert_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print("✅ Currency bot is running!")

    app.run_polling()


if __name__ == "__main__":
    main()
