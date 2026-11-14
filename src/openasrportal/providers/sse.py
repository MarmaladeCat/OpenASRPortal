"""Bounded SSE framing, including UTF-8 and CR/LF split across transport chunks."""

import codecs

from ..domain.transcript import protocol_error


async def events(chunks, limit=1024 * 1024):
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    line, data, kind, size, after_cr = [], [], "", 0, False
    try:
        async for chunk in chunks:
            for character in decoder.decode(chunk):
                if after_cr and character == "\n":
                    after_cr = False
                    continue
                after_cr = character == "\r"
                if character not in "\r\n":
                    line.append(character)
                    size += 1
                    if size > limit:
                        raise protocol_error()
                    continue
                value, line = "".join(line), []
                if not value:
                    if data:
                        yield kind, "\n".join(data)
                    data, kind, size = [], "", 0
                elif not value.startswith(":"):
                    field, _, value = value.partition(":")
                    if value.startswith(" "):
                        value = value[1:]
                    if field == "data":
                        data.append(value)
                    elif field == "event":
                        kind = value
        decoder.decode(b"", final=True)
        # The last event needs its blank-line delimiter; EOF cannot invent done.
        if line or data:
            raise protocol_error()
    except UnicodeError:
        raise protocol_error() from None
