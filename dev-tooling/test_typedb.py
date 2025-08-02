import os
from typedb.driver import TypeDB, Credentials, TransactionType
from dotenv import load_dotenv

load_dotenv()

# TypeDB configuration
address = os.environ.get("TYPEDB_ADDRESS", "localhost:1729")
database = os.environ.get("TYPEDB_DATABASE", "ampr-core")
username = os.environ.get("TYPEDB_USERNAME", "admin")
password = os.environ.get("TYPEDB_PASSWORD", "password")

try:
    # Create credentials
    credentials = Credentials(username, password)

    # Create driver options
    from typedb.driver import DriverOptions
    options = DriverOptions()

    # Initialize driver
    with TypeDB.driver(address, credentials, options) as driver:
        print("Driver created successfully")

        # Check if database exists
        databases = driver.databases.all()
        if database in databases:
            print(f"Database '{database}' exists")

            # Try to open a transaction
            with driver.transaction(database, TransactionType.READ) as transaction:
                print("Transaction opened successfully")
                print("Database connection test passed!")
        else:
            print(f"Database '{database}' does not exist")
            print("Available databases:", databases)

except Exception as e:
    print(f"Error: {e}")