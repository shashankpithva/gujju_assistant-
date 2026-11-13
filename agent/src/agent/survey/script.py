"""The survey script: every question and every fixed line the agent says, in Gujarati.

The agent never makes up what to say next: the flow (flow.py) picks one of these lines, and the LLM
only reads the person's answers (reader.py). So the call can't drift off-script, ask a question
twice in different words, or forget where it was after an answer it didn't expect.

Lines are written for the ear: short sentences, one question at a time, spoken Gujarati rather than
written. They avoid first-person verbs that change with the speaker's gender (સમજી ગયો / સમજી ગઈ),
so the same text fits any voice. tests/test_script.py runs every line through gujarati/style.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The order the survey asks in. frequency and duration are only asked when water comes.
FIELDS: tuple[str, ...] = ("name", "village", "taluka", "district", "water_supply", "frequency", "duration")
PLACE_FIELDS = ("village", "taluka", "district")
WATER_DETAILS = ("frequency", "duration")


@dataclass(frozen=True)
class Question:
    field: str
    ask: str  # the first time
    again: str  # when the answer didn't come through: in other words, so it isn't a stuck recording
    unlisted: str = ""  # a place that isn't in the list of Gujarat's places (places/gazetteer.py)


QUESTIONS: dict[str, Question] = {
    q.field: q
    for q in (
        Question("name", "તમારું નામ શું છે?", "માફ કરજો, નામ બરાબર સંભળાયું નહીં. ફરીથી કહેશો?"),
        Question(
            "village",
            "તમારું ગામ કે શહેર કયું છે?",
            "માફ કરજો, ગામ કે શહેરનું નામ ફરીથી કહેશો?",
            "માફ કરજો, આ નામ મારી યાદીમાં નથી. ગામ કે શહેરનું નામ ફરીથી કહેશો?",
        ),
        Question(
            "taluka",
            "તાલુકો કયો છે?",
            "માફ કરજો, તાલુકાનું નામ ફરીથી કહેશો?",
            "માફ કરજો, આ નામ મારી યાદીમાં નથી. તાલુકાનું નામ ફરીથી કહેશો?",
        ),
        Question(
            "district",
            "અને જિલ્લો કયો છે?",
            "માફ કરજો, જિલ્લાનું નામ ફરીથી કહેશો?",
            "માફ કરજો, આ નામ મારી યાદીમાં નથી. જિલ્લાનું નામ ફરીથી કહેશો?",
        ),
        Question("water_supply", "તમારે ત્યાં પાણી આવે છે?", "માફ કરજો, તમારે ત્યાં પાણી આવે છે, હા કે ના?"),
        Question(
            "frequency",
            "પાણી કેટલા દિવસે આવે છે?",
            "માફ કરજો, પાણી રોજ આવે છે, કે કેટલા દિવસે એક વાર?",
        ),
        Question(
            "duration",
            "દિવસમાં કેટલો સમય પાણી આવે છે?",
            "માફ કરજો, પાણી આવે ત્યારે કેટલા કલાક કે કેટલી મિનિટ ચાલુ રહે છે?",
        ),
    )
}

# A place is read back for a yes before it goes in the sheet. "{}" is its name: the person's own
# words, or the list's name when theirs were another name for it ("Baroda" is read back "વડોદરા").
CONFIRM_PLACE = {
    "village": "તમારું ગામ {}, બરાબર?",
    "city": "તમારું શહેર {}, બરાબર?",
    "taluka": "{} તાલુકો, બરાબર?",
    "district": "{} જિલ્લો, બરાબર?",
}
# Several places said at once are read back at once: "ખાંભા ગામ, ખાંભા તાલુકો અને અમરેલી જિલ્લો, બરાબર?"
PLACE_PHRASES = {"village": "{} ગામ", "city": "{} શહેર", "taluka": "{} તાલુકો", "district": "{} જિલ્લો"}
CONFIRM_SEVERAL = "{}, બરાબર?"
# After their yes, before the next question: the name has just been said twice, so not again.
CONFIRMED = {"village": "સરસ.", "taluka": "ઠીક છે.", "district": "સારું."}

# Said before the first water question, so the change of subject doesn't come out of nowhere.
TO_WATER = "હવે પાણી વિશે પૂછું."

THANKS = "સમય આપવા બદલ ખૂબ ખૂબ આભાર. આવજો!"
RECORDED = "તમારી બધી માહિતી નોંધાઈ ગઈ છે."
NO_WATER = "સમજાયું, તમારે ત્યાં પાણી નથી આવતું."
BUSY = "કોઈ વાંધો નહીં, અમે પછી ફરી ફોન કરીશું. આભાર, આવજો!"
DECLINED = "કોઈ વાંધો નહીં. સમય આપવા બદલ આભાર. આવજો!"
EARLY_GOODBYE = "ઠીક છે. સમય આપવા બદલ આભાર. આવજો!"
WAITING = "હા, કોઈ વાંધો નહીં."  # to "એક મિનિટ": hold on, and ask nothing until they're back
MOVE_ON = "કોઈ વાંધો નહીં, આગળ વધીએ."
ONCE_MORE = "એક વાર ફરી પૂછું."  # before the question, on a second re-ask: never the same line twice
DONT_KNOW = "માફ કરજો, એની મને ખબર નથી. હું ફક્ત સર્વેના થોડા સવાલ પૂછું છું."
CHECK_IN = "હેલો, તમને મારો અવાજ સંભળાય છે?"
SILENCE_GOODBYE = "લાગે છે અવાજ નથી આવતો. અમે પછી ફરી ફોન કરીશું. આવજો!"
TIME_UP = "માફ કરજો, હવે ફોન મૂકવો પડશે. સમય આપવા બદલ આભાર. આવજો!"
DEFAULT_PURPOSE = "દરેક ગામમાં પાણી કેટલું અને ક્યારે આવે છે, એની માહિતી ભેગી કરીએ છીએ."


def with_suffix(name: str, suffix: str) -> str:
    """A postposition joins a Gujarati word, and stands apart from a Latin one: "પંચાયતનો", "Jal Seva નો"."""
    return f"{name} {suffix}" if name[-1:].isascii() else f"{name}{suffix}"


@dataclass(frozen=True)
class Script:
    """The lines that depend on who is calling. Everything else is a constant above."""

    org: str = ""  # who the call is from, as people would know it: "ગ્રામ પંચાયત", "જળ સેવા ટ્રસ્ટ"
    purpose: str = DEFAULT_PURPOSE  # the answer to "why are you asking?"

    @classmethod
    def from_env(cls) -> Script:
        return cls(
            org=" ".join(os.getenv("SURVEY_ORG_NAME", "").split()),
            purpose=" ".join(os.getenv("SURVEY_PURPOSE", "").split()) or DEFAULT_PURPOSE,
        )

    def intro(self) -> str:
        """Who is calling, that it's an AI, and what for. The first question follows separately."""
        who = f"હું {self.org} તરફથી AI આસિસ્ટન્ટ બોલું છું." if self.org else "હું AI આસિસ્ટન્ટ બોલું છું."
        return f"નમસ્તે! {who} પાણીની સુવિધા વિશે બે મિનિટનો નાનો સર્વે છે."

    def who(self) -> str:
        """ "Who is this?": an AI, never a person."""
        if self.org:
            return f"હું {with_suffix(self.org, 'નો')} AI આસિસ્ટન્ટ છું, પાણીના સર્વે માટે ફોન કર્યો છે."
        return "હું AI આસિસ્ટન્ટ છું, પાણીના સર્વે માટે ફોન કર્યો છે."

    def why(self) -> str:
        return self.purpose
