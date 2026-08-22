"""Asking an LLM to write the message shown to a matched pair.

This runs after matching.
The model explains a decision that has already been made. It never affects
who gets matched with who. If it did, the same input would stop giving the
same result.

It only runs when the --explain flag is given and the answers are saved to a
JSON file. This is to prevent a failed API call breaking a live demo.
"""
import json
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env into the environment

api_key = os.getenv("GEMINI_API_KEY")


from pathlib import Path

from .models import User

MODEL = "gemini-3.6-flash"

SYSTEM_PROMPT = """\
You write a short message shown to two people who have just been matched by
an automated matching system.

You will be given both users' profiles, the score they were matched with,
and a breakdown of the separate measurements that made up that score (for
example timetable overlap, shared major, shared interests). The matching
decision has already been made. Your only job is to explain it in plain
language and give the two of them a reason to say hello.

Write one message, addressed to both of them together, that:
- points to one or two specific reasons they were matched
- suggests one simple, low-effort first step they could take

Rules:
- Only use reasons that appear in the measurements you were given. Do not
  invent a shared trait, guess at something not in the data, or mention a
  measurement you were not handed.
- Keep the tone warm and casual, like a friend making an introduction, not
  corporate or robotic.
- If the user's purpose is to seek a romantic partner, write the message in
  a flirty tone
- Two to three sentences. Stay under 300 characters.
- Output only the message itself. No greeting, no signature, no labels like
  "Message:".
"""

def describe(user: User) -> str:
    return (
        f"User {user.id}: {user.major} {user.faculty}, year {user.year}, "
        f"age {user.age}, languages {sorted(user.languages)}, "
        f"interests {sorted(user.interests)}, looking for a {user.mode}"
    )


def build_prompt(
    a: User,
    b: User,
    score: float,
    breakdown: dict[str, float],
) -> str:
    """Turn one match into the message sent to the model.

    Input: the two matched users, their score, and the separate measurements
    from scoring.score_pair.
    Output: one string.

    To implement: state both profiles, the score, and the measurements.
    Pointing out which measurements came back highest gives the model
    something definite to name as the reason, rather than leaving it to
    guess.
    """
    usera = describe(a)
    userb = describe(b)

    ranked = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    measurement_lines = "\n".join(f"  - {name}: {value:.2f}" for name, value in ranked)
    top_name, top_value = ranked[0]

    return (
        f"{usera}\n"
        f"{userb}\n\n"
        f"Match score: {score:.2f}\n"
        f"Measurements:\n{measurement_lines}\n\n"
        f"The highest-scoring measurement is {top_name} ({top_value:.2f}). "
        f"Write the match message now."
    )


def explain(
    a: User,
    b: User,
    score: float,
    breakdown: dict[str, float],
    cache: Path | None = None,
) -> str:
    """Get the message for one matched pair.

    Input: the details of the match, and an optional file of saved answers.
    Output: the text of the message.

    To implement: look in the saved answers first, and return the stored
    message if this pair is already there. Otherwise call the API with
    SYSTEM_PROMPT and the built message, check the reply with verify, save
    it, and return it.

    If the API call fails, return a plain message built from the
    measurements rather than raising an error, so the rest of the run still
    finishes.
    """
    key = "|".join(sorted((a.id, b.id)))

    saved: dict[str, str] = {}
    if cache is not None and cache.exists():
        saved = json.loads(cache.read_text())
        if key in saved:
            return saved[key]

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=build_prompt(a, b, score, breakdown),
            config={"system_instruction": SYSTEM_PROMPT},
        )
        message = (response.text or "").strip()
        if not verify(message, breakdown):
            raise ValueError("model reply failed verification")
    except Exception:
        ranked = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
        top_names = [name for name, value in ranked if value > 0][:2]
        if top_names:
            return f"You two were matched because of {' and '.join(top_names)}. Say hi!"
        return "You two were matched. Say hi and see what you have in common."

    if cache is not None:
        saved[key] = message
        cache.write_text(json.dumps(saved, indent=2))

    return message


def verify(message: str, breakdown: dict[str, float]) -> bool:
    """Check the message the model wrote, before anyone sees it.

    Input: the model's reply, and the measurements it was given.
    Output: True when the message is safe to show.

    To implement: turn down an empty message, one that is longer than the
    limit, or one that gives a reason which is not in the measurements it
    was handed.
    """
    if not message.strip():
        return False

    if len(message) > 300:
        return False

    lowered = message.lower()
    all_reasons = {
        "timetable": ["free time", "schedule", "timetable", "free hour"],
        "proximity": ["live close", "nearby", "distance", "commute"],
        "interests": ["interest", "hobby", "hobbies"],
        "languages": ["language"],
        "major": ["major", "subject", "study the same", "both study"],
        "age": ["age", "years old"],
    }
    for name, keywords in all_reasons.items():
        if name in breakdown:
            continue
        for keyword in keywords:
            if keyword in lowered:
                return False

    return True
