"""
CIDR Slicer: IPAM CLI tool

Manages named IPv4 address pools from the command line, one command per run:

    cidr_slicer.py [--db PATH] create_pool <name> <cidr>
    cidr_slicer.py [--db PATH] allocate <pool> <prefix> [--vlan N] [--desc TEXT]
    cidr_slicer.py [--db PATH] release <pool> <network>
    cidr_slicer.py [--db PATH] report <pool>

Pools and their allocations are saved in a SQLite database (database.py),
which is the source of truth. Each run rebuilds the pool's buddy allocation
tree (allocator.py) from the saved rows, runs the command, and saves any
change. Argument parsing lives in cli/parser.py and the commands in
cli/commands.py.
"""

import sys

from cli.parser import create_parser
from database import SubnetStore

def main():
    """Entry point: parse the command, run it against the database, report errors.

    Malformed input (a bad pool name, CIDR, prefix, or VLAN) is rejected by
    argparse before the database is opened, with a usage line and a message
    on stderr, and exit status 2. Otherwise the store is opened and the
    subcommand's handler (args.func) is run with it.

    main() is the single place errors from running a command are reported:
    any ValueError, such as a database file that can't be opened, a missing
    pool, a duplicate, or a release the allocator refuses, is printed to stderr as "[ERROR] ..." and the program
    exits with status 1. Normal output goes to stdout, so redirecting a
    report to a file doesn't capture errors. A successful command, including
    an allocate that finds no free block, exits with status 0.

    The store is opened inside the try block so a failure to open it is
    reported the same way, not as a traceback. It is closed in a finally
    block whether the command succeeds or fails; sys.exit() raises
    SystemExit, so the finally block still runs. store starts as None so the
    finally block can tell whether there is a store to close.
    """
    
    parser = create_parser()
    args = parser.parse_args()

    store = None

    try:
        store = SubnetStore(args.db)
        args.func(args, store)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if store is not None:
            store.close_db()

if __name__ == "__main__":
    main()