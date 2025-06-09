import os
import io
import logging
import pandas as pd
from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
import boto3
from botocore.exceptions import ClientError
from hdfs import InsecureClient

from mongo_meta_ingest import Mongo_meta

load_dotenv()
logging.basicConfig(level=logging.INFO)

ENDPOINT = os.getenv("MINIO_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")
HDFS_URL = os.getenv("HDFS_URL")
HDFS_USER = os.getenv("HDFS_USER")
HDFS_MINIO_METADATA = os.getenv("HDFS_MINIO_METADATA")

class MinIO_HDFS_Ingest:
    def __init__(self, hdfs_url:str, hdfs_metadata:str, minio_config):
        self.hdfs_client = InsecureClient(hdfs_url)
        self.hdfs_metadata = hdfs_metadata

        self.endpoint = minio_config["endpoint"]
        self.access_key = minio_config["access_key"]
        self.secret_key = minio_config["secret_key"]
        self.bucket_name = minio_config["bucket_name"]
        self.use_ssl = minio_config.get("use_ssl", False)

        self.method = None
        self.client = None
        self._connect() # Connect to MinIO
        self.metadata_df = self._load_metadata() # Load metadata of MinIO - for CDC

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
            # List existing buckets
            client.list_buckets()
            self.client = client
            self.method = "minio"
            logging.info("[MinIO SDK] Connected successfully.")
            return
        except Exception as e:
            logging.warning(f"[MinIO SDK] Failed: {e}")
        
        # Then use Boto3
        if not self.client:
            try:
                session = boto3.session.Session()
                client = session.client(
                    "s3",
                    endpoint_url=f"http{'s' if self.use_ssl else ''}://{self.endpoint}",
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key
                )
                client.list_buckets()
                self.client = client
                self.method = "boto3"
                logging.info("[Boto3] Connected successfully.")
            except Exception as e:
                raise RuntimeError(f"[Boto3] Connection failed: {e}")
        
    def _load_metadata(self):
        '''
            Load metadata file to track file changes from MinIO
            CSV format (file_path, etag)
        '''
        if self.hdfs_client.status(self.hdfs_metadata, strict=False):
            with self.hdfs_client.read(self.hdfs_metadata) as reader:
                return pd.read_csv(reader)
        return pd.DataFrame(columns=["file_path", "etag"])
    
    def _save_metadata(self):
        '''
            Save ingested files information to metadata file
        '''
        with self.hdfs_client.write(self.hdfs_metadata, overwrite=True, encoding="utf-8") as writer:
            self.metadata_df.to_csv(writer, index=False)
    
    def _get_objects(self):
        '''
            Get all the objects inside MinIO bucket
        '''
        if self.method == "minio":
            return list(self.client.list_objects(self.bucket_name, recursive=True))
        else: # boto3
            response = self.client.list_objects_v2(Bucket=self.bucket_name)
            objects = []
            for obj in response.get("Contents", []):
                objects.extend(obj)
            return objects
    
    def ingest(self, hdfs_base_path:str = "/documents"):
        objects = self._get_objects()
        new_metadata = []
        
        for obj in objects:
            if self.method == "minio":
                file_path, etag = obj.object_name, obj.etag
            else:
                file_path, etag = obj["Key"], obj["ETag"].strip('"')

            # Check for new/changed files
            previous = self.metadata_df[
                (self.metadata_df["file_path"] == file_path) &
                (self.metadata_df["etag"] == etag)
            ]
            if not previous.empty:
                logging.info(f"File unchanged: {file_path}")
                continue

            hdfs_path = os.path.join(hdfs_base_path, "minio", file_path)
            hdfs_dir = os.path.dirname(hdfs_path)
            self.hdfs_client.makedirs(hdfs_dir)
            logging.info(f"Ingest file: {file_path}")

            # Ingest file to HDFS
            if self.method == "minio":
                data = self.client.get_object(self.bucket_name, file_path)
                with self.hdfs_client.write(hdfs_path, overwrite=True) as writer:
                    for d in data.stream(32 * 1024):
                        writer.write(d)
            else:
                response = self.client.get_object(Bucket=self.bucket_name, Key=file_path)
                with self.hdfs_client.write(hdfs_path, overwrite=True) as writer:
                    writer.write(response["Body"].read())

            new_metadata.append({"file_path":file_path, "etag":etag})
            
        # Save metadata
        if new_metadata:
            self.metadata_df = pd.concat(
                [self.metadata_df, pd.DataFrame(new_metadata)],
                ignore_index=True, axis=0
            ).drop_duplicates(subset=["file_path"], keep="last")
            self._save_metadata()
            logging.info(f"Updated {len(new_metadata)} records")
        
if __name__ == "__main__":
    minio_config = {
        "endpoint": os.getenv("MINIO_ENDPOINT"),
        "access_key": os.getenv("ACCESS_KEY"),
        "secret_key": os.getenv("SECRET_KEY"),
        "bucket_name": os.getenv("BUCKET_NAME"),
        "use_ssl": False
    }

    minio_ingestor = MinIO_HDFS_Ingest(
        hdfs_url=HDFS_URL,
        hdfs_metadata=HDFS_MINIO_METADATA,
        minio_config=minio_config
    )

    minio_ingestor.ingest()
