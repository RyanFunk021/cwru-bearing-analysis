#!/usr/bin/env python3
"""
Bible Verse Lookup & Sci-Fi Connector
--------------------------------------
Enter a subject → get the top 10 Bible verses on that subject,
see the original Hebrew/Greek keywords analysed, then discover
10 sci-fi stories/movies that share those themes.
"""

import anthropic
import os
import sys

# ── API KEY ────────────────────────────────────────────────────────────────
# Paste your Anthropic API key between the quotes below, or leave it empty
# and set the ANTHROPIC_API_KEY environment variable instead.
API_KEY = ""
# ──────────────────────────────────────────────────────────────────────────

DIVIDER = "─" * 70

PROMPT_TEMPLATE = """\
You are a biblical scholar with expertise in Hebrew and Greek, and also a \
knowledgeable sci-fi enthusiast.

The user has entered the subject: "{subject}"

Respond in exactly the structure below — no extra commentary before or after.

════════════════════════════════════════════════════════════════════════
📖  TOP 10 BIBLE VERSES — {subject_upper}
════════════════════════════════════════════════════════════════════════

For each verse (1–10):

[N]. REFERENCE (e.g. John 3:16 — NIV)
     Quote the full verse text.
     ▸ Original-language keywords:
       • Word 1 (transliteration, language): meaning / nuance
       • Word 2 (transliteration, language): meaning / nuance
       (Include 2–4 key words per verse, Hebrew for OT, Greek for NT)

════════════════════════════════════════════════════════════════════════
🚀  TOP 10 SCI-FI STORIES / MOVIES — CONNECTED BY ORIGINAL THEMES
════════════════════════════════════════════════════════════════════════

Using the original-language keywords and themes you identified above,
list 10 sci-fi works (films, novels, TV series, or short stories) that \
explore the SAME deep themes — even if the surface subject looks nothing \
like the Bible verses.

For each work (1–10):

[N]. TITLE (year) — medium
     One-sentence logline.
     ▸ Theme bridge: explain in 1–2 sentences exactly which \
original-language concept(s) link this work to the biblical subject.

════════════════════════════════════════════════════════════════════════
"""


def run(subject: str) -> None:
    key = API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ERROR: No API key found.")
        print("  Either paste your key into API_KEY at the top of this file,")
        print("  or run:  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=key)

    prompt = PROMPT_TEMPLATE.format(
        subject=subject,
        subject_upper=subject.upper(),
    )

    print()
    print(DIVIDER)
    print(f"  Searching for: {subject!r}")
    print(DIVIDER)
    print()

    # Stream so the user sees output immediately
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)

    print()
    print()
    print(DIVIDER)
    print("  Done.")
    print(DIVIDER)
    print()


def main() -> None:
    if len(sys.argv) > 1:
        # Subject passed on the command line
        subject = " ".join(sys.argv[1:])
    else:
        try:
            subject = input("Enter a subject: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)

    if not subject:
        print("No subject entered. Exiting.")
        sys.exit(1)

    run(subject)


if __name__ == "__main__":
    main()
