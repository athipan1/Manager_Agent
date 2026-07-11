# Paper protection retry policy

The Paper protection workflow runs after a successful Hourly Auto Trading workflow and also retries every hour on weekdays.

Before any order mutation, the workflow performs a read-only preflight against the broker clock and current protection diagnostics.

- If the market is closed and every position needing attention is explained by an existing `pending_cancel` protective order, the workflow records a deferred status and skips mutation.
- If the market is open, reconciliation continues through the existing Paper-only exact-ticket safety gate.
- If any unprotected position is not explained by a pending cancellation, the workflow does not defer and continues through the fail-closed path.

Scheduled retries exist because re-running a completed Hourly Actions attempt does not reliably emit a new `workflow_run` event for downstream workflows.
