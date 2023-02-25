import json
import logging
from scalecodec import ScaleBytes
from pydantic import BaseModel


class CustomFormatter(logging.Formatter):

    green = "\x1b[32m"
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(levelname)s: - %(asctime)s - %(message)s"

    FORMATS = {
        logging.DEBUG: green + format + reset,
        logging.INFO: green + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


# create logger with 'spam_application'
logger = logging.getLogger("Indexer")
logger.setLevel(logging.INFO)

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

ch.setFormatter(CustomFormatter())

logger.addHandler(ch)


def get_abi(path: str) -> dict:
    file = open(path, "r")

    abi = json.loads(file.read())
    if type(abi) == list:
        return abi

    if abi["abi"] == None:
        Raise("Invalid ABI")

    return abi["abi"]


class SigData(BaseModel):
    key_manager_address: bytes
    chain_id: int
    msg_hash: int
    sig: int
    nonce: int
    k_time_g_addr: bytes


class ClaimSignature(BaseModel):
    sig_data: SigData
    node_id: bytes
    amount: int
    staker: bytes
    expiry_time: int


def decode_claim_signature(sb: ScaleBytes) -> ClaimSignature:
    _ = sb.get_next_bytes(4)

    key_man_address = sb.get_next_bytes(32)[12:]
    chain_id = int(sb.get_next_bytes(32).hex(), 16)
    msg_hash = int(sb.get_next_bytes(32).hex(), 16)
    sig = int(sb.get_next_bytes(32).hex(), 16)
    nonce = int(sb.get_next_bytes(32).hex(), 16)
    k_time_g_addr = sb.get_next_bytes(32)[12:]

    sig_data = SigData(
        key_manager_address=key_man_address,
        chain_id=chain_id,
        msg_hash=msg_hash,
        sig=sig,
        nonce=nonce,
        k_time_g_addr=k_time_g_addr,
    )
    node_id = sb.get_next_bytes(32)
    amount = int(sb.get_next_bytes(32).hex(), 16)
    staker = sb.get_next_bytes(32)[12:]
    expiry_time = int(sb.get_next_bytes(32).hex(), 16)

    claim_sig = ClaimSignature(
        sig_data=sig_data,
        node_id=node_id,
        amount=amount,
        staker=staker,
        expiry_time=expiry_time,
    )
    return claim_sig
