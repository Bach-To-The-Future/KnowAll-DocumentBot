import os
import io
import json
import logging
import hashlib
from typing import Union, List
from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .mongo_meta_ingest import Mongo_meta
from app.config import Config

config = Config()
mongo_meta = Mongo_meta()
load_dotenv()
logging.basicConfig(level=logging.INFO)

ENDPOINT = os.getenv("MINIO_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")


class Minio_localdisk:
    def __init__(self, endpoint:str, access_key:str, secret_key:str, bucket_name:str, use_ssl:bool=False):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.use_ssl = use_ssl
    
        self.client = None
        self.method = None
        self._connect()

    def _connect(self):
        '''
            Establish connection to MinIO - using MinIO SDK first, if failed then Boto3
        '''
        # Connect using MinIO SDK first
        try:
            client = Minio(
                self.endpoint,
                access_key = self.access_key,
                secret_key = self.secret_key,
                secure = self.use_ssl
            )

            # Ensure bucket exists - if not then create bucket
            if not client.bucket_exists(self.bucket_name):
                logging.info(f"[MinIO SDK] Bucket '{self.bucket_name}' does not exist - Creating")
                client.make_bucket(self.bucket_name)
            else:
                logging.info(f"[MinIO SDK] Bucket '{self.bucket_name}' exists")
            self.client = client
            self.method = "minio"
            return
        except S3Error as e:
            logging.warning(f"[MinIO SDK] Failed: {e}")
        
        # Then use Boto3
        try:
            session = boto3.session.Session()
            client = session.client(
                service_name = "s3",
                endpoint_url = f"http{'s' if self.use_ssl else ''}://{self.endpoint}",
                aws_access_key_id = self.access_key,
                aws_secret_access_key = self.secret_key,
            )

            try:
                client.head_bucket(Bucket = self.bucket_name)
                logging.info(f"[Boto3] Bucket '{self.bucket_name}' exists")
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    logging.info(f"[Boto3] Bucket '{self.bucket_name}' does not exist - Creating")
                    client.create_bucket(Bucket = self.bucket_name)
                else:
                    raise
            self.client = client
            self.method = "boto3"
        except (BotoCoreError, ClientError) as e:
            logging.info(f"[Boto3] Failed to connect: {e}")
            raise RuntimeError("Failed to connect using both MinIO SDK and Boto3")

    def list_files(self):
        '''
            List all the files in the MinIO Bucket
        '''
        if self.method == "minio":
            for obj in self.client.list_objects(self.bucket_name, recursive=True):
                print(f"[MinIO SDK] {obj.object_name}")
        elif self.method == "boto3":
            response = self.client.list_objects_v2(Bucket=self.bucket_name)
            for obj in response.get("Contents", []):
                print(f"[Boto3] {obj['Key']}")
    

    def upload_files(self, file_paths:Union[str, List[str]]):
        '''
            Upload one or multiple files from local to MinIO bucket
        '''
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        created_paths = set()
        uploaded_info = []

        for file_path in file_paths:
            if not os.path.isfile(file_path):
                logging.warning(f"Skipping non-existent file: {file_path}")
                continue

            file_name = os.path.basename(file_path) # Get filename
            ext = os.path.splitext(file_name)[-1][1:].lower() # Get extension lowered-case
            # ext = file_name.split(".")[-1].lower() 
            if not ext:
                logging.warning(f"Skipping file without extension: {file_name}")
                continue

            # Check if file is a supported file format
            if ext in config.EXTENSIONS:
                # Add a .keep file to ensure existence
                marker_key = f"{ext}/.keep"
                # Check suitable extension path and create them if not exists
                if ext not in created_paths:
                    try:
                        if self.method == "minio":
                            self.client.stat_object(self.bucket_name, marker_key)
                        elif self.method == "boto3":
                            self.client.head_object(Bucket=self.bucket_name, Key=marker_key)
                    except (S3Error, ClientError):
                        if self.method == "minio":
                            self.client.put_object(self.bucket_name, marker_key, data=io.BytesIO(b''), length=0)
                        elif self.method == "boto3":
                            self.client.put_object(Bucket=self.bucket_name, Key=marker_key, Body=b'')
                        logging.info(f"[{self.method}] Created folder path with marker: {marker_key}")
                    created_paths.add(ext)

                object_name = f"{ext}/{file_name}"
                
                # Upload file
                if self.method == "minio":
                    self.client.fput_object(self.bucket_name, object_name, file_path)   
                elif self.method == "boto3":
                    with open(file_path, "rb") as f:
                        self.client.upload_fileobj(f, self.bucket_name, object_name)

                logging.info(f"[{self.method}] Uploaded: {object_name}")
                uploaded_info.append({
                    "filename": file_name,
                    "bucket": self.bucket_name,
                    "key": object_name,
                    "status": "uploaded"
                })
            else:
                logging.info(f"File format is not supported {file_name}")

        if uploaded_info:
            mongo_meta.ingest_metadata(file_keys=[item["key"] for item in uploaded_info])
        return uploaded_info

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    connector = Minio_localdisk(
        endpoint=ENDPOINT,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        bucket_name=BUCKET_NAME
    )

    connector.list_files()
    connector.upload_files([
        "./documents/error.txt",
        "./documents/PHIẾU ĐÁNH GIÁ THỰC TẬP HUST_DatND48.docx",
        "./documents/PHIẾU ĐÁNH GIÁ THỰC TẬP HUST_HoangNH155.docx",
        "./documents/Internship_confirmation_request (1).pdf"
    ])

