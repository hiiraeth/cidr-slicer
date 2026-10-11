"""
CIDR Slicer: IPAM CLI tool

Takes a master IPv4 subnet from the command line and opens an interactive
session for allocating, releasing, and reporting subnets carved from it.
Allocation is handled by a buddy allocator (see allocator.py). State lasts
only for the session; it is not yet saved between runs.
"""

import ipaddress
import argparse
# import sqlite3 - will be used for the database enhancement
from typing import Optional

import allocator

COMMANDS = {
    "allocate": {
        "usage": "allocate <prefix>",
        "desc": "allocates a free subnet of the requested size and prints it"
    },
    "release": {
        "usage": "release <network>",
        "desc": "releases a previously allocated subnet and confirms it"
    },
    "report": {
        "usage": "report",
        "desc": "prints every currently allocated subnet, in address order"
    },
    "quit": {
        "usage": "quit",
        "desc": "quits the program. can also be triggered by Ctrl+C and Ctrl+D"
    },
    "help": {
        "usage": "help [command]",
        "desc": "prints out all commands available with their usage and a brief description"
    }
}

class NetworkManager:
    """Manages subnet allocation within a validated master IPv4 network.

    Holds two pieces of state: the parsed master network, and a
    BuddyAllocator that tracks which subnets of it are allocated. Per-call
    values, like a requested prefix, are passed to individual methods rather
    than stored on the instance, since they vary per operation.

    Methods print their results. Input parsing and error reporting belong to
    the caller, so the same methods can serve any front end.
    """

    def __init__(self, master_subnet: str) -> None:
        """Validate the master subnet and build an allocator for it.

        Arguments:
            master_subnet: A CIDR string, i.e. "10.0.0.0/24"

        Raises:
            ValueError: if master_subnet is not a valid IPv4 network.
                Left to propagate to the caller rather than caught here,
                since construction failing means there's no valid object
                to hand back.        
        """

        self.network = ipaddress.IPv4Network(master_subnet)
        self.allocator = allocator.BuddyAllocator(master_subnet)

    def _usable_host_count(self, network: ipaddress.IPv4Network) -> int:
        """Return the number of usable host addresses in a network.

        Standard subnets reserve the network and broadcast addresses, so
        they have num_addresses - 2 usable hosts. A /31 is a point-to-point
        link with no reserved addresses (RFC 3021), so both are usable. A /32
        is a single host route with one usable address.
        """

        if network.prefixlen < 31:
            return max(0, network.num_addresses - 2)
        return network.num_addresses

    def _range_string(self, network: ipaddress.IPv4Network) -> str:
        """Return a display string for a network's usable address range.

        A /31 has no reserved addresses (RFC 3021), so both addresses are
        usable. A /32 is a single host route with exactly one address, so
        there is no range to show.
        """

        if network.prefixlen < 31:
            return f"{network.network_address + 1} - {network.broadcast_address - 1}"
        elif network.prefixlen == 31:
            return f"{network.network_address} - {network.broadcast_address}"
        else:
            return f"{network.network_address}"

    def _display_subnet_info(self, subnet: ipaddress.IPv4Network) -> None:
        """Print one subnet's CIDR, usable range, and usable host count.

        Shared by report() and allocate() so every command shows
        a subnet in the same format.

        Arguments:
            subnet: the IPv4Network to display.
        """

        print(f"  Subnet: {subnet}")
        print(f"  Range: {self._range_string(subnet)}")
        print(f"  Hosts: {self._usable_host_count(subnet)}\n")

    def report(self) -> None:
        """Print every currently allocated subnet, in address order.

        Each subnet is shown with its usable range and host count. Prints a
        message instead of an empty list when nothing is allocated, so the
        user always sees a response.
        """

        print("\n--- Currently allocated subnets ---")
        subnets = self.allocator.get_allocations()

        if not subnets:
            print("No subnets currently allocated.")
        else: 
            for subnet in subnets:
                self._display_subnet_info(subnet=subnet)


        print("")

    def allocate(self, prefix_len: int) -> None:
        """Allocate a free subnet of the requested size and print it.

        If the request is valid but no free block of that size remains,
        prints a message saying so. That case is not an error, so it is
        reported here rather than raised.

        Arguments:
            prefix_len: prefix length of the subnet to allocate, i.e. 26 for
                a /26.

        Raises:
            ValueError: if prefix_len is outside the range the master
                network allows. Left to propagate so the caller reports it.
        """

        subnet = self.allocator.allocate(prefix_len=prefix_len)

        if subnet is None:
            print(f"unable to allocate: no free /{prefix_len}\n")
            return

        self._display_subnet_info(subnet=subnet)

    def release(self, network: ipaddress.IPv4Network) -> None:
        """Release a previously allocated subnet and confirm it.

        Freed space merges with free neighboring blocks, so larger subnets
        can become available again.

        Arguments:
            network: the subnet to release. Must exactly match one returned
                by allocate().

        Raises:
            ValueError: if network is outside the master network, was never
                allocated as that exact block, or is not currently allocated.
                Left to propagate so the caller reports it.
        """

        self.allocator.release(network=network)
        print(f"released {network}\n")

def parse() -> str:
    """Parse command-line arguments for CIDR Slicer.

    Returns:
        The master subnet as the raw CIDR string typed by the user. It is
        validated later, when NetworkManager is constructed.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("master_subnet", type=str, help="the main subnet")
    args = parser.parse_args()

    return args.master_subnet

def print_help(command: Optional[str] = None) -> None:
    """Print usage and a description for one command, or for all of them.

    Text comes from COMMANDS, so help output and the usage messages in
    handle_command() always match.

    Arguments:
        command: the command to describe (case insensitive). If None,
            every command is listed. An unrecognized name prints an
            "unknown command" message naming it.
    """

    if command is not None:
        command = command.lower()

        if command in COMMANDS:
            print(f"\n{COMMANDS[command]['usage']:<20}{COMMANDS[command]['desc']}")
        else:
            print(f"unknown command: {command}")
    else:
        print("\n--- CIDR Slicer commands ---\n")
        for entry in COMMANDS.values():
            print(f"{entry['usage']:<20}{entry['desc']}")

    print("")

def main():
    """Entry point of the program.

    Parses the master subnet, builds a NetworkManager, and starts an
    interactive session. main() owns error reporting for construction
    failures: an invalid master subnet prints an [ERROR] message and exits
    before any session starts.
    """

    master_subnet = parse()
            
    try:
        main_network = NetworkManager(master_subnet=master_subnet)
    except ValueError as e:
        print(f"[ERROR] IPv4Network object creation failed! {e}")
        return

    run_session(manager=main_network)

def run_session(manager: NetworkManager):
    """Read commands from the user until they quit.

    Only reads input and decides when to stop; each command is passed to
    handle_command(). The session ends on "quit" (any case, surrounding
    whitespace ignored), Ctrl-D, or Ctrl-C.

    Allocation state lives in manager, so it lasts for the whole session
    but is lost when the program exits.

    Arguments:
        manager: the NetworkManager whose allocator the session works on.
    """

    print("\nwelcome to CIDR slicer. type help for commands.\n")

    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\ngoodbye")
            break

        if line.lower().strip() == "quit":
            print("\ngoodbye")
            break

        handle_command(manager=manager, line=line)

def handle_command(manager: NetworkManager, line: str):
    """Run a single command typed by the user.

    Splits the line into words; the first word is the command (case
    insensitive) and the rest are its arguments. Recognized commands:

        allocate <prefix>    allocate a free subnet, i.e. "allocate 26"
        release <network>    release an allocated subnet, i.e.
                             "release 192.168.50.0/26"
        report               list every allocated subnet
        help [command]       list every command, or describe one

    quit is handled by run_session(), not here.

    Blank lines are ignored, and anything else prints an "unknown command"
    message. Each command accepts only the arguments shown above; any other
    count prints that command's usage message, taken from COMMANDS.

    This is where typed text becomes typed values: the prefix is converted
    with int() and the network with IPv4Network(). Any ValueError, whether
    from that conversion or from the allocator rejecting the request, is
    caught here and printed as an [ERROR] message, so a bad command never
    ends the session.

    Arguments:
        manager: the NetworkManager to run the command against.
        line: the raw line the user typed.
    """

    list_of_words = line.split()
    if not list_of_words:
        return
    
    command = list_of_words[0].lower()


    if command == "allocate":
        if len(list_of_words) == 2:
            arg = list_of_words[1]
        else:
            print(f"usage: {COMMANDS['allocate']['usage']}\n")
            return
        
        try:
            manager.allocate(int(arg))
        except ValueError as e:
            print(f"[ERROR] {e}")
            
    elif command == "release":
        if len(list_of_words) == 2:
            arg = list_of_words[1]
        else:
            print(f"usage: {COMMANDS['release']['usage']}\n")
            return
        
        try:
            manager.release(ipaddress.IPv4Network(arg))
        except ValueError as e:
            print(f"[ERROR] {e}")
            
    elif command == "report":
        if len(list_of_words) == 1:
            manager.report()
        else:
            print(f"usage: {COMMANDS['report']['usage']}\n")
    elif command == "help":
        if len(list_of_words) == 2:
            arg = list_of_words[1]
            print_help(command=arg)
        elif len(list_of_words) > 2:
            print(f"usage: {COMMANDS['help']['usage']}\n")
        else:
            print_help()
    else:
        print("unknown command. type help for a list of commands.")

if __name__ == "__main__":
    main()