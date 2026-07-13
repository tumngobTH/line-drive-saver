import os

os.environ.setdefault("LINE_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/fake-sa.json")
os.environ.setdefault("SHARED_DRIVE_ID", "0Atest")
os.environ.setdefault("ROOT_FOLDER_ID", "1roottest")
