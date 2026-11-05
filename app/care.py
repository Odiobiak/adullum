"""Signs that someone may not be safe, shared by Refuge's two places where a
person writes freely: talking with Aquila (app/agent/nodes.py::listen) and
posting to the One another wall (app/one_another.py).

This is a backstop, never the whole judgment. Aquila also asks the model, and
the wall also runs OpenAI's moderation check; a match here simply always counts.
When it matches, the person is shown real helplines (web/refuge.js::HELPLINES)
rather than being met with silence or a refusal.
"""

import re

CRISIS_RE = re.compile(
    r"\b(kill(ing)? myself|end(ing)? (it all|my life)|suicid\w*|hurt(ing)? myself|self[- ]?harm\w*"
    r"|(don'?t|do not) want to (be here|live|wake up)|no reason to live|better off without me"
    r"|want to die)\b",
    re.IGNORECASE,
)


def sounds_unsafe(text: str) -> bool:
    """True when `text` contains a phrase that always counts as a sign of risk."""
    return bool(CRISIS_RE.search(text or ""))
