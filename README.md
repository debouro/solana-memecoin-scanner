# Solana Memecoin Market Scanner

Scanner automatisé de memecoins **Solana uniquement** : collecte périodique des données de marché, filtre market cap ≥ 50 000 $, détection des variations ≥ ±35 % sur le prix réel, détection des cycles (haut → bas → hausse ≥ 35 % → haut → baisse → bas), analyse de liquidité, statistiques historiques et API interne. Aucun interface graphique (v1 = moteur uniquement).

## Installation

```bash
cd solana-memecoin-scanner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # puis éditer .env si besoin
```

Python 3.12 requis. Aucune clé API obligatoire (DexScreener + GeckoTerminal sont gratuits et sans clé). `BIRDEYE_API_KEY` est optionnel (source tertiaire + OHLCV). `USE_SOLANA_RPC=1` active l'enrichissement on-chain (date de création estimée via RPC).

## Configuration (variables d'environnement, voir `.env.example`)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATABASE_URL` | `sqlite:///scanner.db` | Base persistante (SQLite v1, Postgres possible) |
| `MCAP_THRESHOLD_USD` | `50000` | Seuil de market cap du filtre |
| `VARIATION_THRESHOLD_PCT` | `35` | Amplitude minimale hausse/baisse détectée |
| `COLLECT_INTERVAL_SECONDS` | `60` | Fréquence de collecte |
| `CONFIRMATION_WINDOW` | `3` | Nb d'observations pour confirmer un point haut/bas |
| `RETRACEMENT_PCT` | `5` | Retracement déclenchant la confirmation d'un extrême |
| `LIQUIDITY_LOW_USD` / `LIQUIDITY_DECLINE_PCT` / `LIQUIDITY_DECLINE_WINDOW` | `10000` / `30` / `10` | Alertes liquidité faible / fortement décroissante |
| `SOURCE_COHERENCE_TOLERANCE_PCT` | `20` | Écart max toléré entre sources avant signalement |
| `RATE_LIMIT_PER_MINUTE` | `55` | Limite de requêtes/min (backoff auto sur 429) |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | Bind de l'API interne (loopback uniquement) |
| `API_ONLY=1` | `0` | `serve` lance l'API sans la boucle de collecte |

## Utilisation (CLI)

```bash
python -m scanner.cli init-db                          # créer le schéma
python -m scanner.cli add-token <MINT_ADDRESS>        # suivre un mint manuellement
python -m scanner.cli scan                             # un passage complet (découverte + collecte + analyse)
python -m scanner.cli serve                            # collecte périodique en continu + API sur http://127.0.0.1:8000
python -m scanner.cli report                           # rapport console des tokens suivis
python -m scanner.cli report --mint <MINT_ADDRESS>     # rapport d'un seul token
```

Règles de fiabilité : identité = **Mint Address** uniquement, historique append-only jamais réinitialisé (même sous le seuil), market cap et FDV stockées séparément, données manquantes = NULL (jamais inventées), divergences entre sources consignées dans `data_quality`, chaque observation porte son `source` et son horodatage UTC.

## API interne (FastAPI, loopback)

Démarrée par `python -m scanner.cli serve` (ou `API_ONLY=1` pour l'API seule) :

- `GET /health` — état du service
- `GET /config` — configuration effective (clés masquées)
- `GET /tokens?tracked=true&min_market_cap=50000` — liste des tokens (filtrable)
- `POST /tokens/{mint}` — ajouter un mint à la watchlist
- `GET /tokens/{mint}` — fiche token (création, 1er franchissement, mcap max)
- `GET /tokens/{mint}/observations?source=dexscreener&limit=500` — historique de collecte
- `GET /tokens/{mint}/extremes` — points hauts/bas confirmés
- `GET /tokens/{mint}/movements?counted_only=true` — variations (±35 % = `counted=true`)
- `GET /tokens/{mint}/cycles` — cycles détectés (prix départ/min/max, amplitudes, durées, horodatages, liquidité aux extrêmes)
- `GET /tokens/{mint}/liquidity` — évolution de la liquidité + alertes
- `GET /tokens/{mint}/stats` — statistiques agrégées du token
- `GET /alerts` — alertes liquidité + problèmes de qualité de données + tokens anomaliques
- `POST /scan/run` — déclencher un passage de collecte (tâche de fond)

Docs interactives : `http://127.0.0.1:8000/docs`

## Interface web (V2)

L'interface est servie par le même processus que l'API :

```bash
python -m scanner.cli serve
# puis ouvrir http://127.0.0.1:8000/ dans un navigateur
```

Espaces disponibles (navigation par onglets, 100 % en français, dark mode) :

1. **Dashboard** — KPI globaux (tokens surveillés, passés filtres, nouveaux aujourd'hui, cycles aujourd'hui, phases, état du scanner), tableau triable/recherchable/filtrable avec pagination et actualisation automatique, badge de phase par token (rouge = descendante, jaune = consolidation, vert = ascendante, bleu = nouveau cycle, gris = données insuffisantes), étoile favoris.
2. **Fiche memecoin** (`#/token/<mint>`) — infos complètes (mint copiable, création, 1er franchissement des 50 k$, mcap/FDV/prix/volume/liquidité/txns/acheteurs-vendeurs, variations 5m/1h/24h), graphique en chandeliers interactif (zoom, pan, périodes 5m à historique complet) avec marqueurs points hauts/bas, mouvements confirmés et cycles, ATH/ATL de l'historique collecté, tableau des cycles, courbe de liquidité.
3. **Favoris** — persistance en base (survit à la fermeture), consultables même hors filtres, tri et accès direct à la fiche.
4. **Centre de contrôle** — tous les paramètres du moteur modifiables (mcap min/max, seuils hausse/baisse, durées min/max des mouvements et cycles avec unité s/min/h/j, liquidité, volume, fréquences de collecte/analyse/UI, nb max de tokens) ; `PUT /settings` applique réellement au moteur à la prochaine collecte, sans jamais supprimer l'historique ; réinitialisation et valeurs par défaut disponibles, dernière modification affichée.
5. **Notifications** — nouveaux tokens, cycles confirmés, hausses/baisses confirmées, alertes liquidité, données indisponibles, erreurs de connexion ; horodatées, avec compteur de non lues.
6. **Backtesting** — simulation virtuelle de stratégies (capital, objectif de gain, seuil de perte, frais, slippage, période, nb max de cycles, mode d'entrée) sur les observations réellement collectées : entrée uniquement après confirmation d'un point bas (jamais de données futures), exécution au prix de l'observation suivante, résultats détaillés + tableau des opérations (clic = marqueurs entrée/sortie sur le graphique) + comparaison de stratégies + historique des simulations persisté.

L'UI consomme exclusivement l'API interne du moteur (aucun deuxième moteur) : `/tokens/summary`, `/tokens/{mint}/overview|chart|phase|ath-atl|cycles|movements|liquidity|stats`, `/stats/global`, `/favorites`, `/notifications`, `/settings`, `/backtest/*`, `/scan/run`.

## Tests

```bash
python -m pytest tests/ -q
```

## Limites connues

- Seuls les tokens indexés par DexScreener/GeckoTerminal sont visibles ; un token sans pool indexé est invisible (pas « à 0 »).
- La découverte couvre les boosts/profils DexScreener et les pools tendance/nouveaux de GeckoTerminal ; complète via `add-token`.
- L'historique démarre au premier franchissement du seuil (rétro-remplissage OHLCV possible via Birdeye/GeckoTerminal, marqué comme tel).
- Les prix à très faible liquidité sont manipulables : ils sont signalés (alertes liquidité), jamais supprimés.
