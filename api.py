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

    if (
        State[1].chainflip_height < chainflip_height
        or State[1].ethereum_height < ethereum_height
    ):
        raise InvalidBlockHeight()

    pending_stakes = 0
    for stake in Stake.select().where(
        Stake.address == address,
        Stake.initiated_height <= ethereum_height,
        Stake.completed_height >= chainflip_height,
    ):
        pending_stakes += stake.amount

    completed_stakes = 0
    for stake in Stake.select().where(
        Stake.address == address,
        Stake.initiated_height <= ethereum_height,
        Stake.completed_height <= chainflip_height,
    ):
        completed_stakes += stake.amount

    uncompleted_stakes = 0
    for stake in Stake.select().where(
        Stake.address == address,
        Stake.initiated_height > ethereum_height,
        Stake.completed_height <= chainflip_height,
    ):
        uncompleted_stakes += stake.amount

    pending_claims = 0
    for claim in Claim.select().where(
        Claim.node == address,
        Claim.initiated_height <= chainflip_height,
        Claim.completed_height >= ethereum_height,
    ):
        pending_claims += claim.amount

    completed_claims = 0
    for claim in Claim.select().where(
        Claim.node == address,
        Claim.initiated_height <= chainflip_height,
        Claim.completed_height <= ethereum_height,
    ):
        completed_claims += claim.amount

    uncompleted_claims = 0
    for claim in Claim.select().where(
        Claim.node == address,
        Claim.initiated_height > chainflip_height,
        Claim.completed_height <= ethereum_height,
    ):
        uncompleted_claims += claim.amount

    block_hash = indexer.chainflip.get_block_hash(chainflip_height)
    validator_balance = indexer.chainflip.query(
        module="Flip",
        storage_function="Account",
        block_hash=block_hash,
        params=[address],
    )["stake"]

    staked_amount = (
        pending_stakes + completed_stakes - completed_claims - pending_claims
    )
    rewards = (
        float(str(validator_balance))
        - staked_amount
        - uncompleted_stakes
        + uncompleted_claims
    )

    r = {
        "address": address,
        "staked_balance": decimal.Decimal(staked_amount),
        "rewards": decimal.Decimal(rewards),
    }

    return r


# get state of database
@api_v1.method()
def get_state() -> dict:
    return {
        "ethereum_height": State[1].ethereum_height,
        "chainflip_height": State[1].chainflip_height,
    }


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
