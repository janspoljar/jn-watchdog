"""
test_faza3.py — Testi za Fazo 3: profili, matching cache/idempotentnost,
pragova in dedup pri pošiljanju, parsing odgovora modela (z mock API).
"""

import db
import matching


def setup_module():
    db.init_db()


def _ustvari(email, token, paket="pro", panoga="gradbenistvo", izbrani=None):
    """Ustvari potrjenega (aktivnega) uporabnika s profilom. Vrne (uid, pid)."""
    db.registriraj_uporabnika(
        email, panoga, "opis dejavnosti", paket, ["Gradbeništvo"], token,
        izbrani=izbrani or [],
    )
    db.potrdi_uporabnika(token)
    uid = db._id_uporabnika(email)
    pid = [p["id"] for p in db.poberi_aktivne_profile() if p["email"] == email][0]
    return uid, pid


# ---------------------------------------------------------------------------
# Profili
# ---------------------------------------------------------------------------

def test_registracija_ustvari_profil():
    uid, pid = _ustvari("prof@test.si", "tok-prof", izbrani=["Fasade in toplotne izolacije"])
    profili = [p for p in db.poberi_aktivne_profile() if p["email"] == "prof@test.si"]
    assert len(profili) == 1
    assert profili[0]["panoga"] == "gradbenistvo"
    assert "Fasade in toplotne izolacije" in profili[0]["izbrani"]


def test_profil_le_za_aktivne():
    # Neaktiven (nepotrjen) uporabnik ne sme imeti aktivnega profila v izboru
    db.registriraj_uporabnika("neakt@test.si", "it", "opis", "osnovni", ["IT & Software"], "tok-na")
    profili = [p for p in db.poberi_aktivne_profile() if p["email"] == "neakt@test.si"]
    assert profili == []


# ---------------------------------------------------------------------------
# Matching cache / idempotentnost
# ---------------------------------------------------------------------------

def test_matching_cache():
    _, pid = _ustvari("cache@test.si", "tok-cache")
    db.shrani_matching("JN-CACHE-1", pid, True, 0.9, "ker ustreza")
    assert "JN-CACHE-1" in db.ze_ocenjeni_pjn_za_profil(pid)
    # Ponovni vnos istega para se ignorira (idempotentnost)
    db.shrani_matching("JN-CACHE-1", pid, False, 0.1, "drugače")
    assert len(db.ze_ocenjeni_pjn_za_profil(pid)) == 1


# ---------------------------------------------------------------------------
# Pragova, dedup, per-user pošiljanje
# ---------------------------------------------------------------------------

def test_matche_pragova_in_poslano():
    uid, pid = _ustvari("send@test.si", "tok-send")
    db.shrani_narocila([
        {"pjn": "JN-S-A", "naziv": "Sanacija fasade", "kategorije": ["Gradbeništvo"]},
        {"pjn": "JN-S-B", "naziv": "Rekonstrukcija ceste", "kategorije": ["Gradbeništvo"]},
        {"pjn": "JN-S-C", "naziv": "Nakup pisal", "kategorije": ["Drugo"]},
    ])
    db.shrani_matching("JN-S-A", pid, True, 0.9, "glavni")
    db.shrani_matching("JN-S-B", pid, True, 0.6, "morda")
    db.shrani_matching("JN-S-C", pid, True, 0.3, "prenizek")

    matchi = db.poberi_matche_za_uporabnika(uid, 0.5)
    pjni = [m["pjn"] for m in matchi]
    assert "JN-S-A" in pjni and "JN-S-B" in pjni
    assert "JN-S-C" not in pjni        # pod pragom morda
    assert pjni[0] == "JN-S-A"          # sortirano po confidence padajoče

    # Po označitvi poslano se naročilo ne vrne več
    db.oznaci_poslano_userju(uid, ["JN-S-A"])
    pjni2 = [m["pjn"] for m in db.poberi_matche_za_uporabnika(uid, 0.5)]
    assert "JN-S-A" not in pjni2 and "JN-S-B" in pjni2


def test_dedup_po_pjn_cez_profile():
    # Dva profila istega uporabnika ujameta isto naročilo -> v emailu enkrat
    uid, pid1 = _ustvari("multi@test.si", "tok-multi")
    pid2 = db.dodaj_profil(uid, "it", "razvoj", [])
    db.shrani_narocila([{"pjn": "JN-DUP-1", "naziv": "Razvoj in gradnja", "kategorije": ["Drugo"]}])
    db.shrani_matching("JN-DUP-1", pid1, True, 0.8, "gradbeno")
    db.shrani_matching("JN-DUP-1", pid2, True, 0.95, "IT")
    matchi = [m for m in db.poberi_matche_za_uporabnika(uid, 0.5) if m["pjn"] == "JN-DUP-1"]
    assert len(matchi) == 1
    assert matchi[0]["confidence"] == 0.95   # obdrži najvišji


# ---------------------------------------------------------------------------
# Parsing odgovora modela
# ---------------------------------------------------------------------------

def test_razcleni_json():
    besedilo = 'Tukaj je rezultat: [{"pjn":"X","relevant":true,"confidence":0.8,"reason":"r"}] konec'
    podatki = matching._razcleni_json(besedilo)
    assert podatki[0]["pjn"] == "X"
    assert matching._razcleni_json("brez jsona") == []
    assert matching._razcleni_json("") == []


def test_opis_profila():
    opis = matching._opis_profila({
        "panoga": "Gradbeništvo", "opis": "fasade", "izbrani": ["Novogradnje"],
    })
    assert "Gradbeništvo" in opis and "Novogradnje" in opis and "fasade" in opis


# ---------------------------------------------------------------------------
# oceni_profil z mock modelom (brez pravega API klica)
# ---------------------------------------------------------------------------

def test_oceni_profil_mock(monkeypatch):
    _, pid = _ustvari("ocena@test.si", "tok-ocena")

    def fake_klic(opis, batch):
        return [
            {"pjn": n["pjn"], "relevant": True, "confidence": 0.85, "reason": "ok"}
            for n in batch
        ]

    monkeypatch.setattr(matching, "_klici_model", fake_klic)
    profil = {"id": pid, "panoga": "gradbenistvo", "opis": "x", "izbrani": []}
    shranjenih = matching.oceni_profil(profil, [
        {"pjn": "JN-OC-1", "naziv": "a"}, {"pjn": "JN-OC-2", "naziv": "b"},
    ])
    assert shranjenih == 2
    assert "JN-OC-1" in db.ze_ocenjeni_pjn_za_profil(pid)
