# Feishu topic reply context: accepted bounded policy

## Implemented policy (supersedes the investigation outcome below)

`topic_context.py` adds a narrow adapter dispatch mixin plus the documented
`pre_llm_call` lifecycle hook. For a native non-DM topic whose selected reply ID
equals its native root ID, normalization replaces only `reply_to_text` with a
short durable content-addressed reference. `reply_to_message_id`, thread routing,
source identity, user text, authorization and non-root quote text are untouched.
The full root is stored before dispatch; nothing is marked seen at that stage.

The hook resolves the reference after actual agent session selection, using
`session_id` supplied by `agent.turn_context._collect_pre_llm_call_context`.
Its context return becomes a current-user sidecar via core's normal injection,
not a changing system prompt or a rewrite of old messages. A SQLite unique key
on actual session ID plus chat/thread/root records first injection. `/new` and
other real session replacement reallow the root without guessing reset from a
chat ID or parsing slash-command text. Ordinary restart of the same session
retains the ledger. Different users' real sessions are independent; shared
sessions share a root record. References are also sender-bound.

Defaults and bounded fallbacks:

- `platforms.feishu.extra.topic_root_context_once: true`; set false to restore
  official quotes. No live configuration was changed.
- Multiplex mode retains official quotes: ingress transport profile and final
  routed profile may differ, and native admission rejects arbitrary plugin
  metadata. No fake chat-based session identity is substituted.
- Inactive/unloaded hooks, failed storage writes, missing native root/thread,
  DMs, commands, media-bearing messages and explicit non-root replies retain official text.
- Roots exceeding core's configured `hooks.output_spill` budget retain official
  full quotes (normally about 10,000 characters). This deliberately forgoes
  suppression rather than turning the first quote into a head/tail preview.
- Profile-local files live in `<HERMES_HOME>/cache/feishu-enhanced-topic/`.
  Root JSON files are capped at 4096 / 64 MiB at insertion, seen rows at 65536;
  capacity means repeat/full-quote fallback, not eviction of queued references.
  There is no unbounded process-memory cache. Files contain message content;
  protect them like transcripts. They persist until operator cleanup. Do not
  remove them while referenced durable turns are queued.

### Explicit limitations: not lossless

- Explicitly quoting the same root later is also suppressed, as accepted.
- Compression or rewind may remove detail; this policy does not inspect whether
  old content is still in the model context. If core assigns a new physical
  session ID during compression it may inject again. This is not a guarantee of
  lossless recall or exactly one quote across a logical compression lineage.
- Seen means **the hook supplied the sidecar**, not successful provider delivery.
  A crash/failure after the hook returns but before core accepts/persists it can
  leave a seen record without a delivered root. A public transactional commit
  seam does not exist here. Clearing that profile-local ledger reallows roots.
- Disabling/unloading between reference admission and execution, hook timeout,
  configuration changes to spill limits while queued, unavailable reference
  files, or a core hook contract change can prevent first injection. A missing
  file produces a visible unavailable-context sidecar. Stable loaded plugin
  and storage are prerequisites; live activation has not been performed.
- Short reference pointers still recur in user history. Fetches still use the
  official message cache; this change targets quote duplication, not all lookups.

### Verification of the implementation

Tests were written and observed failing for repeated-root behavior, inactive
hook fallback, storage capacity and oversized-hook spill before fixes. Existing
nine source-characterization tests remain intact; their final dispatch mock
intentionally bypasses the new dispatch mixin. New policy tests exercise that
mixin separately, the real core context collector, native JSON compatibility,
profile/sender boundaries, non-root/DM/group preservation, capacity fallback,
new topics and the **real `/new` handler with a real SessionStore**.

Full plugin suite: **51 tests passed**; official CLI validator exit 0, `ok: true`.
Existing private-core-import warnings remain; no catalog approval is implied.

Full plugin suite and official CLI validator are run by `scripts/verify.py`
against clean core `bf0203a794a07aac3ff764972ab9087baa4e4f4e`, using existing
managed Python 3.14.7 and real Lark SDK. Latest reports:
`C:/path/to/scratch/feishu-topic-policy-report/`.
No core edit, package installation, live-profile install, gateway restart,
commit or push. Validator success is not catalog eligibility. Still required:
after a separately authorized restart, test first/repeated root, explicit
non-root, another topic, `/new` then root again, private/ordinary groups, and
all three clarify card flows on actual Feishu.

---

# Preserved original investigation (historical; outcome superseded above)

## Outcome

Repeated reply context is reproducible in the current official adapter and is
not introduced by this plugin. No production suppression was implemented:
thread membership alone does not prove that a quoted message is present in the
current model context. Removing all topic quotes would lose useful context and
explicit reference disambiguation. Existing clarify behavior is unchanged.

## Exact source path (inspected Hermes commit)

Baseline: `bf0203a794a07aac3ff764972ab9087baa4e4f4e`. The live checkout was
clean at inspection; no core files were edited.

1. `plugins/platforms/feishu/adapter.py:2615`,
   `FeishuAdapter._process_inbound_message`:
   - line 2635 takes native `message.thread_id` as session thread identity.
   - lines 2636-2639 independently select `parent_id`, then
     `upper_message_id`, then `root_id` as the reply target.
   - line 2640 calls `_fetch_message_text` for that target even in a topic.
   - lines 2665-2673 set both `reply_to_message_id` and `reply_to_text`
     on `MessageEvent` and dispatch through the official inbound pipeline.
2. `FeishuAdapter._fetch_message_text`, same file:3327-3356, uses a
   message-ID LRU cache. A cache hit avoids another Feishu lookup, but still
   returns the entire text for prompt injection. This is a network cache,
   not prompt deduplication.
3. `gateway/run_inbound.py:1555`,
   `GatewayInboundMixin._prepend_inbound_reply_context`, inserts
   `[Replying to: "<reply_to_text>"]` before the incoming message.
   Its explicit policy is to retain full quotes, even when already in history,
   because a reply pointer disambiguates which prior message is referenced.
   There is no preview length limit in this formatter.
4. `gateway/session.py:686`, `build_session_key`, includes the thread ID
   in the session key. Session isolation and reply-context injection are
   separate decisions; isolation does not switch off quotes.
5. This project's `__init__.py`, `ClarifyFeishuAdapter`, inherits these
   methods without overriding them. `clarify.py` handles cards, not this
   reply-prefix construction.

When Feishu supplies the same root/parent on subsequent topic messages, each
message receives another full prefix. A later turn may therefore include
multiple copies in its accumulated history. Cache hits do not prevent this.
No tokenizer measurements or production traffic captures were made; there is
no claimed numerical token saving.

## Why a blanket or adapter-local dedup is unsafe

- `parent_id` / `upper_message_id` may identify a deliberate quoted reply;
  equality with the root does not establish whether that choice was explicit.
- A topic may first reach Hermes midway through a discussion. The root can be
  new context even though the native thread ID is already present.
- `/new`, reset, restart, per-user thread routing, rewind and compression mean
  "seen by this adapter" is not "present in this model's current history".
- `_message_text_cache` contains fetched messages, not session-scoped evidence
  that a message was delivered to an agent.
- Clearing `reply_to_message_id` is especially wrong: it also participates in
  delivery routing/anchors. Session IDs, reply IDs and text are distinct.
- Reading the whole persisted transcript before adapter dispatch is not enough:
  final profile/session admission can differ, reset can occur afterwards, and
  the active agent's compacted context is not necessarily that transcript.

The documented general plugin middleware can rewrite LLM requests, but applying
an ad-hoc quote regex there would change prompt replay/cache behavior and lose
native quote provenance. That is not a narrow adapter fix.

A safe future seam should supply the final routed session and the actual
history for this turn, plus explicit native provenance distinguishing an
implicit topic-root reference from a user-selected quote. Only then compact
an already-represented implicit reference into a short pointer, preserving
explicit quotes and unseen roots. Fail open to the official behavior if any
proof is missing. This investigation does not claim that seam exists today.

## Upstream reconnaissance

- Official plugin and platform-adapter documentation were consulted:
  https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
  https://hermes-agent.nousresearch.com/docs/developer-guide/adding-platform-adapters
- Public search covered topic routing and redundant reply context, including
  open/closed PR results. Search is not proof of absence of another fix.
- Related Feishu routing work: https://github.com/NousResearch/hermes-agent/pull/9118
  and https://github.com/NousResearch/hermes-agent/pull/64332 . These concern
  routing/session/anchor behavior and do not establish safe quote deduplication.
- Slack has a related thread-root fix:
  https://github.com/NousResearch/hermes-agent/commit/bac960e23db54e13acc695472387e015b62fcda1 .
  Its changed files are Slack-specific, not evidence that Feishu quote semantics
  can be treated identically.
- Current public Feishu source was also consulted; the local inspected commit
  and executed tests are the precise baseline for the findings above.

## Real verification

`tests/test_reply_context.py` adds nine characterization tests. They call the
real official `_process_inbound_message` (including text extraction and source
construction) and real gateway `_prepend_inbound_reply_context`. Network,
profile lookup and final dispatch are mocked; there is no Feishu connection.
They exercise repeated topic-root prefixes, parent/upper precedence, ordinary
group quotes, DM quotes, missing references, failed lookup, long untruncated
quotes, thread-session isolation, and official/plugin parity.

These are characterization tests of existing behavior, not RED/GREEN claims
for a production fix. No production code was changed.

Executed with the existing managed Python 3.14.7 and real Lark SDK:

```sh
"C:/path/to/hermes-runtime/python.exe" \
  scripts/verify.py \
  --hermes-root C:/path/to/clean-hermes-checkout \
  --scratch C:/path/to/scratch \
  --report-dir C:/path/to/scratch/feishu-topic-report
```

Result: 38 tests passed, including all 29 pre-existing regressions and real
isolated discovery/unload tests. The actual CLI validator exited zero with
`ok: true`; its existing private-core-import warning and in-process platform
isolation remain. This does not confer official catalog eligibility.
One pre-existing asyncio slow-task diagnostic appeared on cold localization
loading; no test failed. Reports are under the scratch report directory above.

No packages installed, real-profile plugin installed/enabled, gateway restarted,
core edited, commit made or repository pushed. No full upstream suite or live
Feishu acceptance was performed. Historical `VERIFICATION.md` describes the
older baseline; the record here applies to this investigation.
