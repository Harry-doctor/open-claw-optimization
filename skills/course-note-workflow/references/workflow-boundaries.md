# Workflow Boundaries

## Stable role split

- `structure` → `gemini-3.1-flash-lite-preview`
- `audit` → `gemini-3.1-flash-lite-preview`
- `rewrite` → `gpt-5.4`
- `patch` → `gpt-5.4`
- Main session → orchestration, progress reporting, Feishu writing, naming / routing / folder recognition, and minimal final presentation cleanup

## Delivery shape

- Follow the courseware / slide logic first.
- Keep valuable teacher emphasis, exam hints, and clarifications.
- Remove filler speech, repetition, and weak conversational phrasing.
- Embed `【重点】` / `【高频考点】` / `【易错警示】` next to the relevant knowledge point.
- Do not move all highlights into a single summary block.
- When the user asks for final Feishu landing cleanup, tighten formatting and presentation without silently re-authoring the whole note.

## Rerun rule

- If a later stage fails, rerun only from the broken stage forward.
- Do not restart the full chain unless the user explicitly asks.

## Reference doc rule

- Use the long-term Feishu sample doc as a target shape reference.
- Learn structure, pacing, labeling, and delivery form from it.
- Do not copy its literal content into unrelated courses.

## Audit posture

- Judge whether the note is deliverable.
- Do not keep inventing new rejection reasons once the note is already usable.
- Put non-blocking polish suggestions into optimization items rather than hard rejection.