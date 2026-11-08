"""Mise en forme des nombres et montants selon la langue : 1 234,567 TND (français), 1,234.567 TND (anglais)."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils.translation import get_language, pgettext_lazy

NARROW_NBSP = "\u202f"

# Séparateurs (milliers, décimales) par langue ; le français est la référence.
SEPARATORS = {"fr": (NARROW_NBSP, ","), "en": (",", ".")}


def separators():
    return SEPARATORS.get((get_language() or "fr")[:2], SEPARATORS["fr"])


def format_number(value, decimals=0):
    """1234567.8 -> '1 234 567,8' avec `decimals` chiffres après la virgule."""
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    number = number.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    integer_part, _, decimal_part = f"{abs(number):f}".partition(".")
    groups = []
    while len(integer_part) > 3:
        groups.insert(0, integer_part[-3:])
        integer_part = integer_part[:-3]
    groups.insert(0, integer_part)
    thousands, decimal_mark = separators()
    result = sign + thousands.join(groups)
    if decimals:
        result += decimal_mark + decimal_part.ljust(decimals, "0")[:decimals]
    return result


def format_money(value, currency="TND", decimals=3):
    if value is None or value == "":
        return ""
    return f"{format_number(value, decimals)} {currency}"


def smart_number(value):
    """Nombre sans zéros inutiles : 18432.00 -> '18 432', 2.50 -> '2,5'."""
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError):
        return str(value)
    exponent = number.as_tuple().exponent
    decimals = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return format_number(number, decimals)


# Noms des mois et des jours, traduits (contexte distinct : « mars » abrégé et complet diffèrent en anglais).
MONTH_NAMES = [
    pgettext_lazy("month", "janvier"), pgettext_lazy("month", "février"), pgettext_lazy("month", "mars"),
    pgettext_lazy("month", "avril"), pgettext_lazy("month", "mai"), pgettext_lazy("month", "juin"),
    pgettext_lazy("month", "juillet"), pgettext_lazy("month", "août"), pgettext_lazy("month", "septembre"),
    pgettext_lazy("month", "octobre"), pgettext_lazy("month", "novembre"), pgettext_lazy("month", "décembre"),
]
MONTH_ABBREVIATIONS = [
    pgettext_lazy("abbr. month", "janv."), pgettext_lazy("abbr. month", "févr."), pgettext_lazy("abbr. month", "mars"),
    pgettext_lazy("abbr. month", "avr."), pgettext_lazy("abbr. month", "mai"), pgettext_lazy("abbr. month", "juin"),
    pgettext_lazy("abbr. month", "juil."), pgettext_lazy("abbr. month", "août"), pgettext_lazy("abbr. month", "sept."),
    pgettext_lazy("abbr. month", "oct."), pgettext_lazy("abbr. month", "nov."), pgettext_lazy("abbr. month", "déc."),
]
WEEKDAY_ABBREVIATIONS = [
    pgettext_lazy("abbr. weekday", "Lun"), pgettext_lazy("abbr. weekday", "Mar"), pgettext_lazy("abbr. weekday", "Mer"),
    pgettext_lazy("abbr. weekday", "Jeu"), pgettext_lazy("abbr. weekday", "Ven"), pgettext_lazy("abbr. weekday", "Sam"),
    pgettext_lazy("abbr. weekday", "Dim"),
]


def month_name(month):
    """1 → « janvier » / « January »."""
    return str(MONTH_NAMES[month - 1])


def month_abbr(month):
    """1 → « janv. » / « Jan »."""
    return str(MONTH_ABBREVIATIONS[month - 1])


def month_abbreviations():
    return [str(m) for m in MONTH_ABBREVIATIONS]


def weekday_abbreviations():
    return [str(d) for d in WEEKDAY_ABBREVIATIONS]
