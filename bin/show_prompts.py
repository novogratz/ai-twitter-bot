#!/usr/bin/env python3
"""Print the prompts the jobs send to the model, as the Reply generator and
the editorial draft assemble them, without calling a model, opening Safari
or writing state.

    uv run --with-requirements requirements.txt python bin/show_prompts.py
    uv run --with-requirements requirements.txt python bin/show_prompts.py DEBATE

Without an argument, one line per prompt: its label and its size. With a
label, or part of one, the full prompts that match. Each Reply answers the
same sample post from a sample author; the Relations' prompts answer it
under their own handle. The editorial draft uses the Account's first Slot
and one sample source.
"""
import os
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

POST = "Anthropic just shipped a 1M-token context window for Claude. Does long context finally kill RAG?"
ENGAGER_REPLY = "lol so true, RAG was always a patch"
OWN_POST = "Long context is a bigger desk, not a better memory."
SOURCE = {"id": "0", "kind": "news", "url": "https://www.anthropic.com/news/example", "title": "Example",
          "published_at": "",
          "body": "Claude now supports a one million token context window for all developers today. " * 20}


def capture() -> dict:
    """Each prompt by its log label, from one generation per call."""
    from src.core import account
    from src.core.llm_client import LLMResult
    from src.editorial import editorial_bot
    from src.replies import debate_bot, direct_reply, replyback_agent, reply_generator, reply_quality

    prompts = {}

    def model(prompt, _model, **options):
        prompts[options["label"]] = prompt
        # Each caller's own decline, so none logs an error in bot.log.
        return LLMResult(0, '{"skip": true}' if options["output_json"] else "SKIP", "")

    with mock.patch.object(reply_generator, "run_llm", model), mock.patch.object(editorial_bot, "run_llm", model), \
            mock.patch.object(reply_quality, "run_llm", model), \
            mock.patch.object(reply_quality, "require_active"):
        passages = (reply_quality.Passage("0", SOURCE["url"], "", SOURCE["body"][:600]),)
        reply_quality.review(POST, "", OWN_POST, passages)
        reply_generator.generate(direct_reply.reply_call("someone"), author="someone", text=POST,
                                 evidence=reply_quality.evidence_block(passages))
        reply_generator.generate(debate_bot.reply_call(), author="someone", text=POST,
                                 evidence=reply_quality.evidence_block(passages))
        reply_generator.generate(replyback_agent.reply_call(), author="someone", text=ENGAGER_REPLY,
                                 context=OWN_POST)
        for relation in account.current().relations.handles.values():
            call = direct_reply._vip_call(relation.handle)
            if call:
                reply_generator.generate(call, author=relation.handle, text=POST)
        editorial_bot.draft_post(editorial_bot.slots()[0], [SOURCE], [OWN_POST])
    return prompts


def main(argv) -> int:
    prompts = capture()
    if not argv:
        for label, prompt in prompts.items():
            print(f"{label}: {len(prompt)} characters")
        return 0
    wanted = {label: prompt for label, prompt in prompts.items() if argv[0] in label}
    if not wanted:
        print(f"No prompt label contains {argv[0]!r}: {', '.join(prompts)}", file=sys.stderr)
        return 1
    for label, prompt in wanted.items():
        print(f"##### {label}: {len(prompt)} characters\n{prompt}\n")
    return 0


if __name__ == "__main__":
    from src.core import settings
    settings.load()
    sys.exit(main(sys.argv[1:]))
