from peewee import *

db = SqliteDatabase('db', pragmas={'journal_mode': 'wal'})
#  db = PostgresqlDatabase('root', user='root')

class State(Model):
    ethereum_height = IntegerField()
    chainflip_height = IntegerField()

    class Meta:
        database = db

class Stake(Model):
    hash = CharField(null = True)
    amount = FloatField()
    initiated_height = IntegerField(null = True) # height the stake was submitted on eth
    completed_height = IntegerField(null = True) # chainflip confirmation on chainflip
    address = CharField()

    class Meta:
        database = db

class Claim(Model):
    chainflip_hash = CharField(null = True)
    initiated_height = IntegerField(null = True) # height the claim was submitted on chainflip
    completed_height = IntegerField(null = True) # the height the claim was completed on eth
    expired_height = IntegerField(null = True) # the height the claim expired on chainflip (if it did)
    amount = FloatField()
    #  claim_signature = CharField(null = True)
    msg_hash = CharField(null = True)
    start_time = IntegerField(null = True)
    expiry_time = IntegerField(null = True)
    node = CharField()
    staker = CharField(null = True)

    class Meta:
        database = db

# this class doesn't really do anything, but there for easy access.
class Validator(Model):
    address = CharField()
    staked_amount = FloatField()
    rewards = FloatField()

    class Meta:
        database = db

db.create_tables([State, Stake, Validator, Claim])

if State.select().count() == 0:
    State.create(ethereum_height=0, chainflip_height=0)
