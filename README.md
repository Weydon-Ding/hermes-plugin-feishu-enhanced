# Hermes Feishu Enhanced

[中文说明](README.zh-CN.md)

A **community, direct-install** Hermes plugin that adds native Feishu/Lark clarify cards and once-per-session topic-root context. It subclasses the bundled Feishu adapter; it does not fork the gateway or add model tools.

**Not an official Nous Research plugin, not endorsed by Hermes, and not eligible for the official catalog.** This intentionally uses private adapter/clarify internals (catalog rule 9) and replaces the registered `feishu` factory under the same platform name (rule 15). A successful validator run does **not** imply catalog acceptance. Native plugins execute with the gateway's privileges, not in a sandbox.

## What it does

- Single choice: answer immediately; multi-choice: toggle/deselect, then Submit.
- Other: switch the existing pending clarify entry into text capture. Reply in the **same chat/thread/session**. No synthetic command is queued behind the waiting agent.
- Strict originating chat and message checks; missing identity/context is rejected. Per-user group/thread ownership is enforced, shared threads remain shared, and current official group policy is rechecked at click time.
- Duplicate multi-toggle delivery tokens are ignored; empty submit, invalid indices (including booleans), stale/resolved/replaced entries are rejected. Tokenless multi actions are rejected rather than toggled unsafely.
- Open-ended questions remain text. Native card delivery failure falls back to the official numbered-text implementation.
- Gateway retirement removes buttons with the SDK interactive-message patch API. Disconnect clears plugin-owned state and delegates official disconnect.
- Unrecognized actions, approvals, update prompts, ordinary messages, attachments, streaming and connection behavior remain official. No new tools or model settings are registered. One `pre_llm_call` hook supplies session-scoped topic-root context.

Cards and pending state are process-local; restarting does not restore pending cards. Late callbacks after restart are inert. A retirement network failure may leave visible stale buttons, but they cannot resolve an expired entry.

## Topic-mode reply context

Enabled by default for non-multiplex topic groups: a root quote is supplied once
per **actual agent session ID**, not once per chat. `/new` and genuine session
replacement allow it again. Explicit non-root replies, DMs, ordinary groups and
reply anchors remain intact. Explicitly quoting the root again can be suppressed;
compression/rewind can lose previously supplied detail. This is **not lossless**.

Disable with `hermes config set platforms.feishu.extra.topic_root_context_once false`
before an intentional restart (not performed here). Multiplex profiles retain
full official quotes until a routed-profile durable reference seam is available.
See [implementation and limitations](REPLY_CONTEXT.md), including durable local
storage, capacity fallbacks, hook failure caveats and live acceptance checks.

## Compatibility and migration

Latest topic-policy verification: clean Hermes `bf0203a794a07aac3ff764972ab9087baa4e4f4e`, managed Python 3.14.7, real Lark SDK: **51 tests passed**, official validator exit 0 (`ok: true`). Includes real discovery/hook teardown and the actual `/new` handler with real SessionStore. Original clarify-only baseline: `e06df9c2eae6901f4c88f464e0ae6e753c0428b8` on Windows, Python 3.14.7, using the installed `lark-oapi` SDK and stdlib unittest. This is a **tested commit, not a promise of a supported version range**. Retest after upgrading Hermes. Feishu support must already be available through Hermes' own setup/managed environment; this plugin does not install packages.

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

Use a Hermes-managed Python interpreter with Hermes dependencies and its Feishu SDK already present. No pytest, pip, network credentials or package installation are needed. Use a **clean Hermes checkout**, not one with the earlier core patch. `scripts/verify.py` uses throwaway homes under the scratch directory and executes both tests and the actual CLI validator. It exits nonzero if either fails.

```sh
/path/to/hermes/python scripts/verify.py \
  --hermes-root /path/to/clean/hermes-agent \
  --scratch /path/to/scratch \
  --report-dir /path/to/test-report
```

Windows/Git Bash: use quoted `C:/.../python.exe` and `C:/...` paths. For a clean snapshot without changing the live checkout, create `git archive HEAD --output=C:/.../scratch/hermes.tar` and extract it there. Archive creation must finish before tests run.

Lower-level commands (set `HERMES_HOME` to a disposable scratch home and `PYTHONPATH` to the clean checkout):

```sh
python -m unittest discover -s tests -v
python -m hermes_cli.main plugins validate . --json
```

`tests/test_legacy.py` ports the previous local implementation's regression tests. `tests/test_plugin.py` covers the standalone/security/lifecycle contracts. `tests/test_discovery.py` runs real plugin discovery in a child process, forbids direct socket connections, checks inherited non-clarify behavior, scoped unload and restoration. Only network boundaries/parent-dispatch observation are mocked; callbacks resolve the **real** clarify registry. `scripts/verify.py` does not replace the full upstream regression suite.

Validator result on the tested commit: exit 0, `ok: true`; warning for private core imports (rule 9), in-process platform isolation. Its static “no runtime rebinds” result does not certify same-name registration under rule 15. See [verification notes](VERIFICATION.md).

## Live Feishu acceptance still required

After an intentional restart, confirm the actual rendered card and returned tool result separately:

1. Single choice, repeated click, and an expired card.
2. Multi: choose two, deselect one, Submit; retry delivery does not reverse a toggle.
3. Other then typed text, both single and multi, in the original thread.
4. Another group member cannot answer a per-user question; permitted users can answer shared threads. Disabled/allowlist/blacklist/admin group rules still apply.
5. Plain text fallback and timeout/reset/typed-answer retirement.
6. Ordinary messages, attachments, approvals, update prompts and streaming behave as before.

No live channel rendering/callback acceptance is claimed by offline tests.

## Reuse, scope and license

`clarify.py` adapts the user's existing `FeishuClarifyMixin`: card layout, action rows, multi-selection, real registry resolution, Other and retirement protocol are reused. Necessary changes are standalone imports/registration, callback ownership/passthrough, real session-key validation instead of an `ou_` prefix heuristic, strict message/chat checks, per-card idempotency, fallback and lifecycle races. Existing tests were ported, not discarded. Core originals were left untouched.

MIT, generic contributors attribution because no publishing identity was supplied. No repository has been published. See [LICENSE](LICENSE), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md).
