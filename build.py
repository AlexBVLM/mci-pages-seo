"""Génère le mini-site SEO de Mon Consultant Indépendant (TJM par métier, ville et secteur).

Lecture seule d'Airtable (table Annonces de la base Production), calcul des TJM,
textes rédigés par Claude Haiku (mis en cache dans data/textes.json), pages HTML
statiques dans le dossier site/.

Variables d'environnement :
  AIRTABLE_TOKEN     jeton Airtable en lecture seule
  ANTHROPIC_API_KEY  clé Claude (facultative : sans clé, texte de secours)
  BASE_URL           adresse du site (défaut : https://missions.mon-consultant-independant.com)
Option : --from-json fichier.json pour travailler sur un export local.
"""
import datetime as dt
import html
import json
import os
import re
import shutil
import statistics
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

BASE_ID = "appATcYU9dedmMBis"
TABLE_ID = "tbl9QW4UilsMmghL7"
SEUIL = 5
JOURS = 730
BASE_URL = os.environ.get("BASE_URL", "https://missions.mon-consultant-independant.com").rstrip("/")
SITE_MCI = "https://www.mon-consultant-independant.com"
LIEN_FREELANCE = SITE_MCI
LIEN_CLIENT = SITE_MCI
MODELE = "claude-haiku-4-5-20251001"
TEXTES_FICHIER = "data/textes.json"
TEXTE_VERSION = 1
OUT = "site"

CHAMPS = ["Titre", "Métier (Claude)", "Lieu", "Secteur", "TJM consultant", "Etat",
          "Ne plus diffuser (poste pourvu)", "Télétravail", "Durée",
          "Date / heure de création", "Lien candidats pour postuler"]

# Libellés plus naturels pour les titres de pages (au singulier, minuscule).
LIBELLES = {
    "Gestion de projet - pilotage (PMO)": "chef de projet / PMO",
    "Systèmes d'information": "consultant systèmes d'information",
    "AMOA - MOA": "consultant AMOA",
    "MOE": "développeur / MOE",
    "Comptabilité": "comptable",
    "Contrôle de gestion": "contrôleur de gestion",
    "Ingénierie": "ingénieur",
    "Business analyst": "business analyst",
    "Ressources humaines": "consultant RH",
    "Finance d'entreprise": "consultant finance d'entreprise",
    "Achats": "acheteur",
    "Direction générale": "manager de transition / direction générale",
    "Product owner": "product owner",
    "Finance de marché": "consultant finance de marché",
    "Asset management": "consultant asset management",
    "Supply chain - logistique": "consultant supply chain",
    "Data": "consultant data",
    "Data analyst": "data analyst",
    "Data scientist": "data scientist",
    "Cybersécurité": "consultant cybersécurité",
    "Conduite du changement": "consultant conduite du changement",
    "Réglementations bancaires": "consultant réglementation bancaire",
    "Contrôle interne": "consultant contrôle interne",
    "Compliance": "consultant compliance",
    "Gestion des risques crédits": "consultant risques de crédit",
    "Gestion des risques opérationnels": "consultant risques opérationnels",
    "Management qualité - Normes ISO": "consultant qualité",
    "Stratégie": "consultant en stratégie",
    "Commercial": "commercial",
    "Marketing": "consultant marketing",
    "Communication": "consultant communication",
    "Recrutement": "recruteur",
    "Gestion de la paie": "gestionnaire de paie",
    "Droit": "juriste",
    "Audit": "auditeur",
    "Recette": "consultant recette / testeur",
    "Scrum master": "scrum master",
    "DevOps": "ingénieur DevOps",
    "SAP": "consultant SAP",
    "Salesforce": "consultant Salesforce",
    "ERP": "consultant ERP",
    "IFRS": "consultant IFRS / consolidation",
    "Administration réseaux": "administrateur systèmes et réseaux",
    "Intelligence artificielle": "consultant IA",
    "SIRH": "consultant SIRH",
    "Formation": "formateur",
    "Design UX UI": "designer UX / UI",
    "Business intelligence": "consultant BI",
    "CRM": "consultant CRM",
    "Administratif": "assistant administratif",
}

VILLES = {"Paris et région parisienne": ("Paris", "à Paris et en région parisienne")}


def libelle(m):
    return LIBELLES.get(m, m[:1].lower() + m[1:] if not m[:2].isupper() else m)


def ville_nom(v):
    return VILLES.get(v, (v, "à " + v))


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def euros(n):
    return f"{int(round(n)):,}".replace(",", " ") + " €"


# ---------------------------------------------------------------- données

def lire_airtable():
    token = os.environ["AIRTABLE_TOKEN"]
    formule = f"DATETIME_DIFF(NOW(), CREATED_TIME(), 'days')<={JOURS}"
    params = [("filterByFormula", formule), ("pageSize", "100")] + [("fields[]", c) for c in CHAMPS]
    out, offset = [], None
    while True:
        q = params + ([("offset", offset)] if offset else [])
        url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        out += [{"id": x["id"], **x["fields"]} for x in d["records"]]
        offset = d.get("offset")
        if not offset:
            return out
        time.sleep(0.22)  # limite Airtable : 5 requêtes / seconde


def nettoyer(recs):
    ann = []
    for r in recs:
        tjm = r.get("TJM consultant")
        m = r.get("Métier (Claude)")
        if not isinstance(tjm, (int, float)) or tjm <= 0 or not m or m == "Autre":
            continue
        ann.append({
            "id": r["id"], "titre": (r.get("Titre") or "").strip(), "metier": m,
            "ville": r.get("Lieu"), "secteur": r.get("Secteur"), "tjm": float(tjm),
            "ouverte": r.get("Etat") == "Ouverte aux candidatures" and not r.get("Ne plus diffuser (poste pourvu)"),
            "teletravail": r.get("Télétravail"), "duree": r.get("Durée"),
            "date": r.get("Date / heure de création") or "", "lien": r.get("Lien candidats pour postuler"),
        })
    return ann


# ---------------------------------------------------------------- calculs

def quantile(v, q):
    v = sorted(v)
    i = (len(v) - 1) * q
    a, b = int(i), min(int(i) + 1, len(v) - 1)
    return v[a] + (v[b] - v[a]) * (i - a)


def stats(groupe):
    t = [a["tjm"] for a in groupe]
    return {
        "n": len(t), "mediane": statistics.median(t), "moyenne": statistics.mean(t),
        "bas": quantile(t, 0.1), "haut": quantile(t, 0.9),
        "secteurs": Counter(a["secteur"] for a in groupe if a["secteur"]).most_common(6),
        "villes": Counter(a["ville"] for a in groupe if a["ville"]).most_common(6),
        "teletravail": Counter(a["teletravail"] for a in groupe if a["teletravail"]).most_common(3),
        "durees": Counter(a["duree"] for a in groupe if a["duree"]).most_common(3),
        "ouvertes": sorted([a for a in groupe if a["ouverte"] and a["lien"]], key=lambda a: a["date"], reverse=True)[:8],
        "exemples": [a["titre"] for a in sorted(groupe, key=lambda a: a["date"], reverse=True)[:12]],
    }


def construire_pages(ann):
    pages = {}
    par_m, par_mv, par_ms = defaultdict(list), defaultdict(list), defaultdict(list)
    for a in ann:
        par_m[a["metier"]].append(a)
        if a["ville"]:
            par_mv[(a["metier"], a["ville"])].append(a)
        if a["secteur"]:
            par_ms[(a["metier"], a["secteur"])].append(a)
    for m, g in par_m.items():
        if len(g) >= SEUIL:
            p = f"/tjm/{slug(m)}/"
            pages[p] = {"type": "metier", "metier": m, "chemin": p, **stats(g)}
    for (m, v), g in par_mv.items():
        if len(g) >= SEUIL and f"/tjm/{slug(m)}/" in pages:
            p = f"/tjm/{slug(m)}/{slug(ville_nom(v)[0])}/"
            pages[p] = {"type": "ville", "metier": m, "ville": v, "chemin": p, **stats(g)}
    for (m, s), g in par_ms.items():
        if len(g) >= SEUIL and f"/tjm/{slug(m)}/" in pages:
            p = f"/tjm/{slug(m)}/secteur-{slug(s)}/"
            pages[p] = {"type": "secteur", "metier": m, "secteur": s, "chemin": p, **stats(g)}
    return pages


def intitule(p):
    m = libelle(p["metier"])
    if p["type"] == "ville":
        return f"{m} {ville_nom(p['ville'])[1]}"
    if p["type"] == "secteur":
        return f"{m}, secteur {p['secteur'].lower()}"
    return m


# ---------------------------------------------------------------- textes Claude

def faits(p):
    l = [f"Page : TJM freelance {intitule(p)}",
         f"Missions analysées (2 dernières années, plateforme Mon Consultant Indépendant) : {p['n']}",
         f"TJM médian versé au freelance : {round(p['mediane'])} € HT par jour ; 8 missions sur 10 entre {round(p['bas'])} et {round(p['haut'])} €",
         "Secteurs : " + ", ".join(f"{s} ({n})" for s, n in p["secteurs"]),
         "Villes : " + ", ".join(f"{v} ({n})" for v, n in p["villes"]),
         "Télétravail le plus fréquent : " + ", ".join(f"{t} ({n})" for t, n in p["teletravail"]),
         "Durées les plus fréquentes : " + ", ".join(f"{d} ({n})" for d, n in p["durees"]),
         "Exemples d'intitulés de missions récentes : " + " ; ".join(p["exemples"])]
    return "\n".join(l)


def texte_secours(p):
    s = ", ".join(x for x, _ in p["secteurs"][:3]).lower()
    t = p["teletravail"][0][0].lower() if p["teletravail"] else ""
    d = p["durees"][0][0] if p["durees"] else ""
    para = [f"Sur les {p['n']} missions de {intitule(p)} publiées ces deux dernières années sur Mon Consultant Indépendant, "
            f"le TJM médian versé au freelance atteint {round(p['mediane'])} € HT par jour."]
    if s:
        para.append(f"Les demandes viennent surtout des secteurs suivants : {s}.")
    if t or d:
        para.append(f"Le format le plus courant : {t}" + (f", pour une durée de {d}" if d else "") + ".")
    return [" ".join(para)]


def ecrire_texte(p):
    cle = os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        return None
    consigne = (
        "Tu rédiges le texte d'une page web de Mon Consultant Indépendant, plateforme qui met en relation des "
        "freelances (consultants indépendants) et des entreprises. La page présente le TJM (taux journalier moyen) "
        "des missions freelance décrites ci-dessous. Écris 2 paragraphes en français, 110 à 160 mots au total, "
        "utiles à un freelance ou à un client qui cherche ce tarif : ce que le marché demande, les secteurs et types "
        "de missions, ce qui fait varier le TJM d'après les données (missions les mieux payées, séniorité, format). "
        "Uniquement des faits tirés des données ci-dessous, aucun chiffre inventé, aucun nom d'entreprise, pas de "
        "superlatifs publicitaires, pas de titre, pas de liste. Ton sobre et informatif. Sépare les deux paragraphes "
        "par une ligne vide.\n\nDONNÉES\n" + faits(p))
    body = json.dumps({"model": MODELE, "max_tokens": 600,
                       "messages": [{"role": "user", "content": consigne}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": cle, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for essai in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            t = "".join(c.get("text", "") for c in d.get("content", [])).strip()
            paras = [x.strip() for x in re.split(r"\n\s*\n", t) if x.strip()]
            return paras or None
        except Exception as e:  # nouvel essai, puis texte de secours
            print("Claude :", e, file=sys.stderr)
            time.sleep(5 * (essai + 1))
    return None


def textes_pour(pages):
    cache = {}
    if os.path.exists(TEXTES_FICHIER):
        with open(TEXTES_FICHIER, encoding="utf-8") as f:
            cache = json.load(f)
    aujourd = dt.date.today()
    nouveaux = 0
    for chemin, p in pages.items():
        c = cache.get(chemin)
        a_refaire = (not c or c.get("version") != TEXTE_VERSION or c.get("secours")
                     or abs(c.get("n", 0) - p["n"]) > max(5, 0.25 * c.get("n", 1))
                     or (aujourd - dt.date.fromisoformat(c["date"])).days > 180)
        if a_refaire:
            t = ecrire_texte(p)
            cache[chemin] = {"version": TEXTE_VERSION, "n": p["n"], "date": aujourd.isoformat(),
                             "paragraphes": t or texte_secours(p), "secours": t is None}
            nouveaux += 1
        p["texte"] = cache[chemin]["paragraphes"]
    os.makedirs(os.path.dirname(TEXTES_FICHIER), exist_ok=True)
    with open(TEXTES_FICHIER, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"Textes rédigés ou refaits : {nouveaux}")


# ---------------------------------------------------------------- HTML

CSS = """:root{--ink:#1c2430;--muted:#5d6876;--line:#e3e7ec;--brand:#1f5fbf;--soft:#f3f6fa}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);line-height:1.6}
header{border-bottom:1px solid var(--line);padding:14px 20px}header a{color:var(--ink);text-decoration:none;font-weight:700}
main{max-width:820px;margin:0 auto;padding:28px 20px 60px}.crumbs{font-size:13px;color:var(--muted)}.crumbs a{color:var(--muted)}
h1{font-size:30px;line-height:1.25;margin:10px 0 6px}.sub{color:var(--muted);margin:0 0 26px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:10px}.stat{background:var(--soft);border-radius:10px;padding:16px}
.stat b{display:block;font-size:26px}.stat span{font-size:13px;color:var(--muted)}.note{font-size:13px;color:var(--muted);margin-bottom:30px}
h2{font-size:21px;margin:34px 0 10px}.mission{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:10px}
.mission a{font-weight:600;color:var(--brand);text-decoration:none}.mission small{display:block;color:var(--muted)}
.cta{display:flex;gap:12px;flex-wrap:wrap;margin:30px 0}.btn{background:var(--brand);color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600}
.btn.alt{background:#fff;color:var(--brand);border:1px solid var(--brand)}table{border-collapse:collapse;width:100%;font-size:15px}
td{border-bottom:1px solid var(--line);padding:8px 4px}td:last-child{text-align:right;color:var(--muted)}
ul.liens{padding-left:18px}ul.liens li{margin:4px 0}a{color:var(--brand)}
footer{font-size:13px;color:var(--muted);border-top:1px solid var(--line);padding:20px;text-align:center}
@media (max-width:600px){.stats{grid-template-columns:1fr}h1{font-size:25px}}"""

e = html.escape

# Mesure d'audience Plausible (sans cookies), même compte que le site Softr.
PLAUSIBLE = ('<script async src="https://plausible.io/js/pa-BB7h2oE-Lb27wc9X9KLgw.js"></script>'
             '<script>window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},'
             'plausible.init=plausible.init||function(i){plausible.o=i||{}};plausible.init()</script>')


def gabarit(titre, description, chemin, corps, jsonld=None):
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titre)}</title><meta name="description" content="{e(description)}">
<link rel="canonical" href="{BASE_URL}{chemin}"><style>{CSS}</style>{ld}{PLAUSIBLE}</head>
<body><header><a href="{SITE_MCI}">Mon Consultant Indépendant</a></header><main>{corps}</main>
<footer>Mon Consultant Indépendant · chiffres calculés sur les missions publiées sur la plateforme · <a href="{BASE_URL}/">Tous les TJM freelance</a></footer>
</body></html>"""


def page_html(p, pages, maj):
    annee = maj.year
    nom = intitule(p)
    titre = f"TJM freelance {nom} en {annee} : {round(p['mediane'])} € / jour | Mon Consultant Indépendant"
    desc = (f"TJM médian d'un {nom} freelance : {round(p['mediane'])} € HT par jour, calculé sur {p['n']} missions "
            f"réelles publiées sur Mon Consultant Indépendant. Fourchette, secteurs et missions ouvertes.")
    racine = f"/tjm/{slug(p['metier'])}/"
    crumbs = f'<a href="/">TJM freelance</a> › '
    if p["type"] == "metier":
        crumbs += e(libelle(p["metier"]))
    else:
        crumbs += f'<a href="{racine}">{e(libelle(p["metier"]))}</a> › ' + e(ville_nom(p["ville"])[0] if p["type"] == "ville" else p["secteur"])
    h1 = f"TJM d'un {e(nom)} freelance"
    corps = [f'<div class="crumbs">{crumbs}</div><h1>{h1}</h1>',
             f'<p class="sub">Chiffres calculés sur les vraies missions publiées sur Mon Consultant Indépendant ces 2 dernières années. Mis à jour le {maj.strftime("%d/%m/%Y")}.</p>',
             '<div class="stats">',
             f'<div class="stat"><b>{euros(p["mediane"])}</b><span>TJM médian HT / jour</span></div>',
             f'<div class="stat"><b>{euros(p["bas"])} – {euros(p["haut"])}</b><span>fourchette de 8 missions sur 10</span></div>',
             f'<div class="stat"><b>{p["n"]}</b><span>missions analysées</span></div></div>',
             f'<p class="note">TJM versé au freelance, hors frais. La médiane est moins sensible aux missions exceptionnelles que la moyenne ({euros(p["moyenne"])}).</p>',
             '<h2>Ce que disent ces chiffres</h2>'] + [f"<p>{e(x)}</p>" for x in p["texte"]]
    tab, titre_tab = (p["secteurs"], "Par secteur") if p["type"] != "secteur" else (p["villes"], "Par ville")
    if p["type"] == "ville" and p["secteurs"]:
        tab, titre_tab = p["secteurs"], "Par secteur"
    if tab:
        corps.append(f"<h2>{titre_tab}</h2><table>" + "".join(
            f"<tr><td>{e(k)}</td><td>{n} mission{'s' if n > 1 else ''}</td></tr>" for k, n in tab) + "</table>")
    if p["ouvertes"]:
        corps.append("<h2>Missions ouvertes en ce moment</h2>")
        for a in p["ouvertes"]:
            info = " · ".join(x for x in [a["secteur"], a["ville"] if p["type"] != "ville" else None, a["duree"],
                                         (a["teletravail"] or "").lower() or None, f"{round(a['tjm'])} € / jour"] if x)
            corps.append(f'<div class="mission"><a href="{e(a["lien"])}">{e(a["titre"])}</a><small>{e(info)}</small></div>')
    corps.append(f'<div class="cta"><a class="btn" href="{LIEN_FREELANCE}">Je suis freelance : recevoir ces missions</a>'
                 f'<a class="btn alt" href="{LIEN_CLIENT}">Je cherche un {e(libelle(p["metier"]))} freelance</a></div>')
    voisins = []
    if p["type"] != "metier":
        voisins.append((racine, f"TJM {libelle(p['metier'])} en France"))
    for q in pages.values():
        if q["metier"] == p["metier"] and q["chemin"] != p["chemin"] and q["type"] != "metier":
            voisins.append((q["chemin"], f"TJM {intitule(q)}"))
    if voisins:
        corps.append('<h2>Voir aussi</h2><ul class="liens">' + "".join(
            f'<li><a href="{c}">{e(t)}</a></li>' for c, t in voisins[:14]) + "</ul>")
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "TJM freelance", "item": BASE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": libelle(p["metier"]), "item": BASE_URL + racine}]}
    return gabarit(titre, desc, p["chemin"], "".join(corps), ld)


def accueil_html(pages, maj):
    metiers = sorted((p for p in pages.values() if p["type"] == "metier"), key=lambda p: -p["n"])
    corps = ['<h1>TJM freelance par métier, ville et secteur</h1>',
             f'<p class="sub">Taux journaliers calculés sur les missions réellement publiées sur Mon Consultant Indépendant ces 2 dernières années. Mis à jour le {maj.strftime("%d/%m/%Y")}.</p>',
             "<table>"]
    for p in metiers:
        corps.append(f'<tr><td><a href="{p["chemin"]}">{e(libelle(p["metier"]).capitalize())}</a></td>'
                     f'<td>{euros(p["mediane"])} / jour · {p["n"]} missions</td></tr>')
    corps.append("</table>")
    corps.append(f'<div class="cta"><a class="btn" href="{LIEN_FREELANCE}">Je suis freelance</a>'
                 f'<a class="btn alt" href="{LIEN_CLIENT}">Je cherche un freelance</a></div>')
    return gabarit("TJM freelance 2026 par métier, ville et secteur | Mon Consultant Indépendant",
                   "TJM médians des missions freelance par métier, ville et secteur, calculés sur les missions réelles de Mon Consultant Indépendant.",
                   "/", "".join(corps))


def ecrire(chemin, contenu):
    f = os.path.join(OUT, chemin.strip("/"), "index.html") if chemin.endswith("/") else os.path.join(OUT, chemin.lstrip("/"))
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(contenu)


def main():
    if "--from-json" in sys.argv:
        with open(sys.argv[sys.argv.index("--from-json") + 1], encoding="utf-8") as f:
            recs = json.load(f)
    else:
        recs = lire_airtable()
    ann = nettoyer(recs)
    pages = construire_pages(ann)
    print(f"Annonces avec TJM : {len(ann)} · pages : {len(pages)} "
          f"({Counter(p['type'] for p in pages.values())})")
    textes_pour(pages)
    maj = dt.date.today()
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    for p in pages.values():
        ecrire(p["chemin"], page_html(p, pages, maj))
    ecrire("/", accueil_html(pages, maj))
    urls = ["/"] + sorted(pages)
    ecrire("/sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(f"<url><loc>{BASE_URL}{u}</loc><lastmod>{maj.isoformat()}</lastmod></url>" for u in urls) + "</urlset>")
    ecrire("/robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")
    ecrire("/404.html", gabarit("Page introuvable | Mon Consultant Indépendant", "", "/404.html",
                                '<h1>Page introuvable</h1><p><a href="/">Voir tous les TJM freelance</a></p>'))


if __name__ == "__main__":
    main()
