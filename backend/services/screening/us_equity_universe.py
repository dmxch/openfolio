"""Statisches US-Aktienuniversum (S&P Composite 1500) fuer den EPS-Scanner.

Symbol -> {name, sector, index}. Eigenstaendiger Resolver — NICHT an
`resolve_equity_universe()` gekoppelt.

AUTO-GENERIERT von scripts/gen_us_universe.py aus den Wikipedia-
Konstituentenlisten "List of S&P 500/400/600 companies".
Stand-Mitgliederzahl: sp400=400, sp500=503, sp600=600 (gesamt 1503).
Symbol-Normalisierung: Punkt -> Bindestrich (BRK.B -> BRK-B).

Listenpflege (Maintainer-TODO): bei Indexanpassungen (~4x/Jahr) via
scripts/gen_us_universe.py neu generieren.
"""
from __future__ import annotations

UNIVERSE_META: dict[str, dict[str, str]] = {
    "A": {
        "name": "Agilent Technologies",
        "sector": "Health Care",
        "index": "sp500"
    },
    "AA": {
        "name": "Alcoa",
        "sector": "Materials",
        "index": "sp400"
    },
    "AAL": {
        "name": "American Airlines Group",
        "sector": "Industrials",
        "index": "sp400"
    },
    "AAMI": {
        "name": "Acadian Asset Management Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "AAON": {
        "name": "AAON",
        "sector": "Industrials",
        "index": "sp400"
    },
    "AAP": {
        "name": "Advance Auto Parts, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "AAT": {
        "name": "American Assets Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ABBV": {
        "name": "AbbVie",
        "sector": "Health Care",
        "index": "sp500"
    },
    "ABCB": {
        "name": "Ameris Bancorp",
        "sector": "Financials",
        "index": "sp600"
    },
    "ABG": {
        "name": "Asbury Automotive Group",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "ABM": {
        "name": "ABM Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ABNB": {
        "name": "Airbnb",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "ABR": {
        "name": "Arbor Realty Trust",
        "sector": "Financials",
        "index": "sp600"
    },
    "ABT": {
        "name": "Abbott Laboratories",
        "sector": "Health Care",
        "index": "sp500"
    },
    "ACA": {
        "name": "Arcosa, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ACAD": {
        "name": "Acadia Pharmaceuticals",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ACGL": {
        "name": "Arch Capital Group",
        "sector": "Financials",
        "index": "sp500"
    },
    "ACHC": {
        "name": "Acadia Healthcare",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ACI": {
        "name": "Albertsons",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "ACIW": {
        "name": "ACI Worldwide",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ACLS": {
        "name": "Axcelis Technologies, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ACM": {
        "name": "AECOM",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ACMR": {
        "name": "ACM Research, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ACN": {
        "name": "Accenture",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ACT": {
        "name": "Enact Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "ADAM": {
        "name": "Adamas Trust, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ADBE": {
        "name": "Adobe Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ADC": {
        "name": "Agree Realty",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "ADEA": {
        "name": "Adeia, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ADI": {
        "name": "Analog Devices",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ADM": {
        "name": "Archer Daniels Midland",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "ADMA": {
        "name": "ADMA Biologics, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ADNT": {
        "name": "Adient",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "ADP": {
        "name": "Automatic Data Processing",
        "sector": "Industrials",
        "index": "sp500"
    },
    "ADSK": {
        "name": "Autodesk",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ADT": {
        "name": "ADT Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "ADUS": {
        "name": "Addus HomeCare Corp.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AEE": {
        "name": "Ameren",
        "sector": "Utilities",
        "index": "sp500"
    },
    "AEIS": {
        "name": "Advanced Energy",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "AEO": {
        "name": "American Eagle Outfitters",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "AEP": {
        "name": "American Electric Power",
        "sector": "Utilities",
        "index": "sp500"
    },
    "AES": {
        "name": "AES Corporation",
        "sector": "Utilities",
        "index": "sp500"
    },
    "AESI": {
        "name": "Atlas Energy Solutions, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "AFG": {
        "name": "American Financial Group",
        "sector": "Financials",
        "index": "sp400"
    },
    "AFL": {
        "name": "Aflac",
        "sector": "Financials",
        "index": "sp500"
    },
    "AGCO": {
        "name": "AGCO",
        "sector": "Industrials",
        "index": "sp400"
    },
    "AGNT": {
        "name": "eXp World Holdings, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "AGO": {
        "name": "Assured Guaranty Ltd.",
        "sector": "Financials",
        "index": "sp600"
    },
    "AGX": {
        "name": "Argan, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "AGYS": {
        "name": "Agilysys, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "AHCO": {
        "name": "AdaptHealth Corp.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AHR": {
        "name": "American Healthcare REIT",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "AIG": {
        "name": "American International Group",
        "sector": "Financials",
        "index": "sp500"
    },
    "AIN": {
        "name": "Albany International Corp.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "AIR": {
        "name": "AAR CORP.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "AIT": {
        "name": "Applied Industrial Technologies",
        "sector": "Industrials",
        "index": "sp400"
    },
    "AIZ": {
        "name": "Assurant",
        "sector": "Financials",
        "index": "sp500"
    },
    "AJG": {
        "name": "Arthur J. Gallagher & Co.",
        "sector": "Financials",
        "index": "sp500"
    },
    "AKAM": {
        "name": "Akamai Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "AKR": {
        "name": "Acadia Realty Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ALB": {
        "name": "Albemarle Corporation",
        "sector": "Materials",
        "index": "sp500"
    },
    "ALG": {
        "name": "Alamo Group",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ALGM": {
        "name": "Allegro MicroSystems",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "ALGN": {
        "name": "Align Technology",
        "sector": "Health Care",
        "index": "sp500"
    },
    "ALGT": {
        "name": "Allegiant Travel Company",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ALHC": {
        "name": "Alignment Healthcare, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ALK": {
        "name": "Alaska Air Group",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ALKS": {
        "name": "Alkermes plc",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ALL": {
        "name": "Allstate",
        "sector": "Financials",
        "index": "sp500"
    },
    "ALLE": {
        "name": "Allegion",
        "sector": "Industrials",
        "index": "sp500"
    },
    "ALLY": {
        "name": "Ally Financial",
        "sector": "Financials",
        "index": "sp400"
    },
    "ALRM": {
        "name": "Alarm.Com, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "ALV": {
        "name": "Autoliv",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "AM": {
        "name": "Antero Midstream",
        "sector": "Energy",
        "index": "sp400"
    },
    "AMAT": {
        "name": "Applied Materials",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "AMCR": {
        "name": "Amcor",
        "sector": "Materials",
        "index": "sp500"
    },
    "AMD": {
        "name": "Advanced Micro Devices",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "AME": {
        "name": "Ametek",
        "sector": "Industrials",
        "index": "sp500"
    },
    "AMG": {
        "name": "Affiliated Managers Group",
        "sector": "Financials",
        "index": "sp400"
    },
    "AMGN": {
        "name": "Amgen",
        "sector": "Health Care",
        "index": "sp500"
    },
    "AMH": {
        "name": "American Homes 4 Rent",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "AMKR": {
        "name": "Amkor Technology",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "AMN": {
        "name": "Amn Healthcare Services, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AMP": {
        "name": "Ameriprise Financial",
        "sector": "Financials",
        "index": "sp500"
    },
    "AMPH": {
        "name": "Amphstar Pharmaceuticals, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AMR": {
        "name": "Alpha Metallurgical Resources, Inc.",
        "sector": "Materials",
        "index": "sp600"
    },
    "AMRX": {
        "name": "Amneal Pharmaceuticals",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AMSF": {
        "name": "Amerisafe, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "AMT": {
        "name": "American Tower",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "AMTM": {
        "name": "Amentum",
        "sector": "Industrials",
        "index": "sp600"
    },
    "AMZN": {
        "name": "Amazon",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "AN": {
        "name": "AutoNation",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "ANDE": {
        "name": "The Andersons, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "ANET": {
        "name": "Arista Networks",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ANF": {
        "name": "Abercrombie & Fitch",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "ANIP": {
        "name": "ANI Pharmaceuticals, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AON": {
        "name": "Aon plc",
        "sector": "Financials",
        "index": "sp500"
    },
    "AORT": {
        "name": "Artivion",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AOS": {
        "name": "A. O. Smith",
        "sector": "Industrials",
        "index": "sp500"
    },
    "AOSL": {
        "name": "Alpha and Omega Semiconductor, Ltd.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "APA": {
        "name": "APA Corporation",
        "sector": "Energy",
        "index": "sp500"
    },
    "APAM": {
        "name": "Artisan Partners Asset Management, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "APD": {
        "name": "Air Products",
        "sector": "Materials",
        "index": "sp500"
    },
    "APG": {
        "name": "APi Group",
        "sector": "Industrials",
        "index": "sp400"
    },
    "APH": {
        "name": "Amphenol",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "APLE": {
        "name": "Apple Hospitality REIT, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "APO": {
        "name": "Apollo Global Management",
        "sector": "Financials",
        "index": "sp500"
    },
    "APOG": {
        "name": "Apogee Enterprises, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "APP": {
        "name": "AppLovin",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "APPF": {
        "name": "AppFolio",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "APTV": {
        "name": "Aptiv",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "AR": {
        "name": "Antero Resources",
        "sector": "Energy",
        "index": "sp400"
    },
    "ARCB": {
        "name": "ArcBest Corp.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ARE": {
        "name": "Alexandria Real Estate Equities",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "ARES": {
        "name": "Ares Management",
        "sector": "Financials",
        "index": "sp500"
    },
    "ARI": {
        "name": "Apollo Commercial Real Estate Finance",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ARLO": {
        "name": "Arlo Technologies",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ARMK": {
        "name": "Aramark",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "AROC": {
        "name": "Archrock, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "ARR": {
        "name": "Armour Residential REIT",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ARW": {
        "name": "Arrow Electronics",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "ARWR": {
        "name": "Arrowhead Pharmaceuticals",
        "sector": "Health Care",
        "index": "sp400"
    },
    "ASB": {
        "name": "Associated Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "ASH": {
        "name": "Ashland Global",
        "sector": "Materials",
        "index": "sp400"
    },
    "ASO": {
        "name": "Academy Sports + Outdoors",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "ASTE": {
        "name": "Astec Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ASTH": {
        "name": "Astrana Health, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ATEN": {
        "name": "A10 Networks, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ATI": {
        "name": "ATI Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ATMU": {
        "name": "Atmus Filtration Technologies Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ATO": {
        "name": "Atmos Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "ATR": {
        "name": "AptarGroup",
        "sector": "Materials",
        "index": "sp400"
    },
    "AUB": {
        "name": "Atlantic Union Bankshares, Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "AVA": {
        "name": "Avista Corporation",
        "sector": "Utilities",
        "index": "sp600"
    },
    "AVAV": {
        "name": "AeroVironment",
        "sector": "Industrials",
        "index": "sp400"
    },
    "AVB": {
        "name": "AvalonBay Communities",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "AVGO": {
        "name": "Broadcom",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "AVNS": {
        "name": "Avanos Medical, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AVNT": {
        "name": "Avient",
        "sector": "Materials",
        "index": "sp400"
    },
    "AVT": {
        "name": "Avnet",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "AVTR": {
        "name": "Avantor",
        "sector": "Health Care",
        "index": "sp400"
    },
    "AVY": {
        "name": "Avery Dennison",
        "sector": "Materials",
        "index": "sp500"
    },
    "AWI": {
        "name": "Armstrong World Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "AWK": {
        "name": "American Water Works",
        "sector": "Utilities",
        "index": "sp500"
    },
    "AWR": {
        "name": "American States Water Company",
        "sector": "Utilities",
        "index": "sp600"
    },
    "AX": {
        "name": "Axos Financial, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "AXON": {
        "name": "Axon Enterprise",
        "sector": "Industrials",
        "index": "sp500"
    },
    "AXP": {
        "name": "American Express",
        "sector": "Financials",
        "index": "sp500"
    },
    "AXTA": {
        "name": "Axalta",
        "sector": "Materials",
        "index": "sp400"
    },
    "AYI": {
        "name": "Acuity Brands",
        "sector": "Industrials",
        "index": "sp400"
    },
    "AZO": {
        "name": "AutoZone",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "AZTA": {
        "name": "Azenta, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "AZZ": {
        "name": "AZZ, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "BA": {
        "name": "Boeing",
        "sector": "Industrials",
        "index": "sp500"
    },
    "BAC": {
        "name": "Bank of America",
        "sector": "Financials",
        "index": "sp500"
    },
    "BAH": {
        "name": "Booz Allen Hamilton",
        "sector": "Industrials",
        "index": "sp400"
    },
    "BALL": {
        "name": "Ball Corporation",
        "sector": "Materials",
        "index": "sp500"
    },
    "BANC": {
        "name": "Banc Of California, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "BANF": {
        "name": "Bancfirst Corp",
        "sector": "Financials",
        "index": "sp600"
    },
    "BANR": {
        "name": "Banner Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "BAX": {
        "name": "Baxter International",
        "sector": "Health Care",
        "index": "sp500"
    },
    "BBT": {
        "name": "Beacon Financial Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "BBWI": {
        "name": "Bath & Body Works, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "BBY": {
        "name": "Best Buy",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "BC": {
        "name": "Brunswick",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "BCC": {
        "name": "Boise Cascade",
        "sector": "Industrials",
        "index": "sp600"
    },
    "BCO": {
        "name": "Brink's",
        "sector": "Industrials",
        "index": "sp400"
    },
    "BCPC": {
        "name": "Balchem Corporation",
        "sector": "Materials",
        "index": "sp600"
    },
    "BDC": {
        "name": "Belden Inc.",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "BDX": {
        "name": "Becton Dickinson",
        "sector": "Health Care",
        "index": "sp500"
    },
    "BEN": {
        "name": "Franklin Resources",
        "sector": "Financials",
        "index": "sp500"
    },
    "BF-B": {
        "name": "Brown–Forman",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "BFAM": {
        "name": "Bright Horizons Family Solutions Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "BFH": {
        "name": "Bread Financial Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "BFS": {
        "name": "Saul Centers, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "BG": {
        "name": "Bunge Global",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "BGC": {
        "name": "BGC Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "BHE": {
        "name": "Benchmark Electronics, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "BHF": {
        "name": "Brighthouse Financial",
        "sector": "Financials",
        "index": "sp400"
    },
    "BIIB": {
        "name": "Biogen",
        "sector": "Health Care",
        "index": "sp500"
    },
    "BILL": {
        "name": "Bill Holdings",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "BIO": {
        "name": "Bio-Rad Laboratories",
        "sector": "Health Care",
        "index": "sp400"
    },
    "BJ": {
        "name": "BJ's Wholesale Club",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "BJRI": {
        "name": "BJ's Restaurants, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "BKE": {
        "name": "The Buckle, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "BKH": {
        "name": "Black Hills Corporation",
        "sector": "Utilities",
        "index": "sp400"
    },
    "BKNG": {
        "name": "Booking Holdings",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "BKR": {
        "name": "Baker Hughes",
        "sector": "Energy",
        "index": "sp500"
    },
    "BKU": {
        "name": "BankUnited, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "BL": {
        "name": "BlackLine Systems, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "BLD": {
        "name": "TopBuild Corp.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "BLDR": {
        "name": "Builders FirstSource",
        "sector": "Industrials",
        "index": "sp500"
    },
    "BLFS": {
        "name": "BioLife Solutions, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "BLK": {
        "name": "BlackRock",
        "sector": "Financials",
        "index": "sp500"
    },
    "BMI": {
        "name": "Badger Meter, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "BMRN": {
        "name": "BioMarin Pharmaceutical",
        "sector": "Health Care",
        "index": "sp400"
    },
    "BMY": {
        "name": "Bristol Myers Squibb",
        "sector": "Health Care",
        "index": "sp500"
    },
    "BNL": {
        "name": "Broadstone Net Lease, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "BNY": {
        "name": "BNY Mellon",
        "sector": "Financials",
        "index": "sp500"
    },
    "BOH": {
        "name": "Bank of Hawaii",
        "sector": "Financials",
        "index": "sp600"
    },
    "BOOT": {
        "name": "Boot Barn Holdings, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "BOX": {
        "name": "Box, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "BR": {
        "name": "Broadridge Financial Solutions",
        "sector": "Industrials",
        "index": "sp500"
    },
    "BRC": {
        "name": "Brady Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "BRK-B": {
        "name": "Berkshire Hathaway",
        "sector": "Financials",
        "index": "sp500"
    },
    "BRKR": {
        "name": "Bruker",
        "sector": "Health Care",
        "index": "sp400"
    },
    "BRO": {
        "name": "Brown & Brown",
        "sector": "Financials",
        "index": "sp500"
    },
    "BROS": {
        "name": "Dutch Bros Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "BRX": {
        "name": "Brixmor Property Group",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "BSX": {
        "name": "Boston Scientific",
        "sector": "Health Care",
        "index": "sp500"
    },
    "BSY": {
        "name": "Bentley Systems",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "BTSG": {
        "name": "BrightSpring Health Services, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "BTU": {
        "name": "Peabody Energy, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "BURL": {
        "name": "Burlington Stores",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "BWA": {
        "name": "BorgWarner",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "BWXT": {
        "name": "BWX Technologies",
        "sector": "Industrials",
        "index": "sp400"
    },
    "BX": {
        "name": "Blackstone Inc.",
        "sector": "Financials",
        "index": "sp500"
    },
    "BXMT": {
        "name": "Blackstone Mortgage Trust, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "BXP": {
        "name": "BXP, Inc.",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "BYD": {
        "name": "Boyd Gaming",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "C": {
        "name": "Citigroup",
        "sector": "Financials",
        "index": "sp500"
    },
    "CABO": {
        "name": "Cable One",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "CACI": {
        "name": "CACI International",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CAG": {
        "name": "Conagra Brands",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "CAH": {
        "name": "Cardinal Health",
        "sector": "Health Care",
        "index": "sp500"
    },
    "CAKE": {
        "name": "The Cheesecake Factory, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CALM": {
        "name": "Cal-Maine Foods, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "CALX": {
        "name": "Calix",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "CALY": {
        "name": "Callaway Golf Company",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CAR": {
        "name": "Avis Budget Group",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CARG": {
        "name": "CarGurus",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "CARR": {
        "name": "Carrier Global",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CART": {
        "name": "Maplebear Inc.",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "CASH": {
        "name": "Pathward Financial, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "CASY": {
        "name": "Casey's",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "CAT": {
        "name": "Caterpillar Inc.",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CATY": {
        "name": "Cathay General Bancorp",
        "sector": "Financials",
        "index": "sp600"
    },
    "CAVA": {
        "name": "Cava Group",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CB": {
        "name": "Chubb Limited",
        "sector": "Financials",
        "index": "sp500"
    },
    "CBOE": {
        "name": "Cboe Global Markets",
        "sector": "Financials",
        "index": "sp500"
    },
    "CBRE": {
        "name": "CBRE Group",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "CBRL": {
        "name": "Cracker Barrel",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CBSH": {
        "name": "Commerce Bancshares",
        "sector": "Financials",
        "index": "sp400"
    },
    "CBT": {
        "name": "Cabot Corp",
        "sector": "Materials",
        "index": "sp400"
    },
    "CBU": {
        "name": "Community Bank System, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "CC": {
        "name": "Chemours",
        "sector": "Materials",
        "index": "sp600"
    },
    "CCI": {
        "name": "Crown Castle",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "CCK": {
        "name": "Crown Holdings",
        "sector": "Materials",
        "index": "sp400"
    },
    "CCL": {
        "name": "Carnival Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "CCOI": {
        "name": "Cogent Communications Holdings, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "CCS": {
        "name": "Century Communities, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CDE": {
        "name": "Coeur Mining",
        "sector": "Materials",
        "index": "sp400"
    },
    "CDNS": {
        "name": "Cadence Design Systems",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CDP": {
        "name": "COPT Defense Properties",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "CDW": {
        "name": "CDW Corporation",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CE": {
        "name": "Celanese",
        "sector": "Materials",
        "index": "sp600"
    },
    "CEG": {
        "name": "Constellation Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "CELH": {
        "name": "Celsius Holdings",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "CENT": {
        "name": "Central Garden & Pet Company",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "CENTA": {
        "name": "Central Garden & Pet Company (Class A)",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "CENX": {
        "name": "Century Aluminum Company",
        "sector": "Materials",
        "index": "sp600"
    },
    "CERT": {
        "name": "Certara, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "CF": {
        "name": "CF Industries",
        "sector": "Materials",
        "index": "sp500"
    },
    "CFFN": {
        "name": "Capitol Federal Savings Bank",
        "sector": "Financials",
        "index": "sp600"
    },
    "CFG": {
        "name": "Citizens Financial Group",
        "sector": "Financials",
        "index": "sp500"
    },
    "CFR": {
        "name": "Frost Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "CG": {
        "name": "Carlyle Group (The)",
        "sector": "Financials",
        "index": "sp400"
    },
    "CGNX": {
        "name": "Cognex",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "CHCO": {
        "name": "City Holding Company",
        "sector": "Financials",
        "index": "sp600"
    },
    "CHD": {
        "name": "Church & Dwight",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "CHDN": {
        "name": "Churchill Downs Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CHE": {
        "name": "Chemed Corp.",
        "sector": "Health Care",
        "index": "sp400"
    },
    "CHEF": {
        "name": "Chefs' Warehouse, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "CHH": {
        "name": "Choice Hotels",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CHRD": {
        "name": "Chord Energy",
        "sector": "Energy",
        "index": "sp400"
    },
    "CHRW": {
        "name": "C.H. Robinson",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CHTR": {
        "name": "Charter Communications",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "CHWY": {
        "name": "Chewy",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CI": {
        "name": "Cigna",
        "sector": "Health Care",
        "index": "sp500"
    },
    "CIEN": {
        "name": "Ciena",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CINF": {
        "name": "Cincinnati Financial",
        "sector": "Financials",
        "index": "sp500"
    },
    "CL": {
        "name": "Colgate-Palmolive",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "CLB": {
        "name": "Core Laboratories",
        "sector": "Energy",
        "index": "sp600"
    },
    "CLF": {
        "name": "Cleveland-Cliffs",
        "sector": "Materials",
        "index": "sp400"
    },
    "CLH": {
        "name": "Clean Harbors",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CLSK": {
        "name": "CleanSpark, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "CLX": {
        "name": "Clorox",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "CMC": {
        "name": "Commercial Metals",
        "sector": "Materials",
        "index": "sp400"
    },
    "CMCSA": {
        "name": "Comcast",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "CME": {
        "name": "CME Group",
        "sector": "Financials",
        "index": "sp500"
    },
    "CMG": {
        "name": "Chipotle Mexican Grill",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "CMI": {
        "name": "Cummins",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CMS": {
        "name": "CMS Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "CNC": {
        "name": "Centene Corporation",
        "sector": "Health Care",
        "index": "sp500"
    },
    "CNH": {
        "name": "CNH Industrial",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CNK": {
        "name": "Cinemark Holdings, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "CNM": {
        "name": "Core & Main",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CNMD": {
        "name": "CONMED Corporation",
        "sector": "Health Care",
        "index": "sp600"
    },
    "CNO": {
        "name": "CNO Financial Group",
        "sector": "Financials",
        "index": "sp400"
    },
    "CNP": {
        "name": "CenterPoint Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "CNR": {
        "name": "Core Natural Resources, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "CNS": {
        "name": "Cohen & Steers, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "CNX": {
        "name": "CNX Resources",
        "sector": "Energy",
        "index": "sp400"
    },
    "CNXN": {
        "name": "PC Connection, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "COCO": {
        "name": "The Vita Coco Company",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "COF": {
        "name": "Capital One",
        "sector": "Financials",
        "index": "sp500"
    },
    "COHR": {
        "name": "Coherent Corp.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "COHU": {
        "name": "Cohu, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "COIN": {
        "name": "Coinbase",
        "sector": "Financials",
        "index": "sp500"
    },
    "COKE": {
        "name": "Coca-Cola Consolidated",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "COLB": {
        "name": "Columbia Banking System",
        "sector": "Financials",
        "index": "sp400"
    },
    "COLL": {
        "name": "Collegium Pharmaceutical, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "COLM": {
        "name": "Columbia Sportswear",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CON": {
        "name": "Concentra Group Holdings Parent, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "COO": {
        "name": "Cooper Companies (The)",
        "sector": "Health Care",
        "index": "sp500"
    },
    "COP": {
        "name": "ConocoPhillips",
        "sector": "Energy",
        "index": "sp500"
    },
    "COR": {
        "name": "Cencora",
        "sector": "Health Care",
        "index": "sp500"
    },
    "CORT": {
        "name": "Corcept Therapeutics Incorporated",
        "sector": "Health Care",
        "index": "sp600"
    },
    "COST": {
        "name": "Costco",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "CPAY": {
        "name": "Corpay",
        "sector": "Financials",
        "index": "sp500"
    },
    "CPF": {
        "name": "Central Pacific Financial Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "CPK": {
        "name": "Chesapeake Utilities Corp.",
        "sector": "Utilities",
        "index": "sp600"
    },
    "CPRI": {
        "name": "Capri Holdings",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CPRT": {
        "name": "Copart",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CPRX": {
        "name": "Catalyst Pharmaceuticals Partners, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "CPT": {
        "name": "Camden Property Trust",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "CR": {
        "name": "Crane",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CRBG": {
        "name": "Corebridge Financial",
        "sector": "Financials",
        "index": "sp400"
    },
    "CRC": {
        "name": "California Resources Corporation",
        "sector": "Energy",
        "index": "sp600"
    },
    "CRGY": {
        "name": "Crescent Energy Company",
        "sector": "Energy",
        "index": "sp600"
    },
    "CRH": {
        "name": "CRH plc",
        "sector": "Materials",
        "index": "sp500"
    },
    "CRI": {
        "name": "Carter's, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CRK": {
        "name": "Comstock Resources, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "CRL": {
        "name": "Charles River Laboratories",
        "sector": "Health Care",
        "index": "sp500"
    },
    "CRM": {
        "name": "Salesforce",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CROX": {
        "name": "Crocs",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "CRS": {
        "name": "Carpenter Technology",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CRSR": {
        "name": "Corsair Gaming",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "CRUS": {
        "name": "Cirrus Logic",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "CRVL": {
        "name": "CorVel Corporation",
        "sector": "Health Care",
        "index": "sp600"
    },
    "CRWD": {
        "name": "CrowdStrike",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CSCO": {
        "name": "Cisco",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CSGP": {
        "name": "CoStar Group",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "CSL": {
        "name": "Carlisle Companies",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CSR": {
        "name": "Centerspace Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "CSW": {
        "name": "CSW Industrials, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "CSX": {
        "name": "CSX Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CTAS": {
        "name": "Cintas",
        "sector": "Industrials",
        "index": "sp500"
    },
    "CTKB": {
        "name": "Cytek Biosciences, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "CTRE": {
        "name": "CareTrust REIT",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "CTS": {
        "name": "CTS Corporation",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "CTSH": {
        "name": "Cognizant",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "CTVA": {
        "name": "Corteva",
        "sector": "Materials",
        "index": "sp500"
    },
    "CUBE": {
        "name": "CubeSmart",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "CUBI": {
        "name": "Customers Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "CURB": {
        "name": "Curbline Properties Corp.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "CUZ": {
        "name": "Cousins Properties",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "CVBF": {
        "name": "CVB Financial Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "CVCO": {
        "name": "Cavco Industries, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CVI": {
        "name": "CVR Energy, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "CVLT": {
        "name": "CommVault Systems",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "CVNA": {
        "name": "Carvana",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "CVS": {
        "name": "CVS Health",
        "sector": "Health Care",
        "index": "sp500"
    },
    "CVSA": {
        "name": "Covista Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "CVX": {
        "name": "Chevron Corporation",
        "sector": "Energy",
        "index": "sp500"
    },
    "CW": {
        "name": "Curtiss-Wright",
        "sector": "Industrials",
        "index": "sp400"
    },
    "CWEN": {
        "name": "Clearway Energy, Inc. (Class C)",
        "sector": "Utilities",
        "index": "sp600"
    },
    "CWEN-A": {
        "name": "Clearway Energy, Inc. (Class A)",
        "sector": "Utilities",
        "index": "sp600"
    },
    "CWK": {
        "name": "Cushman & Wakefield plc",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "CWST": {
        "name": "Casella Waste Systems, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "CWT": {
        "name": "California Water Service Group",
        "sector": "Utilities",
        "index": "sp600"
    },
    "CXM": {
        "name": "Sprinklr, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "CXT": {
        "name": "Crane NXT",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "CXW": {
        "name": "CoreCivic",
        "sector": "Industrials",
        "index": "sp600"
    },
    "CYTK": {
        "name": "Cytokinetics",
        "sector": "Health Care",
        "index": "sp400"
    },
    "CZR": {
        "name": "Caesars Entertainment",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "D": {
        "name": "Dominion Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "DAL": {
        "name": "Delta Air Lines",
        "sector": "Industrials",
        "index": "sp500"
    },
    "DAN": {
        "name": "Dana Incorporated",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "DAR": {
        "name": "Darling Ingredients",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "DASH": {
        "name": "DoorDash",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "DAVE": {
        "name": "Dave, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "DBD": {
        "name": "Diebold Nixdorf",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "DBX": {
        "name": "Dropbox",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "DCH": {
        "name": "Dauch Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "DCI": {
        "name": "Donaldson Company",
        "sector": "Industrials",
        "index": "sp400"
    },
    "DCOM": {
        "name": "Dime Community Bancshares, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "DD": {
        "name": "DuPont",
        "sector": "Materials",
        "index": "sp500"
    },
    "DDOG": {
        "name": "Datadog",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "DE": {
        "name": "Deere & Company",
        "sector": "Industrials",
        "index": "sp500"
    },
    "DEA": {
        "name": "Easterly Government Properties, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "DECK": {
        "name": "Deckers Brands",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "DEI": {
        "name": "Douglas Emmett",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "DELL": {
        "name": "Dell Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "DFH": {
        "name": "Dream Finders Homes, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "DFIN": {
        "name": "Donnelley Financial Solutions, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "DG": {
        "name": "Dollar General",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "DGII": {
        "name": "Digi International Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "DGX": {
        "name": "Quest Diagnostics",
        "sector": "Health Care",
        "index": "sp500"
    },
    "DHI": {
        "name": "D. R. Horton",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "DHR": {
        "name": "Danaher Corporation",
        "sector": "Health Care",
        "index": "sp500"
    },
    "DINO": {
        "name": "HF Sinclair",
        "sector": "Energy",
        "index": "sp400"
    },
    "DIOD": {
        "name": "Diodes Incorporated",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "DIS": {
        "name": "Walt Disney Company (The)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "DKS": {
        "name": "Dick's Sporting Goods",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "DLB": {
        "name": "Dolby",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "DLR": {
        "name": "Digital Realty",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "DLTR": {
        "name": "Dollar Tree",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "DLX": {
        "name": "Deluxe Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "DNOW": {
        "name": "NOW Inc",
        "sector": "Industrials",
        "index": "sp600"
    },
    "DOC": {
        "name": "Healthpeak Properties",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "DOCN": {
        "name": "DigitalOcean",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "DOCS": {
        "name": "Doximity",
        "sector": "Health Care",
        "index": "sp400"
    },
    "DOCU": {
        "name": "Docusign",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "DORM": {
        "name": "Dorman Products, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "DOV": {
        "name": "Dover Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "DOW": {
        "name": "Dow Inc.",
        "sector": "Materials",
        "index": "sp500"
    },
    "DPZ": {
        "name": "Domino's",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "DRH": {
        "name": "DiamondRock Hospitality Company",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "DRI": {
        "name": "Darden Restaurants",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "DT": {
        "name": "Dynatrace",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "DTE": {
        "name": "DTE Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "DTM": {
        "name": "DT Midstream",
        "sector": "Energy",
        "index": "sp400"
    },
    "DUK": {
        "name": "Duke Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "DUOL": {
        "name": "Duolingo",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "DV": {
        "name": "DoubleVerify Holdings, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "DVA": {
        "name": "DaVita",
        "sector": "Health Care",
        "index": "sp500"
    },
    "DVN": {
        "name": "Devon Energy",
        "sector": "Energy",
        "index": "sp500"
    },
    "DXC": {
        "name": "DXC Technology",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "DXCM": {
        "name": "Dexcom",
        "sector": "Health Care",
        "index": "sp500"
    },
    "DXPE": {
        "name": "DXP Enterprises, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "DY": {
        "name": "Dycom Industries",
        "sector": "Industrials",
        "index": "sp400"
    },
    "EA": {
        "name": "Electronic Arts",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "EAT": {
        "name": "Brinker International, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "EBAY": {
        "name": "eBay Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "ECG": {
        "name": "Everus Construction Group, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ECL": {
        "name": "Ecolab",
        "sector": "Materials",
        "index": "sp500"
    },
    "ECPG": {
        "name": "Encore Capital Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "ED": {
        "name": "Consolidated Edison",
        "sector": "Utilities",
        "index": "sp500"
    },
    "EEFT": {
        "name": "Euronet Worldwide",
        "sector": "Financials",
        "index": "sp400"
    },
    "EFC": {
        "name": "Ellington Financial, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "EFOR": {
        "name": "Everforth Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "EFX": {
        "name": "Equifax",
        "sector": "Industrials",
        "index": "sp500"
    },
    "EG": {
        "name": "Everest Group",
        "sector": "Financials",
        "index": "sp500"
    },
    "EGBN": {
        "name": "Eagle Bancorp Inc",
        "sector": "Financials",
        "index": "sp600"
    },
    "EGP": {
        "name": "EastGroup Properties",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "EHC": {
        "name": "Encompass Health",
        "sector": "Health Care",
        "index": "sp400"
    },
    "EIG": {
        "name": "Employers Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "EIX": {
        "name": "Edison International",
        "sector": "Utilities",
        "index": "sp500"
    },
    "EL": {
        "name": "Estée Lauder Companies (The)",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "ELAN": {
        "name": "Elanco",
        "sector": "Health Care",
        "index": "sp400"
    },
    "ELF": {
        "name": "e.l.f. Beauty",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "ELS": {
        "name": "Equity Lifestyle Properties",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "ELV": {
        "name": "Elevance Health",
        "sector": "Health Care",
        "index": "sp500"
    },
    "EMBC": {
        "name": "Embecta Corp.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "EME": {
        "name": "Emcor",
        "sector": "Industrials",
        "index": "sp500"
    },
    "EMN": {
        "name": "Eastman Chemical Company",
        "sector": "Materials",
        "index": "sp600"
    },
    "EMR": {
        "name": "Emerson Electric",
        "sector": "Industrials",
        "index": "sp500"
    },
    "ENOV": {
        "name": "Enovis",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ENPH": {
        "name": "Enphase Energy",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ENR": {
        "name": "Energizer",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "ENS": {
        "name": "EnerSys",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ENSG": {
        "name": "Ensign Group",
        "sector": "Health Care",
        "index": "sp400"
    },
    "ENTG": {
        "name": "Entegris",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "ENVA": {
        "name": "Enova International, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "EOG": {
        "name": "EOG Resources",
        "sector": "Energy",
        "index": "sp500"
    },
    "EPAC": {
        "name": "Enerpac Tool Group",
        "sector": "Industrials",
        "index": "sp600"
    },
    "EPAM": {
        "name": "EPAM Systems",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "EPC": {
        "name": "Edgewell Personal Care",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "EPR": {
        "name": "EPR Properties",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "EPRT": {
        "name": "Essential Properties Realty Trust, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "EQH": {
        "name": "Equitable Holdings",
        "sector": "Financials",
        "index": "sp400"
    },
    "EQIX": {
        "name": "Equinix",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "EQR": {
        "name": "Equity Residential",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "EQT": {
        "name": "EQT Corporation",
        "sector": "Energy",
        "index": "sp500"
    },
    "ERIE": {
        "name": "Erie Indemnity",
        "sector": "Financials",
        "index": "sp500"
    },
    "ES": {
        "name": "Eversource Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "ESAB": {
        "name": "ESAB",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ESE": {
        "name": "ESCO Technologies Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ESI": {
        "name": "Element Solutions",
        "sector": "Materials",
        "index": "sp600"
    },
    "ESNT": {
        "name": "Essent Group Ltd.",
        "sector": "Financials",
        "index": "sp400"
    },
    "ESS": {
        "name": "Essex Property Trust",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "ETD": {
        "name": "Ethan Allen Interiors, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "ETN": {
        "name": "Eaton Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "ETR": {
        "name": "Entergy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "ETSY": {
        "name": "Etsy",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "EVR": {
        "name": "Evercore",
        "sector": "Financials",
        "index": "sp400"
    },
    "EVRG": {
        "name": "Evergy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "EVTC": {
        "name": "EVERTEC, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "EW": {
        "name": "Edwards Lifesciences",
        "sector": "Health Care",
        "index": "sp500"
    },
    "EWBC": {
        "name": "East West Bancorp",
        "sector": "Financials",
        "index": "sp400"
    },
    "EXC": {
        "name": "Exelon",
        "sector": "Utilities",
        "index": "sp500"
    },
    "EXE": {
        "name": "Expand Energy",
        "sector": "Energy",
        "index": "sp500"
    },
    "EXEL": {
        "name": "Exelixis",
        "sector": "Health Care",
        "index": "sp400"
    },
    "EXLS": {
        "name": "EXL Service",
        "sector": "Industrials",
        "index": "sp400"
    },
    "EXP": {
        "name": "Eagle Materials",
        "sector": "Materials",
        "index": "sp400"
    },
    "EXPD": {
        "name": "Expeditors International",
        "sector": "Industrials",
        "index": "sp500"
    },
    "EXPE": {
        "name": "Expedia Group",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "EXPO": {
        "name": "Exponent, Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "EXR": {
        "name": "Extra Space Storage",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "EXTR": {
        "name": "Extreme Networks, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "EYE": {
        "name": "National Vision Holdings",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "EZPW": {
        "name": "EZCORP, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "F": {
        "name": "Ford Motor Company",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "FAF": {
        "name": "First American Financial Corporation",
        "sector": "Financials",
        "index": "sp400"
    },
    "FANG": {
        "name": "Diamondback Energy",
        "sector": "Energy",
        "index": "sp500"
    },
    "FAST": {
        "name": "Fastenal",
        "sector": "Industrials",
        "index": "sp500"
    },
    "FBIN": {
        "name": "Fortune Brands Innovations",
        "sector": "Industrials",
        "index": "sp400"
    },
    "FBK": {
        "name": "FB Financial Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "FBNC": {
        "name": "First Bancorp (Southern Pines NC)",
        "sector": "Financials",
        "index": "sp600"
    },
    "FBP": {
        "name": "First BanCorp (Puerto Rico)",
        "sector": "Financials",
        "index": "sp600"
    },
    "FBRT": {
        "name": "Franklin BSP Realty Trust, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "FCF": {
        "name": "First Commonwealth Financial, Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "FCFS": {
        "name": "FirstCash",
        "sector": "Financials",
        "index": "sp400"
    },
    "FCN": {
        "name": "FTI Consulting",
        "sector": "Industrials",
        "index": "sp400"
    },
    "FCPT": {
        "name": "Four Corners Property Trust, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "FCX": {
        "name": "Freeport-McMoRan",
        "sector": "Materials",
        "index": "sp500"
    },
    "FDP": {
        "name": "Fresh Del Monte Produce, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "FDS": {
        "name": "FactSet",
        "sector": "Financials",
        "index": "sp500"
    },
    "FDX": {
        "name": "FedEx",
        "sector": "Industrials",
        "index": "sp500"
    },
    "FDXF": {
        "name": "FedEx Freight",
        "sector": "Industrials",
        "index": "sp500"
    },
    "FE": {
        "name": "FirstEnergy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "FELE": {
        "name": "Franklin Electric",
        "sector": "Industrials",
        "index": "sp600"
    },
    "FFBC": {
        "name": "First Financial Bancorp",
        "sector": "Financials",
        "index": "sp600"
    },
    "FFIN": {
        "name": "First Financial Bankshares",
        "sector": "Financials",
        "index": "sp400"
    },
    "FFIV": {
        "name": "F5, Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "FG": {
        "name": "F&G Annuities & Life, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "FHB": {
        "name": "First Hawaiian, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "FHI": {
        "name": "Federated Hermes",
        "sector": "Financials",
        "index": "sp400"
    },
    "FHN": {
        "name": "First Horizon",
        "sector": "Financials",
        "index": "sp400"
    },
    "FIBK": {
        "name": "First Interstate BancSystem, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "FICO": {
        "name": "Fair Isaac",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "FIS": {
        "name": "Fidelity National Information Services",
        "sector": "Financials",
        "index": "sp500"
    },
    "FISV": {
        "name": "Fiserv",
        "sector": "Financials",
        "index": "sp500"
    },
    "FITB": {
        "name": "Fifth Third Bancorp",
        "sector": "Financials",
        "index": "sp500"
    },
    "FIVE": {
        "name": "Five Below",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "FIX": {
        "name": "Comfort Systems USA",
        "sector": "Industrials",
        "index": "sp500"
    },
    "FIZZ": {
        "name": "National Beverage Corp.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "FLEX": {
        "name": "Flex Ltd.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "FLG": {
        "name": "Flagstar Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "FLO": {
        "name": "Flowers Foods",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "FLR": {
        "name": "Fluor",
        "sector": "Industrials",
        "index": "sp400"
    },
    "FLS": {
        "name": "Flowserve",
        "sector": "Industrials",
        "index": "sp400"
    },
    "FMC": {
        "name": "FMC Corporation",
        "sector": "Materials",
        "index": "sp600"
    },
    "FN": {
        "name": "Fabrinet",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "FNB": {
        "name": "FNB Corporation",
        "sector": "Financials",
        "index": "sp400"
    },
    "FND": {
        "name": "Floor & Decor",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "FNF": {
        "name": "Fidelity National Financial",
        "sector": "Financials",
        "index": "sp400"
    },
    "FORM": {
        "name": "FormFactor, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "FOUR": {
        "name": "Shift4",
        "sector": "Financials",
        "index": "sp400"
    },
    "FOX": {
        "name": "Fox Corporation (Class B)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "FOXA": {
        "name": "Fox Corporation (Class A)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "FOXF": {
        "name": "Fox Factory",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "FR": {
        "name": "First Industrial Realty Trust",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "FRPT": {
        "name": "Freshpet",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "FRT": {
        "name": "Federal Realty Investment Trust",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "FSLR": {
        "name": "First Solar",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "FSS": {
        "name": "Federal Signal Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "FTDR": {
        "name": "Frontdoor, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "FTI": {
        "name": "TechnipFMC",
        "sector": "Energy",
        "index": "sp400"
    },
    "FTNT": {
        "name": "Fortinet",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "FTRE": {
        "name": "Fortrea",
        "sector": "Health Care",
        "index": "sp600"
    },
    "FTV": {
        "name": "Fortive",
        "sector": "Industrials",
        "index": "sp500"
    },
    "FUL": {
        "name": "H.B. Fuller Company",
        "sector": "Materials",
        "index": "sp600"
    },
    "FULT": {
        "name": "Fulton Financial Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "FUN": {
        "name": "Six Flags",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "FWRD": {
        "name": "Forward Air Corp.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "G": {
        "name": "Genpact",
        "sector": "Industrials",
        "index": "sp400"
    },
    "GAP": {
        "name": "Gap Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "GATX": {
        "name": "GATX",
        "sector": "Industrials",
        "index": "sp400"
    },
    "GBCI": {
        "name": "Glacier Bancorp",
        "sector": "Financials",
        "index": "sp400"
    },
    "GBX": {
        "name": "The Greenbrier Companies, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "GD": {
        "name": "General Dynamics",
        "sector": "Industrials",
        "index": "sp500"
    },
    "GDDY": {
        "name": "GoDaddy",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "GDYN": {
        "name": "Grid Dynamics Holdings, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "GE": {
        "name": "GE Aerospace",
        "sector": "Industrials",
        "index": "sp500"
    },
    "GEF": {
        "name": "Greif, Inc.",
        "sector": "Materials",
        "index": "sp400"
    },
    "GEHC": {
        "name": "GE HealthCare",
        "sector": "Health Care",
        "index": "sp500"
    },
    "GEN": {
        "name": "Gen Digital",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "GEO": {
        "name": "GEO Group, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "GEV": {
        "name": "GE Vernova",
        "sector": "Industrials",
        "index": "sp500"
    },
    "GFF": {
        "name": "Griffon Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "GGG": {
        "name": "Graco Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "GHC": {
        "name": "Graham Holdings",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "GIII": {
        "name": "G-III Apparel Group, Ltd.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "GILD": {
        "name": "Gilead Sciences",
        "sector": "Health Care",
        "index": "sp500"
    },
    "GIS": {
        "name": "General Mills",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "GKOS": {
        "name": "Glaukos Corp.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "GL": {
        "name": "Globe Life",
        "sector": "Financials",
        "index": "sp500"
    },
    "GLPI": {
        "name": "Gaming and Leisure Properties",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "GLW": {
        "name": "Corning Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "GM": {
        "name": "General Motors",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "GME": {
        "name": "GameStop",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "GMED": {
        "name": "Globus Medical",
        "sector": "Health Care",
        "index": "sp400"
    },
    "GNL": {
        "name": "Global Net Lease, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "GNRC": {
        "name": "Generac",
        "sector": "Industrials",
        "index": "sp500"
    },
    "GNTX": {
        "name": "Gentex",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "GNW": {
        "name": "Genworth Financial, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "GO": {
        "name": "Grocery Outlet",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "GOGO": {
        "name": "Gogo, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "GOLF": {
        "name": "Acushnet Company",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "GOOG": {
        "name": "Alphabet Inc. (Class C)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "GOOGL": {
        "name": "Alphabet Inc. (Class A)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "GPC": {
        "name": "Genuine Parts Company",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "GPI": {
        "name": "Group 1 Automotive, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "GPK": {
        "name": "Graphic Packaging",
        "sector": "Materials",
        "index": "sp400"
    },
    "GPN": {
        "name": "Global Payments",
        "sector": "Financials",
        "index": "sp500"
    },
    "GRBK": {
        "name": "Green Brick Partners, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "GRMN": {
        "name": "Garmin",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "GS": {
        "name": "Goldman Sachs",
        "sector": "Financials",
        "index": "sp500"
    },
    "GSHD": {
        "name": "Goosehead Insurance, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "GT": {
        "name": "Goodyear Tire & Rubber",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "GTES": {
        "name": "Gates Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "GTLS": {
        "name": "Chart Industries",
        "sector": "Industrials",
        "index": "sp400"
    },
    "GTM": {
        "name": "ZoomInfo",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "GTY": {
        "name": "Getty Realty Corp.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "GVA": {
        "name": "Granite Construction, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "GWRE": {
        "name": "Guidewire Software",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "GWW": {
        "name": "W. W. Grainger",
        "sector": "Industrials",
        "index": "sp500"
    },
    "GXO": {
        "name": "GXO Logistics",
        "sector": "Industrials",
        "index": "sp400"
    },
    "H": {
        "name": "Hyatt",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "HAE": {
        "name": "Haemonetics",
        "sector": "Health Care",
        "index": "sp400"
    },
    "HAFC": {
        "name": "Hanmi Financial Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "HAL": {
        "name": "Halliburton",
        "sector": "Energy",
        "index": "sp500"
    },
    "HALO": {
        "name": "Halozyme",
        "sector": "Health Care",
        "index": "sp400"
    },
    "HAS": {
        "name": "Hasbro",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "HASI": {
        "name": "Hannon Armstrong Sustainable Infrastructure Capital, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "HAYW": {
        "name": "Hayward Holdings, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "HBAN": {
        "name": "Huntington Bancshares",
        "sector": "Financials",
        "index": "sp500"
    },
    "HCA": {
        "name": "HCA Healthcare",
        "sector": "Health Care",
        "index": "sp500"
    },
    "HCC": {
        "name": "Warrior Met Coal, Inc.",
        "sector": "Materials",
        "index": "sp600"
    },
    "HCI": {
        "name": "HCI Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "HCSG": {
        "name": "Healthcare Services Group, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "HD": {
        "name": "Home Depot (The)",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "HE": {
        "name": "Hawaiian Electric Industries, Inc.",
        "sector": "Utilities",
        "index": "sp600"
    },
    "HFWA": {
        "name": "Heritage Financial Corporation",
        "sector": "Health Care",
        "index": "sp600"
    },
    "HGV": {
        "name": "Hilton Grand Vacations",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "HIG": {
        "name": "Hartford (The)",
        "sector": "Financials",
        "index": "sp500"
    },
    "HII": {
        "name": "Huntington Ingalls Industries",
        "sector": "Industrials",
        "index": "sp500"
    },
    "HIMS": {
        "name": "Hims & Hers Health",
        "sector": "Health Care",
        "index": "sp400"
    },
    "HIW": {
        "name": "Highwoods Properties",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "HL": {
        "name": "Hecla Mining",
        "sector": "Materials",
        "index": "sp400"
    },
    "HLI": {
        "name": "Houlihan Lokey",
        "sector": "Financials",
        "index": "sp400"
    },
    "HLIT": {
        "name": "Harmonic Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "HLNE": {
        "name": "Hamilton Lane",
        "sector": "Financials",
        "index": "sp400"
    },
    "HLT": {
        "name": "Hilton Worldwide",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "HLX": {
        "name": "Helix Energy Solutions Group, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "HMN": {
        "name": "Horace Mann Educators Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "HNI": {
        "name": "HNI Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "HOG": {
        "name": "Harley-Davidson",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "HOMB": {
        "name": "Home BancShares",
        "sector": "Financials",
        "index": "sp400"
    },
    "HON": {
        "name": "Honeywell",
        "sector": "Industrials",
        "index": "sp500"
    },
    "HOOD": {
        "name": "Robinhood Markets",
        "sector": "Financials",
        "index": "sp500"
    },
    "HOPE": {
        "name": "Hope Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "HP": {
        "name": "Helmerich & Payne, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "HPE": {
        "name": "Hewlett Packard Enterprise",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "HPQ": {
        "name": "HP Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "HQY": {
        "name": "HealthEquity",
        "sector": "Health Care",
        "index": "sp400"
    },
    "HR": {
        "name": "Healthcare Realty Trust",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "HRB": {
        "name": "H&R Block",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "HRL": {
        "name": "Hormel Foods",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "HRMY": {
        "name": "Harmony Biosciences Holdings, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "HSIC": {
        "name": "Henry Schein",
        "sector": "Health Care",
        "index": "sp500"
    },
    "HST": {
        "name": "Host Hotels & Resorts",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "HSTM": {
        "name": "HealthStream, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "HSY": {
        "name": "Hershey Company (The)",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "HTH": {
        "name": "Hilltop Holdings Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "HTLD": {
        "name": "Heartland Express, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "HTO": {
        "name": "H2O America",
        "sector": "Utilities",
        "index": "sp600"
    },
    "HTZ": {
        "name": "Hertz",
        "sector": "Industrials",
        "index": "sp600"
    },
    "HUBB": {
        "name": "Hubbell Incorporated",
        "sector": "Industrials",
        "index": "sp500"
    },
    "HUBG": {
        "name": "Hub Group, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "HUM": {
        "name": "Humana",
        "sector": "Health Care",
        "index": "sp500"
    },
    "HWC": {
        "name": "Hancock Whitney",
        "sector": "Financials",
        "index": "sp400"
    },
    "HWKN": {
        "name": "Hawkins, Inc.",
        "sector": "Materials",
        "index": "sp600"
    },
    "HWM": {
        "name": "Howmet Aerospace",
        "sector": "Industrials",
        "index": "sp500"
    },
    "HXL": {
        "name": "Hexcel",
        "sector": "Industrials",
        "index": "sp400"
    },
    "HZO": {
        "name": "MarineMax, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "IART": {
        "name": "Integra Lifesciences Holdings",
        "sector": "Health Care",
        "index": "sp600"
    },
    "IBKR": {
        "name": "Interactive Brokers",
        "sector": "Financials",
        "index": "sp500"
    },
    "IBM": {
        "name": "IBM",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "IBOC": {
        "name": "Intl Bancshares Corp",
        "sector": "Financials",
        "index": "sp400"
    },
    "IBP": {
        "name": "Installed Building Products, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "ICE": {
        "name": "Intercontinental Exchange",
        "sector": "Financials",
        "index": "sp500"
    },
    "ICHR": {
        "name": "Ichor Holdings, Ltd.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ICUI": {
        "name": "ICU Medical",
        "sector": "Health Care",
        "index": "sp600"
    },
    "IDA": {
        "name": "Idacorp",
        "sector": "Utilities",
        "index": "sp400"
    },
    "IDCC": {
        "name": "InterDigital",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "IDXX": {
        "name": "Idexx Laboratories",
        "sector": "Health Care",
        "index": "sp500"
    },
    "IEX": {
        "name": "IDEX Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "IFF": {
        "name": "International Flavors & Fragrances",
        "sector": "Materials",
        "index": "sp500"
    },
    "IIIN": {
        "name": "Insteel Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "IIPR": {
        "name": "Innovative Industrial Properties, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ILMN": {
        "name": "Illumina, Inc.",
        "sector": "Health Care",
        "index": "sp400"
    },
    "INCY": {
        "name": "Incyte",
        "sector": "Health Care",
        "index": "sp500"
    },
    "INDB": {
        "name": "Independent Bank Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "INDV": {
        "name": "Indivior",
        "sector": "Health Care",
        "index": "sp600"
    },
    "INGR": {
        "name": "Ingredion",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "INSP": {
        "name": "Inspire Medical Systems, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "INSW": {
        "name": "International Seaways, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "INTC": {
        "name": "Intel",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "INTU": {
        "name": "Intuit",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "INVA": {
        "name": "Innoviva, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "INVH": {
        "name": "Invitation Homes",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "INVX": {
        "name": "Innovex International, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "IOSP": {
        "name": "Innospec, Inc.",
        "sector": "Materials",
        "index": "sp600"
    },
    "IP": {
        "name": "International Paper",
        "sector": "Materials",
        "index": "sp500"
    },
    "IPAR": {
        "name": "Inter Parfums, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "IPGP": {
        "name": "IPG Photonics",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "IQV": {
        "name": "IQVIA",
        "sector": "Health Care",
        "index": "sp500"
    },
    "IR": {
        "name": "Ingersoll Rand",
        "sector": "Industrials",
        "index": "sp500"
    },
    "IRDM": {
        "name": "Iridium Communications",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "IRM": {
        "name": "Iron Mountain",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "IRT": {
        "name": "IRT Living",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "ISRG": {
        "name": "Intuitive Surgical",
        "sector": "Health Care",
        "index": "sp500"
    },
    "IT": {
        "name": "Gartner",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ITGR": {
        "name": "Integer Holdings Corporation",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ITRI": {
        "name": "Itron, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ITT": {
        "name": "ITT Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ITW": {
        "name": "Illinois Tool Works",
        "sector": "Industrials",
        "index": "sp500"
    },
    "IVZ": {
        "name": "Invesco",
        "sector": "Financials",
        "index": "sp500"
    },
    "J": {
        "name": "Jacobs Solutions",
        "sector": "Industrials",
        "index": "sp500"
    },
    "JAZZ": {
        "name": "Jazz Pharmaceuticals",
        "sector": "Health Care",
        "index": "sp400"
    },
    "JBGS": {
        "name": "JBG Smith",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "JBHT": {
        "name": "J.B. Hunt",
        "sector": "Industrials",
        "index": "sp500"
    },
    "JBL": {
        "name": "Jabil",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "JBLU": {
        "name": "JetBlue",
        "sector": "Industrials",
        "index": "sp600"
    },
    "JBSS": {
        "name": "John B. Sanfilippo & Son, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "JBTM": {
        "name": "JBT Marel Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "JCI": {
        "name": "Johnson Controls",
        "sector": "Industrials",
        "index": "sp500"
    },
    "JEF": {
        "name": "Jefferies",
        "sector": "Financials",
        "index": "sp400"
    },
    "JHG": {
        "name": "Janus Henderson",
        "sector": "Financials",
        "index": "sp400"
    },
    "JJSF": {
        "name": "J&J Snack Foods Corp.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "JKHY": {
        "name": "Jack Henry & Associates",
        "sector": "Financials",
        "index": "sp500"
    },
    "JLL": {
        "name": "Jones Lang LaSalle",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "JNJ": {
        "name": "Johnson & Johnson",
        "sector": "Health Care",
        "index": "sp500"
    },
    "JOE": {
        "name": "St. Joe Company",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "JPM": {
        "name": "JPMorgan Chase",
        "sector": "Financials",
        "index": "sp500"
    },
    "JXN": {
        "name": "Jackson Financial, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "KAI": {
        "name": "Kadant Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "KALU": {
        "name": "Kaiser Aluminum Corporation",
        "sector": "Materials",
        "index": "sp600"
    },
    "KBH": {
        "name": "KB Home",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "KBR": {
        "name": "KBR, Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "KD": {
        "name": "Kyndryl",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "KDP": {
        "name": "Keurig Dr Pepper",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "KEX": {
        "name": "Kirby Corporation",
        "sector": "Industrials",
        "index": "sp400"
    },
    "KEY": {
        "name": "KeyCorp",
        "sector": "Financials",
        "index": "sp500"
    },
    "KEYS": {
        "name": "Keysight Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "KFY": {
        "name": "Korn/Ferry International",
        "sector": "Industrials",
        "index": "sp600"
    },
    "KGS": {
        "name": "Kodiak Gas Services, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "KHC": {
        "name": "Kraft Heinz",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "KIM": {
        "name": "Kimco Realty",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "KKR": {
        "name": "KKR & Co.",
        "sector": "Financials",
        "index": "sp500"
    },
    "KLAC": {
        "name": "KLA Corporation",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "KLIC": {
        "name": "Kulicke and Soffa Industries, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "KMB": {
        "name": "Kimberly-Clark",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "KMI": {
        "name": "Kinder Morgan",
        "sector": "Energy",
        "index": "sp500"
    },
    "KMPR": {
        "name": "Kemper Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "KMT": {
        "name": "Kennametal",
        "sector": "Industrials",
        "index": "sp600"
    },
    "KMX": {
        "name": "CarMax, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "KN": {
        "name": "Knowles Corporation",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "KNF": {
        "name": "Knife River Corporation",
        "sector": "Materials",
        "index": "sp400"
    },
    "KNSL": {
        "name": "Kinsale Capital Group",
        "sector": "Financials",
        "index": "sp400"
    },
    "KNTK": {
        "name": "Kinetik Holdings, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "KNX": {
        "name": "Knight-Swift",
        "sector": "Industrials",
        "index": "sp400"
    },
    "KO": {
        "name": "Coca-Cola Company (The)",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "KOP": {
        "name": "Koppers Holdings, Inc.",
        "sector": "Materials",
        "index": "sp600"
    },
    "KR": {
        "name": "Kroger",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "KRC": {
        "name": "Kilroy Realty Corp",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "KRG": {
        "name": "Kite Realty Group Trust",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "KRYS": {
        "name": "Krystal Biotech, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "KSS": {
        "name": "Kohl's Corp.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "KTB": {
        "name": "Kontoor Brands",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "KTOS": {
        "name": "Kratos Defense & Security Solutions",
        "sector": "Industrials",
        "index": "sp400"
    },
    "KVUE": {
        "name": "Kenvue",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "KW": {
        "name": "Kennedy-Wilson Holdings, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "KWR": {
        "name": "Quaker Chemical Corporation",
        "sector": "Materials",
        "index": "sp600"
    },
    "L": {
        "name": "Loews Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "LAD": {
        "name": "Lithia Motors",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "LAMR": {
        "name": "Lamar Advertising Company",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "LAUR": {
        "name": "Laureate Education, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LBRT": {
        "name": "Liberty Energy, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "LCII": {
        "name": "LCI Industries",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LDOS": {
        "name": "Leidos",
        "sector": "Industrials",
        "index": "sp500"
    },
    "LEA": {
        "name": "Lear",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "LECO": {
        "name": "Lincoln Electric",
        "sector": "Industrials",
        "index": "sp400"
    },
    "LEG": {
        "name": "Leggett & Platt",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LEN": {
        "name": "Lennar",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "LFST": {
        "name": "Lifestance Health",
        "sector": "Health Care",
        "index": "sp600"
    },
    "LFUS": {
        "name": "Littelfuse",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "LGIH": {
        "name": "LGI Homes",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LGND": {
        "name": "Ligand Pharmaceuticals, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "LH": {
        "name": "Labcorp",
        "sector": "Health Care",
        "index": "sp500"
    },
    "LHX": {
        "name": "L3Harris",
        "sector": "Industrials",
        "index": "sp500"
    },
    "LIF": {
        "name": "Life360",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "LII": {
        "name": "Lennox International",
        "sector": "Industrials",
        "index": "sp500"
    },
    "LIN": {
        "name": "Linde plc",
        "sector": "Materials",
        "index": "sp500"
    },
    "LITE": {
        "name": "Lumentum",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "LIVN": {
        "name": "LivaNova",
        "sector": "Health Care",
        "index": "sp400"
    },
    "LKFN": {
        "name": "Lakeland Financial",
        "sector": "Financials",
        "index": "sp600"
    },
    "LKQ": {
        "name": "LKQ Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LLY": {
        "name": "Lilly (Eli)",
        "sector": "Health Care",
        "index": "sp500"
    },
    "LMAT": {
        "name": "LeMaitre Vascular",
        "sector": "Health Care",
        "index": "sp600"
    },
    "LMT": {
        "name": "Lockheed Martin",
        "sector": "Industrials",
        "index": "sp500"
    },
    "LNC": {
        "name": "Lincoln Financial",
        "sector": "Financials",
        "index": "sp600"
    },
    "LNN": {
        "name": "Lindsay Corporation",
        "sector": "Materials",
        "index": "sp600"
    },
    "LNT": {
        "name": "Alliant Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "LNTH": {
        "name": "Lantheus Holdings",
        "sector": "Health Care",
        "index": "sp400"
    },
    "LOPE": {
        "name": "Grand Canyon Education",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "LOW": {
        "name": "Lowe's",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "LPG": {
        "name": "Dorian LPG Ltd.",
        "sector": "Energy",
        "index": "sp600"
    },
    "LPX": {
        "name": "Louisiana-Pacific",
        "sector": "Materials",
        "index": "sp400"
    },
    "LQDT": {
        "name": "Liquidity Services, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "LRCX": {
        "name": "Lam Research",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "LRN": {
        "name": "Stride, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LSCC": {
        "name": "Lattice Semiconductor",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "LSTR": {
        "name": "Landstar System",
        "sector": "Industrials",
        "index": "sp400"
    },
    "LTC": {
        "name": "LTC Properties, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "LTH": {
        "name": "Life Time Group Holdings, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "LULU": {
        "name": "Lululemon Athletica",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "LUMN": {
        "name": "Lumen Technologies",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "LUV": {
        "name": "Southwest Airlines",
        "sector": "Industrials",
        "index": "sp500"
    },
    "LVS": {
        "name": "Las Vegas Sands",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "LW": {
        "name": "Lamb Weston",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "LXP": {
        "name": "Lexington Realty Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "LYB": {
        "name": "LyondellBasell",
        "sector": "Materials",
        "index": "sp500"
    },
    "LYFT": {
        "name": "Lyft, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "LYV": {
        "name": "Live Nation Entertainment",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "LZ": {
        "name": "LegalZoom.com, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "LZB": {
        "name": "La-Z-Boy, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "M": {
        "name": "Macy's",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "MA": {
        "name": "Mastercard",
        "sector": "Financials",
        "index": "sp500"
    },
    "MAA": {
        "name": "Mid-America Apartment Communities",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "MAC": {
        "name": "Macerich",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "MAN": {
        "name": "ManpowerGroup",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MANH": {
        "name": "Manhattan Associates",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "MAR": {
        "name": "Marriott International",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "MARA": {
        "name": "MARA Holdings, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "MAS": {
        "name": "Masco",
        "sector": "Industrials",
        "index": "sp500"
    },
    "MAT": {
        "name": "Mattel",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "MATW": {
        "name": "Matthews International Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "MATX": {
        "name": "Matson, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MBC": {
        "name": "MasterBrand, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MBIN": {
        "name": "Merchants Bancorp",
        "sector": "Financials",
        "index": "sp600"
    },
    "MC": {
        "name": "Moelis & Company",
        "sector": "Financials",
        "index": "sp600"
    },
    "MCD": {
        "name": "McDonald's",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "MCHP": {
        "name": "Microchip Technology",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "MCK": {
        "name": "McKesson Corporation",
        "sector": "Health Care",
        "index": "sp500"
    },
    "MCO": {
        "name": "Moody's Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "MCRI": {
        "name": "Monarch Casino & Resort, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "MCY": {
        "name": "Mercury General",
        "sector": "Financials",
        "index": "sp600"
    },
    "MD": {
        "name": "Pediatrix Medical Group",
        "sector": "Health Care",
        "index": "sp600"
    },
    "MDLZ": {
        "name": "Mondelez International",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "MDT": {
        "name": "Medtronic",
        "sector": "Health Care",
        "index": "sp500"
    },
    "MDU": {
        "name": "MDU Resources Group, Inc.",
        "sector": "Utilities",
        "index": "sp600"
    },
    "MEDP": {
        "name": "Medpace",
        "sector": "Health Care",
        "index": "sp400"
    },
    "MET": {
        "name": "MetLife",
        "sector": "Financials",
        "index": "sp500"
    },
    "META": {
        "name": "Meta Platforms",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "MGEE": {
        "name": "MGE Energy, Inc.",
        "sector": "Utilities",
        "index": "sp600"
    },
    "MGM": {
        "name": "MGM Resorts",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "MGY": {
        "name": "Magnolia Oil & Gas, Corp.",
        "sector": "Energy",
        "index": "sp600"
    },
    "MHK": {
        "name": "Mohawk Industries",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "MHO": {
        "name": "M/I Homes, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "MIDD": {
        "name": "Middleby",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MIR": {
        "name": "Mirion Technologies, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "MKC": {
        "name": "McCormick & Company",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "MKSI": {
        "name": "MKS Instruments",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "MKTX": {
        "name": "MarketAxess",
        "sector": "Financials",
        "index": "sp600"
    },
    "MLI": {
        "name": "Mueller Industries",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MLKN": {
        "name": "MillerKnoll, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MLM": {
        "name": "Martin Marietta Materials",
        "sector": "Materials",
        "index": "sp500"
    },
    "MMI": {
        "name": "Marcus & Millichap, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "MMM": {
        "name": "3M",
        "sector": "Industrials",
        "index": "sp500"
    },
    "MMS": {
        "name": "Maximus Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MMSI": {
        "name": "Merit Medical Systems, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "MNRO": {
        "name": "Monro, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "MNST": {
        "name": "Monster Beverage",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "MO": {
        "name": "Altria",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "MOG-A": {
        "name": "Moog Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MOH": {
        "name": "Molina Healthcare",
        "sector": "Health Care",
        "index": "sp600"
    },
    "MORN": {
        "name": "Morningstar, Inc.",
        "sector": "Financials",
        "index": "sp400"
    },
    "MOS": {
        "name": "Mosaic Company (The)",
        "sector": "Materials",
        "index": "sp500"
    },
    "MP": {
        "name": "MP Materials",
        "sector": "Materials",
        "index": "sp400"
    },
    "MPC": {
        "name": "Marathon Petroleum",
        "sector": "Energy",
        "index": "sp500"
    },
    "MPT": {
        "name": "Medical Properties Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "MPWR": {
        "name": "Monolithic Power Systems",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "MRCY": {
        "name": "Mercury Systems",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MRK": {
        "name": "Merck & Co.",
        "sector": "Health Care",
        "index": "sp500"
    },
    "MRNA": {
        "name": "Moderna",
        "sector": "Health Care",
        "index": "sp500"
    },
    "MRP": {
        "name": "Millrose Properties, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "MRSH": {
        "name": "Marsh McLennan",
        "sector": "Financials",
        "index": "sp500"
    },
    "MRTN": {
        "name": "Marten Transport, Ltd.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MRVL": {
        "name": "Marvell Technology",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "MS": {
        "name": "Morgan Stanley",
        "sector": "Financials",
        "index": "sp500"
    },
    "MSA": {
        "name": "MSA Safety",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MSCI": {
        "name": "MSCI Inc.",
        "sector": "Financials",
        "index": "sp500"
    },
    "MSEX": {
        "name": "Middlesex Water Company",
        "sector": "Utilities",
        "index": "sp600"
    },
    "MSFT": {
        "name": "Microsoft",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "MSGS": {
        "name": "Madison Square Garden Sports Corp.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "MSI": {
        "name": "Motorola Solutions",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "MSM": {
        "name": "MSC Industrial Direct",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MTB": {
        "name": "M&T Bank",
        "sector": "Financials",
        "index": "sp500"
    },
    "MTCH": {
        "name": "Match Group",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "MTD": {
        "name": "Mettler Toledo",
        "sector": "Health Care",
        "index": "sp500"
    },
    "MTDR": {
        "name": "Matador Resources",
        "sector": "Energy",
        "index": "sp400"
    },
    "MTG": {
        "name": "MGIC Investment Corporation",
        "sector": "Financials",
        "index": "sp400"
    },
    "MTH": {
        "name": "Meritage Homes Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "MTN": {
        "name": "Vail Resorts",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "MTRN": {
        "name": "Materion Corp.",
        "sector": "Materials",
        "index": "sp600"
    },
    "MTSI": {
        "name": "MACOM Technology Solutions",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "MTUS": {
        "name": "Metallus Inc",
        "sector": "Materials",
        "index": "sp600"
    },
    "MTX": {
        "name": "Minerals Technologies",
        "sector": "Materials",
        "index": "sp600"
    },
    "MTZ": {
        "name": "MasTec",
        "sector": "Industrials",
        "index": "sp400"
    },
    "MU": {
        "name": "Micron Technology",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "MUR": {
        "name": "Murphy Oil",
        "sector": "Energy",
        "index": "sp400"
    },
    "MUSA": {
        "name": "Murphy USA",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "MWA": {
        "name": "Mueller Water Products",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MXL": {
        "name": "MaxLinear, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "MYRG": {
        "name": "MYR Group, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "MZTI": {
        "name": "The Marzetti Company",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "NABL": {
        "name": "N-able, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "NATL": {
        "name": "NCR Atleos",
        "sector": "Financials",
        "index": "sp600"
    },
    "NAVI": {
        "name": "Navient",
        "sector": "Financials",
        "index": "sp600"
    },
    "NBHC": {
        "name": "National Bank Holdings Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "NBIX": {
        "name": "Neurocrine Biosciences",
        "sector": "Health Care",
        "index": "sp400"
    },
    "NBTB": {
        "name": "NBT Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "NCLH": {
        "name": "Norwegian Cruise Line Holdings",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "NDAQ": {
        "name": "Nasdaq, Inc.",
        "sector": "Financials",
        "index": "sp500"
    },
    "NDSN": {
        "name": "Nordson Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "NE": {
        "name": "Noble Corporation",
        "sector": "Energy",
        "index": "sp600"
    },
    "NEE": {
        "name": "NextEra Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "NEM": {
        "name": "Newmont",
        "sector": "Materials",
        "index": "sp500"
    },
    "NEO": {
        "name": "NeoGenomics Laboratories, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "NEOG": {
        "name": "Neogen",
        "sector": "Health Care",
        "index": "sp600"
    },
    "NEU": {
        "name": "NewMarket Corporation",
        "sector": "Materials",
        "index": "sp400"
    },
    "NFG": {
        "name": "National Fuel Gas",
        "sector": "Utilities",
        "index": "sp400"
    },
    "NFLX": {
        "name": "Netflix",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "NGVT": {
        "name": "Ingevity, Corp.",
        "sector": "Materials",
        "index": "sp600"
    },
    "NHC": {
        "name": "National Healthcare, Corp.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "NI": {
        "name": "NiSource",
        "sector": "Utilities",
        "index": "sp500"
    },
    "NJR": {
        "name": "New Jersey Resources",
        "sector": "Utilities",
        "index": "sp400"
    },
    "NKE": {
        "name": "Nike, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "NLY": {
        "name": "Annaly Capital Management",
        "sector": "Financials",
        "index": "sp400"
    },
    "NMIH": {
        "name": "NMI Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "NNN": {
        "name": "NNN Reit",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "NOC": {
        "name": "Northrop Grumman",
        "sector": "Industrials",
        "index": "sp500"
    },
    "NOG": {
        "name": "Northern Oil and Gas, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "NOV": {
        "name": "NOV Inc.",
        "sector": "Energy",
        "index": "sp400"
    },
    "NOVT": {
        "name": "Novanta",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "NOW": {
        "name": "ServiceNow",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "NPK": {
        "name": "National Presto Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "NPO": {
        "name": "EnPro Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "NRG": {
        "name": "NRG Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "NSA": {
        "name": "National Storage Affiliates Trust",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "NSC": {
        "name": "Norfolk Southern",
        "sector": "Industrials",
        "index": "sp500"
    },
    "NSIT": {
        "name": "Insight Enterprises, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "NSP": {
        "name": "Insperity",
        "sector": "Industrials",
        "index": "sp600"
    },
    "NSSC": {
        "name": "Napco Security Technologies",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "NTAP": {
        "name": "NetApp",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "NTCT": {
        "name": "NETSCOUT Systems, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "NTNX": {
        "name": "Nutanix",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "NTRS": {
        "name": "Northern Trust",
        "sector": "Financials",
        "index": "sp500"
    },
    "NUE": {
        "name": "Nucor",
        "sector": "Materials",
        "index": "sp500"
    },
    "NVDA": {
        "name": "Nvidia",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "NVR": {
        "name": "NVR, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "NVST": {
        "name": "Envista Holdings",
        "sector": "Health Care",
        "index": "sp400"
    },
    "NVT": {
        "name": "nVent Electric plc",
        "sector": "Industrials",
        "index": "sp400"
    },
    "NWBI": {
        "name": "Northwest Bancshares, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "NWE": {
        "name": "NorthWestern Energy",
        "sector": "Utilities",
        "index": "sp400"
    },
    "NWL": {
        "name": "Newell Brands",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "NWN": {
        "name": "NW Natural",
        "sector": "Utilities",
        "index": "sp600"
    },
    "NWS": {
        "name": "News Corp (Class B)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "NWSA": {
        "name": "News Corp (Class A)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "NX": {
        "name": "Quanex Building Products Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "NXPI": {
        "name": "NXP Semiconductors",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "NXRT": {
        "name": "NexPoint Residential Trust, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "NXST": {
        "name": "Nexstar Media Group",
        "sector": "Communication Services",
        "index": "sp400"
    },
    "NXT": {
        "name": "Nextpower",
        "sector": "Industrials",
        "index": "sp400"
    },
    "NYT": {
        "name": "New York Times Company",
        "sector": "Communication Services",
        "index": "sp400"
    },
    "O": {
        "name": "Realty Income",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "OC": {
        "name": "Owens Corning",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ODFL": {
        "name": "Old Dominion",
        "sector": "Industrials",
        "index": "sp500"
    },
    "OFG": {
        "name": "OFG Bancorp",
        "sector": "Financials",
        "index": "sp600"
    },
    "OGE": {
        "name": "OGE Energy",
        "sector": "Utilities",
        "index": "sp400"
    },
    "OGN": {
        "name": "Organon & Co.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "OGS": {
        "name": "One Gas",
        "sector": "Utilities",
        "index": "sp400"
    },
    "OHI": {
        "name": "Omega Healthcare Investors",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "OI": {
        "name": "O-I Glass, Inc.",
        "sector": "Materials",
        "index": "sp600"
    },
    "OII": {
        "name": "Oceaneering International, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "OKE": {
        "name": "Oneok",
        "sector": "Energy",
        "index": "sp500"
    },
    "OKTA": {
        "name": "Okta, Inc.",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "OLED": {
        "name": "Universal Display",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "OLLI": {
        "name": "Ollie's Bargain Outlet",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "OLN": {
        "name": "Olin Corporation",
        "sector": "Materials",
        "index": "sp400"
    },
    "OMC": {
        "name": "Omnicom Group",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "OMCL": {
        "name": "Omnicell",
        "sector": "Health Care",
        "index": "sp600"
    },
    "ON": {
        "name": "ON Semiconductor",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ONB": {
        "name": "Old National Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "ONTO": {
        "name": "Onto Innovation",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "OPCH": {
        "name": "Option Care Health",
        "sector": "Health Care",
        "index": "sp400"
    },
    "OPLN": {
        "name": "OPENLANE, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ORA": {
        "name": "Ormat Technologies",
        "sector": "Utilities",
        "index": "sp400"
    },
    "ORCL": {
        "name": "Oracle Corporation",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ORI": {
        "name": "Old Republic International",
        "sector": "Financials",
        "index": "sp400"
    },
    "ORLY": {
        "name": "O’Reilly Automotive",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "OSIS": {
        "name": "OSI Systems, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "OSK": {
        "name": "Oshkosh",
        "sector": "Industrials",
        "index": "sp400"
    },
    "OSW": {
        "name": "OneSpaWorld Holdings Limited",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "OTIS": {
        "name": "Otis Worldwide",
        "sector": "Industrials",
        "index": "sp500"
    },
    "OTTR": {
        "name": "Otter Tail Corporation",
        "sector": "Utilities",
        "index": "sp600"
    },
    "OUT": {
        "name": "Outfront Media",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "OVV": {
        "name": "Ovintiv",
        "sector": "Energy",
        "index": "sp400"
    },
    "OXM": {
        "name": "Oxford Industries, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "OXY": {
        "name": "Occidental Petroleum",
        "sector": "Energy",
        "index": "sp500"
    },
    "OZK": {
        "name": "Bank OZK",
        "sector": "Financials",
        "index": "sp400"
    },
    "P": {
        "name": "Everpure",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "PAG": {
        "name": "Penske Automotive Group",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "PAHC": {
        "name": "Phibro Animal Health",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PANW": {
        "name": "Palo Alto Networks",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "PARR": {
        "name": "Par Pacific Holdings, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "PATH": {
        "name": "UiPath",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "PATK": {
        "name": "Patrick Industries, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PAYC": {
        "name": "Paycom",
        "sector": "Industrials",
        "index": "sp600"
    },
    "PAYO": {
        "name": "Payoneer Global Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PAYX": {
        "name": "Paychex",
        "sector": "Industrials",
        "index": "sp500"
    },
    "PB": {
        "name": "Prosperity Bancshares",
        "sector": "Financials",
        "index": "sp400"
    },
    "PBF": {
        "name": "PBF Energy",
        "sector": "Energy",
        "index": "sp400"
    },
    "PBH": {
        "name": "Prestige Consumer Healthcare",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PBI": {
        "name": "Pitney Bowes, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "PCAR": {
        "name": "Paccar",
        "sector": "Industrials",
        "index": "sp500"
    },
    "PCG": {
        "name": "PG&E Corporation",
        "sector": "Utilities",
        "index": "sp500"
    },
    "PCRX": {
        "name": "Pacira BioSciences, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PCTY": {
        "name": "Paylocity",
        "sector": "Industrials",
        "index": "sp400"
    },
    "PDFS": {
        "name": "PDF Solutions, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PEB": {
        "name": "Pebblebrook Hotel Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "PECO": {
        "name": "Phillips Edison & Company",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "PEG": {
        "name": "Public Service Enterprise Group",
        "sector": "Utilities",
        "index": "sp500"
    },
    "PEGA": {
        "name": "Pegasystems",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "PEN": {
        "name": "Penumbra, Inc.",
        "sector": "Health Care",
        "index": "sp400"
    },
    "PENG": {
        "name": "Penguin Solutions, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PENN": {
        "name": "Penn Entertainment",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PEP": {
        "name": "PepsiCo",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "PFBC": {
        "name": "Preferred Bank",
        "sector": "Financials",
        "index": "sp600"
    },
    "PFE": {
        "name": "Pfizer",
        "sector": "Health Care",
        "index": "sp500"
    },
    "PFG": {
        "name": "Principal Financial Group",
        "sector": "Financials",
        "index": "sp500"
    },
    "PFGC": {
        "name": "Performance Food Group",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "PFS": {
        "name": "Provident Financial Services, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PG": {
        "name": "Procter & Gamble",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "PGNY": {
        "name": "Progyny",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PGR": {
        "name": "Progressive Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "PH": {
        "name": "Parker Hannifin",
        "sector": "Industrials",
        "index": "sp500"
    },
    "PHIN": {
        "name": "PHINIA, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PHM": {
        "name": "PulteGroup",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "PI": {
        "name": "Impinj, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PII": {
        "name": "Polaris",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "PINS": {
        "name": "Pinterest",
        "sector": "Communication Services",
        "index": "sp400"
    },
    "PIPR": {
        "name": "Piper Sandler Companies",
        "sector": "Financials",
        "index": "sp600"
    },
    "PJT": {
        "name": "PJT Partners, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PK": {
        "name": "Park Hotels & Resorts",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "PKG": {
        "name": "Packaging Corporation of America",
        "sector": "Materials",
        "index": "sp500"
    },
    "PLAB": {
        "name": "Photronics, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PLD": {
        "name": "Prologis",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "PLMR": {
        "name": "Palomar Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PLNT": {
        "name": "Planet Fitness",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "PLTR": {
        "name": "Palantir Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "PLUS": {
        "name": "ePlus, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PLXS": {
        "name": "Plexus Corp.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PM": {
        "name": "Philip Morris International",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "PMT": {
        "name": "PennyMac Mortgage Investment Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "PNC": {
        "name": "PNC Financial Services",
        "sector": "Financials",
        "index": "sp500"
    },
    "PNFP": {
        "name": "Pinnacle Financial Partners",
        "sector": "Financials",
        "index": "sp400"
    },
    "PNR": {
        "name": "Pentair",
        "sector": "Industrials",
        "index": "sp500"
    },
    "PNW": {
        "name": "Pinnacle West Capital",
        "sector": "Utilities",
        "index": "sp500"
    },
    "PODD": {
        "name": "Insulet Corporation",
        "sector": "Health Care",
        "index": "sp500"
    },
    "POR": {
        "name": "Portland General Electric",
        "sector": "Utilities",
        "index": "sp400"
    },
    "POST": {
        "name": "Post Holdings",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "POWI": {
        "name": "Power Integrations",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "POWL": {
        "name": "Powell Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "PPC": {
        "name": "Pilgrim's Pride",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "PPG": {
        "name": "PPG Industries",
        "sector": "Materials",
        "index": "sp500"
    },
    "PPL": {
        "name": "PPL Corporation",
        "sector": "Utilities",
        "index": "sp500"
    },
    "PPLI": {
        "name": "People Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "PR": {
        "name": "Permian Resources",
        "sector": "Energy",
        "index": "sp400"
    },
    "PRA": {
        "name": "ProAssurance Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "PRAA": {
        "name": "PRA Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PRDO": {
        "name": "Perdoceo Education Corp.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PRG": {
        "name": "PROG Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PRGO": {
        "name": "Perrigo",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PRGS": {
        "name": "Progress Software Corporation",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "PRI": {
        "name": "Primerica",
        "sector": "Financials",
        "index": "sp400"
    },
    "PRIM": {
        "name": "Primoris Services Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "PRK": {
        "name": "Park National Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "PRKS": {
        "name": "United Parks & Resorts",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PRLB": {
        "name": "Protolabs",
        "sector": "Industrials",
        "index": "sp600"
    },
    "PRSU": {
        "name": "Pursuit Attractions & Hospitality, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PRU": {
        "name": "Prudential Financial",
        "sector": "Financials",
        "index": "sp500"
    },
    "PRVA": {
        "name": "Privia Health Group, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PSA": {
        "name": "Public Storage",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "PSKY": {
        "name": "Paramount Skydance Corporation",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "PSMT": {
        "name": "PriceSmart",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "PSN": {
        "name": "Parsons Corporation",
        "sector": "Industrials",
        "index": "sp400"
    },
    "PSX": {
        "name": "Phillips 66",
        "sector": "Energy",
        "index": "sp500"
    },
    "PTC": {
        "name": "PTC Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "PTCT": {
        "name": "PTC Therapeutics, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PTEN": {
        "name": "Patterson-UTI Energy, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "PTGX": {
        "name": "Protagonist Therapeutics, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "PTON": {
        "name": "Peloton Interactive, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "PVH": {
        "name": "PVH Corp.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "PWR": {
        "name": "Quanta Services",
        "sector": "Industrials",
        "index": "sp500"
    },
    "PYPL": {
        "name": "PayPal",
        "sector": "Financials",
        "index": "sp500"
    },
    "PZZA": {
        "name": "Papa John's Pizza",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "Q": {
        "name": "Qnity Electronics",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "QCOM": {
        "name": "Qualcomm",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "QDEL": {
        "name": "QuidelOrtho",
        "sector": "Health Care",
        "index": "sp600"
    },
    "QLYS": {
        "name": "Qualys",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "QNST": {
        "name": "QuinStreet, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "QRVO": {
        "name": "Qorvo",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "QTWO": {
        "name": "Q2 Holdings, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "R": {
        "name": "Ryder",
        "sector": "Industrials",
        "index": "sp400"
    },
    "RAL": {
        "name": "Ralliant Corp",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "RAMP": {
        "name": "LiveRamp Holdings, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "RBA": {
        "name": "RB Global",
        "sector": "Industrials",
        "index": "sp400"
    },
    "RBC": {
        "name": "RBC Bearings",
        "sector": "Industrials",
        "index": "sp400"
    },
    "RCL": {
        "name": "Royal Caribbean Group",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "RCUS": {
        "name": "Arcus Biosciences, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "RDN": {
        "name": "Radian Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "RDNT": {
        "name": "RadNet, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "REG": {
        "name": "Regency Centers",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "REGN": {
        "name": "Regeneron Pharmaceuticals",
        "sector": "Health Care",
        "index": "sp500"
    },
    "RELY": {
        "name": "Remitly",
        "sector": "Financials",
        "index": "sp600"
    },
    "RES": {
        "name": "RPC, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "REX": {
        "name": "REX American Resources Corporation",
        "sector": "Energy",
        "index": "sp600"
    },
    "REXR": {
        "name": "Rexford Industrial Realty",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "REYN": {
        "name": "Reynolds Consumer Products",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "REZI": {
        "name": "Resideo Technologies, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "RF": {
        "name": "Regions Financial Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "RGA": {
        "name": "Reinsurance Group of America",
        "sector": "Financials",
        "index": "sp400"
    },
    "RGEN": {
        "name": "Repligen",
        "sector": "Health Care",
        "index": "sp400"
    },
    "RGLD": {
        "name": "Royal Gold",
        "sector": "Materials",
        "index": "sp400"
    },
    "RH": {
        "name": "RH",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "RHI": {
        "name": "Robert Half",
        "sector": "Industrials",
        "index": "sp600"
    },
    "RHP": {
        "name": "Ryman Hospitality Properties",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "RITM": {
        "name": "Rithm Capital",
        "sector": "Financials",
        "index": "sp600"
    },
    "RJF": {
        "name": "Raymond James Financial",
        "sector": "Financials",
        "index": "sp500"
    },
    "RL": {
        "name": "Ralph Lauren Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "RLI": {
        "name": "RLI Corp.",
        "sector": "Financials",
        "index": "sp400"
    },
    "RMBS": {
        "name": "Rambus",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "RMD": {
        "name": "ResMed",
        "sector": "Health Care",
        "index": "sp500"
    },
    "RNG": {
        "name": "RingCentral, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "RNR": {
        "name": "RenaissanceRe",
        "sector": "Financials",
        "index": "sp400"
    },
    "RNST": {
        "name": "Renasant Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "ROCK": {
        "name": "Gibraltar Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "ROG": {
        "name": "Rogers Corporation",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "ROIV": {
        "name": "Roivant Sciences",
        "sector": "Health Care",
        "index": "sp400"
    },
    "ROK": {
        "name": "Rockwell Automation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "ROKU": {
        "name": "Roku, Inc.",
        "sector": "Communication Services",
        "index": "sp400"
    },
    "ROL": {
        "name": "Rollins, Inc.",
        "sector": "Industrials",
        "index": "sp500"
    },
    "ROP": {
        "name": "Roper Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ROST": {
        "name": "Ross Stores",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "RPM": {
        "name": "RPM International",
        "sector": "Materials",
        "index": "sp400"
    },
    "RRC": {
        "name": "Range Resources",
        "sector": "Energy",
        "index": "sp400"
    },
    "RRR": {
        "name": "Red Rock Resorts, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "RRX": {
        "name": "Regal Rexnord",
        "sector": "Industrials",
        "index": "sp400"
    },
    "RS": {
        "name": "Reliance, Inc.",
        "sector": "Materials",
        "index": "sp400"
    },
    "RSG": {
        "name": "Republic Services",
        "sector": "Industrials",
        "index": "sp500"
    },
    "RTX": {
        "name": "RTX Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "RUN": {
        "name": "Sunrun",
        "sector": "Industrials",
        "index": "sp600"
    },
    "RUSHA": {
        "name": "Rush Enterprises",
        "sector": "Industrials",
        "index": "sp600"
    },
    "RVTY": {
        "name": "Revvity",
        "sector": "Health Care",
        "index": "sp500"
    },
    "RWT": {
        "name": "Redwood Trust, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "RXO": {
        "name": "RXO, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "RYAN": {
        "name": "Ryan Specialty",
        "sector": "Financials",
        "index": "sp400"
    },
    "RYN": {
        "name": "Rayonier",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "SABR": {
        "name": "Sabre",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SAFE": {
        "name": "Safehold, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "SAFT": {
        "name": "Safety Insurance Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "SAH": {
        "name": "Sonic Automotive, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SAIA": {
        "name": "Saia",
        "sector": "Industrials",
        "index": "sp400"
    },
    "SAIC": {
        "name": "Science Applications Intl Corp",
        "sector": "Industrials",
        "index": "sp400"
    },
    "SAM": {
        "name": "Boston Beer Company",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "SANM": {
        "name": "Sanmina Corporation",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "SARO": {
        "name": "StandardAero",
        "sector": "Industrials",
        "index": "sp400"
    },
    "SATS": {
        "name": "EchoStar",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "SBAC": {
        "name": "SBA Communications",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "SBCF": {
        "name": "Seacoast Banking Corporation of Florida",
        "sector": "Financials",
        "index": "sp600"
    },
    "SBH": {
        "name": "Sally Beauty Holdings, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SBRA": {
        "name": "Sabra Health Care REIT",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "SBSI": {
        "name": "Southside Bancshares, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "SBUX": {
        "name": "Starbucks",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "SCHL": {
        "name": "Scholastic Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SCHW": {
        "name": "Charles Schwab Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "SCI": {
        "name": "Service Corp Intl",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "SCL": {
        "name": "Stepan Company",
        "sector": "Materials",
        "index": "sp600"
    },
    "SCSC": {
        "name": "ScanSource, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "SDGR": {
        "name": "Schrödinger, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "SEDG": {
        "name": "SolarEdge",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "SEIC": {
        "name": "SEI Investments Company",
        "sector": "Financials",
        "index": "sp400"
    },
    "SEM": {
        "name": "Select Medical Holdings, Corp.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "SEZL": {
        "name": "Sezzle",
        "sector": "Financials",
        "index": "sp600"
    },
    "SF": {
        "name": "Stifel",
        "sector": "Financials",
        "index": "sp400"
    },
    "SFBS": {
        "name": "ServisFirst Bancshares, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "SFM": {
        "name": "Sprouts Farmers Market",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "SFNC": {
        "name": "Simmons First National Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "SGI": {
        "name": "Somnigroup International",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "SHAK": {
        "name": "Shake Shack, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SHC": {
        "name": "Sotera Health",
        "sector": "Health Care",
        "index": "sp400"
    },
    "SHEN": {
        "name": "Shenandoah Telecommunications Co",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "SHO": {
        "name": "Sunstone Hotel Investors, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "SHOO": {
        "name": "Steven Madden, Ltd.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SHW": {
        "name": "Sherwin-Williams",
        "sector": "Materials",
        "index": "sp500"
    },
    "SIG": {
        "name": "Signet Jewelers",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SIGI": {
        "name": "Selective Insurance Group",
        "sector": "Financials",
        "index": "sp400"
    },
    "SIRI": {
        "name": "SiriusXM",
        "sector": "Communication Services",
        "index": "sp400"
    },
    "SITM": {
        "name": "SiTime",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "SJM": {
        "name": "J.M. Smucker Company (The)",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "SKT": {
        "name": "Tanger Factory Outlet Centers, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "SKY": {
        "name": "Champion Homes, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SKYW": {
        "name": "SkyWest, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "SLAB": {
        "name": "Silicon Labs",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "SLB": {
        "name": "Schlumberger",
        "sector": "Energy",
        "index": "sp500"
    },
    "SLG": {
        "name": "SL Green Realty",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "SLGN": {
        "name": "Silgan Holdings",
        "sector": "Materials",
        "index": "sp400"
    },
    "SLM": {
        "name": "SLM Corp",
        "sector": "Financials",
        "index": "sp400"
    },
    "SLVM": {
        "name": "Sylvamo Corp.",
        "sector": "Materials",
        "index": "sp600"
    },
    "SM": {
        "name": "SM Energy Company",
        "sector": "Energy",
        "index": "sp600"
    },
    "SMCI": {
        "name": "Supermicro",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "SMG": {
        "name": "Scotts Miracle-Gro Company",
        "sector": "Materials",
        "index": "sp400"
    },
    "SMP": {
        "name": "Standard Motor Products, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SMPL": {
        "name": "Simply Good Foods Company",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "SMTC": {
        "name": "Semtech",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "SN": {
        "name": "SharkNinja",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "SNA": {
        "name": "Snap-on",
        "sector": "Industrials",
        "index": "sp500"
    },
    "SNDK": {
        "name": "Sandisk",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "SNDR": {
        "name": "Schneider National",
        "sector": "Industrials",
        "index": "sp600"
    },
    "SNEX": {
        "name": "StoneX Group Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "SNPS": {
        "name": "Synopsys",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "SNX": {
        "name": "TD Synnex",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "SO": {
        "name": "Southern Company",
        "sector": "Utilities",
        "index": "sp500"
    },
    "SOLS": {
        "name": "Solstice Advanced Materials",
        "sector": "Materials",
        "index": "sp400"
    },
    "SOLV": {
        "name": "Solventum",
        "sector": "Health Care",
        "index": "sp500"
    },
    "SON": {
        "name": "Sonoco",
        "sector": "Materials",
        "index": "sp400"
    },
    "SONO": {
        "name": "Sonos, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "SPG": {
        "name": "Simon Property Group",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "SPGI": {
        "name": "S&P Global",
        "sector": "Financials",
        "index": "sp500"
    },
    "SPHR": {
        "name": "Sphere Entertainment",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "SPNT": {
        "name": "SiriusPoint Ltd.",
        "sector": "Financials",
        "index": "sp600"
    },
    "SPSC": {
        "name": "SPS Commerce, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "SPXC": {
        "name": "SPX Technologies",
        "sector": "Industrials",
        "index": "sp400"
    },
    "SR": {
        "name": "Spire",
        "sector": "Utilities",
        "index": "sp400"
    },
    "SRE": {
        "name": "Sempra",
        "sector": "Utilities",
        "index": "sp500"
    },
    "SRPT": {
        "name": "Sarepta Therapeutics",
        "sector": "Health Care",
        "index": "sp600"
    },
    "SSB": {
        "name": "South State Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "SSD": {
        "name": "Simpson Manufacturing",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ST": {
        "name": "Sensata Technologies",
        "sector": "Industrials",
        "index": "sp400"
    },
    "STAA": {
        "name": "STAAR Surgical Company",
        "sector": "Health Care",
        "index": "sp600"
    },
    "STAG": {
        "name": "STAG Industrial",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "STBA": {
        "name": "S&T Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "STC": {
        "name": "Stewart Information Services Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "STE": {
        "name": "Steris",
        "sector": "Health Care",
        "index": "sp500"
    },
    "STEL": {
        "name": "Stellar Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "STEP": {
        "name": "StepStone Group",
        "sector": "Financials",
        "index": "sp600"
    },
    "STLD": {
        "name": "Steel Dynamics",
        "sector": "Materials",
        "index": "sp500"
    },
    "STRA": {
        "name": "Strategic Education, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "STRL": {
        "name": "Sterling Infrastructure",
        "sector": "Industrials",
        "index": "sp400"
    },
    "STT": {
        "name": "State Street Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "STWD": {
        "name": "Starwood Property Trust",
        "sector": "Financials",
        "index": "sp400"
    },
    "STX": {
        "name": "Seagate Technology",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "STZ": {
        "name": "Constellation Brands",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "SUPN": {
        "name": "Supernus Pharmaceuticals, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "SW": {
        "name": "Smurfit Westrock",
        "sector": "Materials",
        "index": "sp500"
    },
    "SWK": {
        "name": "Stanley Black & Decker",
        "sector": "Industrials",
        "index": "sp500"
    },
    "SWKS": {
        "name": "Skyworks Solutions",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "SWX": {
        "name": "Southwest Gas Corp",
        "sector": "Utilities",
        "index": "sp400"
    },
    "SXI": {
        "name": "Standex International Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "SXT": {
        "name": "Sensient Technologies",
        "sector": "Materials",
        "index": "sp600"
    },
    "SYF": {
        "name": "Synchrony Financial",
        "sector": "Financials",
        "index": "sp500"
    },
    "SYK": {
        "name": "Stryker Corporation",
        "sector": "Health Care",
        "index": "sp500"
    },
    "SYNA": {
        "name": "Synaptics",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "SYY": {
        "name": "Sysco",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "T": {
        "name": "AT&T",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "TALO": {
        "name": "Talos Energy, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "TAP": {
        "name": "Molson Coors Beverage Company",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "TBBK": {
        "name": "The Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "TCBI": {
        "name": "Texas Capital Bancshares",
        "sector": "Financials",
        "index": "sp400"
    },
    "TDC": {
        "name": "Teradata",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "TDG": {
        "name": "TransDigm Group",
        "sector": "Industrials",
        "index": "sp500"
    },
    "TDS": {
        "name": "Telephone and Data Systems, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "TDW": {
        "name": "Tidewater, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "TDY": {
        "name": "Teledyne Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "TECH": {
        "name": "Bio-Techne",
        "sector": "Health Care",
        "index": "sp500"
    },
    "TEL": {
        "name": "TE Connectivity",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "TER": {
        "name": "Teradyne",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "TEX": {
        "name": "Terex",
        "sector": "Industrials",
        "index": "sp400"
    },
    "TFC": {
        "name": "Truist Financial",
        "sector": "Financials",
        "index": "sp500"
    },
    "TFIN": {
        "name": "Triumph Bancorp, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "TFX": {
        "name": "Teleflex",
        "sector": "Health Care",
        "index": "sp600"
    },
    "TGT": {
        "name": "Target Corporation",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "TGTX": {
        "name": "TG Therapeutics, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "THC": {
        "name": "Tenet Health",
        "sector": "Health Care",
        "index": "sp400"
    },
    "THG": {
        "name": "Hanover Insurance",
        "sector": "Financials",
        "index": "sp400"
    },
    "THO": {
        "name": "Thor Industries",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "THRM": {
        "name": "Gentherm Incorporated",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "TILE": {
        "name": "Interface, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "TJX": {
        "name": "TJX Companies",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "TKO": {
        "name": "TKO Group Holdings",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "TKR": {
        "name": "Timken",
        "sector": "Industrials",
        "index": "sp400"
    },
    "TLN": {
        "name": "Talen Energy",
        "sector": "Utilities",
        "index": "sp400"
    },
    "TMDX": {
        "name": "TransMedics Group, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "TMHC": {
        "name": "Taylor Morrison",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "TMO": {
        "name": "Thermo Fisher Scientific",
        "sector": "Health Care",
        "index": "sp500"
    },
    "TMP": {
        "name": "Tompkins Financial Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "TMUS": {
        "name": "T-Mobile US",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "TNC": {
        "name": "Tennant Company",
        "sector": "Industrials",
        "index": "sp600"
    },
    "TNDM": {
        "name": "Tandem Diabetes Care",
        "sector": "Health Care",
        "index": "sp600"
    },
    "TNL": {
        "name": "Travel + Leisure Co.",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "TOL": {
        "name": "Toll Brothers",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "TPL": {
        "name": "Texas Pacific Land Corporation",
        "sector": "Energy",
        "index": "sp500"
    },
    "TPR": {
        "name": "Tapestry, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "TR": {
        "name": "Tootsie Roll Industries, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "TREX": {
        "name": "Trex",
        "sector": "Industrials",
        "index": "sp400"
    },
    "TRGP": {
        "name": "Targa Resources",
        "sector": "Energy",
        "index": "sp500"
    },
    "TRIP": {
        "name": "TripAdvisor",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "TRMB": {
        "name": "Trimble Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "TRMK": {
        "name": "Trustmark Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "TRN": {
        "name": "Trinity Industries, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "TRNO": {
        "name": "Terreno Realty Corporation",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "TROW": {
        "name": "T. Rowe Price",
        "sector": "Financials",
        "index": "sp500"
    },
    "TRST": {
        "name": "TrustCo Bank Corp NY",
        "sector": "Financials",
        "index": "sp600"
    },
    "TRU": {
        "name": "TransUnion",
        "sector": "Industrials",
        "index": "sp400"
    },
    "TRUP": {
        "name": "Trupanion",
        "sector": "Financials",
        "index": "sp600"
    },
    "TRV": {
        "name": "Travelers Companies (The)",
        "sector": "Financials",
        "index": "sp500"
    },
    "TSCO": {
        "name": "Tractor Supply",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "TSLA": {
        "name": "Tesla, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "TSN": {
        "name": "Tyson Foods",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "TT": {
        "name": "Trane Technologies",
        "sector": "Industrials",
        "index": "sp500"
    },
    "TTC": {
        "name": "Toro",
        "sector": "Industrials",
        "index": "sp400"
    },
    "TTD": {
        "name": "Trade Desk (The)",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "TTEK": {
        "name": "Tetra Tech",
        "sector": "Industrials",
        "index": "sp400"
    },
    "TTMI": {
        "name": "TTM Technologies",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "TTWO": {
        "name": "Take-Two Interactive",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "TWLO": {
        "name": "Twilio",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "TWO": {
        "name": "Two Harbors Investment Corp.",
        "sector": "Financials",
        "index": "sp600"
    },
    "TXN": {
        "name": "Texas Instruments",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "TXNM": {
        "name": "TXNM Energy",
        "sector": "Utilities",
        "index": "sp400"
    },
    "TXRH": {
        "name": "Texas Roadhouse",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "TXT": {
        "name": "Textron",
        "sector": "Industrials",
        "index": "sp500"
    },
    "TYL": {
        "name": "Tyler Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "UA": {
        "name": "Under Armour (Class C)",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "UAA": {
        "name": "Under Armour (Class A)",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "UAL": {
        "name": "United Airlines Holdings",
        "sector": "Industrials",
        "index": "sp500"
    },
    "UBER": {
        "name": "Uber",
        "sector": "Industrials",
        "index": "sp500"
    },
    "UBSI": {
        "name": "United Bankshares",
        "sector": "Financials",
        "index": "sp400"
    },
    "UCB": {
        "name": "United Community Banks, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "UCTT": {
        "name": "Ultra Clean Holdings, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "UDR": {
        "name": "UDR, Inc.",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "UE": {
        "name": "Urban Edge Properties",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "UFCS": {
        "name": "United Fire Group, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "UFPI": {
        "name": "UFP Industries",
        "sector": "Industrials",
        "index": "sp400"
    },
    "UFPT": {
        "name": "UFP Technologies, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "UGI": {
        "name": "UGI Corp",
        "sector": "Utilities",
        "index": "sp400"
    },
    "UHS": {
        "name": "Universal Health Services",
        "sector": "Health Care",
        "index": "sp500"
    },
    "UHT": {
        "name": "Universal Health Realty Income Trust",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "ULS": {
        "name": "UL Solutions",
        "sector": "Industrials",
        "index": "sp400"
    },
    "ULTA": {
        "name": "Ulta Beauty",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "UMBF": {
        "name": "UMB Financial Corp.",
        "sector": "Financials",
        "index": "sp400"
    },
    "UNF": {
        "name": "UniFirst Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "UNFI": {
        "name": "United Natural Foods Inc",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "UNH": {
        "name": "UnitedHealth Group",
        "sector": "Health Care",
        "index": "sp500"
    },
    "UNIT": {
        "name": "Uniti Group",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "UNM": {
        "name": "Unum",
        "sector": "Financials",
        "index": "sp400"
    },
    "UNP": {
        "name": "Union Pacific Corporation",
        "sector": "Industrials",
        "index": "sp500"
    },
    "UPBD": {
        "name": "Upbound Group, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "UPS": {
        "name": "United Parcel Service",
        "sector": "Industrials",
        "index": "sp500"
    },
    "UPWK": {
        "name": "Upwork, Inc.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "URBN": {
        "name": "Urban Outfitters, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "URI": {
        "name": "United Rentals",
        "sector": "Industrials",
        "index": "sp500"
    },
    "USB": {
        "name": "U.S. Bancorp",
        "sector": "Financials",
        "index": "sp500"
    },
    "USFD": {
        "name": "US Foods",
        "sector": "Consumer Staples",
        "index": "sp400"
    },
    "USPH": {
        "name": "U.S. Physical Therapy, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "UTHR": {
        "name": "United Therapeutics",
        "sector": "Health Care",
        "index": "sp400"
    },
    "UTI": {
        "name": "Universal Technical Institute",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "UTL": {
        "name": "Unitil Corporation",
        "sector": "Utilities",
        "index": "sp600"
    },
    "UVV": {
        "name": "Universal Corporation",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "V": {
        "name": "Visa Inc.",
        "sector": "Financials",
        "index": "sp500"
    },
    "VAC": {
        "name": "Marriott Vacations Worldwide",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "VAL": {
        "name": "Valaris",
        "sector": "Energy",
        "index": "sp400"
    },
    "VC": {
        "name": "Visteon",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "VCEL": {
        "name": "Vericel",
        "sector": "Health Care",
        "index": "sp600"
    },
    "VCTR": {
        "name": "Victory Capital Holdings, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "VCYT": {
        "name": "Veracyte, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "VECO": {
        "name": "Veeco Instruments Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "VEEV": {
        "name": "Veeva Systems",
        "sector": "Health Care",
        "index": "sp500"
    },
    "VFC": {
        "name": "VF Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "VGNT": {
        "name": "Versigent PLC",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "VIAV": {
        "name": "Viavi Solutions",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "VICI": {
        "name": "Vici Properties",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "VICR": {
        "name": "Vicor Corporation",
        "sector": "Industrials",
        "index": "sp400"
    },
    "VIR": {
        "name": "Vir Biotechnology, Inc.",
        "sector": "Health Care",
        "index": "sp600"
    },
    "VIRT": {
        "name": "Virtu Financial, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "VITL": {
        "name": "Vital Farms, Inc.",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "VLO": {
        "name": "Valero Energy",
        "sector": "Energy",
        "index": "sp500"
    },
    "VLTO": {
        "name": "Veralto",
        "sector": "Industrials",
        "index": "sp500"
    },
    "VLY": {
        "name": "Valley Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "VMC": {
        "name": "Vulcan Materials Company",
        "sector": "Materials",
        "index": "sp500"
    },
    "VMI": {
        "name": "Valmont Industries",
        "sector": "Industrials",
        "index": "sp400"
    },
    "VNO": {
        "name": "Vornado Realty Trust",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "VNOM": {
        "name": "Viper Energy",
        "sector": "Energy",
        "index": "sp400"
    },
    "VNT": {
        "name": "Vontier",
        "sector": "Information Technology",
        "index": "sp400"
    },
    "VOYA": {
        "name": "Voya Financial",
        "sector": "Financials",
        "index": "sp400"
    },
    "VRRM": {
        "name": "Verra Mobility Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "VRSK": {
        "name": "Verisk Analytics",
        "sector": "Industrials",
        "index": "sp500"
    },
    "VRSN": {
        "name": "Verisign",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "VRT": {
        "name": "Vertiv",
        "sector": "Industrials",
        "index": "sp500"
    },
    "VRTS": {
        "name": "Virtus Investment Partners, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "VRTX": {
        "name": "Vertex Pharmaceuticals",
        "sector": "Health Care",
        "index": "sp500"
    },
    "VSAT": {
        "name": "Viasat, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "VSEC": {
        "name": "VSE Corporation",
        "sector": "Industrials",
        "index": "sp600"
    },
    "VSH": {
        "name": "Vishay Intertechnology",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "VSNT": {
        "name": "Versant Media Group, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "VST": {
        "name": "Vistra Corp.",
        "sector": "Utilities",
        "index": "sp500"
    },
    "VSTS": {
        "name": "Vestis",
        "sector": "Industrials",
        "index": "sp600"
    },
    "VSXY": {
        "name": "Victoria's Secret",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "VTOL": {
        "name": "Bristow Group Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "VTR": {
        "name": "Ventas",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "VTRS": {
        "name": "Viatris",
        "sector": "Health Care",
        "index": "sp500"
    },
    "VVV": {
        "name": "Valvoline",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "VYX": {
        "name": "NCR Voyix",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "VZ": {
        "name": "Verizon",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "WAB": {
        "name": "Wabtec",
        "sector": "Industrials",
        "index": "sp500"
    },
    "WABC": {
        "name": "Westamerica Bank",
        "sector": "Financials",
        "index": "sp600"
    },
    "WAFD": {
        "name": "WaFd, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "WAL": {
        "name": "Western Alliance Bancorporation",
        "sector": "Financials",
        "index": "sp400"
    },
    "WAT": {
        "name": "Waters Corporation",
        "sector": "Health Care",
        "index": "sp500"
    },
    "WAY": {
        "name": "Waystar Holding Corp",
        "sector": "Health Care",
        "index": "sp600"
    },
    "WBD": {
        "name": "Warner Bros. Discovery",
        "sector": "Communication Services",
        "index": "sp500"
    },
    "WBS": {
        "name": "Webster Bank",
        "sector": "Financials",
        "index": "sp400"
    },
    "WCC": {
        "name": "WESCO International",
        "sector": "Industrials",
        "index": "sp400"
    },
    "WD": {
        "name": "Walker & Dunlop, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "WDAY": {
        "name": "Workday, Inc.",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "WDC": {
        "name": "Western Digital",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "WDFC": {
        "name": "WD-40 Company",
        "sector": "Consumer Staples",
        "index": "sp600"
    },
    "WEC": {
        "name": "WEC Energy Group",
        "sector": "Utilities",
        "index": "sp500"
    },
    "WELL": {
        "name": "Welltower",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "WEN": {
        "name": "The Wendy's Company",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "WERN": {
        "name": "Werner Enterprises",
        "sector": "Industrials",
        "index": "sp600"
    },
    "WEX": {
        "name": "WEX Inc.",
        "sector": "Financials",
        "index": "sp400"
    },
    "WFC": {
        "name": "Wells Fargo",
        "sector": "Financials",
        "index": "sp500"
    },
    "WFRD": {
        "name": "Weatherford International",
        "sector": "Energy",
        "index": "sp400"
    },
    "WGO": {
        "name": "Winnebago Industries, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "WH": {
        "name": "Wyndham Hotels & Resorts",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "WHD": {
        "name": "Cactus, Inc.",
        "sector": "Energy",
        "index": "sp600"
    },
    "WHR": {
        "name": "Whirlpool Corporation",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "WINA": {
        "name": "Winmark",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "WING": {
        "name": "Wingstop",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "WKC": {
        "name": "World Kinect Corporation",
        "sector": "Energy",
        "index": "sp600"
    },
    "WLK": {
        "name": "Westlake Corporation",
        "sector": "Materials",
        "index": "sp400"
    },
    "WLY": {
        "name": "John Wiley & Sons",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "WM": {
        "name": "Waste Management",
        "sector": "Industrials",
        "index": "sp500"
    },
    "WMB": {
        "name": "Williams Companies",
        "sector": "Energy",
        "index": "sp500"
    },
    "WMG": {
        "name": "Warner Music Group",
        "sector": "Communication Services",
        "index": "sp400"
    },
    "WMS": {
        "name": "Advanced Drainage Systems",
        "sector": "Industrials",
        "index": "sp400"
    },
    "WMT": {
        "name": "Walmart",
        "sector": "Consumer Staples",
        "index": "sp500"
    },
    "WOR": {
        "name": "Worthington Enterprises",
        "sector": "Industrials",
        "index": "sp600"
    },
    "WPC": {
        "name": "W. P. Carey",
        "sector": "Real Estate",
        "index": "sp400"
    },
    "WRB": {
        "name": "W. R. Berkley Corporation",
        "sector": "Financials",
        "index": "sp500"
    },
    "WRLD": {
        "name": "World Acceptance Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "WS": {
        "name": "Worthington Steel",
        "sector": "Materials",
        "index": "sp600"
    },
    "WSC": {
        "name": "WillScot Holdings Corp.",
        "sector": "Industrials",
        "index": "sp600"
    },
    "WSFS": {
        "name": "WSFS Financial Corporation",
        "sector": "Financials",
        "index": "sp600"
    },
    "WSM": {
        "name": "Williams-Sonoma, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "WSO": {
        "name": "Watsco",
        "sector": "Industrials",
        "index": "sp400"
    },
    "WSR": {
        "name": "Whitestone REIT",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "WST": {
        "name": "West Pharmaceutical Services",
        "sector": "Health Care",
        "index": "sp500"
    },
    "WT": {
        "name": "WisdomTree Investments, Inc.",
        "sector": "Financials",
        "index": "sp600"
    },
    "WTFC": {
        "name": "Wintrust Financial",
        "sector": "Financials",
        "index": "sp400"
    },
    "WTRG": {
        "name": "Essential Utilities",
        "sector": "Utilities",
        "index": "sp400"
    },
    "WTS": {
        "name": "Watts Water Technologies",
        "sector": "Industrials",
        "index": "sp400"
    },
    "WTW": {
        "name": "Willis Towers Watson",
        "sector": "Financials",
        "index": "sp500"
    },
    "WU": {
        "name": "Western Union",
        "sector": "Financials",
        "index": "sp600"
    },
    "WWD": {
        "name": "Woodward, Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "WWW": {
        "name": "Wolverine World Wide, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "WY": {
        "name": "Weyerhaeuser",
        "sector": "Real Estate",
        "index": "sp500"
    },
    "WYNN": {
        "name": "Wynn Resorts",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "XEL": {
        "name": "Xcel Energy",
        "sector": "Utilities",
        "index": "sp500"
    },
    "XHR": {
        "name": "Xenia Hotels & Resorts, Inc.",
        "sector": "Real Estate",
        "index": "sp600"
    },
    "XNCR": {
        "name": "Xencor Inc",
        "sector": "Health Care",
        "index": "sp600"
    },
    "XOM": {
        "name": "ExxonMobil",
        "sector": "Energy",
        "index": "sp500"
    },
    "XPEL": {
        "name": "XPEL, Inc.",
        "sector": "Consumer Discretionary",
        "index": "sp600"
    },
    "XPO": {
        "name": "XPO, Inc.",
        "sector": "Industrials",
        "index": "sp400"
    },
    "XRAY": {
        "name": "Dentsply Sirona",
        "sector": "Health Care",
        "index": "sp400"
    },
    "XYL": {
        "name": "Xylem Inc.",
        "sector": "Industrials",
        "index": "sp500"
    },
    "XYZ": {
        "name": "Block, Inc.",
        "sector": "Financials",
        "index": "sp500"
    },
    "YELP": {
        "name": "Yelp, Inc.",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "YETI": {
        "name": "Yeti Holdings",
        "sector": "Consumer Discretionary",
        "index": "sp400"
    },
    "YOU": {
        "name": "Clear Secure, Inc.",
        "sector": "Information Technology",
        "index": "sp600"
    },
    "YUM": {
        "name": "Yum! Brands",
        "sector": "Consumer Discretionary",
        "index": "sp500"
    },
    "ZBH": {
        "name": "Zimmer Biomet",
        "sector": "Health Care",
        "index": "sp500"
    },
    "ZBRA": {
        "name": "Zebra Technologies",
        "sector": "Information Technology",
        "index": "sp500"
    },
    "ZD": {
        "name": "Ziff Davis",
        "sector": "Communication Services",
        "index": "sp600"
    },
    "ZION": {
        "name": "Zions Bancorporation",
        "sector": "Financials",
        "index": "sp400"
    },
    "ZTS": {
        "name": "Zoetis",
        "sector": "Health Care",
        "index": "sp500"
    },
    "ZWS": {
        "name": "Zurn Elkay Water Solutions Corp.",
        "sector": "Industrials",
        "index": "sp600"
    },
}


UNIVERSE_TICKERS: list[str] = sorted(UNIVERSE_META)


def resolve_universe() -> list[str]:
    """Liefert die statische US-Symbolliste (sortiert). Keine Netzabfrage."""
    return sorted(UNIVERSE_META)


def company_name(ticker: str) -> str | None:
    """Firmenname zum Ticker, oder None wenn nicht im Universum."""
    m = UNIVERSE_META.get((ticker or "").strip().upper())
    return m["name"] if m else None


def gics_sector(ticker: str) -> str | None:
    """GICS-Sektor zum Ticker, oder None wenn nicht im Universum."""
    m = UNIVERSE_META.get((ticker or "").strip().upper())
    return m["sector"] if m else None


def index_membership(ticker: str) -> str | None:
    """Index-Zugehoerigkeit (sp500/sp400/sp600), oder None wenn unbekannt."""
    m = UNIVERSE_META.get((ticker or "").strip().upper())
    return m["index"] if m else None
