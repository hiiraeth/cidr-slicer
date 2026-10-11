import ipaddress

from enum import Enum
from typing import Optional

class NodeState(Enum):
    """Allocation state of a single node in the buddy tree.

    FREE: a leaf whose whole block is available to hand out.
    SPLIT: an internal node whose space lives in its two children. It can
        never be handed out itself, since part of it may already be in use.
    ALLOCATED: a leaf whose whole block has been handed out.
    """

    FREE = 1
    SPLIT = 2
    ALLOCATED = 3

class _BuddyNode:
    """A single block of address space in the buddy allocation tree.

    Each node covers one IPv4 network. When split, it gets two children
    (buddies) that each cover exactly half of its range, with no gaps and
    no overlap. The parent link lets release() walk back up the tree to
    merge buddies.

    Each node also records largest_free: the size, in addresses, of the
    largest FREE block anywhere beneath it, including itself. It is always:

        FREE       the node's own size
        ALLOCATED  0
        SPLIT      the larger of its two children's largest_free

    Allocation reads these values to descend straight to a block that fits,
    never entering a subtree without room, so every change of state must
    keep them correct all the way up to the root.
    """

    def __init__(self, network: ipaddress.IPv4Network, parent: Optional[_BuddyNode] = None):
        """Create a FREE leaf node covering the given network.

        A new node is entirely free, so largest_free starts at its own size.

        Arguments:
            network: the block of address space this node represents.
            parent: the node this one was split from, or None for the root.
        """

        self.network: ipaddress.IPv4Network = network
        self.parent: Optional[_BuddyNode] = parent
        self.left: Optional[_BuddyNode] = None
        self.right: Optional[_BuddyNode] = None
        self.state: NodeState = NodeState.FREE
        self.largest_free: int = self.network.num_addresses

    def split(self):
        """Divide this node into two FREE child nodes, each half its size.

        The lower half becomes self.left and the upper half self.right,
        both linked back to this node as their parent. This node's state
        becomes SPLIT, and its largest_free becomes half its size, since
        each fresh child is entirely free.

        Assumes this node is FREE and larger than a /32. Callers must check
        that first: splitting an ALLOCATED node would hand out space already
        in use, and a /32 has no halves.
        """

        split_networks: list = list(self.network.subnets(prefixlen_diff=1))

        self.left = _BuddyNode(network=split_networks[0], parent=self)
        self.right = _BuddyNode(network=split_networks[1], parent=self)

        self.state = NodeState.SPLIT

        self.largest_free = self._find_largest_free()

    def _find_largest_free(self) -> int:
        """Return this SPLIT node's largest_free, computed from its children.

        The single place the SPLIT rule lives: the larger of the two
        children's largest_free. Only valid on a SPLIT node, which always
        has both children.
        """

        assert self.left is not None and self.right is not None
        return max(self.left.largest_free, self.right.largest_free)

    def _allocate(self, prefix_len: int) -> Optional[ipaddress.IPv4Network]:
        """Recursively find and allocate a free block of the requested size.

        If this node is exactly the requested size and FREE, it is marked
        ALLOCATED, its largest_free drops to 0, and it is returned. If it is
        larger, it splits (when still FREE), then descends into one child
        whose largest_free can hold the request, checking the left child
        first so blocks are taken from the lowest available address. If
        neither child has room, it returns None without descending.

        Because a subtree without room is never entered, the search never
        backtracks: it visits at most one node per level. After the child
        returns, this node recomputes its own largest_free, so every node on
        the path is correct once the recursion unwinds.

        Arguments:
            prefix_len: prefix length of the block to allocate, i.e. 26 for
                a /26. Assumed to be between this node's own prefix length
                and 32; BuddyAllocator.allocate() validates that before the
                recursion starts.

        Returns:
            The allocated network, or None if no free block of that size
            exists under this node.
        """

        if self.network.prefixlen == prefix_len:
            if self.state == NodeState.FREE:
                self.state = NodeState.ALLOCATED
                self.largest_free = 0
                return self.network
            else:
                return None

        if self.state == NodeState.ALLOCATED:
            return None

        if self.state == NodeState.FREE:
            self.split()

        size = 2 ** (32 - prefix_len)

        assert self.left is not None and self.right is not None

        if self.left.largest_free >= size:
            chosen_child = self.left
        elif self.right.largest_free >= size:
            chosen_child = self.right
        else:
            return None

        result = chosen_child._allocate(prefix_len=prefix_len)
        self.largest_free = self._find_largest_free()

        return result

    def _release(self):
        """Free this node, then merge FREE buddies upward as far as possible.

        After marking this node FREE, walks up one parent at a time. If the
        current node's buddy is also FREE, the pair merges: their parent
        becomes a FREE leaf and its children are removed. The walk stops at
        the root, or at the first buddy that is ALLOCATED or SPLIT.

        Freed and merged nodes take their own size as largest_free. Merging
        can stop partway up, but every ancestor above that point still gained
        free space, so the walk continues to the root recomputing
        largest_free without merging. Stopping early would leave stale values
        that make allocate() refuse requests that should succeed.

        Stopping at a SPLIT buddy is safe because merging happens every time
        a block is released, so a SPLIT node always has at least one
        ALLOCATED block beneath it. The tree never holds a SPLIT node with
        two FREE children.

        Assumes this node is ALLOCATED and currently in the tree;
        BuddyAllocator.release() checks both before calling.
        """

        self.state = NodeState.FREE
        self.largest_free = self.network.num_addresses
        current_node = self

        while current_node.parent is not None:
            parent = current_node.parent

            if current_node is parent.left:
                buddy = parent.right
            else:
                buddy = parent.left

            assert buddy is not None

            if buddy.state != NodeState.FREE:
                break

            parent.state = NodeState.FREE
            parent.largest_free = parent.network.num_addresses
            parent.left = None
            parent.right = None

            current_node = parent

        ancestor = current_node.parent
        while ancestor is not None:
            ancestor.largest_free = ancestor._find_largest_free()
            ancestor = ancestor.parent

    def _claim(self, target: ipaddress.IPv4Network) -> None:
        """Recursively allocate exactly the target network.

        Unlike _allocate(), which picks any free block of a given size, this
        allocates one specific network. It follows a single path down: at
        each level, it descends into the one child whose range contains the
        target, splitting a FREE node first so that child exists. When it
        reaches the node that matches the target exactly, a FREE node is
        marked ALLOCATED and its largest_free drops to 0.

        After the child returns, this node recomputes its own largest_free,
        so every node on the path is correct once the recursion unwinds.

        Arguments:
            target: the network to allocate. Assumed to be inside this
                node's network; BuddyAllocator.claim() validates that before
                the recursion starts.

        Raises:
            ValueError: if the target is already allocated, contains an
                allocation (its node is SPLIT), or is inside a larger block
                that is already allocated.
        """

        if self.network == target:
            if self.state == NodeState.FREE:
                self.state = NodeState.ALLOCATED
                self.largest_free = 0
                return
            if self.state == NodeState.SPLIT:
                raise ValueError(f"{target} overlaps an allocation!")
            if self.state == NodeState.ALLOCATED:
                raise ValueError(f"{target} is already allocated!")

        if self.state == NodeState.ALLOCATED:
            raise ValueError(f"{target} is inside allocated {self.network}")
        if self.state == NodeState.FREE:
            self.split()

        assert self.left is not None and self.right is not None

        if target.subnet_of(self.left.network):
            child = self.left
        else:
            child = self.right

        child._claim(target=target)

        self.largest_free = self._find_largest_free()

class BuddyAllocator:
    """Allocates subnets from a master network using a buddy allocation tree.

    Public entry point for the tree. Validates requests before they reach
    the node-level logic in _BuddyNode.

    Also keeps allocated_subnets, a set of every currently allocated network,
    so get_allocations() doesn't need to walk the tree. The set is a second
    record alongside the tree's ALLOCATED nodes: allocate(), release() and
    claim() keep the two in sync, and nothing else should change either one.
    """

    def __init__(self, root_cidr: str):
        """Build a tree whose root covers the whole master network.

        Arguments:
            root_cidr: a CIDR string, i.e. "10.0.0.0/24".

        Raises:
            ValueError: if root_cidr is not a valid IPv4 network. Left to
                propagate so a broken allocator is never created.
        """

        self.root = _BuddyNode(ipaddress.IPv4Network(root_cidr))
        self.allocated_subnets: set[ipaddress.IPv4Network] = set()

    def _find_node(self, cur_node: _BuddyNode, target_node_network: ipaddress.IPv4Network) -> Optional[_BuddyNode]:
        """Find the node whose network exactly matches target_node_network.

        Follows a single path down the tree: at each node it descends only
        into the child whose range contains the target, so it visits at most
        one node per level.

        A node that only contains the target does not count as a match. For
        example, asking for .0/27 when the tree ends at an allocated .0/26
        returns None, not the .0/26 node, so release() can never free an
        enclosing block by mistake.

        Arguments:
            cur_node: the node to search from; callers pass the root.
            target_node_network: the network to look for.

        Returns:
            The matching node, or None if the tree was never split down to
            exactly that network.
        """

        if cur_node.network == target_node_network:
            return cur_node

        if cur_node.left is not None and target_node_network.subnet_of(cur_node.left.network):
            return self._find_node(cur_node=cur_node.left, target_node_network=target_node_network)
        
        if cur_node.right is not None and target_node_network.subnet_of(cur_node.right.network):
            return self._find_node(cur_node=cur_node.right, target_node_network=target_node_network)

        return None

    def allocate(self, prefix_len: int) -> Optional[ipaddress.IPv4Network]:
        """Allocate a free subnet of the requested size.

        Validates the request before touching the tree, so an invalid
        prefix never causes a split.

        Arguments:
            prefix_len: prefix length of the block to allocate, i.e. 26 for
                a /26. Must be between the root's prefix length and 32.

        Returns:
            The allocated network, or None if the request is valid but no
            free block of that size remains.

        Raises:
            ValueError: if prefix_len is outside the valid range.
        """

        smallest_allowed = self.root.network.prefixlen
        largest_allowed = 32

        if prefix_len < smallest_allowed or prefix_len > largest_allowed:
            raise ValueError(f"prefix must be between /{smallest_allowed} and /32: got /{prefix_len}")

        result = self.root._allocate(prefix_len=prefix_len)

        if result is not None:
            self.allocated_subnets.add(result)

        return result

    def release(self, network: ipaddress.IPv4Network) -> None:
        """Return a previously allocated subnet to the pool.

        Every check runs before the tree is modified, so a rejected request
        leaves the tree exactly as it was. Once validated, the block is freed
        and merged with its buddies where possible, so larger blocks become
        available again.

        Arguments:
            network: the subnet to release. Must exactly match a block
                returned by allocate(), i.e. 192.168.50.64/26.

        Raises:
            ValueError: if network is outside the master network.
            ValueError: if the tree has no block that exactly matches
                network, such as a /27 inside an allocated /26.
            ValueError: if the matching block is not ALLOCATED. Covers
                releasing a block twice, and releasing a SPLIT block,
                which would free other allocations beneath it.
        """

        if not network.subnet_of(self.root.network):
            raise ValueError(f"{network} is not in {self.root.network}!")

        node = self._find_node(self.root, network)

        if node is None:
            raise ValueError(f"{network} cannot be released: not allocated!")

        if node.state != NodeState.ALLOCATED:
            raise ValueError(f"{network} cannot be released: not allocated!")

        node._release()
        self.allocated_subnets.remove(node.network)

    def get_allocations(self) -> list[ipaddress.IPv4Network]:
        """Return every currently allocated network, sorted by address.

        Sorts IPv4Network objects rather than strings, so .64/26 comes
        before .128/25. An empty list means nothing is allocated.
        """

        return sorted(self.allocated_subnets)

    def claim(self, network: ipaddress.IPv4Network) -> None:
        """Allocate one exact network, such as one loaded from the database.

        Used to rebuild the tree from saved allocations. Replaying
        allocate(prefix_len) would not restore the same addresses, because
        allocate() always takes the lowest free block of that size. Claiming
        every saved network rebuilds a tree that holds the same allocations
        and gives the same answers to later allocate() calls.

        Arguments:
            network: the network to allocate, i.e. 10.0.0.64/26. Must be
                inside the master network.

        Raises:
            ValueError: if network is outside the master network.
            ValueError: if network is already allocated, contains an
                allocated block, or is inside an allocated block. A rejected
                claim leaves allocated_subnets unchanged.
        """

        if not network.subnet_of(self.root.network):
            raise ValueError(f"{network} is not in {self.root.network}!")
        if network in self.allocated_subnets:
            raise ValueError(f"{network} is already allocated")

        self.root._claim(network)
        self.allocated_subnets.add(network)