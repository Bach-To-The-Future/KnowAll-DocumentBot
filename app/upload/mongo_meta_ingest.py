from pymongo import MongoClient, UpdateOne
import logging
from datetime import datetime
import os
from minio import Minio

from config import Config

logging.basicConfig(level=logging.INFO)
config = Config()

ENDPOINT = config.MINIO_ENDPOINT
ACCESS_KEY = config.MINIO_ACCESS_KEY
SECRET_KEY = config.MINIO_SECRET_KEY
BUCKET_NAME = config.MINIO_BUCKET

MONGODB_URI = config.MONGO_URI
MONGO_DB = config.MONGO_DB
MONGO_COLLECTION = config.MONGO_COLLECTION

class Mongo_meta:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGO_DB]
        self.collection = self.db[MONGO_COLLECTION]
        self.minio_client = Minio(
            ENDPOINT,
            access_key = ACCESS_KEY,
            secret_key = SECRET_KEY,
            secure = False
        )

    def ingest_metadata(self, file_keys: list[str]):
        """
        Ingests or updates metadata for given MinIO file keys into MongoDB.
        Performs CDC tracking using object_key + etag.
        """
        operations = []

        for key in file_keys:
            stat = self.minio_client.stat_object(BUCKET_NAME, key)

            metadata = {
                "file_name": os.path.basename(key),
                "object_key": key,
                "path": f"s3://{BUCKET_NAME}/{key}",
                "size": stat.size,
                "file_type": os.path.splitext(key)[-1][1:].lower(),
                "last_modified": stat.last_modified,
                "etag": stat.etag,
                "bucket": BUCKET_NAME,
                "ingested_at": datetime.utcnow()
            }

            operations.append(UpdateOne(
                {"object_key": key, "etag": stat.etag},
                {"$set": metadata},
                upsert=True
            ))
            logging.info(f"[mongo] Metadata added: {metadata["file_name"]}")

        if operations:
            result = self.collection.bulk_write(operations)
            logging.info(f"[mongo] Upserts: {result.upserted_count}, Modified: {result.modified_count}")