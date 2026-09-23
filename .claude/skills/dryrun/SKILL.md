---
name: dryrun
description: Preview the bot without publishing - scheduled jobs and policy, then the editorial draft for the current slot
allowed-tools: Bash Read
---

Preview what the bot would do. Nothing here touches the browser.

1. Jobs and policy, no browser and no model:
   `uv run --with-requirements requirements.txt python main.py --dry-run`
2. Optional, during an editorial slot window only (05:00, 08:00, 11:30,
   14:30, 17:30, 20:30 Toronto, 45 minutes each): draft and review the
   original the next pass would submit. Calls the models, writes no
   editorial state and spends no attempt:
   `uv run python -c "from src.editorial_bot import run_editorial_cycle; print(run_editorial_cycle(preview=True))"`
   `None` means no slot is due, the daily ceiling is reached, the slot's
   attempts are spent, or no source or draft came back. Outside
   04:30–22:00 Toronto time it raises `OutsideActiveHours`.
3. Show the draft, its source URL and the editor's verdict and reason.

Never publish the previewed draft by hand: originals ship only through the
scheduled editorial cycle.
