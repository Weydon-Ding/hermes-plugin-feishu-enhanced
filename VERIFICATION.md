# Verification record

## Tested baseline

- Hermes clean `git archive HEAD`: `e06df9c2eae6901f4c88f464e0ae6e753c0428b8`.
- Windows; managed Python 3.14.7 with the actual installed Feishu/Lark SDK.
- No pytest present; stdlib unittest used without modifying the managed environment.
- Existing live checkout has an earlier local core mixin. It was **not** used as the test parent and was not reverted.

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

- `Ran 29 tests ... OK` (exit 0).
- CLI `plugins validate <project> --json`: exit 0; `ok: true`.
- Real PluginManager discovery selected the enhanced adapter, preserved official registration metadata/inherited send/connect/approval methods, and restored the bundled deferred factory on scoped unload even after ambient home changed.
- Validation warning: private core imports, catalog rule 9.
- Validation isolation: `in_process`, `host_ready: false` for platform adapters.
- Validator's static “no core override” result means no runtime core rebind was detected. It does not approve the intentional same-name factory replacement under catalog rule 15.

New feature/security tracer tests were observed failing before fixes (native card, direct registry resolution, multi-toggle/submit, Other, fallback, retirement, disconnect, real session layout, late send retirement, reused id and incompatible signature). The old regression tests were ported from the previous implementation; they are not claimed as newly test-first authored.

The bundled dependency is deferred. Forcing `platform_registry.get('feishu')` inside external `register()` caused a real loader timeout in an experiment and was removed. The successful test uses only normal scoped `ctx.register_platform` forwarding, no global registry mutation. Restored bundled factories may be loaded under Hermes' synthetic plugin module namespace; behavioral identity, not an accidentally duplicated Python class object, is the restoration contract.

## Limits

- Not the full canonical upstream regression suite.
- No real Feishu API calls, card UI rendering, callback transport, credentials or gateway restart tested.
- Initial direct unittest runs exposed an upstream Lark/protobuf Python deprecation warning during SDK import; the verification runner preloads the SDK before async test loops. An asyncio slow-task diagnostic may appear on cold localization imports; it is not a failing test.
- Internal compatibility remains an upgrade risk. Missing internal import paths fail plugin loading rather than modifying the official adapter. Signature checks cover the callback/send seams used here, not all future upstream semantic changes.
- Source-level completion and isolated discovery are not activation. This deliverable is **not installed or enabled**.

Live acceptance steps are in both READMEs. Review them after an intentional restart before relying on the plugin in production.
