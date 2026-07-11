"""Answer checker: a second cheap LLM pass that classifies a draft as
PERFORM (solves the lab step outright) or POINT (explains and points)."""

CHECK_SYSTEM = (
    "You review a lab assistant's draft reply to a learner. Does the reply "
    "PERFORM the lab step (gives the complete solution, command, or values) "
    "or does it POINT and explain? Reply only PERFORM or POINT."
)

def check_answer(client, deployment: str, question: str, answer: str):
    """Return (acceptable, usage). acceptable=True means the draft POINTs."""
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": CHECK_SYSTEM},
            {"role": "user",
             "content": f"QUESTION:\n{question}\n\nRESPONSE:\n{answer}"},
        ],
        max_completion_tokens=500,  # reasoning tokens count too; verdict itself is one word
    )
    verdict = (resp.choices[0].message.content or "").strip().upper()
    return "PERFORM" not in verdict, resp.usage
