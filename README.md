# ai-twitter-bot

Le compte IA et Crypto numero 1 en francais sur X/Twitter. Tranchant, drole, sans filtre. Propulse par Claude Code.

## Comment ca marche

A chaque cycle, le bot invoque le CLI `claude` avec la recherche web activee. Claude trouve la news IA ou Crypto la plus fraiche du jour, choisit l'angle le plus savoureux, et redige un tweet en francais (280 chars max) avec du caractere. Aucune cle API requise - le post se fait via le navigateur + AppleScript.

Le bot poste toutes les 10-15 minutes (aleatoire), uniquement entre 6h et 23h EST.

## Setup

```bash
pip install -r requirements.txt
```

Installe et authentifie le CLI Claude Code :

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

C'est tout. Pas de cles Twitter, pas de cle Anthropic, rien d'autre.

## Usage

```bash
# Lancer le bot (poste en continu)
python main.py

# Poster un seul tweet manuellement
python test_tweet.py
```

Stopper avec `Ctrl+C`.

## Prerequis

- macOS (le post utilise AppleScript pour cliquer automatiquement sur le bouton Tweet)
- CLI Claude Code installe et authentifie
- X/Twitter connecte sur ton navigateur par defaut
