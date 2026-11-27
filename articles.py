"""Article hebdomadaire de Mon Consultant Indépendant, rédigé par Claude et publié sur la page Articles.

Deux étapes, lancées par .github/workflows/article-hebdo.yml :
  python articles.py rediger   choisit le sujet, rédige l'article avec les vrais chiffres MCI,
                               fabrique l'image (images/<slug>.png) et prépare data/article_en_attente.json
  python articles.py publier   ajoute l'article dans la table « Articles MCI » de la base Airtable « Bases »
                               (ajout uniquement : rien n'est jamais modifié ni supprimé)

Variables : AIRTABLE_TOKEN (lecture base Production), AIRTABLE_TOKEN_ARTICLES (écriture table Articles MCI),
ANTHROPIC_API_KEY.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

import build

BASE_ARTICLES = "appnrcfpfDDEBpL6R"
TABLE_ARTICLES = "tblKdOy2ElO2uJ7FK"
MODELE = "claude-sonnet-4-6"
AUTEUR = "Mon Consultant Indépendant"
DEPOT_BRUT = "https://raw.githubusercontent.com/AlexBVLM/mci-pages-seo/main"
EN_ATTENTE = "data/article_en_attente.json"
HISTORIQUE = "data/articles_publies.json"
SUJETS = "data/sujets_articles.json"
LIEN_INSCRIPTION = "https://www.mon-consultant-independant.com/sign-up"
LIEN_MISSIONS = "https://www.mon-consultant-independant.com/missions-consultants-freelance"
LIEN_ENTREPRISES = "https://www.mon-consultant-independant.com/entreprises"


def lire_json(chemin, defaut):
    if os.path.exists(chemin):
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    return defaut


def ecrire_json(chemin, donnees):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=1)


def airtable(methode, url, token, corps=None):
    req = urllib.request.Request(url, method=methode, data=json.dumps(corps).encode() if corps else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def titres_existants():
    token = os.environ["AIRTABLE_TOKEN_ARTICLES"]
    titres, offset = [], None
    while True:
        url = f"https://api.airtable.com/v0/{BASE_ARTICLES}/{TABLE_ARTICLES}?fields[]=Titre%20de%20l%27article&pageSize=100"
        d = airtable("GET", url + (f"&offset={offset}" if offset else ""), token)
        titres += [r["fields"].get("Titre de l'article", "") for r in d["records"]]
        offset = d.get("offset")
        if not offset:
            return [t for t in titres if t]


def donnees_marche():
    ann = build.nettoyer(build.lire_airtable())
    pages = build.construire_pages(ann)
    lignes = [f"Annonces analysées (2 dernières années, avec TJM) : {len(ann)}"]
    for p in sorted(pages.values(), key=lambda p: -p["n"]):
        if p["n"] < 8:
            continue
        lignes.append(f"- TJM {build.intitule(p)} : médiane {round(p['mediane'])} €, 8 missions sur 10 entre "
                      f"{round(p['bas'])} et {round(p['haut'])} €, {p['n']} missions ; secteurs : "
                      + ", ".join(s for s, _ in p["secteurs"][:3])
                      + f" ; télétravail fréquent : {p['teletravail'][0][0] if p['teletravail'] else 'inconnu'}"
                      + f" ; page : {build.BASE_URL}{p['chemin']}")
    return "\n".join(lignes[:140])


def claude(consigne, max_tokens=6000):
    corps = json.dumps({"model": MODELE, "max_tokens": max_tokens, "temperature": 0.6,
                        "messages": [{"role": "user", "content": consigne}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=corps, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return "".join(c.get("text", "") for c in d.get("content", [])).strip()


def choisir_sujet(historique):
    faits = {a["sujet"] for a in historique}
    for s in lire_json(SUJETS, []):
        if s not in faits:
            return s
    return None  # liste épuisée : Claude propose un sujet lui-même


CONSIGNE = """Tu es le rédacteur de Mon Consultant Indépendant (MCI), plateforme française qui met en relation des
consultants freelance (consultants indépendants, managers de transition) et des entreprises qui publient des missions.
Écris un article de blog en français pour la page Articles du site, destiné à être bien référencé sur Google.

SUJET : {sujet}

CONSIGNES
- 1 000 à 1 400 mots. Ton professionnel, concret, utile ; vouvoiement ; pas de superlatifs publicitaires.
- Format Markdown : une introduction de 2 ou 3 phrases (sans titre), puis 4 à 6 parties avec des titres « ## »,
  quelques listes à puces si utile, et une conclusion « ## En résumé ».
- Intègre naturellement les expressions que les gens tapent sur Google sur ce sujet (consultant freelance,
  consultant indépendant, mission freelance, TJM, etc.), sans bourrage de mots-clés.
- Chiffres : utilise UNIQUEMENT les chiffres MCI fournis ci-dessous, en précisant qu'ils viennent des missions
  publiées sur Mon Consultant Indépendant. N'invente aucun autre chiffre, aucune statistique, aucune étude.
- Sujets juridiques, fiscaux ou sociaux : reste général, ne donne aucun taux, plafond ou montant réglementaire,
  et invite à vérifier sur les sites officiels (urssaf.fr, impots.gouv.fr, service-public.fr) ou auprès d'un expert.
- Aucun nom d'entreprise cliente, aucune personne réelle.
- Liens : ajoute 2 à 4 liens Markdown vers les pages TJM fournies ci-dessous qui correspondent au sujet,
  puis termine l'article par un court paragraphe (après « En résumé ») invitant les freelances à s'inscrire
  ({inscription}) ou à consulter les missions ouvertes ({missions}) ; si l'article vise aussi les entreprises,
  ajoute le lien {entreprises}.
- Ne reprends pas un sujet déjà traité dans les titres existants ci-dessous.

TITRES DÉJÀ PUBLIÉS
{titres}

CHIFFRES MCI (missions réelles)
{donnees}

RÉPONSE : uniquement un objet JSON, sans texte autour, au format
{{"titre": "titre de l'article (70 caractères maximum, contient le mot-clé principal)", "contenu": "article en Markdown"}}"""


def rediger():
    historique = lire_json(HISTORIQUE, [])
    sujet = choisir_sujet(historique) or ("Propose toi-même un nouveau sujet utile aux consultants freelance ou aux "
                                         "entreprises qui les recrutent, différent des titres déjà publiés")
    titres = titres_existants() + [a["titre"] for a in historique]
    consigne = CONSIGNE.format(sujet=sujet, titres="\n".join(f"- {t}" for t in titres), donnees=donnees_marche(),
                               inscription=LIEN_INSCRIPTION, missions=LIEN_MISSIONS, entreprises=LIEN_ENTREPRISES)
    texte = claude(consigne)
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte.strip())
    article = json.loads(texte)
    titre, contenu = article["titre"].strip(), article["contenu"].strip()
    mots = len(contenu.split())
    if mots < 700 or "##" not in contenu:
        sys.exit(f"Article refusé (trop court ou sans parties) : {mots} mots")
    slug = build.slug(titre)[:70]
    image = f"images/{dt.date.today().isoformat()}-{slug}.png"
    fabriquer_image(titre, image)
    ecrire_json(EN_ATTENTE, {"sujet": sujet, "titre": titre, "contenu": contenu, "image": image, "mots": mots})
    print(f"Article rédigé : {titre} ({mots} mots)")


def fabriquer_image(titre, chemin):
    from PIL import Image, ImageDraw, ImageFont
    largeur, hauteur = 1200, 630
    img = Image.new("RGB", (largeur, hauteur), (34, 44, 82))
    d = ImageDraw.Draw(img)
    d.rectangle([0, hauteur - 18, largeur, hauteur], fill=(90, 154, 166))
    d.rectangle([70, 90, 82, 330], fill=(90, 154, 166))

    def police(taille, gras=False):
        for f in (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if gras else []) + \
                 ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
            if os.path.exists(f):
                return ImageFont.truetype(f, taille)
        return ImageFont.load_default(size=taille)

    f_titre, f_bas = police(54, True), police(30)
    lignes, ligne = [], ""
    for mot in titre.split():
        essai = (ligne + " " + mot).strip()
        if d.textlength(essai, font=f_titre) > largeur - 220:
            lignes.append(ligne)
            ligne = mot
        else:
            ligne = essai
    lignes.append(ligne)
    y = 90
    for l in lignes[:5]:
        d.text((115, y), l, font=f_titre, fill=(255, 255, 255))
        y += 72
    d.text((115, hauteur - 110), "Mon Consultant Indépendant", font=f_bas, fill=(170, 205, 212))
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    img.save(chemin, optimize=True)


def publier():
    a = lire_json(EN_ATTENTE, None)
    if not a:
        sys.exit("Aucun article en attente")
    token = os.environ["AIRTABLE_TOKEN_ARTICLES"]
    if a["titre"] in titres_existants():
        sys.exit("Article déjà présent dans Airtable : rien n'est ajouté")
    champs = {"Titre de l'article": a["titre"], "Contenu article": a["contenu"], "Auteur": AUTEUR,
              "Image": [{"url": f"{DEPOT_BRUT}/{a['image']}"}]}
    r = airtable("POST", f"https://api.airtable.com/v0/{BASE_ARTICLES}/{TABLE_ARTICLES}", token,
                 {"records": [{"fields": champs}], "typecast": False})
    historique = lire_json(HISTORIQUE, [])
    historique.append({"date": dt.date.today().isoformat(), "sujet": a["sujet"], "titre": a["titre"],
                       "mots": a["mots"], "airtable": r["records"][0]["id"], "image": a["image"]})
    ecrire_json(HISTORIQUE, historique)
    os.remove(EN_ATTENTE)
    print("Article publié :", a["titre"])


if __name__ == "__main__":
    {"rediger": rediger, "publier": publier}[sys.argv[1]]()
