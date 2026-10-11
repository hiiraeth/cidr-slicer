from argparse import Namespace

from database import SubnetStore
from allocator import BuddyAllocator
from cli.display import display_info

def load_pool(pool_name: str, store: SubnetStore) -> tuple[int, BuddyAllocator]:
    """Look up a pool and rebuild its allocation tree from the database.

    Each CLI run is a separate process, so the tree from the last run is
    gone. This builds an empty BuddyAllocator for the pool's CIDR and claims
    every saved allocation, leaving it in the same state as if the program
    had never exited. Commands that read or change a pool's allocations
    call this first; it is also where a missing pool is detected.

    Arguments:
        pool_name: name of the pool to load.
        store: an open SubnetStore.

    Returns:
        A tuple of (pool_id, allocator). The id is needed to save changes
        with add_allocation() or remove_allocation(); the allocator is the
        rebuilt tree.

    Raises:
        ValueError: if no pool has that name.
        ValueError: if two saved allocations overlap or one falls outside
            the pool. The program never saves such rows, so this means the
            database was edited or damaged; the command stops rather than
            run on a tree that would treat the conflicting space as free.
    """

    pool_id, cidr = store.get_pool_id_cidr(pool_name)

    allocator = BuddyAllocator(root_cidr=cidr)
    allocations = store.get_allocations_db(pool_id=pool_id)

    for allocation in allocations:
        try:
            allocator.claim(allocation["subnet"])
        except ValueError as e:
            raise ValueError(f"pool {pool_name} has conflicting saved allocations: {e}") from e

    return pool_id, allocator

def handle_create_pool(args: Namespace, store: SubnetStore):
    """Run the create_pool command: save a new, empty pool and confirm it.

    No tree is rebuilt, since a new pool has no allocations.

    Arguments:
        args: parsed arguments. Uses args.pool_name (already validated by
            validate_pool_name) and args.cidr (an IPv4Network).
        store: an open SubnetStore.

    Raises:
        ValueError: if a pool with that name or that CIDR already exists.
            Left to propagate so main() reports it.
    """

    store.create_pool(args.pool_name, args.cidr)
    print(f"{args.pool_name} created for {args.cidr}")

def handle_allocate(args: Namespace, store: SubnetStore):
    """Run the allocate command: allocate a free subnet, save it, and print it.

    Rebuilds the pool's tree with load_pool(), then asks the allocator for the
    lowest free block of the requested size. The tree changes first and the
    database is written last: if the allocator finds no room, nothing is
    saved, and if anything fails after the tree changes, the tree is simply
    discarded when the run ends, since the next run rebuilds from the
    database.

    A full pool is not an error: it prints a "no free /N" message and saves
    nothing. A missing --desc is saved as "" (the column is NOT NULL), and a
    missing --vlan is saved as NULL.

    Arguments:
        args: parsed arguments. Uses args.pool_name, args.prefix, args.vlan
            (already range-checked, or None), and args.desc (or None).
        store: an open SubnetStore.

    Raises:
        ValueError: if the pool doesn't exist or its saved allocations
            conflict (from load_pool()), or if the prefix is outside the
            range the pool allows (from the allocator). Left to propagate so
            main() reports it.
    """

    pool_id, allocator = load_pool(args.pool_name, store)
    network = allocator.allocate(args.prefix)

    if network is None:
        print(f"no free /{args.prefix} in {args.pool_name}")
        return

    if args.desc is None:
        desc = ""
    else:
        desc = args.desc

    store.add_allocation(pool_id=pool_id, subnet=network, vlan_id=args.vlan, desc=desc)

    vlan = args.vlan

    display_info(network, vlan, desc)

def handle_release(args: Namespace, store: SubnetStore):
    """Run the release command: free an allocated subnet and delete its row.

    Rebuilds the pool's tree with load_pool(), then releases the network in
    the tree first; the allocator performs every check. The database row is
    deleted only after that succeeds, so a rejected release changes nothing.

    Merging freed buddies happens only in the tree and is never saved: the
    database stores allocated blocks only, so the next run's rebuild produces
    the merged free space on its own.

    Arguments:
        args: parsed arguments. Uses args.pool_name and args.network (an
            IPv4Network).
        store: an open SubnetStore.

    Raises:
        ValueError: if the pool doesn't exist or its saved allocations
            conflict (from load_pool()); if the network is outside the pool,
            isn't exactly an allocated block, or isn't currently allocated
            (from the allocator); or if no matching row is deleted, which
            would mean the tree and database disagree (from
            remove_allocation()). Left to propagate so main() reports it.
    """

    pool_id, allocator = load_pool(args.pool_name, store)

    allocator.release(network=args.network)
    store.remove_allocation(pool_id=pool_id, subnet=args.network)

    print(f"released {args.network} from {args.pool_name}")

def handle_report(args: Namespace, store: SubnetStore):
    """Run the report command: print every allocation in a pool.

    The pool is loaded with load_pool() first, even though the report reads
    its rows from the database, so a missing pool or conflicting saved
    allocations are reported as errors instead of displayed.

    Allocations are listed in address order. Each shows its subnet, usable
    range, and host count, then its VLAN, description, and creation time in
    UTC. A missing VLAN or an empty description is shown as such, and an
    empty pool prints a message instead of an empty list.

    Arguments:
        args: parsed arguments. Uses args.pool_name (already validated by
            validate_pool_name).
        store: an open SubnetStore.

    Raises:
        ValueError: if the pool doesn't exist or its saved allocations
            conflict, from load_pool(). Left to propagate so main() reports
            it.
    """

    pool_id, allocator = load_pool(args.pool_name, store)
    allocations = store.get_allocations_db(pool_id=pool_id)
    print(f"--- Pool {args.pool_name} {allocator.root.network} ---")

    if not allocations:
        print("no allocations currently exist.")
        return
    
    for row in allocations:
        display_info(row['subnet'], row['vlan_id'], row['description'], row['created_at'])
