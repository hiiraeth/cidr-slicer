PARSER_COMMANDS = {
    "database_path": "path of database to use: default is set to the project dir"
}

PARSER_SUBCOMMANDS = {
    "create_pool": "creates a new pool with a given CIDR",
    "allocate": "allocates a network of a given prefix from the given pool",
    "release": "frees an allocated network so it can be reused",
    "report": "lists out all current allocations of a given pool"
}

PARSER_ARGUMENTS = {
    "pool_name": "name of a pool, pool name must be 1-32 letters, digits, hyphens, or underscores",
    "cidr": "cidr value in X.X.X.X/X format",
    "prefix": "cidr prefix, must be an integer. e.g. 26 for /26",
    "vlan": "optional. vlan ID to use, must be an integer in range of 1-4094",
    "desc": "optional. description of the vlan/network",
    "network": "IPv4 network, must be an allocated block exactly as shown when running report"
}

PARSER_DESCRIPTIONS = {
    "create_pool": 
        "create a new, empty address pool. the pool name and CIDR value must be unique, "
        "and the CIDR can't have host bits already set: use 10.0.0.0/24, not 10.0.0.1/24. "
        "subnets are allocated from the pool with the allocate command",

    "allocate":
        "allocate the lowest free subnet of the requested size from a pool, and save it. "
        "the prefix must fit inside the pool: a /24 pool can hand out /24 through /32. "
        "if no free block of that size remains, nothing is saved. freeing space with release "
        "can make larger blocks available again",

    "release":
        "free an allocated subnet so it can be reused. the network must match an allocation "
        "exactly, as listed by report: releasing part of an allocation, or a block that "
        "contains allocations, is refused. freed blocks merge with free neighbors, so larger "
        "subnets can become available",

    "report":
        "list every subnet from a pool in address order with its usable range, host count, "
        "VLAN, description, and the time that it was allocated in UTC"
}