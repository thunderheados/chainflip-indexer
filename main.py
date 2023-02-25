from indexer import Indexer
from multiprocessing import Process
from api import start
import json
import time


def main(config_path: str):
    config = json.loads(open(config_path).read())

    indexer = Indexer(**config)
    sync = Process(target=indexer.start, args=())
    sync.start()

    api = Process(target=start, args=(indexer, 3000,))
    api.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sync.terminate()
        api.terminate()
        sync.join()
        api.join()


if __name__ == "__main__":
    main("./config.json")
