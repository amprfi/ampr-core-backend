from dotenv import load_dotenv
load_dotenv()
import os
import time

# LLM setup
from llama_index.llms.mistralai import MistralAI

# Web loading - using multiple readers for different sites
from llama_index.readers.web import TrafilaturaWebReader, BeautifulSoupWebReader

# Text processing
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.extractors import TitleExtractor, KeywordExtractor

# Initialize LLM for keyword extraction
llm = MistralAI(model="mistral-medium")

print("Step 1: Loading documents from websites...")
# Separate URLs by domain for different readers
lancedb_urls = [
    "https://docs.lancedb.com/core/ingestion",
    "https://docs.lancedb.com/core"
]

llamaindex_urls = [
    "https://docs.llamaindex.ai/en/stable/understanding/loading/loading/",
    "https://docs.llamaindex.ai/en/stable/understanding/indexing/indexing/",
    "https://docs.llamaindex.ai/en/stable/understanding/storing/storing/"
]

# Load LanceDB pages with BeautifulSoupWebReader (better for these sites)
print("Loading LanceDB documentation...")
bs_loader = BeautifulSoupWebReader()
lancedb_docs = bs_loader.load_data(urls=lancedb_urls)

# Load LlamaIndex pages with TrafilaturaWebReader
print("Loading LlamaIndex documentation...")
trafilatura_loader = TrafilaturaWebReader()
llamaindex_docs = trafilatura_loader.load_data(
    urls=llamaindex_urls,
    output_format="markdown",  # Get markdown format for better structure
    include_comments=False,    # Exclude comments
    include_tables=True,       # Include tables
    include_links=True,        # Include links
    show_progress=True         # Show progress bar
)

# Combine documents
documents = lancedb_docs + llamaindex_docs
print(f"Successfully loaded {len(documents)} documents from websites")

# Print document information
for i, doc in enumerate(documents):
    print(f"\nDocument {i+1}:")
    print(f"  ID: {doc.doc_id}")
    
    # Print metadata values if available
    if hasattr(doc, 'metadata') and doc.metadata:
        if 'url' in doc.metadata:
            print(f"  URL: {doc.metadata['url']}")
        if 'title' in doc.metadata:
            print(f"  Title: {doc.metadata['title']}")
    
    # Print content length
    print(f"  Content length: {len(doc.text)} characters")
    print("  " + "-"*40)

print("\nStep 2: Processing web documents...")
# Initialize text splitter
text_splitter = SentenceSplitter(
    chunk_size=1000,
    chunk_overlap=200
)

# Process documents into nodes
start_time = time.time()
nodes = text_splitter.get_nodes_from_documents(documents)
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
    
    # Extract title - wrap node in a list for process_nodes
    node_with_title = title_extractor.process_nodes([node])[0]  # Get first item from result
    
    # Extract keywords - wrap node in a list for process_nodes
    enhanced_node = keyword_extractor.process_nodes([node_with_title])[0]  # Get first item from result
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
print("Website processing complete with title and keyword extraction!")
