import ipaddress

MASTER_SUBNET = "10.0.0.0/24"
REQUESTED_PREFIX = 26

def analyze_master_block():
    print(f"--- Analyzing Master Block: {MASTER_SUBNET} ---")
    network = ipaddress.IPv4Network(MASTER_SUBNET)
    
    print(f"Network Address: {network.network_address}")
    print(f"Broadcast Address: {network.broadcast_address}")
    print(f"Subnet Mask: {network.netmask}")
    print(f"Total Usable Hosts: {network.num_addresses - 2}")
    print("\n")

def subnet_allocation():
    print(f"--- Carving subnets with /{REQUESTED_PREFIX} prefix ---")
    network = ipaddress.IPv4Network(MASTER_SUBNET)
    
    allocated_subnets = list(network.subnets(new_prefix=REQUESTED_PREFIX))
    
    for i, subnet in enumerate(allocated_subnets):
        print(f"Allocation {i + 1}:")
        print(f"  Subnet: {subnet}")
        print(f"  Range: {subnet.network_address + 1} - {subnet.broadcast_address - 1}")
        print(f"  Hosts: {subnet.num_addresses - 2}\n")

if __name__ == "__main__":
    analyze_master_block()
    subnet_allocation()