# Module implementation workflow TODO

Review date: 2026-09-28. Discuss and handle these items one at a time.

- [x] 1. Make the workflow executable: register approved capability records and their modes through the CLI; fix the import scanner CLI's optional module argument (`nargs="?"`).
- [x] 2. Make state changes reflect completed gates: validate approval evidence in the state CLI, and update state after the Owner's decision.
- [x] 3. Add a production code quality criterion to developer and reviewer instructions, using the existing four-score review format.
- [x] 4. In full mode, dispatch the reviewer automatically after the developer gate checks pass; keep the Owner's card and final review decisions.
- [x] 5. Assign all STATE.yaml writes to the dispatcher and remove developer state CLI instructions.

Additional request:

- [x] Document how to resume interrupted developer, reviewer, and Owner gates without adding a new state; provide `retry` for a rejected capability.
- [x] Add a persistent design blocker report and routing for contract or Card defects discovered during development or review.
