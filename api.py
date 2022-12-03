from models import *
import fastapi_jsonrpc as jsonrpc
import uvicorn
import time
import contextlib
import json
import decimal

decimal.getcontext().prec = 64

indexer = None
api_v1 = jsonrpc.Entrypoint("/api/v1/jsonrpc")

class InvalidBlockHeight(jsonrpc.BaseError):
    CODE = -32001
    MESSAGE = "invalid block height"

@api_v1.method(errors=[InvalidBlockHeight])
def get_balance(address: str, ethereum_height: int, chainflip_height: int) -> dict:
    if ethereum_height == 0:
        ethereum_height = State[1].ethereum_height
    if chainflip_height == 0:
        chainflip_height = State[1].chainflip_height

    if State[1].chainflip_height < chainflip_height or State[1].ethereum_height < ethereum_height:
        raise InvalidBlockHeight() 

    pending = 0
    pending_stakes = Stake.select().where(Stake.address==address, Stake.initiated_height<=ethereum_height, Stake.completed_height >= chainflip_height)
    for stake in pending_stakes:
        pending += stake.amount

    completed = 0
    completed_stakes = Stake.select().where(Stake.address==address, Stake.initiated_height <= ethereum_height, Stake.completed_height <= chainflip_height)
    for stake in completed_stakes:
        completed += stake.amount

    uncompleted = 0
    uncompleted_stakes = Stake.select().where(Stake.address==address, Stake.initiated_height > ethereum_height, Stake.completed_height <= chainflip_height)
    for stake in uncompleted_stakes:
        uncompleted += stake.amount

    block_hash = indexer.chainflip.get_block_hash(chainflip_height)
    validator_balance = indexer.chainflip.query(module="Flip", storage_function="Account", block_hash=block_hash, params=[address])['stake']

    staked_amount = pending + completed
    rewards = float(str(validator_balance))- staked_amount - uncompleted

    r = {"address": address, "staked_balance": decimal.Decimal(staked_amount), "rewards": decimal.Decimal(rewards)}

    return r

# get state of database
@api_v1.method()
def get_state() -> dict:
    return {"ethereum_height": State[1].ethereum_height, "chainflip_height": State[1].chainflip_height}


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

    

