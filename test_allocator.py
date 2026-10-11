import random
import unittest
from itertools import combinations

from allocator import BuddyAllocator, NodeState
from ipaddress import IPv4Network

class TestBuddyAllocator(unittest.TestCase):
    """Unit tests for splitting, allocation, and input validation in the buddy tree."""

    def setUp(self):
        """Give each test a fresh, unallocated /24 tree."""
        self.alloc = BuddyAllocator('192.168.50.0/24')
        self.root = self.alloc.root

    def test_split_state(self):
        """A node that has been split is marked SPLIT."""
        self.root.split()
        self.assertEqual(self.root.state, NodeState.SPLIT)

    def test_left_network(self):
        """The left child of a split covers the lower half of the parent."""
        self.root.split()
        assert self.root.left is not None

        self.assertEqual(self.root.left.network, IPv4Network('192.168.50.0/25'))

    def test_right_network(self):
        """The right child of a split covers the upper half of the parent."""
        self.root.split()
        assert self.root.right is not None

        self.assertEqual(self.root.right.network, IPv4Network('192.168.50.128/25'))

    def test_parent_node(self):
        """Both children of a split link back to the node they were split from."""
        self.root.split()
        assert self.root.left is not None and self.root.right is not None

        self.assertEqual(self.root, self.root.left.parent)
        self.assertEqual(self.root, self.root.right.parent)

    def test_adjacent_node_state(self):
        """Both children of a split start out FREE."""
        self.root.split()
        assert self.root.left is not None and self.root.right is not None

        self.assertEqual(self.root.left.state, NodeState.FREE)
        self.assertEqual(self.root.right.state, NodeState.FREE)

    def test_prefix_shorter_than_root(self):
        """A request larger than the master block raises and leaves the tree untouched."""
        with self.assertRaises(ValueError):
            self.alloc.allocate(16)

        self.assertEqual(self.root.state, NodeState.FREE)

    def test_prefix_longer_than_32(self):
        """A prefix beyond the IPv4 limit raises and leaves the tree untouched."""
        with self.assertRaises(ValueError):
            self.alloc.allocate(33)

        self.assertEqual(self.root.state, NodeState.FREE)

    def test_negative_prefix(self):
        """A negative prefix raises and leaves the tree untouched."""
        with self.assertRaises(ValueError):
            self.alloc.allocate(-1)

        self.assertEqual(self.root.state, NodeState.FREE)

    def test_root_sized_request(self):
        """A request the size of the master block allocates the root itself."""
        network = self.alloc.allocate(24)
        self.assertEqual(self.root.state, NodeState.ALLOCATED)
        self.assertEqual(network, IPv4Network('192.168.50.0/24'))

    def test_single_address_request(self):
        """A /32 request splits down to and returns a single address."""
        self.assertEqual(self.alloc.allocate(32), IPv4Network('192.168.50.0/32'))

    def test_allocation_sequence(self):
        """Successive requests take the lowest free block and return None once no fit remains."""
        first  = self.alloc.allocate(26)
        self.assertEqual(first, IPv4Network('192.168.50.0/26'))

        second = self.alloc.allocate(26)
        self.assertEqual(second, IPv4Network('192.168.50.64/26'))

        third  = self.alloc.allocate(25)
        self.assertEqual(third, IPv4Network('192.168.50.128/25'))

        fourth = self.alloc.allocate(25)
        self.assertIsNone(fourth)

    def test_allocations_never_overlap(self):
        """No two allocated blocks share any addresses."""
        check_overlap_list = []

        first  = self.alloc.allocate(26)
        check_overlap_list.append(first)

        second = self.alloc.allocate(26)
        check_overlap_list.append(second)

        third  = self.alloc.allocate(25)
        check_overlap_list.append(third)

        for net_1, net_2 in combinations(check_overlap_list, 2):
            self.assertFalse(net_1.overlaps(net_2), f"{net_1} and {net_2} overlap!")


class TestBuddyRelease(unittest.TestCase):
    """Unit tests for releasing blocks and merging buddies back together."""

    def setUp(self):
        """Build a fully allocated /24: .0/26, .64/26, and .128/25.

        Resulting tree:
            /24 SPLIT
            ├── .0/25 SPLIT
            │   ├── .0/26   ALLOCATED
            │   └── .64/26  ALLOCATED
            └── .128/25 ALLOCATED
        """
        self.alloc = BuddyAllocator('192.168.50.0/24')
        self.root = self.alloc.root

        self.alloc.allocate(26)
        self.alloc.allocate(26)
        self.alloc.allocate(25)

        assert self.root.left is not None and self.root.right is not None
        assert self.root.left.left is not None and self.root.left.right is not None
        self.left_25 = self.root.left
        self.right_25 = self.root.right
        self.first_26 = self.root.left.left
        self.second_26 = self.root.left.right

    def test_release_outside_root_raises(self):
        """Releasing a network outside the master block raises and changes nothing."""
        with self.assertRaises(ValueError):
            self.alloc.release(IPv4Network('10.0.0.0/26'))

        self.assertEqual(self.first_26.state, NodeState.ALLOCATED)
        self.assertEqual(self.second_26.state, NodeState.ALLOCATED)
        self.assertEqual(self.right_25.state, NodeState.ALLOCATED)

    def test_release_block_not_in_tree_raises(self):
        """Releasing a network the tree never split down to raises and changes nothing."""
        with self.assertRaises(ValueError):
            self.alloc.release(IPv4Network('192.168.50.0/27'))

        self.assertEqual(self.first_26.state, NodeState.ALLOCATED)
        self.assertIsNone(self.first_26.left)

    def test_release_on_fresh_tree_raises(self):
        """Releasing from a tree with no allocations raises and leaves the root FREE."""
        fresh = BuddyAllocator('192.168.50.0/24')

        with self.assertRaises(ValueError):
            fresh.release(IPv4Network('192.168.50.0/26'))

        self.assertEqual(fresh.root.state, NodeState.FREE)

    def test_release_split_node_raises(self):
        """Releasing a SPLIT block raises, so allocated blocks beneath it stay allocated."""
        with self.assertRaises(ValueError):
            self.alloc.release(IPv4Network('192.168.50.0/25'))

        self.assertEqual(self.left_25.state, NodeState.SPLIT)
        self.assertEqual(self.first_26.state, NodeState.ALLOCATED)
        self.assertEqual(self.second_26.state, NodeState.ALLOCATED)

    def test_double_release_raises(self):
        """Releasing the same block twice raises on the second attempt."""
        self.alloc.release(IPv4Network('192.168.50.0/26'))

        with self.assertRaises(ValueError):
            self.alloc.release(IPv4Network('192.168.50.0/26'))

    def test_release_marks_block_free(self):
        """A released block becomes FREE; its parent stays SPLIT while the buddy is in use."""
        self.alloc.release(IPv4Network('192.168.50.0/26'))

        self.assertEqual(self.first_26.state, NodeState.FREE)
        self.assertEqual(self.second_26.state, NodeState.ALLOCATED)
        self.assertEqual(self.left_25.state, NodeState.SPLIT)

    def test_release_merges_free_buddies(self):
        """Releasing both buddies merges them into a FREE parent with no children."""
        self.alloc.release(IPv4Network('192.168.50.0/26'))
        self.alloc.release(IPv4Network('192.168.50.64/26'))

        self.assertEqual(self.left_25.state, NodeState.FREE)
        self.assertIsNone(self.left_25.left)
        self.assertIsNone(self.left_25.right)
        self.assertEqual(self.root.state, NodeState.SPLIT)

    def test_release_all_restores_root(self):
        """Releasing every block merges all the way up to a single FREE root."""
        self.alloc.release(IPv4Network('192.168.50.0/26'))
        self.alloc.release(IPv4Network('192.168.50.64/26'))
        self.alloc.release(IPv4Network('192.168.50.128/25'))

        self.assertEqual(self.root.state, NodeState.FREE)
        self.assertIsNone(self.root.left)
        self.assertIsNone(self.root.right)

    def test_release_recovers_from_fragmentation(self):
        """A /25 request fails while fragmented and succeeds once buddies merge."""
        self.alloc.release(IPv4Network('192.168.50.0/26'))
        self.assertIsNone(self.alloc.allocate(25))

        self.alloc.release(IPv4Network('192.168.50.64/26'))
        self.assertEqual(self.alloc.allocate(25), IPv4Network('192.168.50.0/25'))


def allocated_in_tree(node) -> set[IPv4Network]:
    """Walk the tree and collect every ALLOCATED node's network.

    Independent of BuddyAllocator.allocated_subnets, so tests can check
    the set against what the tree actually holds.
    """
    if node.state == NodeState.ALLOCATED:
        return {node.network}
    if node.state == NodeState.SPLIT:
        return allocated_in_tree(node.left) | allocated_in_tree(node.right)
    return set()


class TestAllocationTracking(unittest.TestCase):
    """Unit tests for get_allocations() and the set that backs it."""

    def setUp(self):
        """Give each test an unallocated /24 tree."""
        self.alloc = BuddyAllocator('192.168.50.0/24')

    def assertInSync(self):
        """The tracked set holds exactly the networks the tree marks ALLOCATED."""
        self.assertEqual(set(self.alloc.get_allocations()), allocated_in_tree(self.alloc.root))

    def test_fresh_allocator_has_no_allocations(self):
        """A new allocator reports nothing allocated."""
        self.assertEqual(self.alloc.get_allocations(), [])

    def test_allocations_listed_in_address_order(self):
        """Allocations come back sorted by address, not as text.

        Sorting CIDR strings would put .128/25 before .64/26, since '1' < '6'.
        """
        self.alloc.allocate(26)
        self.alloc.allocate(26)
        self.alloc.allocate(25)

        self.assertEqual(self.alloc.get_allocations(), [
            IPv4Network('192.168.50.0/26'),
            IPv4Network('192.168.50.64/26'),
            IPv4Network('192.168.50.128/25'),
        ])

    def test_release_removes_from_allocations(self):
        """A released block no longer appears in the list."""
        self.alloc.allocate(26)
        self.alloc.allocate(26)
        self.alloc.release(IPv4Network('192.168.50.0/26'))

        self.assertEqual(self.alloc.get_allocations(), [IPv4Network('192.168.50.64/26')])

    def test_failed_allocate_leaves_allocations_unchanged(self):
        """An allocate that returns None adds nothing to the list."""
        self.alloc.allocate(25)
        self.alloc.allocate(25)
        before = self.alloc.get_allocations()

        self.assertIsNone(self.alloc.allocate(25))
        self.assertEqual(self.alloc.get_allocations(), before)

    def test_rejected_release_leaves_allocations_unchanged(self):
        """A release that raises ValueError removes nothing from the list."""
        self.alloc.allocate(26)
        before = self.alloc.get_allocations()

        with self.assertRaises(ValueError):
            self.alloc.release(IPv4Network('192.168.50.64/26'))

        self.assertEqual(self.alloc.get_allocations(), before)

    def test_tracked_set_matches_tree(self):
        """After a mix of allocates and releases, the set and the tree agree."""
        self.alloc.allocate(26)
        self.assertInSync()
        self.alloc.allocate(27)
        self.assertInSync()
        self.alloc.allocate(25)
        self.assertInSync()
        self.alloc.release(IPv4Network('192.168.50.0/26'))
        self.assertInSync()
        self.alloc.allocate(28)
        self.assertInSync()
        self.alloc.release(IPv4Network('192.168.50.128/25'))
        self.assertInSync()

    def test_random_operations_keep_invariants(self):
        """Across many random allocates and releases: no overlaps, set and tree agree, full merge at the end."""
        rng = random.Random(499)

        for _ in range(50):
            alloc = BuddyAllocator('10.0.0.0/22')
            held = []

            for _ in range(100):
                if held and rng.random() < 0.45:
                    alloc.release(held.pop(rng.randrange(len(held))))
                else:
                    result = alloc.allocate(rng.randint(22, 30))
                    if result is not None:
                        held.append(result)

                self.assertEqual(set(alloc.get_allocations()), set(held))
                self.assertEqual(allocated_in_tree(alloc.root), set(held))
                for net_1, net_2 in combinations(held, 2):
                    self.assertFalse(net_1.overlaps(net_2), f"{net_1} and {net_2} overlap!")

            for network in held:
                alloc.release(network)

            self.assertEqual(alloc.root.state, NodeState.FREE)
            self.assertEqual(alloc.get_allocations(), [])


if __name__ == '__main__':
    unittest.main()