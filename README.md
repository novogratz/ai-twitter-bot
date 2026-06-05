# Bot influenceur Twitter/X autonome

> **Tu me détesteras jusqu'à ce que j'aie raison.**

Agent influenceur Twitter/X auto-évolutif spécialisé sur trois piliers : **Bourse** (indices, macro, résultats, dividendes, crypto comme classe d'actifs — pas seulement les valeurs IA/spatiales), **IA** et **Spatial**. Il publie une analyse **française** pointue (thèses pluriannuelles, jamais d'objectif de prix court terme), répond dans la langue du tweet parent, amplifie les signaux fiables et gère son ratio d'abonnements sous une politique de suivi maîtrisée. Ollama (local) comme LLM principal, avec Codex / Claude / Gemini en repli. Pas de clé API Twitter — automatisation navigateur uniquement.

> **Pivot 2026-06-02 :** retour au **français** (toute la création + les commentaires de quote-repost en FR ; les réponses suivent la langue du parent). Spécialité **Bourse large + IA + Spatial**, le plus pointu de la pièce. Objectifs de prix court terme **interdits**. Suivi **hybride** : on suit de nouveaux comptes français, mais tant que le ratio dépasse le plafond (abonnements < 0,8 × abonnés) un suivi n'est autorisé qu'un jour **net-négatif** (suivis du jour < désabonnements du jour), pour que le ratio se soigne chaque jour. Le quote-repost est la surface la plus rentable et tourne à plein régime.

---

## Ce que fait le bot

Le bot fait tourner **plus de 30 micro-bots concurrents** orchestrés par une boucle APScheduler. Chaque bot a un rôle :

| Couche | Bots | Rôle |
|---|---|---|
| **Contenu** | `agent`, `hotake_agent`, `breakout_bot`, `spicy_bot`, `thread_bot`, `digest_thread_bot` | Posts originaux — news, Décodes quotidiens/hebdo/mensuels, hot takes, threads (en français) |
| **Repartage** | `retweet_bot`, `quote_tweet_bot`, `notify_bot` (boost) | Amplifie les sources fiables et les gros posts visibles avec filtres fraîcheur + niche ; le quote ajoute toujours un angle français par-dessus |
| **Réponse** | `direct_reply`, `reply_bot`, `engagement_targeting`, `early_bird_bot`, `mega_watch_bot`, `replyback_agent`, `viral_followup_bot`, `spike_bot` | Engagement temps réel sur les tweets à forte vélocité, fenêtre top-réponses des gros comptes |
| **Suivi** | `engage_bot`, `discover_bot`, `scout_agent`, `followback_bot`, `smart_unfollow_bot` | Croissance réseau — découverte FR, suivi maîtrisé, élagage des non-réciproques |
| **Like** | `like_bot`, `notify_bot` | Likes groupés pour notifications sortantes |
| **Promotion** | `pin_bot`, `promote_bot` | Épingle le meilleur post, repartage la meilleure réponse sur le profil |
| **Signal temps réel** | `rss_signal_bot`, `hn_signal_bot`, `x_home_scout_bot`, `auto_tune_bot` | Agrège les tendances RSS + HN + Reddit + X home ; 20-50 min avant WebSearch |
| **Auto-évolution** | `meta_strategy_agent`, `strategy_agent`, `evolution_agent`, `reflection_agent`, `self_evolution_agent`, `analyzer_bot` | Runs agentiques qui réécrivent stratégie, persona, dossiers ; activés par `ENABLE_AI_MAINTENANCE` / `ENABLE_AI_DISCOVERY` |
| **Sécurité** | `suppression_watch_bot`, `health.py`, `respect_list` | Détection de shadowban + watchdog Safari + liste de comptes protégés |
| **Hygiène** | `cleanup_bot`, `heartbeat_bot`, `daily_digest`, `follower_tracker_bot`, `performance.py` | Rotation d'état, battements de cœur, métriques de croissance, apprentissages |

---

## Fiabilité + voix thérapeute 2026-06-05 (round 2)

- **`engine_health_bot`** — sentinelle horaire : rythme du jour vs moyenne 7 jours à la même heure, alerte si une surface tombe sous 40 % (né de l'effondrement silencieux des retweets). **`conversion_attribution_bot`** — nouveaux followers rapprochés des auteurs auxquels on a répondu sous 48 h → poids par auteur ajusté dans le ciblage. Bouton Follow réparé (3 stratégies de sélecteur + statut réel du clic, anti-churn 30 j dans les deux sens). Replyback : @handle récupéré depuis l'URL du statut. Langue des réponses : match strict du parent (EN par défaut). **Voix thérapeute** alignée sur tous les prompts (quote, réponses, spicy) : nommer l'émotion → valider → re-cadrer calmement avec le fait précis.

## Full agentic (2026-06-05 PM)

- **`tests/test_guards.py`** (19 tests, <1 s) + **CI GitHub Actions** sur chaque push : le filet de sécurité des pushes autonomes. **`bin/auto_improve.sh`** + launchd (07h17 quotidien) : session Claude Code headless qui diagnostique les métriques, livre UNE amélioration testée et pousse sur main chaque jour. **Auto-guérison** : une alerte d'effondrement (`engine_health_bot`) déclenche un run d'urgence (cooldown 6 h, coupe-circuit `ENABLE_SELF_HEAL=0`). Le bot ne démarre JAMAIS tout seul — l'opérateur garde la main.

## Surge quote-RT + persona thérapeute (2026-06-05 PM)

- Quote-RT validé (4 likes en 2 h sur la première sortie) → **150/jour**, espacement 90 s, barre du sweeper 200 likes, 4 quotes/cycle — mandat opérateur « abuse un peu pendant quelques semaines ». `bot_self_en/fr.json` réécrits dans l'esprit de la bio (« Treating market trauma… Heal the fear ») — l'ancien état « trader cynique à 3 h du matin » combattait l'identité thérapeute dans chaque prompt. Release de lancement **`launch-v1.0`** publiée sur GitHub (point de rollback).

## Poussée croissance 2026-06-05

- **`feed_sweeper_bot`** — balaye For You / Following en alternance (8 min) : post ≥300 likes → quote-retweet avec un angle malin, sinon → réponse. **`viral_stunt_bot`** — comédie « superviral format » (max 2/jour, cadence irrégulière, barre 9/10 sinon SKIP). **`space_promo_bot`** — campagne opérateur jusqu'au 13/06 (IPO SpaceX 12/06) : promo douce $MNTS/$SPCX/$SPCE, 2 posts/jour avec GIF (`media/promo_gifs/`), disclaimer « Not financial advice », rotation WSB verrouillée (`operator_locked`). Moteur quote réparé (le bot brûlait son meilleur candidat à chaque skip d'espacement), spacing 120 s, cap 100/jour, handles prioritaires (TheBTCTherapist), fenêtre réponses 72 h + scroll profond des feeds.

## Garde-fous 2026-06-02 (points de passage uniques)

Toutes les actions d'écriture passent par les fonctions de plus bas niveau de `twitter_client` (`post_tweet` / `quote_tweet` / `reply_to_tweet` / `follow_account` / `unfollow_account` / `like_tweet` / `retweet_post`), pour que les ~30 bots obéissent aux mêmes règles sans réécriture :

- **`src/content_guard.py`** — validation avant publication. Rejette tout brouillon qui associe un prix/multiplicateur à une échéance proche (regex FR+EN), exige le **français** pour les originaux + quotes, et refuse les **réponses paresseuses** (« bien vu », trop courtes). `generate_validated()` régénère jusqu'à N fois puis skip+log — un brouillon signalé n'est JAMAIS publié. **Anti-doublon v2 (2026-06-05)** : `is_duplicate()` détecte « même thèse, mots différents » (Jaccard sur mots racinisés, containment, bigrammes partagés, même-actualité sous 24h), appliqué aux DEUX points de passage (`post_tweet` ET `quote_tweet`) ; chaque post/quote publié est enregistré dans `tweet_history.json` depuis le point de passage pour que la mémoire couvre toutes les surfaces et survive aux redémarrages. `spicy_bot` est désormais **ancré sur l'actualité** : take/question obligatoirement en réaction à un item frais d'`external_signal.json` (≤6h), sinon SKIP — plus de divagations hors-actu.
- **`src/action_guard.py`** — registre d'actions horodaté (`action_ledger.json`) pour l'anti-churn 30 jours + audit. Plafonds quotidiens (3 originaux, **18 quote-reposts**, 30 réponses, 5 suivis, 25 désabonnements) avec espacement jitter (45 min posts, 12 min quotes, 90 s réponses), jamais de rafale. Politique de suivi hybride + règle net-négative. `DRY_RUN=1` journalise sans exécuter (coupe-circuit).
- **`whitelist.json`** — comptes curatés en tiers (tier1 sources/cibles, tier2 pairs FR, tier3 veille). Source pour le quote-repost + le ciblage d'engagement. Le bot peut **suggérer** des ajouts mais ne s'auto-ajoute jamais.
- **`src/engagement_targeting.py`** — moteur de croissance : classe les posts des comptes whitelist tier1/2 par **vélocité** (likes+reposts / heure) et répond aux plus chauds avec une prise substantielle, langue alignée.
- **`src/bot_memory.py`** — mémoire : injecte un digest des derniers posts dans chaque prompt pour rappeler une thèse passée quand ça apporte de la valeur.
- **`following_count.json`** — compteur d'abonnements vivant (amorcé au vrai socle ~4,2K), maintenu par `adjust_following()` pour que l'invariant de ratio soit honnête.

---

## Architecture en un coup d'œil

```
┌──────────────────── COUCHE SIGNAL TEMPS RÉEL ──────────────────┐
│  Flux RSS (5m)   HN+Reddit (20m)   X /home (7m)   Comptes fiables│
│        └────────────┬──────────────┘              │             │
│                     ▼                              ▼             │
│             external_signal.json          retweet_bot/quote     │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── COUCHE GÉNÉRATION (français) ────────────────────┐
│   agent (news)   hotake   breakout   spicy   thread   digest    │
│        └────────────┬───────────────────────────────────┘       │
│                     ▼   content_guard → twitter_client.post_tweet│
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── COUCHE ENGAGEMENT ───────────────────────────────┐
│  engagement_targeting  direct_reply  reply_bot  early_bird      │
│  mega_watch  replyback  viral_followup  spike  + action_guard   │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── COUCHE ADAPTATION (auto-push git) ───────────────┐
│  meta_strategy(4h)  strategy(3h)  evolution(3h)  analyzer(4h)   │
│  reflection(6h)     self_evolution(4h)  scout(4h)               │
│        ▼  live_strategy.json | bot_self.json | personality.json │
│           directives.md | dynamic_*.json | learnings.json       │
└─────────────────────────────────────────────────────────────────┘
                     │
┌─────────────── COUCHE SÉCURITÉ + HYGIÈNE ───────────────────────┐
│  suppression_watch  health(watchdog Safari)  respect_list       │
│  cleanup  heartbeat  daily_digest  follower_tracker             │
└─────────────────────────────────────────────────────────────────┘
```

Voir [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) pour le détail complet.

---

## Démarrage rapide

**Prérequis**

- macOS (automatisation Safari + AppleScript, pilotage navigateur, pas de clé API)
- Python 3.10+
- Ollama en local, avec le CLI Codex (`codex`) authentifié en secours
- Compte Twitter/X connecté dans Safari

**Installation**

```bash
git clone https://github.com/<vous>/ai-twitter-bot.git
cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env  # puis éditer les plafonds + modèle + handle
```

**Lancer (premier plan)**

```bash
./bin/run.sh        # Ctrl-C pour arrêter
```

**Arrêter depuis un autre terminal**

```bash
./bin/stop.sh
```

**Suivre les logs**

```bash
tail -F bot.log
```

**Mode vérification (recommandé avant le live)** : mettre `DRY_RUN=1` dans `.env`, relancer, observer dans `bot.log` les lignes `[DRY_RUN] would …` pour chaque post/réponse/quote/suivi/désabonnement, puis repasser à `DRY_RUN=0`.

Voir [`docs/OPERATIONS.md`](docs/OPERATIONS.md) pour le runbook complet.

---

## Configuration

Chaque réglage est une variable d'environnement dans `.env`. Les valeurs par défaut sont calibrées pour le build **français** (pivot 2026-06-02) avec des plafonds prudents. Bloc complet des réglables dans `src/config.py`.

| Variable | Défaut | Rôle |
|---|---|---|
| `BOT_HANDLE` | `AISpaceDecoder` | Ton handle X (sans `@`) |
| `CONTENT_LANG_PRIMARY` | `fr` | `fr` / `en` / `mixed` — langue du contenu autonome (les réponses suivent toujours le parent) |
| `AI_CLI` | `ollama` | `ollama` / `codex` / `opencode` / `claude` / `gemini` |
| `DRY_RUN` | `0` | `1` = journalise les écritures sans les exécuter (coupe-circuit) |
| `MAX_ORIGINALS_PER_DAY` | `3` | Plafond de posts originaux/jour |
| `MAX_QUOTE_REPOSTS_PER_DAY` | `18` | Plafond de quote-reposts/jour (surface la plus rentable) |
| `MAX_REPLIES_PER_DAY` | `30` | Plafond de réponses/jour |
| `MIN_SECONDS_BETWEEN_POSTS` | `2700` | Espacement mini posts (45 min) + jitter |
| `MIN_SECONDS_BETWEEN_QUOTES` | `720` | Espacement mini quotes (12 min) + jitter |
| `MIN_SECONDS_BETWEEN_REPLIES` | `90` | Espacement mini réponses (90 s) + jitter |
| `FOLLOW_WHITELIST_ONLY` | `0` | `1` = ne suivre que la whitelist (aucun nouveau compte) |
| `ENABLE_FOLLOW_BLAST` | `0` | `1` = réactive le suivi de masse réciproque (déconseillé) |
| `FOLLOW_RATIO_CEILING` | `0.8` | Plafond : abonnements < 0,8 × abonnés |
| `MAX_FOLLOWS_PER_DAY` | `5` | Plafond de suivis/jour |
| `MAX_UNFOLLOWS_PER_DAY` | `25` | Plafond de désabonnements/jour (élagage) |
| `CHURN_COOLDOWN_DAYS` | `30` | Anti-churn : pas de re-suivi/re-désabonnement avant 30 j |
| `BAN_SHORT_TERM_PRICE_TARGETS` | `1` | Bloque prix + échéance proche dans tout brouillon |
| `ENABLE_AI_MAINTENANCE` | `1` | Active les agents d'auto-évaluation/stratégie (Claude/Ollama) |

Référence complète : [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

---

## Principes de conception

1. **Sécurité du process > parité de fonctionnalités.** Chaque cycle est enveloppé dans `safe_run_*` : une exception d'un cycle ne peut pas crasher le scheduler. Le watchdog redémarre Safari après 3 échecs consécutifs. Le `BlockingScheduler` tourne avec 30 threads, `misfire_grace_time=3600` et `coalesce=True`.
2. **Auto-modification autonome à rayon de souffle borné.** La maintenance agentique réécrit l'état dans des plages bornées et auto-pousse sur git (tout est audité).
3. **État idempotent.** Les compteurs quotidiens sont indexés par date ; un redémarrage en cours de journée reprend sans double-poster.
4. **Automatisation UI best-effort.** Chaque clic JS dans le DOM de X est protégé par try/except avec repli ; un cycle échoué est logué et sauté, jamais de crash.
5. **Attribution bandit intégrée.** Chaque tweet porte une ligne `[PATTERN: <ID>]` retirée avant publication et loguée dans `engagement_log.csv` ; `evolution_agent` en calcule le ROI par pattern.
6. **L'impact concret bat l'esprit abstrait.** Acteurs nommés + chiffres exacts + conséquences réelles surperforment les punchlines isolées.
7. **Séparation liste dure / liste douce.** `BLOCKLIST` (dure, jamais d'engagement) vs `respect_list` (douce, engager mais ne jamais critiquer nommément).

---

## Pipeline de signal temps réel

```
RSS (5m)        → 20 flux de sources fiables, fetch parallèle 8 threads (~1s)
HN/Reddit (20m) → front page HN + r/MachineLearning + r/CryptoCurrency
X /home (7m)    → filtre niche du fil d'accueil
                ↓
        external_signal.json (top 30, par fraîcheur)
                ↓
   agent.py + hotake_agent.py + breakout_bot.py injectent en contexte
```

WebSearch (indexation Google) retarde la publication de 30-60 min ; le RSS publie en quelques secondes. Net : le prompt voit le scoop **20-50 min** avant WebSearch.

---

## Auto-évaluation autonome (Claude/Ollama)

Les agents de maintenance tournent en cron quand `ENABLE_AI_MAINTENANCE=1` (par défaut activé). Chacun écrit ses décisions dans un fichier d'état JSON/MD ET auto-pousse sur git :

| Agent | Cadence | Décide | Fichier d'état |
|---|---|---|---|
| `analyzer_bot` | 4h | Top patterns, meilleures heures, sujets montants | `performance_insights.json` |
| `meta_strategy_agent` | 4h | Plafonds quotidiens, facteur de cadence, focus sujet | `live_strategy.json` |
| `strategy_agent` | 3h | Nouvelles requêtes + comptes à engager | `dynamic_*.json` |
| `evolution_agent` | 3h | Directives de style, élagage/renfort | `directives.md` + `*_accounts.json` |
| `reflection_agent` | 6h | Dossiers par compte (catégorie, posture, ressenti) | `personality.json` |
| `self_evolution_agent` | 4h | Humeur / obsession / dérive / voix du bot | `bot_self.json` |
| `scout_agent` | 4h | Nouvelles voix FR à surveiller + auto-suivis | `dynamic_accounts.json` |

Chaque agent est borné (plages min/max sur les caps, élagage plafonné, etc.) — un mauvais cycle se dégrade proprement.

---

## Architecture de sécurité

- **`BLOCKLIST`** (dure) — comptes jamais engagés.
- **`respect_list.py`** (douce) — influenceurs engageables mais jamais critiqués nommément ; scrub à chaque chemin de publication.
- **`personality_store.HARD_RULES_BLOCK`** — règles non négociables dans chaque prompt : (1) aucun contenu illégal, (2) pas de troll des institutions gouvernementales US.
- **`suppression_watch_bot`** — contrôle de santé horaire ; met en pause les bots agressifs si les likes moyens chutent sous le plancher.
- **`health.py`** — watchdog Safari ; redémarre Safari après 3 échecs consécutifs.
- **`safari_hygiene.py`** — quit+relance préventif toutes les 2h, nettoyage service workers/caches ; relance réactive après 5 pages blanches consécutives.

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — lattice complète des bots + catalogue des modules
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — runbook + debug + tuning
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — référence des variables d'environnement
- [`CLAUDE.md`](CLAUDE.md) / [`CODEX.md`](CODEX.md) — contexte projet pour les sessions Claude Code / Codex
- [`core_identity.md`](core_identity.md) — colonne idéologique stable du bot (chargée dans chaque prompt)

---

## Licence

MIT. Voir [`LICENSE`](LICENSE).
