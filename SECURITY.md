# Security

This is full-trust in-process gateway code, not a sandbox. It uses private Hermes APIs and intentionally replaces the same-name Feishu factory; review before installing, pin reviewed revisions and re-test after upgrades.

For a suspected authorization bypass or secret disclosure, do not file raw exploit details or production logs publicly. Use the repository's private security advisory channel if available after publication. No private contact identity has been configured in this unpublished project; if private reporting is unavailable, ask for a secure reporting channel without disclosing exploit details. Never paste bot credentials.

The callback transport, signature verification and Feishu/Lark membership guarantees are owned by the official adapter. This plugin additionally binds clicks to the exact pending entry, message, chat and session owner, and rechecks official group policy. It does not weaken pairing or global allowlists or mark inbound events trusted. Text replies continue through official gateway authorization and routing.

Known limits: SDK/adapter internals may change; state is memory-only; stale buttons may remain visible after network failure or restart; shared sessions deliberately allow multiple policy-authorized participants. No security audit or live-channel acceptance is claimed.
