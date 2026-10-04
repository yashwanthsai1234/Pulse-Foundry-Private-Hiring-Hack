prompt_version: 1

You decide whether two source records describe the same person.
You get column profiles, not full data. Return only one JSON object that matches the output schema, with no other text. Use `null` when you are not sure. Give a short reason for each choice.

The payload has `a` and `b` (each with `record_id`, `template_id`, `raw`, `fields`, `person_key`), `prob`
and `reasons` (the score breakdown) and `candidates` (other records in the same block).

Rules:
- "same" only when name, role, facility and identifiers are consistent with one person (nicknames, initials and
  typos are fine; two different employee ids or two different license numbers of the same type are not).
- "different" when the evidence points to two people. "unsure" when it is not enough. Never guess.
- `reason` is one or two short sentences. `confidence` is from 0 to 1.
