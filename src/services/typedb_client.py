import os
from typedb.driver import TypeDB, TransactionType, Credentials
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

class TypeDBClient:
    def __init__(self):
        self.address = os.environ.get("TYPEDB_ADDRESS", "localhost:1729")
        self.database = os.environ.get("TYPEDB_DATABASE", "ampr-core")
        self.username = os.environ.get("TYPEDB_USERNAME", "admin")
        self.password = os.environ.get("TYPEDB_PASSWORD", "password")
        self._driver = None
    
    @property
    def driver(self):
        if self._driver is None:
            credentials = Credentials(self.username, self.password)
            self._driver = TypeDB.driver(self.address, credentials)
        return self._driver
    
    @contextmanager
    def session(self, session_type: str = "data"):
        """Context manager for TypeDB sessions"""
        session = self.driver.session(self.database, session_type)
        try:
            yield session
        finally:
            session.close()
    
    @contextmanager
    def transaction(self, session, transaction_type: TransactionType = TransactionType.WRITE):
        """Context manager for TypeDB transactions"""
        transaction = session.transaction(transaction_type)
        try:
            yield transaction
            if transaction_type == TransactionType.WRITE:
                transaction.commit()
        except Exception as e:
            transaction.close()
            raise e
        finally:
            if not transaction.is_open():
                transaction.close()
    
    def close(self):
        """Close the TypeDB driver connection"""
        if self._driver:
            self._driver.close()
            self._driver = None

# Global TypeDB client instance
typedb_client = TypeDBClient()
