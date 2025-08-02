import os
from typedb.driver import TypeDB, TransactionType, Credentials, DriverOptions
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

class TypeDBClient:
    def __init__(self):
        self.address = os.environ.get("TYPEDB_ADDRESS", "localhost:1729")
        self.database = os.environ.get("TYPEDB_DATABASE", "default")
        self.username = os.environ.get("TYPEDB_USERNAME", "admin")
        self.password = os.environ.get("TYPEDB_PASSWORD", "password")
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            # For TypeDB 3.x with credentials and options
            credentials = Credentials(self.username, self.password)
            # Create DriverOptions - for local connection, TLS is typically disabled
            driver_options = DriverOptions(False, None)
            self._driver = TypeDB.driver(self.address, credentials, driver_options)
        return self._driver

    @contextmanager
    def transaction(self, transaction_type: TransactionType = TransactionType.WRITE):
        """Context manager for TypeDB transactions using TypeDB 3.x API"""
        transaction = None
        try:
            # Create transaction directly from driver (TypeDB 3.x pattern)
            transaction = self.driver.transaction(self.database, transaction_type)
            yield transaction
            if transaction_type == TransactionType.WRITE:
                transaction.commit()
        except Exception as e:
            if transaction:
                try:
                    transaction.close()
                except:
                    pass
            raise e
        finally:
            if transaction:
                try:
                    transaction.close()
                except:
                    pass

    def close(self):
        """Close the TypeDB driver connection"""
        if self._driver:
            self._driver.close()
            self._driver = None

# Global TypeDB client instance
typedb_client = TypeDBClient()
