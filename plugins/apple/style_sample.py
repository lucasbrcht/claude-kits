#!/usr/bin/env python3
"""Schreibstil-Stichprobe aus den eigenen gesendeten Mails ziehen.

Liest die letzten N Mails aus dem Postfach Gesendet des Kontos eines Profils aus
config.json, schneidet Zitate und Signaturen ab, ersetzt Namen und Adressen durch
[NAME] und [MAIL] und schreibt zwei Dateien in den Ordner style/<profil>/:

  style/<profil>/samples.md   eine Mail pro Abschnitt (Datum, Betreff, bereinigter Text)
  style/<profil>/stats.md     Zeichensetzung, Satz- und Absatzlängen, Anreden, Grußformeln

Alles bleibt lokal. Die beiden Dateien enthalten trotzdem eigene Mailtexte und
gehören nicht in Repos oder externe Dienste (siehe .gitignore).

Aufruf:
  python3 style_sample.py --profile privat            # letzte 40 gesendete Mails
  python3 style_sample.py --profile arbeit --n 60     # Arbeit, mehr Mails
  python3 style_sample.py --profile privat --days 730 # weiter zurück suchen (Standard 365 Tage)

Die Namensersetzung ist eine Heuristik: eigener Name, Empfängernamen (An und Cc) und
Namen aus Anredezeilen werden ersetzt, auch mit Genitiv-s. Nummern ersetzt
kit_basis.maskiere_nummern wie in den anderen Kits. Namen Dritter im Text erkennt sie
nicht. Vor dem Weitergeben der Dateien selbst prüfen.
"""
from __future__ import annotations  # Typangaben wie str | None auch mit dem System-Python 3.9

import argparse
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT_DIR))
import kit_basis  # noqa: E402  (Nummern ersetzen wie in den anderen Kits)
import mail as mk  # noqa: E402  (Helfer aus mail.py wiederverwenden)

STUFEN = (30, 90, 180)  # Tage: erst kurz suchen, weiter zurück nur, wenn zu wenige Mails da sind

# ---------- Mails holen ----------

# Gesendete Mails eines Kontos seit N Sekunden, je Mail eine Zeile aus dem Handler zeile(m). Erst im Postfach Gesendet
# des Kontos (schnell, ohne das Exchange-Postfach), sonst im Sammelpostfach mit Kontoprüfung je Mail. Die Grenze von
# 80 s liegt unter dem Timeout von run_as.
AS_SENT_RUN = '''
on run argv
  set secs to (item 1 of argv) as integer
  set acct to item 2 of argv
  set cutoff to (current date) - secs
  set out to ""
  tell application "Mail"
    with timeout of 80 seconds
      set boxes to {}
      if acct is not "" then set boxes to my account_boxes("sent", {acct})
      set perAcct to (count boxes) > 0
      if not perAcct then set boxes to {sent mailbox}
      repeat with mb in boxes
        set hits to (get messages of (contents of mb) whose date sent > cutoff)
        repeat with m in hits
          if perAcct or acct is "" or (name of account of mailbox of m) is acct then set out to out & my zeile(m)
        end repeat
      end repeat
    end timeout
  end tell
  return out
end run
'''
META_ZEILE = '''
on zeile(m)
  tell application "Mail" to return (id of m as string) & "|" & my iso(date sent of m) & linefeed
end zeile
'''
# no_sep aus mail.AS_COMMON: Trennzeichen in Betreff, Namen und Text würden sonst Felder oder Mails verschieben
TEXT_ZEILE = '''
on zeile(m)
  set fs to character id 31
  tell application "Mail"
    set tos to ""
    repeat with r in to recipients of m
      try
        set tos to tos & my no_sep(name of r) & ", "
      end try
    end repeat
    repeat with r in cc recipients of m
      try
        set tos to tos & my no_sep(name of r) & ", "
      end try
    end repeat
    return (id of m as string) & fs & my iso(date sent of m) & fs & my no_sep(subject of m) & fs & tos & fs & my no_sep(content of m) & (character id 30)
  end tell
end zeile
'''


def nfc(s: str) -> str:
    """Umlaute in einer Form. Mail liefert teils NFD, dann fände die Ersetzung Jürgen aus den Empfängern im Text nicht."""
    return unicodedata.normalize("NFC", s)


def zeitraeume(days: int) -> list[int]:
    """Suchfenster in Tagen bis days. Die übliche Stichprobe braucht kein ganzes Jahr, das lag nah am Timeout."""
    return [t for t in STUFEN if t < days] + [days]


def fetch_sent(prof: dict, n: int, days: int) -> list[dict]:
    """Die n neuesten gesendeten Mails des Kontos mit Text holen.

    Zwei Schritte, damit nicht der Text aller Mails des Zeitraums geladen wird:
    1. nur id und Datum der gesendeten Mails, erst 30 Tage, bei zu wenigen weiter zurück bis days
    2. Text nur für die Mails ab dem Datum der n-ten neuesten
    """
    account = prof.get("account", "") or ""
    rows = []
    for tage in zeitraeume(days):
        out = mk.run_as(mk.AS_COMMON + META_ZEILE + AS_SENT_RUN, str(tage * 86400), account)
        rows = [r for r in (ln.split("|", 1) for ln in out.splitlines() if "|" in ln)
                if mk.NUR_ZIFFERN.fullmatch(r[0]) and mk.ISO_ZEIT.fullmatch(r[1])]
        if len(rows) >= n:
            break
    if not rows:
        return []
    rows.sort(key=lambda r: r[1], reverse=True)
    chosen = rows[:n]
    oldest = datetime.strptime(chosen[-1][1], "%Y-%m-%d %H:%M")
    seconds_back = int((datetime.now() - oldest).total_seconds()) + 120
    wanted = {r[0] for r in chosen}

    out = mk.run_as(mk.AS_COMMON + TEXT_ZEILE + AS_SENT_RUN, str(seconds_back), account)
    # nur vollständige Datensätze mit id und Datum (Review 21.10.2026), die übrigen nennt eine Zeile
    gut, falsch = mk.gueltige(mk.records(out), 5, datum=1)
    if falsch:
        print(mk.uebersprungen(falsch), file=sys.stderr)
    mails = []
    for parts in gut:
        if parts[0] not in wanted:
            continue
        mails.append({
            "id": parts[0],
            "date": parts[1],
            "subject": nfc(parts[2]),
            "to_names": [t.strip() for t in nfc(parts[3]).split(",") if t.strip()],  # An und Cc
            "body": nfc(parts[4]),
        })
    mails.sort(key=lambda m: m["date"], reverse=True)
    return mails[:n]


# ---------- Text bereinigen ----------

QUOTE_START = re.compile(
    r"^\s*("
    r"Am .{6,120} schrieb .*:?\s*$"
    r"|On .{6,120} wrote:?\s*$"
    r"|>"
    r"|-{2,}\s*(Ursprüngliche Nachricht|Original Message|Weitergeleitete Nachricht|Forwarded message)"
    r"|(Von|From):\s.*\n?\s*(Gesendet|Sent|Datum|Date):"
    r"|Anfang der weitergeleiteten (E-Mail|Nachricht):"
    r"|Begin forwarded message:"
    r")",
    re.I,
)
QUOTE_HEADER = re.compile(r"^\s*(Von|From):\s.+$", re.I)
CLOSING = re.compile(
    r"^\s*("
    r"(viele|liebe|beste|herzliche|freundliche|schöne|sonnige|sportliche)\s+grüße"
    r"|mit (freundlichen|besten|herzlichen|sportlichen) grüßen"
    r"|(vg|lg|mfg|bg|glg|hg)\b"
    r"|gruß|grüße|gruss|gruesse|ciao|cheers|bis (dann|bald|morgen|später|gleich|dahin)"
    r"|((best|kind|warm)\s+)?regards|best|thanks|thank you|many thanks|danke( dir| euch| ihnen)?"
    r"|schönen (tag|abend)|schönes wochenende|einen schönen \w+"
    r")[\s,!.]*$",
    re.I,
)
# Liebe Grüße ist ein Gruß, keine Anrede: sonst würde Grüße zum Namen und überall ersetzt
GREETING = re.compile(
    r"^\s*(hallo|hi|hey|moin|servus|hoi|guten (morgen|tag|abend)|liebe[rs]?(?!\s+gr(?:ü|ue)(?:ß|ss))|"
    r"sehr geehrte[rs]?( frau| herr)?|dear|hello)\b\s*(?P<name>[^,!:\n]*)",
    re.I,
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# Wörter in Anreden, die kein Name sind (klein geschrieben verglichen): Hallo zusammen, Hi Team, Moin Moin, Sehr geehrte
# Damen und Herren. Sie bleiben im Text stehen und werden nie zu [NAME].
STOP_TOKENS = {"frau", "herr", "herrn", "dr", "prof", "team", "alle", "allerseits", "zusammen", "damen", "herren",
               "leute", "ihr", "euch", "moin", "und", "all", "everyone"}
TITEL = {"dr", "prof"}


def cut_quotes_and_signature(body: str, prof: dict) -> str:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Zitate: alles ab der ersten Zitat-Einleitung oder ">"-Zeile fällt weg.
    cut = len(lines)
    for i, ln in enumerate(lines):
        if QUOTE_START.match(ln):
            cut = i
            break
        if QUOTE_HEADER.match(ln) and i + 3 < len(lines):
            nxt = "\n".join(lines[i + 1:i + 4])
            if re.search(r"^\s*(Gesendet|Sent|Datum|Date|An|To):", nxt, re.I | re.M):
                cut = i
                break
    lines = lines[:cut]

    # Signatur: Standardtrenner "-- ", die Signatur aus dem Profil,
    # sonst alles nach Grußformel plus Namenszeile.
    sig = (prof.get("signature") or "").strip().split("\n")
    sig_first = sig[0].strip() if sig and sig[0].strip() else None
    for i, ln in enumerate(lines):
        if ln.rstrip() == "--" or ln == "-- ":
            lines = lines[:i]
            break
    # Die Signatur beginnt mit einer Zeile, die mit der Marke anfängt. Die letzte solche Zeile zählt, eine Nennung im
    # Fließtext (die Firma GmbH bietet) schneidet nichts ab. Ist die Marke eine Grußformel, bleibt sie für die Statistik.
    starts = [i for i, ln in enumerate(lines) if sig_first and ln.strip().startswith(sig_first)]
    if starts:
        lines = lines[:starts[-1] + (1 if CLOSING.match(lines[starts[-1]]) else 0)]
    last_close = None
    for i, ln in enumerate(lines):
        if CLOSING.match(ln):
            last_close = i
    if last_close is not None:
        keep = last_close + 1
        # eine Namenszeile direkt danach behalten (wird zu [NAME])
        j = keep
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and len(lines[j].split()) <= 4:
            keep = j + 1
        lines = lines[:keep]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def kein_name(text: str) -> bool:
    """Besteht text nur aus Wörtern, die kein Name sind (zusammen, Team, Damen und Herren)? Leer zählt auch."""
    return all(w.strip(".&").casefold() in STOP_TOKENS or not w.strip(".&") for w in text.split())


def anrede_name(rest: str) -> str:
    """Name vorn im Rest einer Anredezeile: Wörter mit Großbuchstaben vorn, verbunden mit und oder &. Ein klein
    geschriebenes Wort oder ein Satzende beendet ihn, Initialen und Titel (A., Dr.) nicht. Aus Hallo Anna und danke für
    die Unterlagen wird Anna, nicht auch Unterlagen: Jedes Wort hier ersetzt anonymise in allen Mails."""
    woerter = []
    for wort in rest.split():
        kern = wort.rstrip(".?")
        if wort in ("und", "&") and woerter:
            woerter.append(wort)
            continue
        if not kern[:1].isupper():
            break
        woerter.append(wort)
        if wort.endswith((".", "?")) and len(kern) > 1 and kern.casefold() not in TITEL:
            break
    while woerter and woerter[-1] in ("und", "&"):
        woerter.pop()
    return " ".join(woerter).rstrip(".?")


def collect_names(prof: dict, mails: list[dict]) -> set[str]:
    names = set()

    def add(full: str) -> None:
        full = nfc(full).strip().strip('"')
        if len(full) < 2 or "@" in full or kein_name(full):
            return
        names.add(full)
        for tok in re.split(r"[\s,]+", full):
            tok = tok.strip(".-")
            if len(tok) >= 3 and tok[0].isupper() and tok.casefold() not in STOP_TOKENS:
                names.add(tok)

    add(prof.get("from_name", "") or "")
    for m in mails:
        for t in m["to_names"]:
            add(t)
        for ln in m["body"].split("\n")[:3]:
            g = GREETING.match(ln)
            if g and g.group("name"):
                add(anrede_name(g.group("name")))
    return names


def anonymise(text: str, names: set[str]) -> str:
    text = EMAIL.sub("[MAIL]", nfc(text))
    text = kit_basis.maskiere_nummern(text, "[TEL]")  # Telefon, Konto, IBAN, auch mit geschütztem Leerzeichen oder Punkten
    # Anredezeile: Namensteil komplett ersetzen, außer es ist keiner (Hallo zusammen)
    out_lines = []
    for ln in text.split("\n"):
        g = GREETING.match(ln)
        if g and not kein_name(g.group("name")):
            ln = ln[:g.start("name")] + "[NAME]" + ln[g.end("name"):]
        out_lines.append(ln)
    text = "\n".join(out_lines)
    for nm in sorted(names, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(nm) + r"s?(?!\w)", "[NAME]", text)  # auch Genitiv: Annas Vorschlag
    # Vor- und Nachname einzeln ersetzt ergibt ein [NAME], Zeilenumbrüche und Satzzeichen danach bleiben
    return re.sub(r"\[NAME\](?:[^\S\n]+\[NAME\])+", "[NAME]", text)


# ---------- Statistik ----------

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿⭐⭕⌚-⏿]"
)
ABBREV = re.compile(
    r"(?<!\w)(z\.\s?B\.|bzw\.|usw\.|vs\.|ca\.|evtl\.|ggf\.|d\.\s?h\.|u\.\s?a\.|etc\.|inkl\.|"
    r"exkl\.|max\.|min\.|Nr\.|Std\.|Min\.|asap|FYI|btw|ok|okay|thx|LG|VG|MfG)(?!\w)",
    re.I,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=\S)")


def is_frame_line(ln: str) -> bool:
    """Anrede, Grußformel oder Namenszeile: zählt nicht als Satz oder Absatz."""
    s = ln.strip()
    return not s or bool(GREETING.match(ln)) or bool(CLOSING.match(ln)) or s == "[NAME]"


def content_paragraphs(text: str) -> list[str]:
    paras = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if not is_frame_line(ln)]
        if lines:
            paras.append("\n".join(lines))
    return paras


def sentences_of(text: str) -> list[str]:
    body = "\n".join(ln.strip() for ln in text.split("\n") if not is_frame_line(ln))
    body = re.sub(r"\b(z\.\s?B|bzw|usw|vs|ca|evtl|ggf|d\.\s?h|u\.\s?a|etc|inkl|Nr|Std|Min)\.", lambda m: m.group(0).replace(".", "§"), body)
    parts = []
    for line in body.split("\n"):  # Zeilenumbruch ist Satzgrenze (Listen, Kurzzeilen)
        parts += [s.strip() for s in SENTENCE_SPLIT.split(line) if s.strip()]
    return [p.replace("§", ".").lstrip("-*• ").strip() for p in parts if p.strip("-*• ")]


def stats_for(text: str) -> dict:
    sents = sentences_of(text)
    paras = content_paragraphs(text)
    words_total = sum(len(s.split()) for s in sents)
    lower_start = sum(1 for s in sents if s and s[0].islower())
    return {
        "em": text.count("—"),
        "en": text.count("–"),
        "hyphen": len(re.findall(r"\w-\w", text)),
        "excl": text.count("!"),
        "quest": text.count("?"),
        "semi": text.count(";"),
        "colon": len(re.findall(r":(?!\d)", text)),
        "paren": text.count("("),
        "ellipsis": text.count("…") + len(re.findall(r"\.\.\.", text)),
        "emoji": len(EMOJI.findall(text)),
        "q_de": text.count("„") + text.count("“") + text.count("‚"),
        "q_ascii": text.count('"'),
        "q_guillemet": text.count("»") + text.count("«"),
        "sentences": len(sents),
        "words": words_total,
        "paras": len(paras),
        "lower_start": lower_start,
        "bullets": len(re.findall(r"^\s*([-*•]|\d+[.)])\s", text, re.M)),
    }


def greeting_of(text: str) -> str | None:
    for ln in text.split("\n")[:3]:
        g = GREETING.match(ln)
        if g:
            return re.sub(r"\s+", " ", ln.strip().rstrip(",!:")).strip()
    return None


def closing_of(text: str) -> str | None:
    for ln in reversed(text.split("\n")):
        if CLOSING.match(ln):
            return re.sub(r"\s+", " ", ln.strip().rstrip(",!.")).strip()
    return None


def fmt_ratio(a: int, b: int) -> str:
    return f"{a / b:.1f}" if b else "0"


PROFIL_ANHANG = "## Aus dem Profil"  # Belege, Entstehung und Notizen, aus profil.md verschoben


def profil_anhang(alt: str) -> str:
    """Abschnitt PROFIL_ANHANG bis zum Ende aus der bisherigen stats.md. Ein neuer Lauf erzeugt nur die Statistik neu,
    die Herleitung aus dem Profil bleibt."""
    i = alt.find("\n" + PROFIL_ANHANG)
    return alt[i:].rstrip() + "\n" if i != -1 else ""


def build_stats_md(mails: list[dict], n_requested: int, n_skipped: int) -> str:
    per = [(m, stats_for(m["clean"])) for m in mails]
    tot = Counter()
    for _, s in per:
        tot.update(s)
    n = len(mails)
    greet = Counter(g for g in (greeting_of(m["clean"]) for m in mails) if g)
    close = Counter(c for c in (closing_of(m["clean"]) for m in mails) if c)
    abbr = Counter(a.lower().replace(" ", "") for m in mails for a in ABBREV.findall(m["clean"]))
    quote_type = "„“" if tot["q_de"] > tot["q_ascii"] else ('""' if tot["q_ascii"] else "keine")
    if tot["q_guillemet"] > max(tot["q_de"], tot["q_ascii"]):
        quote_type = "»«"

    L = []
    L.append("# Stil-Statistik aus gesendeten Mails")
    L.append("")
    L.append(f"Erstellt: {datetime.now():%Y-%m-%d %H:%M}. Angefordert: {n_requested}, ausgewertet: {n}, "
             f"übersprungen (kein eigener Text nach dem Bereinigen): {n_skipped}.")
    L.append("")
    L.append("## Gesamt")
    L.append("")
    L.append("| Merkmal | gesamt | pro Mail |")
    L.append("|---|---|---|")
    rows = [
        ("Em-Dashes (—)", "em"), ("En-Dashes (–)", "en"), ("Bindestriche in Komposita", "hyphen"),
        ("Ausrufezeichen", "excl"), ("Fragezeichen", "quest"), ("Semikolons", "semi"),
        ("Doppelpunkte", "colon"), ("Klammern (öffnend)", "paren"), ("Auslassungspunkte", "ellipsis"),
        ("Emojis", "emoji"), ("Aufzählungszeilen", "bullets"),
        ("Anführungszeichen „“", "q_de"), ('Anführungszeichen ""', "q_ascii"), ("Anführungszeichen »«", "q_guillemet"),
    ]
    for label, key in rows:
        L.append(f"| {label} | {tot[key]} | {fmt_ratio(tot[key], n)} |")
    L.append("")
    L.append(f"- Anführungszeichen-Typ überwiegend: {quote_type}")
    L.append(f"- Sätze gesamt: {tot['sentences']}, Wörter gesamt: {tot['words']}")
    L.append(f"- Durchschnittliche Satzlänge: {fmt_ratio(tot['words'], tot['sentences'])} Wörter")
    L.append(f"- Durchschnittliche Absatzlänge: {fmt_ratio(tot['sentences'], tot['paras'])} Sätze, "
             f"{fmt_ratio(tot['words'], tot['paras'])} Wörter ({tot['paras']} Absätze)")
    L.append(f"- Durchschnittliche Mail-Länge: {fmt_ratio(tot['words'], n)} Wörter, {fmt_ratio(tot['sentences'], n)} Sätze")
    pct = f"{100 * tot['lower_start'] / tot['sentences']:.0f} %" if tot["sentences"] else "0 %"
    L.append(f"- Anteil Sätze mit Kleinschreibung am Anfang: {pct} ({tot['lower_start']} von {tot['sentences']})")
    L.append("")
    L.append("## Anreden (Top 5)")
    L.append("")
    L += [f"- {g}: {c}" for g, c in greet.most_common(5)] or ["- keine erkannt"]
    L.append("")
    L.append("## Grußformeln (Top 5)")
    L.append("")
    L += [f"- {g}: {c}" for g, c in close.most_common(5)] or ["- keine erkannt"]
    L.append("")
    L.append("## Abkürzungen (Top 10)")
    L.append("")
    L += [f"- {a}: {c}" for a, c in abbr.most_common(10)] or ["- keine erkannt"]
    L.append("")
    L.append("## Pro Mail")
    L.append("")
    L.append("| Datum | Betreff | Wörter | Sätze | Ø Satz | — | – | Komp.- | ! | ? | ; | : | ( | … | Emoji | klein |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m, s in per:
        subj = m["subject_clean"][:40].replace("|", "/")
        L.append(f"| {m['date'][:10]} | {subj} | {s['words']} | {s['sentences']} | {fmt_ratio(s['words'], s['sentences'])} "
                 f"| {s['em']} | {s['en']} | {s['hyphen']} | {s['excl']} | {s['quest']} | {s['semi']} | {s['colon']} "
                 f"| {s['paren']} | {s['ellipsis']} | {s['emoji']} | {s['lower_start']} |")
    L.append("")
    return "\n".join(L)


def build_samples_md(mails: list[dict]) -> str:
    L = ["# Stichprobe gesendeter Mails (bereinigt, Namen und Adressen ersetzt)", "",
         "Nur lokal verwenden. Zitate und Signaturen sind abgeschnitten.", ""]
    for m in mails:
        L.append(f"## {m['date']} | {m['subject_clean']}")
        L.append("")
        L.append(m["clean"])
        L.append("")
    return "\n".join(L)


# ---------- main ----------


def main() -> None:
    p = argparse.ArgumentParser(description="Stil-Stichprobe aus gesendeten Mails (lokal).", allow_abbrev=False)
    p.add_argument("--n", type=int, default=40, help="Anzahl der neuesten gesendeten Mails (Standard 40)")
    p.add_argument("--days", type=int, default=365, help="wie weit zurück gesucht wird (Standard 365 Tage)")
    p.add_argument("--profile", help="Kontoprofil aus config.json (Standard: default_profile)")
    p.add_argument("--out", help="Zielordner unter style/ im Kit (Standard style/<profil>/)")
    a = p.parse_args()
    if a.n < 1 or a.days < 1:  # --n 0 endete sonst mit IndexError, negative Werte suchten nichts (Review 21.10.2026)
        p.error("--n und --days ab 1")

    cfg = mk.load_config()
    profile_name = a.profile or cfg.get("default_profile")
    if not profile_name:
        sys.exit("Kein Profil: --profile angeben oder default_profile in config.json setzen. Nichts geschrieben.")
    prof = mk.get_profile(cfg, profile_name)
    # Ohne Konto liest AS_SENT_RUN die gesendeten Mails aller Konten, auch der Arbeit (Prüfung 20.10.2026)
    if not prof.get("account", "").strip():
        sys.exit(f"Profil {profile_name} hat kein account in config.json. Den Kontonamen wie in Apple Mail eintragen. "
                 "Nichts geschrieben.")
    # Nur unter style/ im Kit: Das Skript läuft ohne Rückfrage außerhalb der Sandbox und schreibt eigene Mailtexte.
    daten = kit_basis.datenordner(KIT_DIR)  # Datenordner des MCP-Servers, sonst der Plugin-Ordner
    stil = (daten / "style").resolve()
    if a.out:
        out_dir = Path(a.out).expanduser()
        out_dir = (out_dir if out_dir.is_absolute() else daten / out_dir).resolve()
    else:
        out_dir = (stil / profile_name).resolve()
    if out_dir != stil and stil not in out_dir.parents:
        sys.exit(f"--out muss unter {stil} liegen, die Stilproben enthalten eigene Mailtexte. Nichts geschrieben.")

    mails = fetch_sent(prof, a.n, a.days)
    if not mails:
        sys.exit("Keine gesendeten Mails im Zeitraum gefunden. --days vergrößern oder Profil/Konto in config.json prüfen.")

    names = collect_names(prof, mails)
    kept, skipped = [], 0
    for m in mails:
        clean = cut_quotes_and_signature(m["body"], prof)
        if len(clean.split()) < 3:
            skipped += 1
            continue
        m["clean"] = anonymise(clean, names)
        m["subject_clean"] = anonymise(m["subject"], names)
        kept.append(m)
    if not kept:
        sys.exit("Alle Mails waren nach dem Bereinigen leer (nur Weiterleitungen oder Zitate).")

    out_dir.mkdir(parents=True, exist_ok=True)
    stats_md = build_stats_md(kept, a.n, skipped)
    (out_dir / "samples.md").write_text(build_samples_md(kept), encoding="utf-8")
    stats_pfad = out_dir / "stats.md"
    anhang = profil_anhang(stats_pfad.read_text(encoding="utf-8")) if stats_pfad.exists() else ""
    stats_pfad.write_text(stats_md.rstrip() + "\n" + anhang, encoding="utf-8")

    # Statistik ohne die Pro-Mail-Tabelle auf die Konsole
    print(stats_md.split("## Pro Mail")[0].rstrip())
    print()
    print(f"Geschrieben: {out_dir / 'samples.md'} und {out_dir / 'stats.md'}")
    print("Beide Dateien enthalten eigene Mailtexte. Lokal lassen, nicht committen, nicht weitergeben.")


if __name__ == "__main__":
    kit_basis.starten(main, __file__)
