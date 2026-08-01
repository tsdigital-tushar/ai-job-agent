"""Phase 3 — Telegram one-tap loop.

Pushes the top-ranked roles to your phone as cards with three buttons —
✅ Apply / ✏️ Draft / ⏭ Skip — and records your tap back into the DB
(applications table). This is the "10+ interested a day, one-tap" experience
from the design doc: the agent surfaces and pre-decides; you approve.

Uses Telegram's plain HTTP Bot API via `requests` — no extra dependency, no
polling framework. Two modes:

  send-only : push the cards and exit (fire-and-forget).
  listen    : push the cards, then stay open briefly to capture your taps
              (long-polling getUpdates) and log them.

Token + chat_id come from config.telegram (never hard-coded).
"""

from __future__ import annotations

import time
import requests

_API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str, chat_id: str, timeout: int = 20):
        if not token or not chat_id:
            raise RuntimeError(
                "Telegram needs token + chat_id in config (telegram:). "
                "Get a token from @BotFather; use `python -m src.notify --whoami` "
                "to find your chat_id."
            )
        self.token = token
        self.chat_id = str(chat_id)
        self.timeout = timeout

    def _call(self, method: str, **params):
        url = _API.format(token=self.token, method=method)
        r = requests.post(url, json=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def send_role(self, dedup_key: str, title: str, company: str,
                  score: float, reason: str, url: str) -> None:
        """Send one job as a card with inline Apply/Draft/Skip buttons."""
        text = (
            f"*{_esc(title)}*\n"
            f"{_esc(company or '—')}  ·  score {score:.0f}\n"
            f"_{_esc(reason)}_\n"
            f"[Open listing]({url})" if url else
            f"*{_esc(title)}*\n{_esc(company or '—')}  ·  score {score:.0f}\n_{_esc(reason)}_"
        )
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Apply", "callback_data": f"apply|{dedup_key}"},
            {"text": "✏️ Draft", "callback_data": f"draft|{dedup_key}"},
            {"text": "⏭ Skip", "callback_data": f"skip|{dedup_key}"},
        ]]}
        self._call("sendMessage", chat_id=self.chat_id, text=text,
                   parse_mode="Markdown", disable_web_page_preview=True,
                   reply_markup=keyboard)

    def send_text(self, text: str) -> None:
        self._call("sendMessage", chat_id=self.chat_id, text=text)

    def poll_updates(self, seconds: int, on_tap) -> int:
        """Long-poll for button taps for up to `seconds`. Calls
        on_tap(action, dedup_key) for each. Returns count handled."""
        handled = 0
        offset = None
        deadline = time.time() + seconds
        while time.time() < deadline:
            resp = self._call("getUpdates", offset=offset, timeout=10)
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                cb = upd.get("callback_query")
                if not cb:
                    continue
                data = cb.get("data", "")
                if "|" in data:
                    action, key = data.split("|", 1)
                    on_tap(action, key)
                    handled += 1
                    # Acknowledge so the button stops spinning. The tap is
                    # already recorded by on_tap above, so a failed ack — e.g.
                    # Telegram's 400 when the callback is too old to accept —
                    # must not crash the poll. Log it and move on.
                    try:
                        self._call("answerCallbackQuery",
                                   callback_query_id=cb["id"], text=f"{action} ✓")
                    except requests.RequestException as e:
                        print(f"   ! ack failed for {key} (already recorded): {e}")
        return handled

    def get_chat_id_hint(self) -> str:
        """Read recent updates and report the chat_id of whoever messaged the
        bot — used by --whoami so the user doesn't hunt for it manually."""
        resp = self._call("getUpdates")
        for upd in reversed(resp.get("result", [])):
            msg = upd.get("message") or upd.get("edited_message")
            if msg and msg.get("chat"):
                c = msg["chat"]
                return f"chat_id = {c['id']}  ({c.get('first_name','')} {c.get('username','')})".strip()
        return "No messages found. Send your bot a 'hi' first, then retry."


def _esc(text: str) -> str:
    """Escape Markdown-special chars so titles don't break formatting."""
    if not text:
        return ""
    for ch in ("_", "*", "[", "]", "`"):
        text = text.replace(ch, " ")
    return text
