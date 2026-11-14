"""Small lifecycle facade shared by streaming adapters and the legacy bridge."""


class StreamingProvider:
    async def write_audio(self, pcm):
        await self.send_audio(pcm)

    async def finish_input(self):
        # Returning means the termination marker was written, not merely queued.
        await self.send_audio(b"", last=True)

    async def cancel(self):
        await self.close()
