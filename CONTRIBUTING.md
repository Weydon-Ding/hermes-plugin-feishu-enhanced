# Contributing

Use a clean Hermes checkout and its managed Python runtime with Feishu support already installed. Do not pip/uv-mutate a managed Hermes environment. No extra project dependencies are required.

Run `python scripts/verify.py --hermes-root <clean-hermes> --scratch <scratch> --report-dir <report>` with that interpreter. See README for details and limitations. Tests use stdlib unittest, real plugin discovery and the real clarify registry; mock only network boundaries or parent dispatch observation. Keep test homes out of real profiles.

Architecture: `__init__.py` owns compatibility checks and metadata-forwarding scoped registration. `clarify.py` adapts the original local mixin. All non-clarify operations must remain inherited/delegated. The manifest intentionally declares no new tools/hooks. Avoid moving SDK dependencies into this repository.

Use test-first red/green changes for behavior and bugs. Ported existing tests are regression coverage; do not claim they were newly written using TDD. Include the tested Hermes commit/runtime, commands and output in PRs. One concern per PR; use Conventional Commits (`fix:`, `test:`, `docs:`) and sign commits with `git commit -s` (Developer Certificate of Origin, https://developercertificate.org/).

Report bugs with sanitized reproduction, expected/actual results and Hermes/plugin versions. Do not publish credentials, chat content, private identifiers or raw production logs. See SECURITY.md for sensitive reports. There is no automated release/publishing workflow; maintainers publish intentionally after tests and live acceptance.
