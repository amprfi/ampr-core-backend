import os
import stytch
from dotenv import load_dotenv

load_dotenv()

stytch_client = stytch.Client(
    project_id=os.environ["STYTCH_PROJECT_ID"],
    secret=os.environ["STYTCH_SECRET"],
    environment=os.environ.get("STYTCH_ENV", "test"),
)