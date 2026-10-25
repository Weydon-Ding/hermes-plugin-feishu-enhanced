# Verification record

## Readable clarify options

- Repository baseline: `8a0618bd47d1bde17c7989a632c75014afbcd835` (fresh clone of main, including the merged owner-identity fix).
- Same clean Hermes commit and existing managed Python/Lark SDK as the owner-identity record below. No dependency installation, installed-plugin changes, profile changes or gateway restart.
- Before implementation: added seven tests in `tests/test_card_layout.py`; the unchanged implementation produced two layout assertion failures and one missing-option-block index error. The remaining 62 tests passed. This reproduces the absence of full choice text outside the buttons, not a live rendering test.
- After implementation: **65 tests, OK**, `scripts/verify.py` exit 0; official validation handler returned `ok: true`. The existing private-core-import / in-process warnings remain. The pre-existing short-card expectation was updated for numbered buttons.
- New coverage traverses the actual send-card serialization and real clarify registry with only the network boundary mocked: full Chinese/emoji/newline/recommendation text, literal Markdown characters, uncapped plain-text blocks before buttons, short labels and original callback indices, selected/deselected refresh, duplicate deliveries, empty submit, original-order multi answers, exact original single answer, Other text capture and wrong-user rejection. Numeric labels also work beyond the alphabet.
- Layout uses Feishu's documented `div` / `plain_text` content component without the optional `lines` cap: https://open.feishu.cn/document/feishu-cards/card-components/content-components/plain-text . The official documentation describes `lines` as a maximum with ellipsis beyond it. No CSS, undocumented wrap flag or Markdown interpretation is needed for choice text.
- No actual Feishu API call, mobile/desktop rendering or live callback acceptance is claimed. A platform card-size limit can still reject an oversized payload; the existing send failure path remains the official numbered-text fallback. Use the acceptance steps in both READMEs after intentional deployment.

## Owner-identity fix — 2026-10-25

- Repository baseline: `406725bc4c4649c64c8dbda7da9238a6a0a4f2b6` (fresh clone/fetch).
- Actual Hermes source HEAD: `bf0203a794a07aac3ff764972ab9087baa4e4f4e`; macOS 27.0.1, existing managed Python 3.14.9 and installed `lark-oapi` 1.6.8 (runtime probe executed). No dependency changes are required for this fix.
- Installed SDK source: `lark_oapi/event/callback/model/p2_card_action_trigger.py`, `CallBackOperator` defines open/user/union IDs, each initialized to `None`. Field support does not guarantee a field is present in an actual event.
- Core evidence: `plugins/platforms/feishu/adapter.py::_resolve_sender_profile` maps primary=`user_id or open_id`, alt=`union_id`; `gateway/session.py::_canonical_participant` prefers alt. No core changes made.
- RED before changing `clarify.py`: the real session-key/SDK callback tests failed eight user/union owner subcases (ordinary group and per-user topic; full and open-only callbacks). The original 42 tests passed. Two additional cache-lifecycle tests errored because the cache implementation did not yet exist; those are not counted as identity reproduction evidence.
- GREEN after the fix: **58 tests, OK**, runner exit 0. Includes all original 42 tests plus 15 owner-identity tests (with parameterized subcases) and one verification-isolation test. New tests exercise the actual inbound normalization/resolver → SessionSource → build_session_key → card send → real SDK callback → real clarify registry path, with network/name lookup and terminal dispatch observation mocked.
- Official validation handler `hermes_cli.plugins_cmd_catalog.cmd_validate(..., as_json=True, install_deps=False)`: exit 0, `ok: true`; private-import warning remains, isolation `in_process`, `host_ready: false`. This is not official catalog admission or a live gateway check.
- The fix uses only adapter-local, typed inbound identity proofs: TTL 3600 seconds, at most 1024 canonical participants, lazy expiry pruning on writes/card creation, no persistence/alias chaining/new API calls. Per-card snapshots are removed with existing retirement state; disconnect clears both maps and prevents in-flight resolver repopulation. Missing proof fails closed. Shared sessions remain shared, exact context and official permission gates remain enforced.
- Additional checks cover wrong users in the same chat/thread, optional/malformed fields, conflicting typed IDs, proof immutability, adapter isolation, bot exclusion, TTL/size bound, disconnect races and resolver-signature incompatibility. Existing expiry/replay/unknown-callback tests remain green.

### Verification isolation and startup caveat

The first RED run, despite temporary HOME/HERMES_HOME and an environment allowlist, exposed that `python -m hermes_cli.main plugins validate` enters fresh-home startup dependency preparation before validation; its output included automatic installation steps. This was an unintended side effect of the original runner, not a manual dependency-install command, and the disposable home was cleaned. Do not interpret that run as proof of a no-install validation boundary.

The runner now calls the official validation handler directly with `install_deps=False`, avoiding CLI startup maintenance, and sets `HERMES_DISABLE_LAZY_INSTALLS=1`. Subsequent GREEN runs produced only test/validation output, without dependency preparation. Both child processes receive a minimal environment allowlist, temporary HOME/USERPROFILE/HERMES_HOME/XDG directories and no inherited provider tokens/profile-selection variables. A regression verifies this boundary using synthetic markers, not real secrets. No credentials were read by task commands; no plugin deployment, profile configuration change or gateway restart was performed.

Use the reproducible runner command below with this macOS runtime or any already provisioned compatible runtime; the Windows example remains a generic path example. Real Feishu transport/UI acceptance is still required: verify the initiating user succeeds and another member is rejected in ordinary per-user groups and per-user topics with open-only callbacks; shared topics and current group policies must retain their original behavior. Do not request extra permissions to fill missing IDs. Without proof, expire/reissue after a fresh inbound message (or use the existing text-answer path where available).

## Prior topic-root baseline (historical)

- Clean Hermes checkout: `bf0203a794a07aac3ff764972ab9087baa4e4f4e`.
- Windows; managed Python 3.14.9 with the actual installed Feishu/Lark SDK (interpreter/import probe executed).
- Stdlib unittest used without modifying the managed environment or core checkout.

## Reproducible command

```sh
"C:/path/to/hermes-runtime/python.exe" \
  scripts/verify.py \
  --hermes-root "C:/path/to/scratch/feishu-clean" \
  --scratch "C:/path/to/scratch" \
  --report-dir "C:/path/to/scratch/feishu-clarify-report"
```

The paths above are generic examples, not paths from the original verification environment. Run from the plugin repository root and substitute your own interpreter, clean checkout and scratch directory. The runner creates temporary homes and strips Feishu/Lark environment variables. It does not install, enable or restart the real gateway.

## Actual results

- `Ran 42 tests ... OK` (exit 0).
- CLI `plugins validate <project> --json`: exit 0; `ok: true`.
- Real PluginManager discovery selected the enhanced adapter, installed no topic hook, preserved official registration metadata/inherited send/connect/approval methods, and restored the bundled deferred factory on scoped unload even after ambient home changed.
- Validation warning: private core imports, catalog rule 9.
- Validation isolation: `in_process`, `host_ready: false` for platform adapters.
- Validator's static “no core override” result means no runtime core rebind was detected. It does not approve the intentional same-name factory replacement under catalog rule 15.

The root-text suppression tracer was observed RED against the old implementation: the fetched full root remained in `reply_to_text`. After the minimal override, it was GREEN. Tests exercise actual official normalization and gateway quote formatting, with only network lookups and the parent dispatch boundary replaced. Checks cover repeated roots, explicit parent/upper precedence, long non-root quotes, DMs, ordinary groups, missing native fields/IDs, failed lookup, media/commands, native thread isolation, same-object dispatch/return passthrough, multiplex and no sidecar writes. A real SessionStore and `/new` handler verify session rotation followed by continued root suppression. Existing clarify/security tests are retained; obsolete marker/SQLite/hook/routed-reference tests and the historical investigation document were removed.

The implementation clears only `reply_to_text` for native group/topic root references, on every turn. There are no reference markers, caches, lifecycle hooks or once-per-session bookkeeping; the manifest declares no hooks. `/new` does not reinsert the root. Reply anchors, user text, non-root quotes and official routing/authorization remain untouched. Existing runtime sidecars are not deleted. This is an intentional context-loss policy, not history-aware deduplication.

The bundled dependency is deferred. Forcing `platform_registry.get('feishu')` inside external `register()` caused a real loader timeout in an experiment and was removed. The successful test uses only normal scoped `ctx.register_platform` forwarding, no global registry mutation. Restored bundled factories may be loaded under Hermes' synthetic plugin module namespace; behavioral identity, not an accidentally duplicated Python class object, is the restoration contract.

## Limits

- Not the full canonical upstream regression suite.
- No real Feishu API calls, card UI rendering, callback transport, credentials or gateway restart tested.
- Initial direct unittest runs exposed an upstream Lark/protobuf Python deprecation warning during SDK import; the verification runner preloads the SDK before async test loops. An asyncio slow-task diagnostic may appear on cold localization imports; it is not a failing test.
- Internal compatibility remains an upgrade risk. Missing internal import paths fail plugin loading rather than modifying the official adapter. Signature checks cover the callback/send seams used here, not all future upstream semantic changes.
- Source-level completion and isolated discovery are not activation. This deliverable is **not installed or enabled**.

Live acceptance steps are in both READMEs. Review them after an intentional restart before relying on the plugin in production.
