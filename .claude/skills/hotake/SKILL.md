---
name: hotake
description: Generate a hot take, preview it, then optionally post
disable-model-invocation: true
allowed-tools: Bash
---

Generate and review a hot take:

1. Run `python3 -c "from src.hotake_agent import generate_hotake; print(generate_hotake())"` to generate
2. Show the hot take to the user with character count
3. Ask: post it, edit it, or generate a new one?
4. If approved, post with `python3 -c "from src.twitter_client import post_tweet; post_tweet('''TEXT''')"`
