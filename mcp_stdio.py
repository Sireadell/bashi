"""Bashi over stdio, for Claude Desktop, Cursor and other tools that start a program and talk to it.

Same five tools as the /mcp address on the site, from the same code (agent_api.py).
Each line in is one JSON message, each line out is one reply. Run it from this folder
with the database settings in .env:

  python mcp_stdio.py

Nothing else is printed to the output; messages for a person go to stderr.
"""
import json
import os
import sys

import agent_api


def serve(lines, out):
    base = os.environ.get("BASHI_URL", "").rstrip("/")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = agent_api._rpc_error(None, -32700, "Parse error")
        else:
            reply = agent_api.handle_rpc(msg, base)
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()


def main():
    sys.stderr.write("Bashi MCP server ready on stdio\n")
    serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
