"""
test_faza4.py — Testi za Fazo 4: lead magnet matching, leadi, double opt-in.
"""

import db
import panoge
import pregled


def setup_module():
    db.init_db()


# ---------------------------------------------------------------------------
# Panoge — besede in preslikava v kategorije
# ---------------------------------------------------------------------------

def test_besede_za_izbrana_podpodrocja():
    besede = panoge.vse_besede_za_panogo("gradbenistvo", ["Fasade in toplotne izolacije"])
    assert "fasad" in besede
    # Besede drugih podpodročij niso vključene
    assert "streh" not in besede


def test_besede_vsa_podpodrocja_ko_ni_izbire():
    besede = panoge.vse_besede_za_panogo("gradbenistvo", None)
    assert "fasad" in besede and "streh" in besede


def test_kategorije_za_panogo():
    assert panoge.kategorije_za_panogo("it") == ["IT & Software"]
    assert panoge.kategorije_za_panogo("drugo") == []


# ---------------------------------------------------------------------------
# Lead magnet matching
# ---------------------------------------------------------------------------

def test_najdi_zamujena_po_podpodrocju():
    db.shrani_narocila([
        {"pjn": "JN-F4-001", "narocnik": "OŠ Koper", "naziv": "Sanacija fasade na osnovni šoli",
         "vrsta": "Gradnja", "kategorije": ["Gradbeništvo"]},
        {"pjn": "JN-F4-002", "narocnik": "MF", "naziv": "Dobava pisarniškega materiala",
         "vrsta": "Blago", "kategorije": ["Drugo"]},
    ])
    rezultati = pregled.najdi_zamujena("gradbenistvo", ["Fasade in toplotne izolacije"], "")
    pjni = [r["pjn"] for r in rezultati]
    assert "JN-F4-001" in pjni
    assert "JN-F4-002" not in pjni


def test_najdi_zamujena_prosto_besedilo():
    db.shrani_narocila([
        {"pjn": "JN-F4-003", "narocnik": "Občina X", "naziv": "Rekonstrukcija kanalizacije",
         "vrsta": "Gradnja", "kategorije": ["Gradbeništvo"]},
    ])
    # Brez izbranih podpodročij, samo prosto besedilo
    rezultati = pregled.najdi_zamujena("gradbenistvo", [], "kanalizacija in vodovod")
    assert any(r["pjn"] == "JN-F4-003" for r in rezultati)


def test_iskalne_besede_izlocijo_kratke_in_stop():
    besede = pregled.sestavi_iskalne_besede("drugo", [], "mi delamo razne stvari za")
    # "mi", "za" prekratke; "delamo" je stop-beseda
    assert "delamo" not in besede
    assert "mi" not in besede


# ---------------------------------------------------------------------------
# Leadi
# ---------------------------------------------------------------------------

def test_shrani_lead():
    lead_id = db.shrani_lead("lead@test.si", "it", "razvoj aplikacij", ["Razvoj programske opreme in aplikacij"])
    assert lead_id > 0


# ---------------------------------------------------------------------------
# Double opt-in
# ---------------------------------------------------------------------------

def test_opt_in_flow():
    db.registriraj_uporabnika(
        "optin@test.si", "gradbenistvo", "fasade", "pro",
        ["Gradbeništvo"], "token-abc",
    )
    # Pred potrditvijo ni aktiven
    aktivni = [u["email"] for u in db.poberi_aktivne_uporabnike()]
    assert "optin@test.si" not in aktivni

    # Potrditev z veljavnim tokenom aktivira
    email = db.potrdi_uporabnika("token-abc")
    assert email == "optin@test.si"
    aktivni = [u["email"] for u in db.poberi_aktivne_uporabnike()]
    assert "optin@test.si" in aktivni


def test_opt_in_neveljaven_token():
    assert db.potrdi_uporabnika("ne-obstaja") is None
    assert db.potrdi_uporabnika("") is None


def test_ponovna_registracija_posodobi_token():
    db.registriraj_uporabnika("ponovni@test.si", "it", "opis1", "osnovni", ["IT & Software"], "tok-1")
    db.registriraj_uporabnika("ponovni@test.si", "it", "opis2", "pro", ["IT & Software"], "tok-2")
    # Star token ne velja več, nov velja
    assert db.potrdi_uporabnika("tok-1") is None
    assert db.potrdi_uporabnika("tok-2") == "ponovni@test.si"
