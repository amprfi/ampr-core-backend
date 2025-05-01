from dotenv import load_dotenv
load_dotenv()
import os

from llama_index.llms.mistralai import MistralAI
from llama_index.core.agent.workflow import AgentWorkflow
from llama_index.readers.minio import MinioReader

llm = MistralAI(model="mistral-medium")

loader = MinioReader(
    bucket="education-defi-kraken",
    minio_endpoint=os.getenv("MINIO_URL"),
    minio_secure=True,
    minio_cert_check=True,
    minio_access_key=os.getenv("MINIO_USERNAME"),
    minio_secret_key=os.getenv("MINIO_PASSWORD"),
)
documents = loader.load_data()

# Print document information
print(f"Successfully loaded {len(documents)} documents from MinIO")
for i, doc in enumerate(documents):
    print(f"Document {i+1}:")
    print(f"  ID: {doc.doc_id}")
    
    # Print metadata values if available
    if hasattr(doc, 'metadata') and doc.metadata:
        # Print file name (the key is 'file_name', not 'filename')
        if 'file_name' in doc.metadata:
            print(f"  File name: {doc.metadata['file_name']}")
        
        # Print file type
        if 'file_type' in doc.metadata:
            print(f"  File type: {doc.metadata['file_type']}")
            
        # Print file size
        if 'file_size' in doc.metadata:
            print(f"  File size: {doc.metadata['file_size']}")
            
        # Print last modified date
        if 'last_modified_date' in doc.metadata:
            print(f"  Last modified: {doc.metadata['last_modified_date']}")
    
    print("  " + "-"*40)
