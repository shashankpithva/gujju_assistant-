"""Gujarati as people speak it on the phone: numbers, times, and text written for the ear.

Everything here is deterministic. The parts of a call that must be exact (a number of days, a number
of hours, how a number is read aloud) are never left to the LLM or the voice model.

Python's \\b and \\w treat Gujarati vowel signs and the virama as non-word characters, so \\bહા\\b
doesn't match "હા" and \\bના\\b matches inside "નાસ્તો". Code here splits text into words (see
understanding.words) instead of using those.
"""
