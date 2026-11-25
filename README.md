# Pages SEO Mon Consultant Indépendant

Mini-site de pages « TJM freelance » par métier, ville et secteur, calculées sur les annonces réelles de la base Airtable Production (lecture seule).

- `build.py` : lit Airtable, calcule les TJM, fait rédiger les textes par Claude Haiku (gardés dans `data/textes.json`) et fabrique les pages dans `site/`.
- `.github/workflows/mise-a-jour.yml` : relance tout chaque lundi matin et met le site en ligne (GitHub Pages).
- Secrets à renseigner dans Settings > Secrets and variables > Actions : `AIRTABLE_TOKEN` (lecture seule sur la base Production) et `ANTHROPIC_API_KEY`.
- Une page n'est publiée qu'à partir de 5 annonces avec TJM sur les 2 dernières années.
