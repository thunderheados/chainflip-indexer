#!/usr/bin/env python # -*- coding: utf-8 -*-


from substrateinterface import SubstrateInterface
from substrateinterface.utils.ss58 import ss58_decode, ss58_encode
from models import *
from web3 import Web3
from utils import logger, get_abi
from typing import List
from threading import Thread
from tqdm import tqdm
from retrying import retry
import json
import time
import sys

MAX_CALL_RETRIES = 1
CHAINFLIP_SS58_PREFIX = 2112
SYNC_THRESHOLD = 50

# allows threading functions to give return values.
class Request(Thread):
    def __init__(
        self, group=None, target=None, name=None, args=(), kwargs={}, Verbose=None
    ):
        Thread.__init__(self, group, target, name, args, kwargs)
        self._return = None

    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)

    def join(self, *args):
        Thread.join(self, *args)
        return self._return


class Indexer:
    def __init__(
        self,
        flip_staker_address: str,
        flip_staker_abi_path: str,
        node_evm: str,
        node_substrate: str,
        chainflip_batch_size: int = 4,
        threading_delay: float = 0.02,
        eth_reorg_protection: int = 2,
        chainflip_reorg_protection: int = 0,
    ):

        # create providers
        self.eth = Web3(Web3.HTTPProvider(node_evm))

        self.chainflip = SubstrateInterface(url=node_substrate)

        self.flip_staker_contract = self.eth.eth.contract(
            address=Web3.toChecksumAddress(flip_staker_address),
            abi=get_abi(flip_staker_abi_path),
        )

        self.logger = logger

        self.state = State[1]

        self.batch_size = chainflip_batch_size
        self.thread_delay = threading_delay

        self.eth_reorg_protection = eth_reorg_protection
        self.chainflip_reorg_protection = chainflip_reorg_protection

    def watch_eth(self):  # ethereum
        with db.atomic():
            self.logger.info("Checking for new stakes")
            previous_height = self.state.ethereum_height
            current_height = self.eth.eth.block_number - self.eth_reorg_protection
            self.logger.info("Current height: {}".format(current_height))

            self.logger.info(
                "Getting stakes between {} and {}".format(
                    previous_height, current_height
                )
            )

            if current_height == previous_height:
                return

            event_filter = self.flip_staker_contract.events.Staked.createFilter(
                fromBlock=hex(previous_height), toBlock=hex(current_height)
            )

            stakes = event_filter.get_all_entries()
            self.logger.info(
                "A total of {} stake events found between {} and {}".format(
                    len(stakes), previous_height, current_height
                )
            )

            id = 0
            try:
                id = Stake.select().order_by(Stake.id.desc()).get().id
            except:
                pass
            bulk_stakes = []
            for stake in tqdm(stakes):
                address = self.chainflip.ss58_encode(stake["args"]["nodeID"].hex())
                s = Stake.select().where(Stake.hash == stake["transactionHash"].hex())

                if s == None:
                    id += 1
                    bulk_stakes.append(
                        Stake(
                            id=id,
                            hash=stake["transactionHash"].hex(),
                            amount=stake["args"]["amount"],
                            initiated_height=stake["blockNumber"],
                            address=address,
                        )
                    )
                else:
                    self.logger.info(
                        "Watch Stakes is behind confirmations, modifying {} stake".format(
                            stake["transactionHash"].hex()
                        )
                    )
                    s.initiated_height = stake["blockNumber"]
                    s.save()

            event_filter = self.flip_staker_contract.events.ClaimRegistered.createFilter(
                fromBlock=hex(previous_height), toBlock=hex(current_height)
            )

            claims = event_filter.get_all_entries()
            self.logger.info(
                "A total of {} claim events found between {} and {}".format(
                    len(claims), previous_height, current_height
                )
            )

            id = 0
            try:
                id = Claim.select().order_by(Stake.id.desc()).get().id
            except:
                pass
            bulk_claims = []
            for claim in tqdm(claims):
                # get params of transaction
                tx = self.eth.eth.getTransaction(claim["transactionHash"])

                # decode input data, its in the abi of the contract (registerClaim)
                decoded = self.flip_staker_contract.decode_function_input(tx.input)
                args = decoded[1]
                msg_hash = args["sigData"][2]

                count = Claim.select().where(Claim.msg_hash == msg_hash).count()

                if count == 0:
                    id += 1
                    bulk_claims.append(
                        Claim(
                            id=id,
                            msg_hash=msg_hash,
                            amount=args["amount"],
                            node=ss58_encode(
                                args["nodeID"].hex(), CHAINFLIP_SS58_PREFIX
                            ),
                            start_time=claim["args"]["startTime"],
                            expiry_time=claim["args"]["expiryTime"],
                            staker=claim["args"]["staker"],
                        )
                    )
                else:
                    claim = Claim.select().where(Claim.msg_hash == msg_hash).get()
                    claim.start_time = claim["args"]["startTime"]
                    claim.expiry_time = claim["args"]["expiryTime"]
                    claim.staker = claim["args"]["staker"]
                    claim.save()

            self.logger.info("Paired up all stakes, inserting...")
            Stake.bulk_create(bulk_stakes, batch_size=250)
            Claim.bulk_create(bulk_claims, batch_size=250)

            event_filter = self.flip_staker_contract.events.ClaimExecuted.createFilter(
                fromBlock=hex(previous_height), toBlock=hex(current_height)
            )

            events = event_filter.get_all_entries()
            for event in events:
                # get the claims that it executed
                pending_claim = self.flip_staker_contract.functions.getPendingClaim(
                    event["args"]["nodeID"]
                ).call(block_identifier=event["blockNumber"] - 1)

                exists = (
                    Claim.select()
                    .where(
                        Claim.amount == pending_claim[0],
                        Claim.staker == pending_claim[1],
                        Claim.start_time == pending_claim[2],
                        Claim.expiry_time == pending_claim[3],
                    )
                    .count()
                )

                if exists == 0:
                    self.logger.fatal("Claim {} not found".format(event["args"]))

                    raise Exception("Claim not found")
                else:
                    claim = (
                        Claim.select()
                        .where(
                            Claim.amount == pending_claim[0],
                            Claim.staker == pending_claim[1],
                            Claim.start_time == pending_claim[2],
                            Claim.expiry_time == pending_claim[3],
                        )
                        .get()
                    )

                    self.logger.info("Claim {} completed".format(claim.id))
                    claim.completed_height = event["blockNumber"]
                    claim.save()

            self.state.ethereum_height = current_height + 1
            self.state.save()

    @retry(stop_max_attempt_number=MAX_CALL_RETRIES)
    def index_chainflip_block(
        self, block: int
    ):  # gets according stakes on the chainflip chain
        hash = self.chainflip.get_block_hash(block)

        events = self.chainflip.get_events(hash)
        extrinsics = self.chainflip.get_block(hash)
        self.logger.info("Block {} has {} events".format(block, len(events)))

        for event in events:
            # figure out unstakes as well
            if event.value["event_id"] == "Staked":
                # args look like (address, staked_amount, <not sure yet, but is always the same as staked_amount>)
                args = event.value["attributes"]

                args = {
                    "account_id": args[0],
                    "tx_hash": args[1],
                    "stake_added": args[2],
                    "stake_total": args[3],
                }

                self.logger.info(
                    "index: {}, args {}".format(event.value["extrinsic_idx"], args)
                )

                stake = Stake.select().where(Stake.hash == args["tx_hash"]).first()
                if stake == None:
                    self.logger.warning("Stake not found for event: {}".format(event))
                    stake = Stake.create(
                        address=args["account_id"],
                        amount=args["stake_added"],
                        confirmed_height=block,
                        hash=args["tx_hash"],
                    )
                else:
                    stake.completed_height = block
                    stake.save()

                if (
                    Validator.select()
                    .where(Validator.address == args["account_id"])
                    .count()
                    == 0
                ):
                    Validator.create(
                        address=args["account_id"],
                        staked_amount=args["stake_added"],
                        rewards=0,
                    )

                    self.logger.info(
                        "Create validator {} with {} stake".format(
                            args["account_id"], args["tx_hash"]
                        )
                    )
                else:
                    v = Validator.get(Validator.address == args["account_id"])
                    v.staked_amount += args["stake_added"]
                    v.save()

                    self.logger.info(
                        "Added {} balance to validator {}".format(
                            args["stake_added"], args["account_id"]
                        )
                    )
            elif (
                event.value["event_id"] == "ThresholdSignatureRequest"
            ):
                extrinsic = extrinsics[event.value["extrinsic_idx"]]
                
                # make sure it originated from a staking.Claim event
                if extrinsic["call"]["call_module"]["name"] != "Staking":
                    continue
                
                # get original extrinsic
                identifier = "{}-{}".format(block, event.value["extrinsic_idx"])
                self.logger.info(
                    "Found claim initiation with identifier {}".format(identifier)
                )

                msg_hash = event.value["attributes"][3]

                claim = Claim.select().where(Claim.msg_hash == msg_hash).first()
                if claim == None:
                    Claim.create(
                        msg_hash=msg_hash,
                        initiated_height=block,
                        chainflip_hash=extrinsic.value["extrinsic_hash"],
                        amount=extrinsic.value["call"]["call_args"][0]["value"][
                            "Exact"
                        ],
                        node=extrinsic.value["address"],
                    )
                else:
                    claim.initiated_height = block
                    claim.chainflip_hash = extrinsic.value["extrinsic_hash"]

                    claim.save()
            elif event.value["event_id"] == "ClaimExpired":
                claim = (
                    Claim.select()
                    .where(
                        Claim.node == event.value["attributes"][0],
                        Claim.expired_height == None,
                    )
                    .order_by(Claim.id.asc())
                    .first()
                )
                if claim == None:
                    self.logger.fatal("Claim not found for event: {}".format(event))
                    raise Exception("Claim not found")
                else:
                    self.logger.info("Claim {} expired".format(claim.id))
                    claim.expired_height = block
                    claim.save()

        return True

    def watch_chainflip(self):
        previous_height = self.state.chainflip_height
        current_height = (
            self.chainflip.get_block()["header"]["number"]
            - self.chainflip_reorg_protection
        )

        if current_height == previous_height:
            return

        self.logger.info(
            "Starting threads for blocks between {} and {}".format(
                previous_height + 1,
                min(previous_height + self.batch_size, current_height),
            )
        )

        blocks = []
        threads = []
        for block in range(previous_height + 1, current_height):
            with db.atomic():
                if not self.index_chainflip_block(block):
                    self.logger.fatal("Block {} failed to sync".format(block))

                    quit()
                else:
                    self.logger.info("Succesfully synced block {}".format(block))

                self.state.chainflip_height += 1
                self.state.save()

    def sync_chainflip(self, target_height: int, batch_size: int, thread_delay: float):
        previous_height = self.state.chainflip_height

        self.logger.info(
            "Syncing chainflip from {} to {}".format(previous_height, target_height)
        )

        # create batches
        for batch in range(previous_height, target_height, batch_size):
            self.logger.info(
                "Starting batch {} to {}".format(
                    batch + 1, min(batch + batch_size, target_height)
                )
            )

            blocks = []
            threads = []
            with db.atomic():
                for block in range(
                    batch + 1, min(batch + 1 + batch_size, target_height)
                ):
                    t = Request(target=self.index_chainflip_block, args=[block])
                    blocks.append(block)
                    t.start()

                    threads.append(t)
                    time.sleep(thread_delay)

                for i, thread in enumerate(threads):
                    a = thread.join()

                    if not a:
                        self.logger.fatal(
                            "Thread returned false, block {} failed to sync".format(
                                blocks[i]
                            )
                        )
                        quit()
                    else:
                        self.logger.info(
                            "Thread returned true, block {} succesfully synced".format(
                                blocks[i]
                            )
                        )

                self.state.chainflip_height = min(batch + batch_size, target_height)
                self.state.save()

    def start(self):
        self.watch_eth()

        latest = (
            self.chainflip.get_block()["header"]["number"]
            - self.chainflip_reorg_protection
        )

        while latest - self.state.chainflip_height > SYNC_THRESHOLD:
            self.sync_chainflip(latest, self.batch_size, self.thread_delay)

            latest = (
                self.chainflip.get_block()["header"]["number"]
                - self.chainflip_reorg_protection
            )

        while True:
            self.watch_eth()
            self.watch_chainflip()
