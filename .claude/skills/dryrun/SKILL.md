---
name: dryrun
description: Preview the bot without publishing - scheduled jobs and policy, then the editorial draft for the current slot
allowed-tools: Bash Read
---

Preview what the bot would do. Nothing here touches the browser.

1. Jobs and policy, no browser and no model:
   `uv run --with-requirements requirements.txt python main.py --dry-run`
   Its `slots` list is the Slot table (`SLOTS` in
   `src/editorial/editorial_bot.py`), the last one the Exceptional slot. Each Slot runs 45 minutes from its
   start, cut at bedtime, 23:30 (`due_slot`).
2. Optional, only while a Slot from that list is open: draft and review the
   original the next pass would submit. Calls the models, writes no
   editorial state and spends no Attempt:
   `uv run python -c "from src.editorial.editorial_bot import run_editorial_cycle; print(run_editorial_cycle(preview=True))"`
   `None` means no Slot is due, the daily ceiling is reached, the Slot's
   Attempts are spent, or no source or Draft came back. Overnight it raises
   `OutsideActiveHours`.
3. Show the Draft, its source URL and the Editor's verdict and reason.

Never publish the previewed Draft by hand: originals ship only through the
scheduled editorial cycle.
