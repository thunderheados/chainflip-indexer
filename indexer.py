from substrateinterface import SubstrateInterface
from models import *
from web3 import Web3
from utils import logger, get_abi 
from typing import List
from threading import Thread
from tqdm import tqdm
from retrying import retry
import json
import time

MAX_CALL_RETRIES = 5
THREADING_DELAY = 0.01

ETH_REORG_PROTECTION = 5
ETH_BLOCK_DELAY = 5

CHAINFLIP_REORG_PROTECTION = 5
CHAINFLIP_BLOCK_DELAY = 5
CHAINFLIP_BATCH_SIZE = 10

# allows threading functions to give return values.
class Request(Thread):
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs={}, Verbose=None):
        Thread.__init__(self, group, target, name, args, kwargs)
        self._return = None
    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args,
                                                **self._kwargs)
    def join(self, *args):
        Thread.join(self, *args)
        return self._return

class Indexer:
    def __init__(
        self,
        flip_staker_address: str,
        flip_staker_abi_path: str,
        node_evm: str,
        node_substrate: str):

        # create providers
        self.eth = Web3(
            Web3.HTTPProvider(node_evm)
        )

        self.chainflip = SubstrateInterface(url=node_substrate)

        self.flip_staker_contract = self.eth.eth.contract(
            address=Web3.toChecksumAddress(flip_staker_address), abi=get_abi(flip_staker_abi_path)
        )

        self.logger = logger

        self.state = State[1]

    def watch_stakes(self): # ethereum
        self.logger.info("Checking for new stakes")
        previous_height = self.state.ethereum_height
        current_height = self.eth.eth.block_number - ETH_REORG_PROTECTION
        self.logger.info("Current height: {}".format(current_height))

        self.logger.info("Getting stakes between {} and {}".format(previous_height, current_height))

        if current_height - previous_height < ETH_BLOCK_DELAY:
            return

        event_filter = self.flip_staker_contract.events.Staked.createFilter(
            fromBlock=hex(previous_height),
            toBlock=hex(current_height)
        )

        stakes = event_filter.get_all_entries()
        self.logger.info("A total of {} stake events found between {} and {}".format(len(stakes), previous_height, current_height))

        id = Stake.select().order_by(Stake.id.desc()).get().id
        bulk_stakes = []
        for stake in tqdm(stakes):
            address = self.chainflip.ss58_encode(stake["args"]["nodeID"].hex())
            s = Stake.select().where(Stake.hash==stake["transactionHash"].hex())
            
            if s == None:
                id += 1
                bulk_stakes.append(Stake(id=id, hash = stake["transactionHash"].hex(), amount = stake["args"]["amount"], initiated_height = stake["blockNumber"], address=address))
            else:
                self.logger.info("Watch Stakes is behind confirmations, modifying {} stake".format(stake["transactionHash"].hex()))
                s.initiated_height=stake["blockNumber"]
                s.save()


        self.logger.info("Paired up all stakes, inserting...")
        Stake.bulk_create(bulk_stakes, batch_size=250)
        self.state.ethereum_height = current_height + 1
        self.state.save()


    @retry(stop_max_attempt_number=MAX_CALL_RETRIES)
    def get_confirmations(self, block: int): # gets according stakes on the chainflip chain
        hash = self.chainflip.get_block_hash(block)

        events = self.chainflip.get_events(hash)
        self.logger.info("Block {} has {} events".format(block, len(events)))

        for event in events:
            # figure out unstakes as well
            if event.value["event_id"] == "Staked":
                # args look like (address, staked_amount, <not sure yet, but is always the same as staked_amount>)
                args = event.value["attributes"]
                self.logger.info("index: {}, args {}".format(event.value["extrinsic_idx"], args))

                stake = Stake.select().where(Stake.hash==args["tx_hash"]).first()
                if stake == None:
                    self.logger.warning("Stake not found for event: {}".format(event))
                    stake = Stake.create(address=args["account_id"], amount=args["stake_added"], confirmed_height=block, hash=args["tx_hash"])
                else:
                    stake.completed_height = block
                    stake.save()

                if Validator.select().where(Validator.address==args["account_id"]).count() == 0:
                    Validator.create(address=args["account_id"], staked_amount=args["stake_added"], rewards=0)

                    self.logger.info("Create validator {} with {} stake".format(args["account_id"], args["tx_hash"]))
                else:
                    v = Validator.get(Validator.address==args["account_id"])
                    v.staked_amount += args["stake_added"]
                    v.save()

                    self.logger.info("Added {} balance to validator {}".format(args["stake_added"], args["account_id"]))
            elif "claim" in event.value["event_id"].lower():
                self.logger.info("CLAIM"+ str(event))

        return True

    def watch_confirmations(self):
        previous_height = self.state.chainflip_height
        current_height = self.chainflip.get_block()["header"]["number"] - CHAINFLIP_REORG_PROTECTION

        if current_height - previous_height < CHAINFLIP_BLOCK_DELAY:
            return

        self.logger.info("Starting threads for blocks between {} and {}".format(previous_height+1, min(previous_height+CHAINFLIP_BATCH_SIZE, current_height)))

        blocks = []
        threads = []
        for block in range(previous_height+1, min(previous_height+CHAINFLIP_BATCH_SIZE+1, current_height)):
            t = Request(target=self.get_confirmations, args=[block])
            blocks.append(block)
            t.start()

            threads.append(t)
            time.sleep(THREADING_DELAY)

        for i, thread in enumerate(threads):
            a = thread.join()

            if not a:
                self.logger.fatal("Thread returned false, block {} failed to sync".format(blocks[i]))
                quit()

        self.state.chainflip_height = previous_height + CHAINFLIP_BATCH_SIZE
        self.state.save()

    def loop(self):
        while True:
            with db.atomic() as transaction:
                self.get_stakes()
                self.watch_confirmations()
            transaction.commit()

    def sync(self):
        # TODO: implement claims to the calculation
        while True:
            with db.atomic() as transaction:
                self.watch_stakes()
                self.watch_confirmations()
