"""Dropping the throwaway Cosmos databases the integration tests create (D27).

Since 2026-11-21 the vNext emulator (same digest as before) answers some DELETEs of a database that held containers
with 500 "Database query failed: PostgresError(SqlState(E58P01))", on CI runners, after every check in the test
has passed. The cleanup is not what the tests test, and the emulator lives only as long as the job, so a database
that will not drop is retried, then reported as a warning instead of an error. Any other failure still fails.
"""

import time
import warnings

from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError


def drop_database(client, name: str, *, attempts: int = 3, wait: float = 2.0) -> bool:
    """Delete a database; True when it is gone. Emulator 500s are retried, then warned about (never raised)."""
    for attempt in range(1, attempts + 1):
        try:
            client.delete_database(name)
            return True
        except CosmosResourceNotFoundError:
            return True
        except CosmosHttpResponseError as exc:
            if exc.status_code != 500:
                raise
            if attempt == attempts:
                first_line = (str(exc).splitlines() or ["no message"])[0]
                warnings.warn(f"emulator did not drop {name} after {attempts} attempts: {first_line}", stacklevel=2)
                return False
            time.sleep(wait)
    return False
