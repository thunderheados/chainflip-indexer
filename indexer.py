from substrateinterface import SubstrateInterface
from models import *
from web3 import Web3
from utils import logger, get_abi, multi_getattr
from typing import List
from threading import Thread
import json
import time

CALL_RETRIES = 5
THREADING_DELAY = 0.01

ETH_REORG_PROTECTION = 5
ETH_BLOCK_DELAY = 5

CHAINFLIP_REORG_PROTECTION = 5
CHAINFLIP_BLOCK_DELAY = 5
CHAINFLIP_BATCH_SIZE = 100


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
            address=flip_staker_address, abi=get_abi(flip_staker_abi_path)
        )

        self.logger = logger

        self.state = State[1]

    def watch_stakes(self): # ethereum
        self.logger.info("Started watching stakes")
        while True:
            self.logger.info("Checking for new stakes")
            previous_height = self.state.ethereum_height
            current_height = self.eth.eth.block_number - ETH_REORG_PROTECTION
            self.logger.info("Current height: {}".format(current_height))

            self.logger.info("Getting stakes between {} and {}".format(previous_height, current_height))

            if current_height - previous_height < ETH_BLOCK_DELAY:
                time.sleep(2)
                continue

            event_filter = self.flip_staker_contract.events.Staked.createFilter(
                fromBlock=hex(previous_height),
                toBlock=hex(current_height)
            )

            stakes = event_filter.get_all_entries()
            self.logger.info("A total of {} stake events found between {} and {}".format(len(stakes), previous_height, current_height))

            for stake in stakes:
                address = self.chainflip.ss58_encode(stake["args"]["nodeID"].hex())
                Stake.create(hash = stake["transactionHash"].hex(), amount = stake["args"]["amount"], initiated_height = stake["blockNumber"], address=address)

            self.state.ethereum_height = current_height + 1
            self.state.save()

    def get_confirmations(self, block: int): # gets according stakes on the chainflip chain
        hash = self.chainflip.get_block_hash(block)

        events = self.chainflip.get_events(hash)

        for event in events:
            # figure out unstakes as well
            if event.value["event_id"] == "Staked":
                # args look like (address, staked_amount, <not sure yet, but is always the same as staked_amount>)
                args = event.value["attributes"]
                self.logger.info(args)

                # TODO: the txhash in the event has not been implemented yet, but will be soon by the chainflip team
                stake = Stake.select().where(Stake.address==args[0], Stake.amount==args[1]).first()
                if stake == None:
                    self.logger.warning("Stake not found for event: {}".format(event))
                    stake = Stake.create(address=args[0], amount=args[1], confirmed_height=block)
                else:
                    stake.completed_height = block
                    stake.save()

                if Validator.select().where(Validator.address==args[0]).count() == 0:
                    Validator.create(address=args[0], staked_amount=args[1], rewards=0)

                    self.logger.info("Create validator {} with {} stake".format(args[0], args[1]))
                else:
                    v = Validator.get(Validator.address==args[0])
                    v.staked_amount += args[1]
                    v.save()

                    self.logger.info("Added {} balance to validator {}".format(args[1], args[0]))
            elif "claim" in event.value["event_id"].lower():
                self.logger.info("Event")

        return True

    def watch_confirmations(self):
        while True:
            previous_height = self.state.chainflip_height
            current_height = self.chainflip.get_block()["header"]["number"] - CHAINFLIP_REORG_PROTECTION

            if current_height - previous_height < CHAINFLIP_BLOCK_DELAY:
                time.sleep(2)
                continue

            self.logger.info("Starting threads for blocks between {} and {}".format(previous_height+1, min(previous_height+CHAINFLIP_BATCH_SIZE, current_height)))

            threads = []
            for block in range(previous_height+1, min(previous_height+CHAINFLIP_BATCH_SIZE+1, current_height)):
                t = Thread(target=self.get_confirmations, args=(block,))
                t.start()

                threads.append(t)
                time.sleep(THREADING_DELAY)

            for thread in threads:
                t.join()

            self.state.chainflip_height = previous_height + CHAINFLIP_BATCH_SIZE
            self.state.save()

    def sync(self):
        # TODO: implement claims to the calculation

        # as events pass on two seperate blockchains it makes sense to process them in two different threads, they also use different tables in the sqlite3 database so that isn't an issue either
        stakes = Thread(target=self.watch_stakes, args=())
        confirmations = Thread(target=self.watch_confirmations, args=())

        stakes.daemon = True
        confirmations.daemon = True

        stakes.start()
        confirmations.start()

        # they never actually complete, but just to make python happy :)
        stakes.join()
        confirmations.join()


