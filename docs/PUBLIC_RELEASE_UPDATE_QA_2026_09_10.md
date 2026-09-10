# Public release update and rollback QA — 2026-09-10

Status: **PORTABLE UPDATE PATH PASS / NATIVE INSTALL LIFECYCLE PENDING**

## Scope

This check exercises the early-release new-folder update model without modifying or
deleting an existing application folder. It verifies that an older package, the current
package and the older package again can use the same explicitly isolated per-user data
root without changing retained state during a read-only startup.

## Packages

- Previous package source: `423707f6bce01b8a4616b2307f6b2ea6515cce83`.
- Current package source: `7e0181b` (`GUI v1.75`).
- Both packages identify themselves as `0.1.0-rc.1` and retain their own complete
  application folders.

## Isolated state

- Root: `data/local/public_update_qa_2026_09_10/user_state`.
- One preferences sentinel and one generated-report sentinel were created expressly
  for this QA run.
- Composite SHA-256 before launch:
  `d6830369dbb6dc7596d894402ab08de2caadd23e61e609d885af9e426a78a9e9`.

## Sequence and result

| Step | Package | Command mode | Exit | State SHA-256 |
|---|---|---|---:|---|
| Baseline | — | — | — | `d6830369...a9e9` |
| Previous version | `423707f` | hidden `--list` | 1 | `d6830369...a9e9` |
| Updated version | `7e0181b` | hidden `--list` | 1 | `d6830369...a9e9` |
| Rollback | `423707f` | hidden `--list` | 1 | `d6830369...a9e9` |

Exit 1 is the expected empty-catalog result. No application error occurred. The exact
state hash remained unchanged after every package, so settings and generated data were
retained across update and rollback. Neither application folder was overwritten or
removed.

## Limits

This check did not simulate visual first-run setup, Explorer extraction, a clean Windows
account or deletion of an application folder. Those native install/uninstall checks
remain in R4. No real History, telemetry, report or user preference was changed.
