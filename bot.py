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
        "BOT_TOKEN is missing. Add BOT_TOKEN to Railway Variables."
    )

# ExchangeRate-API Open Access endpoint.
# No API key is required, but attribution is required.
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
# CURRENCY NAMES / SYMBOLS
# ============================================================

CURRENCY_ALIASES = {
    # US Dollar
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "$": "USD",

    # Nigerian Naira
    "ngn": "NGN",
    "naira": "NGN",
    "nairas": "NGN",
    "nigerian naira": "NGN",
    "nigerian nairas": "NGN",
    "₦": "NGN",

    # Euro
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "€": "EUR",

    # British Pound
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "british pound": "GBP",
    "british pounds": "GBP",
    "£": "GBP",

    # Canadian Dollar
    "cad": "CAD",
    "canadian dollar": "CAD",
    "canadian dollars": "CAD",

    # Australian Dollar
    "aud": "AUD",
    "australian dollar": "AUD",
    "australian dollars": "AUD",

    # Japanese Yen
    "jpy": "JPY",
    "yen": "JPY",
    "japanese yen": "JPY",
    "¥": "JPY",

    # Chinese Yuan
    "cny": "CNY",
    "yuan": "CNY",
    "chinese yuan": "CNY",
    "renminbi": "CNY",

    # Indian Rupee
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "indian rupee": "INR",
    "₹": "INR",

    # South African Rand
    "zar": "ZAR",
    "rand": "ZAR",
    "south african rand": "ZAR",

    # Ghanaian Cedi
    "ghs": "GHS",
    "cedi": "GHS",
    "cedis": "GHS",
    "ghana cedi": "GHS",
    "ghanaian cedi": "GHS",
    "₵": "GHS",

    # Kenyan Shilling
    "kes": "KES",
    "kenyan shilling": "KES",
    "kenyan shillings": "KES",

    # Swiss Franc
    "chf": "CHF",
    "swiss franc": "CHF",
    "swiss francs": "CHF",

    # Brazilian Real
    "brl": "BRL",
    "real": "BRL",
    "reals": "BRL",
    "brazilian real": "BRL",

    # Mexican Peso
    "mxn": "MXN",
    "peso": "MXN",
    "pesos": "MXN",
    "mexican peso": "MXN",
}

# Display symbols
CURRENCY_SYMBOLS = {
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


def normalize_currency(currency_text: str):
    """Convert currency names, symbols or codes to ISO codes."""

    text = currency_text.strip().lower()

    # Direct alias
    if text in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[text]

    # ISO code
    if re.fullmatch(r"[a-zA-Z]{3}", text):
        return text.upper()

    return None


def currency_symbol(code: str) -> str:
    return CURRENCY_SYMBOLS.get(code.upper(), code.upper())


def format_number(value: Decimal) -> str:
    """Format large/small currency amounts nicely."""

    if abs(value) >= Decimal("1000000"):
        return f"{value:,.2f}"

    if value == value.to_integral_value():
        return f"{value:,.0f}"

    return f"{value:,.2f}"


# ============================================================
# API
# ============================================================


def get_rates(base_currency: str):
    """Fetch the latest rates for a base currency."""

    url = API_URL.format(base_currency)

    response = requests.get(
        url,
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("result") != "success":
        raise ValueError(
            data.get("error-type", "Currency API error")
        )

    return data


# ============================================================
# PARSER
# ============================================================


def extract_conversion(text: str):
    """
    Understand requests such as:

    50 USD to NGN
    50 dollars to naira
    How much is 50$ in naira?
    100 euros in dollars
    £200 to Nigerian naira
    5000 NGN to USD
    """

    original = text.strip()

    # Normalize common wording
    cleaned = original.lower()

    cleaned = cleaned.replace(",", "")

    cleaned = re.sub(
        r"\bhow much is\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\bwhat is\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\bworth\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\bthe\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Remove question mark
    cleaned = cleaned.replace("?", " ")

    # --------------------------------------------------------
    # Detect amount
    # --------------------------------------------------------

    amount_match = re.search(
        r"(?<![a-zA-Z])\d+(?:\.\d+)?",
        cleaned,
    )

    if not amount_match:
        return None

    amount_text = amount_match.group(0)

    try:
        amount = Decimal(amount_text)
    except InvalidOperation:
        return None

    # --------------------------------------------------------
    # Detect currency using aliases
    # --------------------------------------------------------

    found_currencies = []

    # Sort longest names first so "us dollars" wins over "dollars"
    aliases = sorted(
        CURRENCY_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for alias, code in aliases:

        # Currency symbol
        if len(alias) == 1 and not alias.isalpha():
            if alias in cleaned:
                found_currencies.append(
                    (cleaned.find(alias), alias, code)
                )
            continue

        # Word/code match
        pattern = rf"(?<![a-zA-Z]){re.escape(alias)}(?![a-zA-Z])"

        match = re.search(
            pattern,
            cleaned,
            flags=re.IGNORECASE,
        )

        if match:
            found_currencies.append(
                (match.start(), alias, code)
            )

    # Remove duplicates while preserving positions
    unique = {}

    for position, alias, code in found_currencies:
        if code not in unique:
            unique[code] = position

    currencies = sorted(
        [
            (position, code)
            for code, position in unique.items()
        ],
        key=lambda item: item[0],
    )

    if len(currencies) < 2:
        return None

    # The first detected currency is normally FROM.
    # The second is normally TO.
    source_currency = currencies[0][1]
    target_currency = currencies[1][1]

    return amount, source_currency, target_currency


# ============================================================
# CONVERSION
# ============================================================


def convert_currency(
    amount: Decimal,
    source_currency: str,
    target_currency: str,
):
    data = get_rates(source_currency)

    rates = data.get("rates", {})

    if target_currency not in rates:
        raise ValueError(
            f"Unsupported currency: {target_currency}"
        )

    rate = Decimal(str(rates[target_currency]))

    converted = amount * rate

    return {
        "converted": converted,
        "rate": rate,
        "last_update": data.get(
            "time_last_update_utc",
            "Unknown",
        ),
        "next_update": data.get(
            "time_next_update_utc",
            "Unknown",
        ),
    }


# ============================================================
# RESPONSE
# ============================================================


def build_response(
    amount: Decimal,
    source_currency: str,
    target_currency: str,
    result: dict,
):
    converted = result["converted"]
    rate = result["rate"]
    last_update = result["last_update"]

    source_symbol = currency_symbol(
        source_currency
    )

    target_symbol = currency_symbol(
        target_currency
    )

    amount_text = format_number(amount)
    converted_text = format_number(converted)
    rate_text = format_number(rate)

    return (
        "💱 *Currency Conversion*\n\n"
        f"{source_symbol}{amount_text} "
        f"{source_currency} = "
        f"{target_symbol}{converted_text} "
        f"{target_currency}\n\n"
        f"📊 *Exchange rate:*\n"
        f"1 {source_currency} = "
        f"{target_symbol}{rate_text} "
        f"{target_currency}\n\n"
        f"🕒 *Rate updated:*\n"
        f"{last_update}\n\n"
        "⚠️ This is an indicative exchange rate. "
        "Banks, cards and money-transfer services may "
        "use different rates and fees.\n\n"
        "📡 Rates: ExchangeRate-API"
    )


# ============================================================
# PROCESS REQUEST
# ============================================================


async def process_conversion(
    update: Update,
    text: str,
):
    parsed = extract_conversion(text)

    if not parsed:
        await update.message.reply_text(
            "❌ I couldn't understand that conversion.\n\n"
            "Try:\n"
            "• 50 USD to NGN\n"
            "• 50 dollars to naira\n"
            "• How much is 100 euros in dollars?\n"
            "• £200 to Nigerian naira\n"
            "• 5000 NGN to USD"
        )
        return

    amount, source_currency, target_currency = parsed

    status = await update.message.reply_text(
        "🔎 Checking the latest exchange rate..."
    )

    try:
        result = convert_currency(
            amount,
            source_currency,
            target_currency,
        )

        message = build_response(
            amount,
            source_currency,
            target_currency,
            result,
        )

        await status.edit_text(
            message,
            parse_mode="Markdown",
        )

    except requests.RequestException as error:
        logger.error(
            "Currency API request failed: %s",
            error,
        )

        await status.edit_text(
            "⚠️ I couldn't connect to the currency service "
            "right now. Please try again."
        )

    except Exception as error:
        logger.exception(
            "Conversion error: %s",
            error,
        )

        await status.edit_text(
            "⚠️ I couldn't complete that conversion.\n\n"
            "Please check the currency names and try again."
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
        "I can convert currencies around the world.\n\n"
        "Examples:\n"
        "• 50 USD to NGN\n"
        "• 50 dollars to naira\n"
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
        "💱 *Currency Bot Help*\n\n"
        "Ask me how much one currency is worth in another.\n\n"
        "*Examples:*\n"
        "• 50 USD to NGN\n"
        "• 50 dollars to naira\n"
        "• How much is 100 euros in dollars?\n"
        "• £200 to Nigerian naira\n"
        "• 5000 NGN to USD\n"
        "• 1000 yen to dollars\n\n"
        "🌍 You can use currency names, symbols or ISO codes.\n\n"
        "Examples:\n"
        "USD = dollar\n"
        "NGN = naira\n"
        "EUR = euro\n"
        "GBP = pound\n"
        "JPY = yen",
        parse_mode="Markdown",
    )


# ============================================================
# COMMAND
# ============================================================


async def convert_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text or ""

    # /convert 50 USD to NGN
    text = re.sub(
        r"^/convert(@\w+)?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

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
    print("💱 Currency bot is starting...")

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "convert",
            convert_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("✅ Currency bot is running!")

    application.run_polling()


if __name__ == "__main__":
    main()
