# run_syncer.py
from data.syncer import DataSyncer

if __name__ == "__main__":
    service = DataSyncer()
    service.run()