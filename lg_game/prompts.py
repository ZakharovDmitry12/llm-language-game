"""Versioned experimental instructions; prompts are deliberately not augmented."""

OFFERS = tuple(range(10, 100, 10))
BASE = ("You and another player have 100 points to divide in a single round. "
        "Choose how many points to offer the other player: 10, 20, 30, 40, 50, 60, 70, 80, or 90. "
        "If the other player accepts, they receive the amount you offer and you receive the rest. "
        "If they reject, both players receive zero. Your payoff is the number of points you receive.")
CHANCE = "The other player’s instructions are equally likely to be in English or Russian."
REVEAL = "In this round, the other player's instructions are in {language}."
RESP_EN = ("You and another player have 100 points to divide in a single round. "
           "The other player offers you {x} points. If you accept, you receive {x} points and the other player receives the rest. "
           "If you reject, both players receive zero. Your payoff is the number of points you receive. "
           "Reply with exactly one digit and no other text: 1 to accept or 0 to reject.")
RESP_RU = ("Вы и другой игрок делите 100 очков за один раунд. Другой игрок предлагает вам {x} очков. "
           "Если вы примете предложение, вы получите {x} очков, а другой игрок получит остаток. "
           "Если вы отклоните предложение, оба получите ноль. Ваш выигрыш равен числу очков, которые вы получите. "
           "Ответьте ровно одной цифрой без другого текста: 1, чтобы принять предложение, или 0, чтобы его отклонить.")
# The project only specifies this stage by reference; this version must be frozen and reviewed.
FORECAST_BASE = ("You and another player have 100 points to divide in a single round. "
                 "The possible offers to the other player are 10, 20, 30, 40, 50, 60, 70, 80, or 90 points. "
                 "If the other player accepts, they receive the amount offered and you receive the rest. "
                 "If they reject, both players receive zero. Your payoff is the number of points you receive.")
FORECAST = ("For each possible offer, estimate the probability that the other player would accept it. "
            "Return nine numbers between 0 and 1, in order of offers from 10 to 90 points, "
            "on one comma-separated line with no other text.")
IV_PROPOSE = ("Choose the offer and the language of its message, English or Russian. Using {D} costs you {c} points. "
              "The other language costs zero. The cost is deducted whether the other player accepts or rejects. "
              "The other player sees the offer in the language you choose. "
              "Reply with a single line in the format <amount>, <language>. Use only the number, a comma, and the language name.")
IV_RESP = ("This is a single round. If you accept, you receive the offered amount and the other player receives the rest of the 100 points before any message cost. "
           "If you reject, each receives zero before any message cost. Only the other player can be charged for the message. "
           "Reply with exactly one digit and no other text: 1 to accept or 0 to reject.")

def proposer(stage, language=None, reveal=None, D=None, c=None):
    if stage == "II":
        parts = [BASE, CHANCE]
        if reveal:
            parts.append(REVEAL.format(language=language))
        parts.append("Reply with the number of points you offer.")
        return "\n\n".join(parts)
    if stage == "III":
        return "\n\n".join([FORECAST_BASE, CHANCE, REVEAL.format(language=language), FORECAST])
    if stage == "IV":
        return "\n\n".join([BASE, IV_PROPOSE.format(D=D, c=c)])
    raise ValueError(stage)

def responder(stage, language, x):
    if stage in ("I", "II"):
        return (RESP_EN if language == "English" else RESP_RU).format(x=x)
    if stage == "IV":
        message = f"I offer you {x} of the 100 points" if language == "English" else f"Предлагаю вам {x} из 100 очков"
        return IV_RESP + "\n\n" + message
    raise ValueError(stage)
