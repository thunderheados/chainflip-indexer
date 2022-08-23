# Chainflip-indexer architecture

## Indexer

### Database
The indexer will run on a database with models like this:

```
State:
	height: int

Stake:
	hash: str
	amount: int
	initiated_height: int (ethereum block height of when the stake was confirmed)
	completed_height: int (chainflip block height of when the witness was included in a block)

Validator:
	address: str
	stake_amount: int
	rewards: int
```
