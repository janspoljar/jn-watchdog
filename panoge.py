"""
panoge.py — Panoge in podpodročja za lead magnet / profil stranke (Faza 4).

Vsaka panoga ima:
- ime:      prikazno ime (slovensko, za uporabnika),
- ikona:    emoji za prikaz,
- predlogi: seznam podpodročij, ki jih uporabnik odkljuka — vsako ima
            'label' (kar vidi uporabnik) in 'besede' (ASCII-normalizirani
            stemi ključnih besed za matching).

Struktura sledi logiki CPV klasifikacije (npr. divizija 45 gradbena dela,
72 IT storitve, 90 čiščenje in okolje), a v človeku berljivi obliki, da
uporabnik prepozna vse, kar dejansko počne, in zgradi širok profil.

POMEMBNO: 'besede' so v ASCII-normalizirani obliki (brez šumnikov, lowercase),
ker se matching izvaja prek scraper._normaliziraj() nad nazivom naročila.
Stemi naj bodo kratki, da ujamejo različne sklone (npr. "fasad" ujame
"fasada", "fasade", "fasadna").
"""

# Vrstni red določa prikaz na strani; prve tri so prioritetne panoge.
PANOGE = {
    "gradbenistvo": {
        "ime": "Gradbeništvo",
        "ikona": "🏗️",
        "predlogi": [
            {"label": "Novogradnje objektov", "besede": ["novogradnj", "gradnja objekt", "izgradnj"]},
            {"label": "Rekonstrukcije in adaptacije", "besede": ["rekonstrukcij", "adaptacij", "prenov"]},
            {"label": "Sanacije in obnove", "besede": ["sanacij", "obnov"]},
            {"label": "Fasade in toplotne izolacije", "besede": ["fasad", "toplotna izolacij", "omet"]},
            {"label": "Strehe in krovska dela", "besede": ["streh", "krovsk", "kritin"]},
            {"label": "Notranja dela, suhomontaža, mavčne stene", "besede": ["notranja dela", "suhomontaz", "mavcn", "predelne sten", "knauf"]},
            {"label": "Elektroinštalacije", "besede": ["elektroinstalacij", "elektricne instalacij"]},
            {"label": "Vodovodne in kanalizacijske inštalacije", "besede": ["vodovodne instalacij", "vodovod", "kanalizacij"]},
            {"label": "Ogrevanje, klima, prezračevanje", "besede": ["ogrevanj", "prezracevanj", "klimatizacij", "strojne instalacij"]},
            {"label": "Ceste in asfaltiranje", "besede": ["cest", "asfalt", "plocnik", "kolesarsk"]},
            {"label": "Komunalna infrastruktura", "besede": ["komunaln", "kanalizacij", "vodovod", "plinovod"]},
            {"label": "Mostovi in inženirski objekti", "besede": ["most", "viadukt", "inzenirsk"]},
            {"label": "Zemeljska, izkopna in rušitvena dela", "besede": ["zemeljsk", "izkop", "gradbena jam", "rusitv", "rusenj"]},
            {"label": "Betonska in armiranobetonska dela", "besede": ["betonsk", "armatur", "armiranobetonsk"]},
            {"label": "Tlakovanje in zunanja ureditev", "besede": ["tlakovan", "zunanja ureditev", "parkovn", "ureditev okolic"]},
            {"label": "Stavbno pohištvo (okna, vrata)", "besede": ["stavbno pohistv", "okn", "vrata", "sencil"]},
            {"label": "Gradbeni nadzor in projektiranje", "besede": ["gradbeni nadzor", "projektiranj", "projektna dokumentacij", "idejna zasnov"]},
        ],
    },
    "it": {
        "ime": "IT & programska oprema",
        "ikona": "💻",
        "predlogi": [
            {"label": "Razvoj programske opreme in aplikacij", "besede": ["razvoj programsk", "aplikacij", "razvoj aplikacij"]},
            {"label": "Spletne strani in portali", "besede": ["spletna stran", "spletni portal", "spletisc", "prenova spletn"]},
            {"label": "Informacijski sistemi", "besede": ["informacijski sistem", "programska resitev", "programski sistem"]},
            {"label": "Vzdrževanje IT sistemov", "besede": ["vzdrzevanje sistem", "vzdrzevanje programsk", "vzdrzevanje informacijsk"]},
            {"label": "Licence in programska oprema", "besede": ["licenc", "programsk oprema", "narocnina na programsk"]},
            {"label": "Strežniki in infrastruktura", "besede": ["streznik", "podatkovni center", "gostovanj", "racunalniska infrastruktur"]},
            {"label": "Omrežja in telekomunikacije", "besede": ["omrezj", "mrezna oprema", "telekomunikacij"]},
            {"label": "Kibernetska varnost", "besede": ["kibernetsk", "informacijska varnost"]},
            {"label": "Računalniška oprema", "besede": ["racunalnik", "prenosnik", "monitor", "racunalniska oprema"]},
            {"label": "Tiskalniki in potrošni material", "besede": ["tiskalnik", "kartus", "toner"]},
            {"label": "Digitalizacija in e-storitve", "besede": ["digitalizacij", "e-storit", "e-uprav", "elektronsko poslovanj"]},
            {"label": "Podatkovne baze in analitika", "besede": ["podatkovn", "baza podatkov", "analitik", "podatkovni model"]},
        ],
    },
    "ciscenje": {
        "ime": "Čiščenje & vzdrževanje",
        "ikona": "🧹",
        "predlogi": [
            {"label": "Čiščenje poslovnih prostorov", "besede": ["ciscenj prostor", "ciscenje pisarn", "ciscenje poslovn"]},
            {"label": "Čiščenje zdravstvenih ustanov", "besede": ["ciscenje bolnisnic", "ciscenje zdravstven", "ciscenje doma"]},
            {"label": "Čiščenje šol in vrtcev", "besede": ["ciscenje sol", "ciscenje vrtc", "ciscenje izobrazeval"]},
            {"label": "Zunanje čiščenje in pometanje", "besede": ["pometanj", "ciscenje zunanjih povrsin", "ciscenje cest"]},
            {"label": "Zimska služba", "besede": ["zimska sluzb", "pluzenj", "posipanj", "zimsko vzdrzevanj"]},
            {"label": "Vzdrževanje objektov (hišnik)", "besede": ["vzdrzevanje objekt", "hisnisk", "tekoce vzdrzevanj"]},
            {"label": "Urejanje zelenic in okolice", "besede": ["kosnj", "zelenic", "urejanje okolic", "vrtnarsk", "vzdrzevanje zelen"]},
            {"label": "Varovanje in receptorska služba", "besede": ["varovanj", "fizicno varovanj", "receptorsk", "varnostna sluzb"]},
            {"label": "Dezinfekcija, dezinsekcija, deratizacija", "besede": ["dezinfekcij", "dezinsekcij", "deratizacij", "razkuzevanj"]},
            {"label": "Odvoz in ravnanje z odpadki", "besede": ["odvoz odpadk", "ravnanje z odpadk", "smetarsk", "zbiranje odpadk"]},
            {"label": "Pranje perila", "besede": ["pranje perila", "pralnic", "najem perila"]},
        ],
    },
    "zdravstvo": {
        "ime": "Zdravstvo & farmacija",
        "ikona": "🏥",
        "predlogi": [
            {"label": "Zdravila in farmacevtski izdelki", "besede": ["zdravil", "farmacevtsk"]},
            {"label": "Medicinski pripomočki", "besede": ["medicinsk pripomoc", "sanitetn"]},
            {"label": "Medicinska in diagnostična oprema", "besede": ["medicinsk oprema", "ultrazvok", "rentgen", "diagnosticn"]},
            {"label": "Laboratorijska oprema in reagenti", "besede": ["laboratorij", "reagent"]},
            {"label": "Bolnišnična oprema in postelje", "besede": ["bolnisnic", "bolnisk postelj", "negovaln"]},
            {"label": "Ortopedski pripomočki in implantati", "besede": ["ortopedsk", "implantat", "protez"]},
            {"label": "Sterilizacija", "besede": ["sterilizacij"]},
            {"label": "Reševalna vozila", "besede": ["resevalno vozil", "resevalna vozil"]},
        ],
    },
    "transport": {
        "ime": "Transport & vozila",
        "ikona": "🚌",
        "predlogi": [
            {"label": "Avtobusni prevozi potnikov", "besede": ["avtobus", "prevoz potnik", "javni potniski promet"]},
            {"label": "Šolski prevozi", "besede": ["solski prevoz", "prevoz otrok", "prevoz ucenc"]},
            {"label": "Tovorni promet in dostava", "besede": ["tovorn", "dostav", "prevoz blag"]},
            {"label": "Nakup vozil", "besede": ["nakup vozil", "osebna vozil", "gospodarska vozil", "dobava vozil"]},
            {"label": "Reševalna in gasilska vozila", "besede": ["resevalno vozil", "gasilsk vozil"]},
            {"label": "Goriva", "besede": ["goriv", "bencin", "dizel", "kurilno olje"]},
            {"label": "Servis in vzdrževanje vozil", "besede": ["servis vozil", "vzdrzevanje vozil", "pnevmatik"]},
            {"label": "Posebni prevozi (invalidi, taksi)", "besede": ["taksi prevoz", "prevoz invalid", "posebni prevoz"]},
        ],
    },
    "energetika": {
        "ime": "Energetika",
        "ikona": "⚡",
        "predlogi": [
            {"label": "Dobava električne energije", "besede": ["dobava elektricne energij", "elektricn energij"]},
            {"label": "Elektroinštalacije", "besede": ["elektroinstalacij", "elektro"]},
            {"label": "Javna razsvetljava", "besede": ["razsvetljav", "javna razsvetljav"]},
            {"label": "Sončne elektrarne in fotovoltaika", "besede": ["soncn", "fotovoltaik", "soncna elektrarn"]},
            {"label": "Ogrevanje in toplotne postaje", "besede": ["ogrevanj", "toplotn", "toplovod", "kotlovnic"]},
            {"label": "Zemeljski plin", "besede": ["zemeljski plin", "plinovod", "plin"]},
            {"label": "Transformatorske postaje", "besede": ["transformator", "razdelilna postaj"]},
            {"label": "Energetska sanacija in učinkovitost", "besede": ["energetska sanacij", "energetsk ucinkovit", "obnovljiv"]},
        ],
    },
    "hrana": {
        "ime": "Hrana & catering",
        "ikona": "🍎",
        "predlogi": [
            {"label": "Živila (splošno)", "besede": ["zivil", "prehrambn", "dobava zivil"]},
            {"label": "Sadje in zelenjava", "besede": ["sadj", "zelenjav"]},
            {"label": "Meso in mesni izdelki", "besede": ["meso", "mesn izdelk"]},
            {"label": "Mlečni izdelki", "besede": ["mlecn", "mlek"]},
            {"label": "Kruh in pekovski izdelki", "besede": ["kruh", "pekovsk", "pekarn"]},
            {"label": "Šolska prehrana in catering", "besede": ["solska prehran", "catering", "priprava obrok", "prehran"]},
            {"label": "Ekološka živila", "besede": ["ekolosk zivil", "ekolosk"]},
            {"label": "Pijače", "besede": ["pijac", "napitk"]},
        ],
    },
    "okolje": {
        "ime": "Okolje & voda",
        "ikona": "💧",
        "predlogi": [
            {"label": "Čistilne naprave", "besede": ["cistilna naprav", "cistiln naprav"]},
            {"label": "Vodooskrba in pitna voda", "besede": ["pitna voda", "vodooskrb"]},
            {"label": "Odpadne vode in kanalizacija", "besede": ["odpadne vode", "kanalizacij"]},
            {"label": "Ravnanje z odpadki in reciklaža", "besede": ["ravnanje z odpadk", "reciklaz", "odpadk"]},
            {"label": "Okoljski monitoring in meritve", "besede": ["monitoring", "emisij", "meritve okolj"]},
            {"label": "Sanacija okolja", "besede": ["sanacija okolj", "onesnazen"]},
            {"label": "Urejanje vodotokov (protipoplavno)", "besede": ["vodotok", "vodne ureditv", "protipoplavn"]},
        ],
    },
    "obramba": {
        "ime": "Obramba & varnost",
        "ikona": "🛡️",
        "predlogi": [
            {"label": "Varnostna in zaščitna oprema", "besede": ["varnostna oprema", "zascitna oprema"]},
            {"label": "Osebna varovalna oprema", "besede": ["osebna varovalna oprema", "zascitna sredstv"]},
            {"label": "Gasilska oprema", "besede": ["gasilsk", "gasilska oprema"]},
            {"label": "Vojaška oprema", "besede": ["vojsk", "vojask", "obramb"]},
            {"label": "Orožje in strelivo", "besede": ["orozj", "streliv"]},
            {"label": "Video nadzor in alarmni sistemi", "besede": ["video nadzor", "alarmn", "varnostni sistem"]},
        ],
    },
    "drugo": {
        "ime": "Druga dejavnost",
        "ikona": "📌",
        "predlogi": [],  # samo prosto besedilo
    },
}


# Preslikava panoge -> obstoječa kategorija scraperja (scraper.KATEGORIJE_*).
# Uporablja se v beti: dnevni job filtrira naročila po kategoriji, dokler
# AI matching (Faza 3) ne prevzame personaliziranega ujemanja po profilu.
PANOGA_V_KATEGORIJO = {
    "gradbenistvo": "Gradbeništvo",
    "it": "IT & Software",
    "ciscenje": "Čiščenje & Vzdrževanje",
    "zdravstvo": "Zdravstvo & Farmacija",
    "transport": "Transport & Vozila",
    "energetika": "Energetika",
    "hrana": "Hrana & Catering",
    "okolje": "Okolje & Voda",
    "obramba": "Obramba & Varnost",
    "drugo": None,
}


def kategorije_za_panogo(panoga_key: str) -> list:
    """Vrne seznam kategorij scraperja za panogo (prazen za 'drugo'/neznano)."""
    kat = PANOGA_V_KATEGORIJO.get(panoga_key)
    return [kat] if kat else []


def vse_besede_za_panogo(panoga_key: str, izbrani_labeli: list | None = None) -> list:
    """
    Vrne združen seznam ključnih besed za izbrano panogo.

    Če je izbrani_labeli podan, vrne samo besede odkljukanih podpodročij;
    sicer vrne besede vseh podpodročij panoge (širok zajem).

    Args:
        panoga_key:     ključ panoge (npr. "gradbenistvo").
        izbrani_labeli: seznam izbranih labelov podpodročij ali None.

    Returns:
        Seznam ASCII-normaliziranih stemov (lahko prazen).
    """
    panoga = PANOGE.get(panoga_key)
    if not panoga:
        return []

    besede = []
    for p in panoga["predlogi"]:
        if izbrani_labeli is None or p["label"] in izbrani_labeli:
            besede.extend(p["besede"])
    # Odstrani dvojnike, ohrani vrstni red
    return list(dict.fromkeys(besede))
