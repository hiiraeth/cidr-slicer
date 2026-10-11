import sqlite3

from ipaddress import IPv4Network
from typing import Optional

class SubnetStore:
    """SQLite storage for address pools and the subnets allocated from them.

    The database is the source of truth: each CLI run loads its state from
    here, rebuilds the allocator, runs one command, and saves the result.

    One connection is opened per SubnetStore and reused by every method until
    close_db() is called. Methods that write commit before returning, so a
    change is saved as soon as the method succeeds.

    Constraint failures are translated into ValueError so callers only ever 
    handle one kind of error.

    SQLite has no CIDR type, so the schema can only reject exact duplicates.
    Overlap and containment (a subnet inside its pool, no two subnets
    overlapping) are enforced by the allocator before anything is saved.
    """

    def __init__(self, path: str):
        """Open the database and create its tables if they don't exist yet.

        Foreign keys are turned on here because SQLite does not save that
        setting in the file: it applies only to the connection that runs it,
        and ON DELETE CASCADE depends on it.

        CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so an
        old .db file must be deleted after any schema change.

        All setup runs inside one try block. SQLite opens the file lazily, so
        a file that isn't a database is often not detected until the first
        CREATE TABLE reads it. If any step fails, the connection is closed
        and the SQLite error is replaced with a generic message.

        The connection is held in a local variable until setup succeeds and
        only then assigned to self.conn, so every SubnetStore that exists has
        an open connection and the other methods never need a None check.

        Arguments:
            path: the database file to open, or ":memory:" for a temporary
                database (used by the tests). A missing file is created.

        Raises:
            ValueError: if path can't be opened as a SQLite database, for
                example a file that isn't a database, a directory, or a
                location without permission.
        """

        conn = None

        try:
            conn = sqlite3.connect(path)

            conn.execute("""PRAGMA foreign_keys = ON;""")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS address_pools (
                    id			INTEGER	PRIMARY KEY,
                    pool_name	TEXT	NOT NULL UNIQUE CHECK (length(pool_name) BETWEEN 1 AND 32),
                    cidr		TEXT	UNIQUE NOT NULL,
                    created_at	TEXT	NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) STRICT;
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS allocations (
                    id			INTEGER	PRIMARY KEY,
                    pool_id		INTEGER	NOT NULL REFERENCES address_pools(id) ON DELETE CASCADE,
                    subnet		TEXT	NOT NULL,
                    vlan_id		INTEGER	CHECK (vlan_id BETWEEN 1 AND 4094),
                    created_at	TEXT	NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    description	TEXT	NOT NULL,
                    UNIQUE (pool_id, subnet)
                ) STRICT;
            """)

            conn.commit()
        except sqlite3.Error as e:
            if conn is not None:
                conn.close()
            raise ValueError(f"cannot open {path} as a CIDR Slicer database!") from e

        self.conn = conn

    def close_db(self):
        """Close the database connection.

        Closing does not commit. Anything not yet committed is rolled back,
        which is why every method that writes commits before returning.
        """

        self.conn.close()

    def lookup_cidr(self, value) -> bool:
        """Report whether a pool already uses the given CIDR.

        Arguments:
            value: the CIDR to look for, as str(IPv4Network(...)) so it
                matches the form create_pool() stores.

        Returns:
            True if a pool has this CIDR, False otherwise.
        """

        query = "SELECT EXISTS(SELECT 1 FROM address_pools WHERE cidr = ?)"
        cursor = self.conn.execute(query, (value,))

        return bool(cursor.fetchone()[0])

    def lookup_pool(self, value) -> bool:
        """Report whether a pool with the given name exists.

        Arguments:
            value: the pool name to look for.

        Returns:
            True if a pool has this name, False otherwise.
        """

        query = "SELECT EXISTS(SELECT 1 FROM address_pools WHERE pool_name = ?)"
        cursor = self.conn.execute(query, (value,))

        return bool(cursor.fetchone()[0])

    def get_pool_id_cidr(self, pool_to_find: str) -> tuple:
        """Look up a pool's id and CIDR by its name.

        Arguments:
            pool_to_find: the name of the pool.

        Returns:
            A tuple of (id, cidr): the pool's integer id and its CIDR as a
            string, for example (1, "10.0.0.0/16").

        Raises:
            ValueError: if no pool has this name.
        """

        query = "SELECT id, cidr FROM address_pools WHERE pool_name = ?"
        cursor = self.conn.execute(query, (pool_to_find,))

        result = cursor.fetchone()

        if result:
            return result
        else:
            raise ValueError(f"no pool named {pool_to_find}! create it with create_pool first")

    def create_pool(self, pool_name: str, cidr: IPv4Network) -> int:
        """Save a new address pool and commit it.

        The CIDR is stored as str(cidr) so the same network is always written
        the same way. The name and CIDR are checked before the insert, so a
        rejected insert can say which of the two was the duplicate.

        Arguments:
            pool_name: a unique name for the pool, 1 to 32 characters.
            cidr: the network the pool hands subnets out of. It must not be
                used by another pool.

        Returns:
            The new pool's id.

        Raises:
            ValueError: if the name or CIDR is already used by another pool,
                or the insert breaks another constraint (such as the name
                length check).
        """

        query = "INSERT INTO address_pools (pool_name, cidr) VALUES (?, ?)"

        pool_name_exists = self.lookup_pool(pool_name)
        cidr_exists = self.lookup_cidr(str(cidr))

        try:
            cursor = self.conn.execute(query, (pool_name, str(cidr)))
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            if pool_name_exists:
                raise ValueError(f"a pool of {pool_name} already exists!") from e   
            elif cidr_exists:
                raise ValueError(f"a cidr of {cidr} already exists!") from e 
            else:
                raise ValueError(f"{e}") from e

        last_row_id = cursor.lastrowid
        assert last_row_id is not None
        return last_row_id

    def add_allocation(self, pool_id: int, subnet: IPv4Network, vlan_id: Optional[int], desc: str) -> int:
        """Save a subnet allocated from a pool and commit it.

        This method trusts its subnet. The schema only rejects the same
        subnet twice in the same pool: it accepts subnets that overlap an
        existing allocation, and subnets outside the pool's CIDR. Callers must
        pass a subnet the allocator has already handed out for this pool.

        Arguments:
            pool_id: the id of the pool the subnet came from, as returned by
                create_pool() or get_pool_id_cidr().
            subnet: the allocated subnet. It is stored as str(subnet).
            vlan_id: the VLAN the subnet is assigned to (1 to 4094), or None
                if it has no VLAN.
            desc: what the subnet is used for. Use "" for no description; the
                column does not accept None.

        Returns:
            The new allocation's id.

        Raises:
            ValueError: if the subnet is already allocated in this pool, or
                the insert breaks another constraint (a pool id that doesn't
                exist, a VLAN out of range, or a None description). Those
                should be caught by the CLI first, so they get a generic
                message, with the SQLite error chained for debugging.
        """

        query = "INSERT INTO allocations (pool_id, subnet, vlan_id, description) VALUES (?, ?, ?, ?)"

        try:
            cursor = self.conn.execute(query, (pool_id, str(subnet), vlan_id, desc))
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            if e.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE":
                raise ValueError(f"a subnet of {subnet} already exists!") from e
            else:
                raise ValueError("adding allocation failed!") from e

        last_row_id = cursor.lastrowid
        assert last_row_id is not None
        return last_row_id

    def remove_allocation(self, pool_id: int, subnet: IPv4Network) -> None:
        query = "DELETE FROM allocations WHERE pool_id = ? AND subnet = ?"

        cursor = self.conn.execute(query, (pool_id, str(subnet)))
        self.conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"{subnet} is not allocated in this pool!")

    def get_allocations_db(self, pool_id: int) -> list[dict]:
        query = """
            SELECT subnet, vlan_id, description, created_at
            FROM allocations
            WHERE pool_id = ?;
        """

        cursor = self.conn.execute(query, (pool_id,))
        rows = cursor.fetchall()

        allocations = [
            {
                "subnet": IPv4Network(row[0]),
                "vlan_id": row[1],
                "description": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]

        return sorted(allocations, key=lambda allocation: allocation["subnet"])