"""ISO-4217-Währungscodes für die Eingabeprüfung.

Enthalten sind die aktiven Landes- und Unionswährungen, das Sonderziehungsrecht
(XDR) und die vier Edelmetall-Codes. Bewusst NICHT enthalten: Fonds-Codes
(CHE, CHW, USN ...), Bond-Einheiten (XBA–XBD), XSU, XUA, der Test-Code XTS und
XXX — für Buchungen und Kursabfragen haben sie keine Bedeutung.

BGN bleibt in der Liste, obwohl Bulgarien am 01.01.2026 den Euro eingeführt
hat: Auszüge für Buchungen bis Ende 2025 tragen den Code noch.

Marktübliche Codes ausserhalb von ISO 4217 (CNH, GBX/GBp, Krypto-Kürzel)
fehlen hier absichtlich. Wer sie zulassen will, entscheidet das am Aufrufort.
"""

ISO_4217_CODES: frozenset[str] = frozenset({
    "AED", "AFN", "ALL", "AMD", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD",
    "CAD", "CDF", "CHF", "CLP", "CNY", "COP", "CRC", "CUP", "CVE", "CZK",
    "DJF", "DKK", "DOP", "DZD",
    "EGP", "ERN", "ETB", "EUR",
    "FJD", "FKP",
    "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD",
    "HKD", "HNL", "HTG", "HUF",
    "IDR", "ILS", "INR", "IQD", "IRR", "ISK",
    "JMD", "JOD", "JPY",
    "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD", "KZT",
    "LAK", "LBP", "LKR", "LRD", "LSL", "LYD",
    "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR",
    "MWK", "MXN", "MYR", "MZN",
    "NAD", "NGN", "NIO", "NOK", "NPR", "NZD",
    "OMR",
    "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG",
    "QAR",
    "RON", "RSD", "RUB", "RWF",
    "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD",
    "SSP", "STN", "SVC", "SYP", "SZL",
    "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS",
    "UAH", "UGX", "USD", "UYU", "UZS",
    "VED", "VES", "VND", "VUV",
    "WST",
    "XAF", "XCD", "XCG", "XOF", "XPF",
    "XDR", "XAU", "XAG", "XPT", "XPD",
    "YER",
    "ZAR", "ZMW", "ZWG",
})
