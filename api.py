from models import *
import fastapi_jsonrpc as jsonrpc
import uvicorn
import time
import contextlib
import json

indexer = None
api_v1 = jsonrpc.Entrypoint("/api/v1/jsonrpc")

class InvalidBlockHeight(jsonrpc.BaseError):
    CODE = -32001
    MESSAGE = "invalid block height"

@api_v1.method(errors=[InvalidBlockHeight])
def get_balance(address: str, ethereum_height: int, chainflip_height: int) -> dict:
    if indexer.state.chainflip_height < chainflip_height or indexer.state.ethereum_height < ethereum_height:
        raise InvalidBlockHeight() 


    block_hash = indexer.chainflip.get_block_hash(chainflip_height)
    validator_balance = indexer.chainflip.query({"module": "Flip", "storage_function": "Account", "block_hash": block_hash, "params": [address]})['stake']

    stakes = Stake.select().where(Stake.address==address, Stake.initiated_height <= ethereum_height, Stake.completed_height >= chainflip_height) # pending stakes
    # TODo: incoroporate claims and claimexpired.

    staked_amount = 0
    for stake in stakes:
        staked_amount += stake.amount

    r = {"address": address, "staked_balance": staked_amount, "rewards": float(str(validator_balance))-staked_amount}

    return r

# get state of database
@api_v1.method()
def get_state() -> dict:
    return {"ethereum_height": indexer.state.ethereum_height, "chainflip_height": indexer.state.chainflip_height}


class Server(uvicorn.Server):
    def install_signal_handlers(self):
        pass

    @contextlib.contextmanager
    def run_in_thread(self):
        thread = threading.Thread(target=self.run)
        thread.start()
        try:
            while not self.started:
                time.sleep(1e-3)
            yield
        finally:
            self.should_exit = True
            thread.join()

def start(indexer_, port):
    global indexer
    indexer = indexer_

    app = jsonrpc.API()
    app.bind_entrypoint(api_v1)
    
    server = Server(uvicorn.Config(app, host="0.0.0.0", port=port, debug=True))
    server.run()

    while server.run_in_thread():
        time.sleep(2)

    
