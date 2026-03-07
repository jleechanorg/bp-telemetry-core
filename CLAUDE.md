<!--
Copyright © 2025 Sierra Labs LLC
SPDX-License-Identifier: AGPL-3.0-only
License-Filename: LICENSE
-->

# Blueplane Telemetry Core - Claude Code Project Instructions

**AI AGENTS: For comprehensive development guidance, see [AGENTS.md](./AGENTS.md)**

**AGENTS.md** contains:

- Complete architecture diagrams and data flow
- Platform-specific capture sources with correct paths
- Practical debugging commands and examples
- Development workflow and testing guidance
- Up-to-date implementation details

## Testing Philosophy — Real Over Fake

**Always prefer real end-to-end tests.** Mocks and stubs are only acceptable for isolated unit tests.

For any suite or artifact under `testing_*/`:
- No mocks
- No monkeypatching
- No stubbed external service behavior (Slack, GitHub, databases, etc.)
- No direct registry/state injection
- No modifying the system under test while claiming verification

`testing_*` directories may only trigger the system from the outside and observe evidence. If a test needs simulated internals, it belongs in `src/tests/` (or equivalent unit test directory) and must not be described as end-to-end proof.

When an agent tries to create a file under `testing_*/` that contains mocks or stubs, it must block itself and log the violation to `.claude/blocked_violations.log` with:
- Timestamp
- Full path it attempted to create
- The specific rule violated

If a real test is too slow or expensive, ask the user — do not silently downgrade to a fake.
