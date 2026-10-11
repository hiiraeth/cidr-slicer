from ipaddress import IPv4Network
from typing import Optional

def usable_host_count(network: IPv4Network) -> int:
    """Return the number of usable host addresses in a network.

    Standard subnets reserve the network and broadcast addresses, so
    they have num_addresses - 2 usable hosts. A /31 is a point-to-point
    link with no reserved addresses (RFC 3021), so both are usable. A /32
    is a single host route with one usable address.
    """

    if network.prefixlen < 31:
        return max(0, network.num_addresses - 2)
    return network.num_addresses

def range_string(network: IPv4Network) -> str:
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

def display_info(subnet: IPv4Network, vlan: Optional[int], desc: str, created_at: Optional[str]=None) -> None:
    """Print one allocation: its subnet details, VLAN, description, and creation time.

    Shared by handle_allocate() and handle_report() so every command shows an
    allocation in the same format. Callers pass the raw saved values; the
    substitutions for missing values happen here, so the wording lives in one
    place: no VLAN prints "Not assigned to a VLAN" and an empty description
    prints "N/A". Each entry ends with a blank line to separate it from the
    next.

    Arguments:
        subnet: the allocated IPv4Network. Its usable range and host count
            are computed from it.
        vlan: the VLAN ID, or None if the allocation has no VLAN.
        desc: the description, or "" if it has none.
        created_at: when the allocation was saved, as the UTC text stored in
            the database. Omitted by handle_allocate(), which has no saved
            row to read it from; the "Created" line is skipped when it's
            None.
    """

    vlan_text = "Not assigned to a VLAN" if vlan is None else vlan
    desc_text = "N/A" if desc == "" else desc

    print(f"  Subnet: {subnet}")
    print(f"  Range: {range_string(subnet)}")
    print(f"  Hosts: {usable_host_count(subnet)}")
    print(f"  VLAN: {vlan_text}")
    print(f"  Description: {desc_text}")

    if created_at:
        print(f"  Created: {created_at} UTC\n")
    else:
        print("")