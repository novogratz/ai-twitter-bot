---
name: news
description: Generate a news tweet preview without posting - review first
disable-model-invocation: true
allowed-tools: Bash
---

Preview a news tweet:

1. Generate: `python3 -c "from src.agent import generate_tweet; t = generate_tweet(); print(t if t else 'SKIP')" `
2. Show tweet with character count
3. Ask: post it, edit it, regenerate, or discard?
4. If posting: `python3 -c "from src.twitter_client import post_tweet; post_tweet('''TEXT''')"`
