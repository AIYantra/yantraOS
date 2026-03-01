import os
from pinecone import Pinecone, ServerlessSpec

def setup_index():
    api_key = os.environ.get("PINECONE_API_KEY")
    if not api_key:
        print("PINECONE_API_KEY environment variable not found.")
        # Try to read from yantraos-web-hud local env if needed
        import dotenv
        dotenv.load_dotenv("c:/Users/AdLoa/Documents/yantraos-web-hud/.env.local")
        api_key = os.environ.get("PINECONE_API_KEY")
        
    if not api_key:
        print("Please provide PINECONE_API_KEY")
        return

    pc = Pinecone(api_key=api_key)
    index_name = "yantra-skills"

    existing_indexes = [idx.name for idx in pc.list_indexes()]
    if index_name not in existing_indexes:
        print(f"Creating index '{index_name}'...")
        pc.create_index(
            name=index_name,
            dimension=1536, # Openai text-embedding-3-small
            metric="cosine",
            spec=ServerlessSpec(
                cloud="aws",
                region="us-east-1"
            )
        )
        print("Index created successfully.")
    else:
        print(f"Index '{index_name}' already exists.")

if __name__ == "__main__":
    setup_index()
