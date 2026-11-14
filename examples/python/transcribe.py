"""Usage: python transcribe.py recording.wav [--profile PROFILE_ID]."""

import argparse
import asyncio
import getpass
import os

from openasr_client import PortalClient, PortalError, wav_chunks


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav")
    parser.add_argument("--portal", default="http://127.0.0.1:10087")
    parser.add_argument("--profile", default="")
    args = parser.parse_args()
    key = os.environ.get("OPENASR_ASR_KEY") or getpass.getpass("Portal ASR key: ")
    async with PortalClient(args.portal, key) as client:
        print(await client.transcribe(wav_chunks(args.wav), profile_id=args.profile))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except PortalError as error:
        raise SystemExit(f"Portal: {error.code} (requestId={error.request_id})") from None
