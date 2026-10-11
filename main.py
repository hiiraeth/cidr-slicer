"""
CIDR Slicer: IPAM CLI tool

Takes in a master IPv4 subnet and a requested prefix length
from the command line and reports it onto the master block,
and carves it into subnets of the requested size.
"""

import ipaddress
import argparse
# import sqlite3 - will be used for the database enhancement

class NetworkManager:
    """Wraps a input-validated IPv4 network address and exposes operations on it
    
    Class holds the master subnet as a parsed state; per call parameters, like a
    requested carve prefix, get passed onto individual methods, rather than stored
    on the instance, since they vary per operation rather than per network
    """

    def __init__(self, master_subnet: str) -> None:
        """Validate master subnet
        
        Arguments:
            master_subnet: A CIDR string, i.e. "10.0.0.0/24"

        Raises:
            ValueError: if master_subnet is not a valid IPv4 network.
                Left to propagate to the caller rather than caught here,
                since construction failing means there's no valid object
                to hand back.        
        """

        self.network = ipaddress.IPv4Network(master_subnet)

    def _usable_host_count(self, network: ipaddress.IPv4Network) -> int:
        """Return number of usable host addresses for a given network"""
        if network.prefixlen < 31:
            return max(0, network.num_addresses - 2)
        return network.num_addresses

    def _range_string(self, network: ipaddress.IPv4Network) -> str:
        """Return a display string for a network's usable address range.
 
        A /31 has no reserved addresses (RFC 3021) — both addresses are usable. A /32 is a single host
        route with exactly one address, so there is no range to show.
        """

        if network.prefixlen < 31:
            return f"{network.network_address + 1} - {network.broadcast_address - 1}"
        elif network.prefixlen == 31:
            return f"{network.network_address} - {network.broadcast_address}"
        else:
            return f"{network.network_address}"

    def analyze(self) -> None:
        """Print summary info about the master network
        
        Reports network address, broadcast address, subnet mask, and
        useable host count for self.network. This assumes a standard
        subnet where two addresses (network and broadcast) are reserved.
        """

        print(f"--- Analyzing Master Block: {self.network.network_address} ---")
            
        print(f"Network Address: {self.network.network_address}")
        print(f"Broadcast Address: {self.network.broadcast_address}")
        print(f"Subnet Mask: {self.network.netmask}")
        print(f"Total Usable Hosts: {self._usable_host_count(self.network)}")
        print("\n")

    def carve(self, requested_prefix: int) -> None:
        """Split master network into subnets of a given prefix
        
        Enumerates every subnet of size /requested_prefix within self.network
        and prints each one's range and usable host count. Only lists what
        subnets are mathematically possible. It does not currently track which
        ones are in use.

        Arguments:
            requested_prefix: prefix length to carve into, i.e. 24 for /24 
                subnets. Must be longer than self.networks own prefix.

        Raises:
            ValueError: when a ValueError is raised, it prints an error and
            returns without carving.
        """

        print(f"--- Carving subnets with /{requested_prefix} prefix ---")
        
        try:
            allocated_subnets = list(self.network.subnets(new_prefix=requested_prefix))
        except ValueError as e:
            print(f"[ERROR] Subnet allocation failed with prefix {requested_prefix}! {e}")
            return
    
        for i, subnet in enumerate(allocated_subnets):
            print(f"Allocation {i + 1}:")
            print(f"  Subnet: {subnet}")
            print(f"  Range: {self._range_string(subnet)}")
            print(f"  Hosts: {self._usable_host_count(subnet)}\n")

def parse() -> tuple:
    """Parse command-line arguments for subnet carver.
    
    Returns:
        Tuple of (master_subnet, requested_prefix), where master_subnet is
        the raw CIDR string as typed by user. requested_prefix is a str.
    """

    parser = argparse.ArgumentParser()

    parser.add_argument("master_subnet", type=str, help="the main subnet")
    parser.add_argument("requested_prefix", type=str, help="the requested prefix")

    args = parser.parse_args()

    return args.master_subnet, args.requested_prefix

def main():
    """Entry point of the program. Parses args, builds NetworkManager object,
    runs analyze and carve.
    
    main() owns error reporting for construction failures
    """

    master_subnet, requested_prefix = parse()
            
    try:
        main_network = NetworkManager(master_subnet=master_subnet)
    except ValueError as e:
        print(f"[ERROR] IPv4Network object creation failed! {e}")
        return

    try:
        requested_prefix = int(requested_prefix)
    except ValueError as e:
        print(f"[ERROR] Requested prefix not valid! {e}")
        return
    
    main_network.analyze()
    main_network.carve(requested_prefix=requested_prefix)

if __name__ == "__main__":
    main()