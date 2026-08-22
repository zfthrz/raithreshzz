# Race Engineer desktop GUI v1.4

GUI v1.4 surfaces the existing deterministic H5.4 P11 driver-focus projection
without changing the validated three-zone next-stint plan.

## Next-stint view

When `session_coaching_facts.next_stint_focus` is consistent and `ACTIVE`, the
**Próxima tanda** tab renders:

1. **FOCO DEL PILOTO** — at most the two P11-selected items, in their existing P10
   presentation order;
2. **PLAN COMPLETO VALIDADO** — the original three-zone `next_stint_plan`.

The GUI does not rank, filter or reconstruct the focus. It checks that `focus_count`
matches one or two unique focus items and that every focus `plan_label` exists in the
complete plan. If any check fails, or the artifact predates P11, the tab falls back
to the original complete-plan rendering.

## GPS-map layer

Validated next-stint intervals remain clickable. P11 focus intervals are rendered
in bright blue and with a heavier line; complete-plan items outside the focus use a
muted thinner blue. Clicking reports **Foco** or **Plan** explicitly. H5.2 loss/gain
layers and the selected white state remain unchanged.

## Authority

P11 is presentation-only. GUI v1.4 never changes `next_stint_plan`, P9/P10/P11
ordering, driver cues, zone eligibility, LLM output, H5.2 authority or historical
action gates. Only an already validated debrief is eligible for the map layer.

## Real checkpoint

The 12 most recent local debrief artifacts were inspected read-only. Five recent
artifacts had `next_stint_focus = ACTIVE / 2`; older artifacts had no P11 block and
remain compatible. The latest Imola artifact rendered focus A/C while retaining the
complete A/C/B plan.

Validation:

- focused P11/GUI tests: `103 passed`;
- full pytest: `987 passed`;
- real read-only session-catalogue smoke test: PASS;
- `git diff --check`: PASS.

