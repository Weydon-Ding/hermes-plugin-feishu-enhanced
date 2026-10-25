# Hermes Feishu Enhanced

[中文说明](README.zh-CN.md)

A **community, direct-install** Hermes plugin that adds native Feishu/Lark clarify cards and suppresses topic-root quote text. It subclasses the bundled Feishu adapter; it does not fork the gateway or add model tools.

**Not an official Nous Research plugin, not endorsed by Hermes, and not eligible for the official catalog.** This intentionally uses private adapter/clarify internals (catalog rule 9) and replaces the registered `feishu` factory under the same platform name (rule 15). A successful validator run does **not** imply catalog acceptance. Native plugins execute with the gateway's privileges, not in a sandbox.

## What it does

- Single choice: answer immediately; multi-choice: toggle/deselect, then Submit.
- Other: switch the existing pending clarify entry into text capture. Reply in the **same chat/thread/session**. No synthetic command is queued behind the waiting agent.
- Strict originating chat and message checks; missing identity/context is rejected. Per-user group/thread ownership is enforced, shared threads remain shared, and current official group policy is rechecked at click time.
- Duplicate multi-toggle delivery tokens are ignored; empty submit, invalid indices (including booleans), stale/resolved/replaced entries are rejected. Tokenless multi actions are rejected rather than toggled unsafely.
- Open-ended questions remain text. Native card delivery failure falls back to the official numbered-text implementation.
- Gateway retirement removes buttons with the SDK interactive-message patch API. Disconnect clears plugin-owned state and delegates official disconnect.
- Unrecognized actions, approvals, update prompts, attachments, streaming and connection behavior remain official. No tools, lifecycle hooks or model settings are registered. Only native topic-root reply text is suppressed.

Cards and pending state are process-local; restarting does not restore pending cards. Late callbacks after restart are inert. A retirement network failure may leave visible stale buttons, but they cannot resolve an expired entry.

### Readable option text

Each choice is shown in full in its own numbered, wrapping `div` / `plain_text` block before the action rows. No `lines` limit is set. Recommendation suffixes, explicit newlines, Unicode and Markdown characters remain literal original text; choices are not summarized or truncated by the plugin. The short buttons read `选项 1`, `选项 2`, etc. (option 1, option 2). Multi-selection adds a checkmark and primary style to selected buttons without changing their numbering.

Button values still carry the original zero-based index. A click returns the original choice string, not the short button label; multi-submit preserves original choice order. Other, text fallback, identity gates and retirement are unchanged. This avoids relying on long button labels on narrow screens; it is not an increase in Feishu's overall card-size limits. Actual mobile rendering still needs the live acceptance below.

### Card owner identity

Ownership accepts the callback's nonempty `open_id`, `user_id` or `union_id`, not just `open_id`: Hermes session keys prefer union, then tenant user ID, then open ID. SDK fields are optional; do not assume callbacks include union. To bridge an open-only callback, the adapter remembers typed IDs already received together by the official inbound sender resolver (no new API calls or permissions). This account/adapter-local memory is keyed by canonical participant, capped at 1024 entries, and expires after one hour; expiry is pruned on writes and card creation. Disconnect clears it, including in-flight resolver protection. No persistence or cross-adapter sharing.

A card snapshots only its owner's proof when sent; later traffic cannot change it. Normal answer/expiry/retirement/disconnect removes that snapshot. Known conflicting ID fields are rejected. If no trusted proof exists and the callback lacks the canonical ID, the click is rejected, not treated as shared; use the existing text-answer path where available, or expire/reissue after a fresh user message. `open_id` remains required for the official interaction gates. Shared sessions still have no individual owner; current group policy and exact chat/message/thread binding still apply.

## Topic-mode reply context

For a group event with a native topic `thread_id`, when the resolved
`reply_to_message_id` equals the raw native `root_id`, clear only
`reply_to_text` before the gateway builds its quote prefix. This applies on
every turn, including explicit replies to the root, commands and media messages.
Non-root replies retain their complete quotes. DMs, ordinary groups and events
without a root or reply ID are unchanged. Reply anchors and topic session keys
remain official.

The same stateless rule applies in multiplex mode; there is no special routing,
reference marker, sidecar, SQLite ledger, lifecycle hook or context reinjection.
`/new` clears context normally and the next root reference is still suppressed.
This intentionally gives up automatic root context, including on the first
turn; paste required details into the new message after a reset. The old
`topic_root_context_once` setting is no longer used. Existing runtime sidecars
are not migrated or deleted. Drain old queued reference-bearing turns before
switching builds. See [verification notes](VERIFICATION.md).

## Compatibility and migration

Verified against clean Hermes `bf0203a794a07aac3ff764972ab9087baa4e4f4e`, managed Python 3.14.9 and the real Lark SDK: **65 tests passed**, official validator exit 0 (`ok: true`). Includes full option text in serialized cards, original-answer mapping, multi refresh/submit, actual adapter normalization/gateway formatting, discovery/unload with no topic hook, the real `/new` handler with SessionStore, real session-key/SDK identity regressions, and verification environment isolation. This is a tested commit, not a supported version range. Retest after upgrading Hermes; this plugin does not install packages.

The plugin calls the official `register()` through a forwarding context, changing only `adapter_factory`. Every official registration field (authorization env names, setup, validation, dependency probes/installers, YAML bridge, standalone sender, delivery settings) is preserved. Registration is owned by the actual `PluginContext` scope/ledger. No private registry-table writes or global monkeypatching.

Bundled Feishu registration is deferred; external enabled plugins load eagerly. Real discovery tests prove enhanced factory selection and that unloading restores/materializes the bundled factory. Do not call `platform_registry.get('feishu')` inside `register()` to force the deferred loader: the current loader's worker/coordinator locks can deadlock.

If the parent already overrides `send_clarify`, registration deliberately does nothing:

- `plugins.platforms.feishu.clarify` is reported as the **prior local core patch**, not upstream native support.
- Other native/unknown overrides are preserved, not stacked upon.
- Missing required internal methods cause an inactive-plugin warning; missing import paths cause a normal plugin load error, leaving the official registration unchanged.

**Existing local patch users:** back up and review `plugins/platforms/feishu/adapter.py`, `clarify.py`, and the old tests first. This project does not remove them. Migrate only your known patch changes manually after verifying the standalone project against a clean checkout. With the prior core mixin still present, this plugin is intentionally inactive. Old cards use a different namespace and are not migrated; finish or expire them before changing builds.

## Install later (not performed by this project)

Review the source first. Select the intended Hermes profile; resolve its actual `HERMES_HOME`. Keep bundled Feishu enabled. Do not run a second Feishu gateway for the same bot just to test this plugin.

For a local directory install, copy this project's files into `<active HERMES_HOME>/plugins/feishu-enhanced/`, then:

```sh
hermes plugins enable feishu-enhanced
hermes plugins list
```

After **you publish the repository**, replace `YOUR_ACCOUNT` with its real owner:

```sh
hermes plugins install YOUR_ACCOUNT/hermes-plugin-feishu-enhanced --no-enable
hermes plugins enable feishu-enhanced
```

These are installation instructions, **not a claim that anything was installed/enabled/restarted**. Arrange a gateway restart at a safe time yourself. Source changes do not activate an already running adapter. To roll back, disable `feishu-enhanced` using `hermes plugins disable feishu-enhanced` and restart at a safe time; do not disable bundled Feishu. Existing adapter instances are not hot-swapped by registry unload.

## Offline verification

Use a Hermes-managed Python interpreter with Hermes dependencies and its Feishu SDK already present. No pytest, pip, network credentials or package installation are needed. Use a **clean Hermes checkout**, not one with the earlier core patch. `scripts/verify.py` uses throwaway HOME/HERMES_HOME/XDG directories and an environment allowlist, not merely removal of Feishu/Lark tokens. It executes tests and the official CLI validation handler directly with `install_deps=False`, bypassing CLI startup maintenance for a fresh home. It exits nonzero if either fails.

```sh
/path/to/hermes/python scripts/verify.py \
  --hermes-root /path/to/clean/hermes-agent \
  --scratch /path/to/scratch \
  --report-dir /path/to/test-report
```

Windows/Git Bash: use quoted `C:/.../python.exe` and `C:/...` paths. For a clean snapshot without changing the live checkout, create `git archive HEAD --output=C:/.../scratch/hermes.tar` and extract it there. Archive creation must finish before tests run.

Prefer the runner over a bare `python -m hermes_cli.main plugins validate`: the latter can perform startup dependency preparation even for validation. The runner invokes the same official `hermes_cli.plugins_cmd_catalog.cmd_validate` handler without that startup path.

`tests/test_legacy.py` ports the previous local implementation's regression tests. `tests/test_plugin.py` covers the standalone/security/lifecycle contracts. `tests/test_discovery.py` runs real plugin discovery in a child process, forbids direct socket connections, checks inherited non-clarify behavior, scoped unload and restoration. Only network boundaries/parent-dispatch observation are mocked; callbacks resolve the **real** clarify registry. `scripts/verify.py` does not replace the full upstream regression suite.

Validator result on the tested commit: exit 0, `ok: true`; warning for private core imports (rule 9), in-process platform isolation. Its static “no runtime rebinds” result does not certify same-name registration under rule 15. See [verification notes](VERIFICATION.md).

## Live Feishu acceptance still required

After an intentional restart, confirm the actual rendered card and returned tool result separately:

1. Single choice, repeated click, and an expired card.
2. Multi: choose two, deselect one, Submit; retry delivery does not reverse a toggle.
3. Other then typed text, both single and multi, in the original thread.
4. Another group member cannot answer a per-user question; permitted users can answer shared threads. Disabled/allowlist/blacklist/admin group rules still apply.
   Test both ordinary groups and per-user topics where the inbound owner is a tenant/union ID but the callback contains only open ID (do not add permissions just to fill missing fields). Verify the initiating member succeeds and another member in the same chat/topic is denied. Without a usable identity proof, verify safe rejection and fresh-message/reissue recovery.
5. Plain text fallback and timeout/reset/typed-answer retirement.
6. Ordinary messages, attachments, approvals, update prompts and streaming behave as before.
7. Topic-root prefixes stay absent on first/repeated turns and after `/new`; explicit non-root replies keep their full quote. Check another topic, DMs, ordinary groups and multiplex operation.
8. On a phone, send short, medium and long Chinese choices (including a recommendation suffix, emoji and explicit newlines). All numbered descriptions must be readable in the body, including the final sentinel of the long choice. Buttons must stay short. Select the long choice and compare the tool result with its complete original text; repeat with multi-toggle/deselect/submit and Other. Test desktop too. This branch has not been deployed or tested against the live card API.

No live channel rendering/callback acceptance is claimed by offline tests.

## Reuse, scope and license

`clarify.py` adapts the user's existing `FeishuClarifyMixin`: card layout, action rows, multi-selection, real registry resolution, Other and retirement protocol are reused. Necessary changes are standalone imports/registration, callback ownership/passthrough, real session-key validation instead of an `ou_` prefix heuristic, strict message/chat checks, per-card idempotency, fallback and lifecycle races. Existing tests were ported, not discarded. Core originals were left untouched.

MIT, generic contributors attribution because no publishing identity was supplied. No repository has been published. See [LICENSE](LICENSE), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md).
