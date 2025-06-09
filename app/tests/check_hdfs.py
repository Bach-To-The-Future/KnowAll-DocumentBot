from hdfs import InsecureClient
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to HDFS
HDFS_URL = os.getenv("HDFS_URL")
HDFS_USER = os.getenv("HDFS_USER", "hdfs")
client = InsecureClient(HDFS_URL, user=HDFS_USER)

def list_hdfs_directory(path="/", show_preview=False, max_preview_lines=5):
    try:
        print(f"\n📁 Contents of HDFS path: {path}")
        files = client.list(path, status=True)
        for fname, meta in files.items():
            fpath = os.path.join(path, fname)
            ftype = '📂 DIR' if meta['type'] == 'DIRECTORY' else '📄 FILE'
            size = meta.get("length", "-")
            print(f"  {ftype:7} | {fpath} | size: {size} bytes")

            # Show file preview
            if show_preview and meta['type'] != 'DIRECTORY':
                print("    └─ Preview:")
                with client.read(fpath, encoding='utf-8') as reader:
                    for i, line in enumerate(reader):
                        if i >= max_preview_lines:
                            break
                        print(f"       {line.strip()}")

    except Exception as e:
        print(f"❌ Error accessing {path}: {e}")

# Example usage
if __name__ == "__main__":
    list_hdfs_directory(path="/data", show_preview=True)
