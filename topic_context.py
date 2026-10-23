"""Topic root sidecars resolved at the documented, actual-session hook.

No model history or core objects are mutated. Durable references survive native
admission's JSON snapshot and gateway restarts; unknown references fail visibly.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from hermes_constants import get_hermes_home

# Refuse NEW references rather than evicting data still owned by queued turns.
MAX_REFERENCE_FILES = 4096
MAX_REFERENCE_BYTES = 64 * 1024 * 1024
MAX_SEEN_ROWS = 65536

_MARKER = re.compile(r'\[Feishu topic root reference: ([0-9a-f]{64})\]')


def _directory():
    path = Path(get_hermes_home()) / 'cache' / 'feishu-enhanced-topic'
    path.mkdir(parents=True, exist_ok=True)
    return path


def reference(event):
    """Return a durable short reference, or None so the full official quote wins."""
    payload = {'text': event.reply_to_text, 'root': event.reply_to_message_id,
               'thread': event.source.thread_id, 'chat': event.source.chat_id,
               'sender': event.source.user_id}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    # Public hook outputs may be replaced by a head/tail preview. Never silently
    # turn a full first root quote into that lossy preview.
    from tools.hook_output_spill import get_spill_config
    spill = get_spill_config()
    if spill['enabled'] and len(payload['text']) + 64 > spill['max_chars']:
        raise ValueError('root exceeds the core hook context spill budget')
    token = hashlib.sha256(encoded).hexdigest()
    path = _directory() / (token + '.json')
    if not path.exists():
        count = size = 0
        for existing in path.parent.glob('*.json'):
            count += 1
            size += existing.stat().st_size
        if count >= MAX_REFERENCE_FILES or size + len(encoded) > MAX_REFERENCE_BYTES:
            raise OSError('Feishu topic context storage capacity reached')
        # Same-content concurrent writers are harmless; replace is atomic for readers.
        import os
        import tempfile
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return f'[Feishu topic root reference: {token}]'


def before_llm(*, session_id='', platform='', user_message='', sender_id='', **kwargs):
    """Inject each root once in the actual session, not once in a chat-derived key."""
    if platform != 'feishu' or not session_id or not isinstance(user_message, str):
        return None
    pieces = []
    directory = None
    for token in dict.fromkeys(_MARKER.findall(user_message)):
        directory = directory or _directory()
        path = directory / (token + '.json')
        try:
            encoded = path.read_bytes()
            if hashlib.sha256(encoded).hexdigest() != token:
                raise ValueError('root reference checksum mismatch')
            payload = json.loads(encoded)
            if not sender_id or payload.get('sender') != sender_id:
                continue
            root_key = json.dumps([payload['chat'], payload['thread'], payload['root']])
            with sqlite3.connect(directory / 'seen.sqlite3', timeout=2) as db:
                db.execute('CREATE TABLE IF NOT EXISTS seen (session TEXT, root TEXT, PRIMARY KEY(session, root))')
                db.execute('BEGIN IMMEDIATE')
                present = db.execute('SELECT 1 FROM seen WHERE session=? AND root=?',
                                     (session_id, root_key)).fetchone()
                if present:
                    inserted = False
                elif db.execute('SELECT COUNT(*) FROM seen').fetchone()[0] >= MAX_SEEN_ROWS:
                    # Capacity fallback repeats the root instead of losing context.
                    inserted = True
                else:
                    inserted = db.execute('INSERT INTO seen VALUES (?, ?)',
                                          (session_id, root_key)).rowcount
            if inserted:
                pieces.append(f'[Replying to topic root: "{payload["text"]}"]')
        except (OSError, ValueError, KeyError, sqlite3.Error):
            # Do not silently claim the root was delivered if storage is unavailable.
            pieces.append('[Feishu topic root context unavailable; ask the user to quote the root again.]')
    return {'context': '\n\n'.join(pieces)} if pieces else None


class TopicRootContextMixin:
    async def _dispatch_inbound_event(self, event):
        source = event.source
        raw = getattr(getattr(event.raw_message, 'event', None), 'message', None)
        root = getattr(raw, 'root_id', None)
        runner = getattr(self, 'gateway_runner', None)
        multiplex = getattr(getattr(runner, 'config', None), 'multiplex_profiles', False)
        enabled = self.config.extra.get('topic_root_context_once', True) is True
        if (enabled and getattr(self, '_topic_context_hook_ready', False) and not multiplex
                and source and source.chat_type != 'dm'
                and source.thread_id and root and event.reply_to_message_id == root
                and not event.media_urls
                and getattr(event.message_type, 'value', None) == 'text'
                and event.reply_to_text and not event.is_command()):
            try:
                event.reply_to_text = reference(event)
            except (OSError, ValueError, TypeError):
                # The original full root text stays intact on a failed write.
                pass
        return await super()._dispatch_inbound_event(event)
