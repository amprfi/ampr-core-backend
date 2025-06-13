from dotenv import load_dotenv
load_dotenv()
import os
import time

# MinIO document loading
from llama_index.llms.mistralai import MistralAI
from llama_index.readers.minio import MinioReader

# PDF processing
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.extractors import TitleExtractor, KeywordExtractor

# Initialize LLM for keyword extraction
llm = MistralAI(model="mistral-medium")

print("Step 1: Loading documents from MinIO...")
loader = MinioReader(
    bucket="education-defi-kraken",
    minio_endpoint=os.getenv("MINIO_URL"),
    minio_secure=True,
    minio_cert_check=True,
    minio_access_key=os.getenv("MINIO_USERNAME"),
    minio_secret_key=os.getenv("MINIO_PASSWORD"),
)
documents = loader.load_data()
print(f"Successfully loaded {len(documents)} documents from MinIO")

# Print document information
for i, doc in enumerate(documents):
    print(f"\nDocument {i+1}:")
    print(f"  ID: {doc.doc_id}")
    
    # Print metadata values if available
    if hasattr(doc, 'metadata') and doc.metadata:
        # Print file name
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
    
    # Print content length
    print(f"  Content length: {len(doc.text)} characters")
    print("  " + "-"*40)

print("\nStep 2: Processing PDF documents...")
# Initialize PDF parser with layout-aware chunking
pdf_parser = SentenceSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    visual_hierarchy=True
)

# Process documents into nodes
start_time = time.time()
nodes = pdf_parser.get_nodes_from_documents(documents)
processing_time = time.time() - start_time
print(f"Processed {len(documents)} documents into {len(nodes)} nodes in {processing_time:.2f} seconds")

# Print sample nodes
print("\nSample nodes after chunking:")
for i, node in enumerate(nodes[:3]):  # Print first 3 nodes
    print(f"\nNode {i+1}:")
    print(f"  ID: {node.node_id}")
    print(f"  Content preview: {node.text[:150]}...")
    if hasattr(node, 'metadata') and node.metadata:
        print(f"  Metadata: {node.metadata}")
    print("  " + "-"*40)

print("\nStep 3: Extracting titles and keywords...")
# Initialize extractors
title_extractor = TitleExtractor(nodes=5, llm=llm)  # Use top 5 nodes for context
keyword_extractor = KeywordExtractor(
    keywords=5,  # Extract 5 keywords per node
    llm=llm
)

# Process nodes with extractors
enhanced_nodes = []
for i, node in enumerate(nodes):
    print(f"\rEnhancing node {i+1}/{len(nodes)}...", end="")
    
    # Extract title
    node_with_title = title_extractor.process_nodes(node)
    
    # Extract keywords
    enhanced_node = keyword_extractor.process_nodes(node_with_title)
    enhanced_nodes.append(enhanced_node)
print("\nEnhancement complete!")

# Print sample enhanced nodes
print("\nSample nodes after enhancement:")
for i, node in enumerate(enhanced_nodes[:5]):  # Print first 5 enhanced nodes
    print(f"\nEnhanced Node {i+1}:")
    print(f"  ID: {node.node_id}")
    
    # Print extracted title if available
    if 'title' in node.metadata:
        print(f"  Title: {node.metadata['title']}")
    
    # Print extracted keywords if available
    if 'keywords' in node.metadata:
        print(f"  Keywords: {node.metadata['keywords']}")
    
    # Print content preview
    print(f"  Content preview: {node.text[:100]}...")
    print("  " + "-"*40)

print(f"\nSummary: Processed {len(documents)} documents into {len(enhanced_nodes)} enhanced nodes")
print("PDF processing complete with title and keyword extraction!")
