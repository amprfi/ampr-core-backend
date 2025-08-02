import os
import asyncio
from typedb.driver import TypeDB, Credentials, TransactionType
from dotenv import load_dotenv

load_dotenv()

# TypeDB configuration
address = os.environ.get("TYPEDB_ADDRESS", "localhost:1729")
database = os.environ.get("TYPEDB_DATABASE", "default")
username = os.environ.get("TYPEDB_USERNAME", "admin")
password = os.environ.get("TYPEDB_PASSWORD", "password")

async def main():
    try:
        # Create credentials
        credentials = Credentials(username, password)

        # Create driver options
        from typedb.driver import DriverOptions
        options = DriverOptions()

        # Initialize driver
        with TypeDB.driver(address, credentials, options) as driver:
            print("Driver created successfully")

            # Try to open a transaction
            with driver.transaction(database, TransactionType.WRITE) as transaction:
                print("Transaction opened successfully")

                # Try to execute a query and get the result
                query = "match $x isa user; get $x;"
                try:
                    # Execute query and get promise
                    promise = transaction.query(query)
                    print("Query executed, got promise:", type(promise))

                    # List available methods on promise
                    promise_methods = [method for method in dir(promise) if not method.startswith('_')]
                    print("Available methods on promise:", promise_methods)

                    # Try to get the result from the promise
                    result = await promise
                    print("Got result from promise:", type(result))
                    print("Result:", result)
                except Exception as e:
                    print(f"Query execution error: {e}")

    except Exception as e:
        print(f"Error: {e}")

# Run the async main function
asyncio.run(main())