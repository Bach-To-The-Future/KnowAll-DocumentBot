from pymongo import MongoClient
from pprint import pprint
import os

from app.config import Config

config = Config()

client = MongoClient(config.MONGO_URI)
db = client[config.MONGO_DB]
collection = db[config.MONGO_COLLECTION]

for doc in collection.find():
    pprint(doc)
