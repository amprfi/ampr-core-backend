from dotenv import load_dotenv
load_dotenv()

from llama_index.llms.mistralai import MistralAI
from llama_index.core.agent.workflow import AgentWorkflow

llm = MistralAI(model="mistral-medium")

