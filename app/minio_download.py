from minio import Minio
import os
from dotenv import load_dotenv

load_dotenv()

client = Minio(
    endpoint = os.getenv("MINIO_ENDPOINT"),
    access_key = os.getenv("ACCESS_KEY"),
    secret_key = os.getenv("SECRET_KEY"),
    secure = False
)

def download_file(bucket_name:str = os.getenv("BUCKET_NAME"), object_name:str = "", download_folder:str = "./downloads"):
    '''
        Download files from MinIO to local for ingestion into vector DB and model
        Files will be in separate folders based on format
    '''
    ext = os.path.splitext(object_name)[-1][1:].lower()
    dest_folder = os.path.join(download_folder, ext)
    os.makedirs(dest_folder, exist_ok=True)

    filename = os.path.basename(object_name)
    dest_path = os.path.join(dest_folder, filename)

    client.fget_object(bucket_name, object_name, dest_path)
    return dest_path
