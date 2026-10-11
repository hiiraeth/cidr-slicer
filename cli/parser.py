import argparse
import re
from pathlib import Path

from ipaddress import IPv4Network
from cli.commands import handle_create_pool, handle_report, handle_allocate, handle_release
from cli.help_text import PARSER_COMMANDS, PARSER_SUBCOMMANDS, PARSER_ARGUMENTS, PARSER_DESCRIPTIONS

PARENT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PARENT_DIR / "cidr_slicer.db"

def parse_network(value):
    try:
        network = IPv4Network(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{e}") from e

    return network

def vlan_range(value) -> int:
    value = int(value)
    if value < 1 or value > 4094:
        raise argparse.ArgumentTypeError(f"{value} must be between 1 and 4094!")

    return value

def cidr_prefix_range(value):
    value = parse_network(value)
    if value.prefixlen > 31:
        raise argparse.ArgumentTypeError(f"{value.prefixlen} must be between 0 and 31!")

    return value

def validate_pool_name(value):
    name_pattern = r'[a-zA-Z0-9_-]{1,32}'
    pool_name_valid = re.fullmatch(name_pattern, value)

    if pool_name_valid is None:
        raise argparse.ArgumentTypeError(f"pool names must be 1-32 letters, digits, hyphens, or underscores")

    return value

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="cidr-slicer, an IPAM tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser.add_argument("--db", "--database", type=str, default=str(DB_PATH), help=PARSER_COMMANDS['database_path'])

    # create-pool subcommand
    create_pool = subparsers.add_parser(
        "create_pool", 
        description=PARSER_DESCRIPTIONS['create_pool'], 
        help=PARSER_SUBCOMMANDS['create_pool']
    )

    create_pool.add_argument("pool_name", type=validate_pool_name, help=PARSER_ARGUMENTS['pool_name'])
    create_pool.add_argument("cidr", type=cidr_prefix_range, help=PARSER_ARGUMENTS['cidr'])
    create_pool.set_defaults(func=handle_create_pool)

    # allocate subcommand
    allocate = subparsers.add_parser(
        "allocate", 
        description=PARSER_DESCRIPTIONS['allocate'], 
        help=PARSER_SUBCOMMANDS['allocate']
    )

    allocate.add_argument("pool_name", type=validate_pool_name, help=PARSER_ARGUMENTS['pool_name'])
    allocate.add_argument("prefix", type=int, help=PARSER_ARGUMENTS['prefix'])
    allocate.add_argument("--vlan", type=vlan_range, help=PARSER_ARGUMENTS['vlan'])
    allocate.add_argument("--desc", type=str, help=PARSER_ARGUMENTS['desc'])
    allocate.set_defaults(func=handle_allocate)

    # release subcommand
    release = subparsers.add_parser(
        "release", 
        description=PARSER_DESCRIPTIONS['release'], 
        help=PARSER_SUBCOMMANDS['release']
    )

    release.add_argument("pool_name", type=validate_pool_name, help=PARSER_ARGUMENTS['pool_name'])
    release.add_argument("network", type=parse_network, help=PARSER_ARGUMENTS['network'])
    release.set_defaults(func=handle_release)

    # report subcommand
    report = subparsers.add_parser(
        "report", 
        description=PARSER_DESCRIPTIONS['report'], 
        help=PARSER_SUBCOMMANDS['report']
    )
    
    report.add_argument("pool_name", type=validate_pool_name, help=PARSER_ARGUMENTS['pool_name'])
    report.set_defaults(func=handle_report)

    return parser