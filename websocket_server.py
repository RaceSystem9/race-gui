from __future__ import annotations

import asyncio

from pi_server.websocket_server import _parse_args, main


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.host, int(args.port)))
