"""
test_faza45.py — Testi za prijavo brez gesla in upravljanje profilov:
žetoni (enkratnost, potek), dodajanje/izbris profilov, iskanje po emailu.
"""

import db


def setup_module():
    db.init_db()


def _user(email, token, paket="pro"):
    db.registriraj_uporabnika(email, "gradbenistvo", "opis", paket, ["Gradbeništvo"], token)
    db.potrdi_uporabnika(token)
    return db._id_uporabnika(email)


def test_zeton_enkratna_uporaba():
    uid = _user("z1@test.si", "r-z1")
    t = db.ustvari_prijavni_zeton(uid)
    assert db.unovci_prijavni_zeton(t) == uid
    # Drugič ne velja več (enkratna uporaba)
    assert db.unovci_prijavni_zeton(t) is None


def test_zeton_potece():
    uid = _user("z2@test.si", "r-z2")
    t = db.ustvari_prijavni_zeton(uid)
    conn = db._poveži()
    conn.execute("UPDATE prijavni_zetoni SET poteklo = ? WHERE token = ?",
                 ("2000-01-01T00:00:00", t))
    conn.commit()
    conn.close()
    assert db.unovci_prijavni_zeton(t) is None


def test_profili_dodaj_in_izbris():
    uid = _user("z3@test.si", "r-z3")
    assert db.aktivnih_profilov(uid) == 1           # registracija ustvari enega
    pid = db.dodaj_profil(uid, "it", "razvoj", [])
    assert db.aktivnih_profilov(uid) == 2
    assert db.izbrisi_profil(pid, uid) is True        # soft-izbris
    assert db.aktivnih_profilov(uid) == 1
    # Tujega/neobstoječega profila ne more izbrisati
    assert db.izbrisi_profil(999999, uid) is False


def test_po_emailu():
    uid = _user("z4@test.si", "r-z4")
    u = db.poberi_uporabnik_po_emailu("z4@test.si")
    assert u and u["id"] == uid and u["aktiven"] == 1
    assert db.poberi_uporabnik_po_emailu("ni@test.si") is None
