from __future__ import annotations

from dataclasses import dataclass

THOUGHT_TEXT_LIMIT = 120
THOUGHT_MARKERS = ("{", "}", "```", "action_input", "システムプロンプト")


@dataclass
class _IncrementalJsonString:
    escape_pending: bool = False
    unicode_digits: str | None = None
    pending_high_surrogate: int | None = None

    @property
    def can_close(self) -> bool:
        return not self.escape_pending and self.unicode_digits is None

    def feed(self, char: str) -> str:
        if self.unicode_digits is not None:
            self.unicode_digits += char
            if len(self.unicode_digits) < 4:
                return ""
            digits = self.unicode_digits
            self.unicode_digits = None
            try:
                code_unit = int(digits, 16)
            except ValueError:
                return self._flush_pending_surrogate() + "�"
            return self._decode_code_unit(code_unit)

        if self.escape_pending:
            self.escape_pending = False
            if char == "u":
                self.unicode_digits = ""
                return ""
            decoded = {
                '"': '"',
                "\\": "\\",
                "/": "/",
                "b": " ",
                "f": " ",
                "n": " ",
                "r": " ",
                "t": " ",
            }.get(char, char)
            return self._flush_pending_surrogate() + decoded

        if char == "\\":
            self.escape_pending = True
            return ""
        return self._flush_pending_surrogate() + char

    def finish(self) -> str:
        return self._flush_pending_surrogate()

    def _decode_code_unit(self, code_unit: int) -> str:
        if 0xD800 <= code_unit <= 0xDBFF:
            prefix = self._flush_pending_surrogate()
            self.pending_high_surrogate = code_unit
            return prefix
        if 0xDC00 <= code_unit <= 0xDFFF:
            if self.pending_high_surrogate is None:
                return "�"
            high = self.pending_high_surrogate
            self.pending_high_surrogate = None
            codepoint = 0x10000 + ((high - 0xD800) << 10) + (code_unit - 0xDC00)
            return chr(codepoint)
        return self._flush_pending_surrogate() + chr(code_unit)

    def _flush_pending_surrogate(self) -> str:
        if self.pending_high_surrogate is None:
            return ""
        self.pending_high_surrogate = None
        return "�"


class ThoughtStreamExtractor:
    """Incrementally extracts a top-level JSON thought string."""

    def __init__(self, *, text_limit: int = THOUGHT_TEXT_LIMIT) -> None:
        self.text_limit = text_limit
        self._state = "seek_object"
        self._decoder: _IncrementalJsonString | None = None
        self._current_key = ""
        self._chars: list[str] = []
        self._pending_space = False
        self._guarded = False
        self._skip_depth = 0
        self._skip_in_string = False
        self._skip_escape = False

    @property
    def text(self) -> str:
        return "".join(self._chars)

    @property
    def guarded(self) -> bool:
        return self._guarded

    @property
    def finished(self) -> bool:
        return self._state == "done"

    def feed(self, chunk: str) -> str | None:
        previous = self.text
        for char in chunk:
            self._consume(char)
        current = self.text
        if self._guarded or current == previous:
            return None
        return current

    def _consume(self, char: str) -> None:
        if self._state == "done":
            return
        if self._state == "seek_object":
            if char == "{":
                self._state = "seek_key"
            return
        if self._state == "seek_key":
            if char.isspace() or char == ",":
                return
            if char == "}":
                self._state = "done"
                return
            if char == '"':
                self._decoder = _IncrementalJsonString()
                self._state = "read_key"
            return
        if self._state == "read_key":
            assert self._decoder is not None
            if char == '"' and self._decoder.can_close:
                self._current_key += self._decoder.finish()
                self._decoder = None
                self._state = "after_key"
                return
            self._current_key += self._decoder.feed(char)
            return
        if self._state == "after_key":
            if char.isspace():
                return
            self._state = "before_value" if char == ":" else "done"
            return
        if self._state == "before_value":
            if char.isspace():
                return
            if self._current_key == "thought":
                if char == '"':
                    self._decoder = _IncrementalJsonString()
                    self._state = "read_thought"
                else:
                    self._state = "done"
                return
            self._start_skipping_value(char)
            return
        if self._state == "read_thought":
            assert self._decoder is not None
            if char == '"' and self._decoder.can_close:
                self._append_decoded(self._decoder.finish())
                self._decoder = None
                self._pending_space = False
                self._state = "done"
                return
            self._append_decoded(self._decoder.feed(char))
            return
        if self._state == "skip_string":
            if self._skip_escape:
                self._skip_escape = False
            elif char == "\\":
                self._skip_escape = True
            elif char == '"':
                self._state = "after_value"
            return
        if self._state == "skip_complex":
            if self._skip_in_string:
                if self._skip_escape:
                    self._skip_escape = False
                elif char == "\\":
                    self._skip_escape = True
                elif char == '"':
                    self._skip_in_string = False
                return
            if char == '"':
                self._skip_in_string = True
            elif char in "[{":
                self._skip_depth += 1
            elif char in "]}":
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._state = "after_value"
            return
        if self._state == "skip_scalar":
            if char == ",":
                self._reset_for_next_key()
            elif char == "}":
                self._state = "done"
            return
        if self._state == "after_value":
            if char.isspace():
                return
            if char == ",":
                self._reset_for_next_key()
            elif char == "}":
                self._state = "done"

    def _start_skipping_value(self, char: str) -> None:
        if char == '"':
            self._skip_escape = False
            self._state = "skip_string"
        elif char in "[{":
            self._skip_depth = 1
            self._skip_in_string = False
            self._skip_escape = False
            self._state = "skip_complex"
        else:
            self._state = "skip_scalar"

    def _reset_for_next_key(self) -> None:
        self._current_key = ""
        self._state = "seek_key"

    def _append_decoded(self, decoded: str) -> None:
        for char in decoded:
            if char.isspace():
                if self._chars:
                    self._pending_space = True
                continue
            if self._pending_space and len(self._chars) < self.text_limit:
                self._chars.append(" ")
            self._pending_space = False
            if len(self._chars) < self.text_limit:
                self._chars.append(char)
            if any(marker in self.text for marker in THOUGHT_MARKERS):
                self._guarded = True
