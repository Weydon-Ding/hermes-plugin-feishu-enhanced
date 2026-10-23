# Verification record

## Tested baseline

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
