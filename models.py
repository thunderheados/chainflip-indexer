from peewee import *

# db = SqliteDatabase('db', pragmas={'journal_mode': 'wal'})
db = PostgresqlDatabase('root', user='root')

class State(Model):
    ethereum_height = IntegerField()
    chainflip_height = IntegerField()

    class Meta:
        database = db

# burns

class Stake(Model):
    hash = CharField(null = True)
    amount = FloatField()
    initiated_height = IntegerField(null = True) # height the stake was submitted on eth
    completed_height = IntegerField(null = True) # chainflip confirmation on chainflip chain
    address = CharField()

    class Meta:
        database = db

class Claim(Model):
    chainflip_hash = CharField(null = True)
    initiated_height = IntegerField(null = True)
    amount = FloatField()
    claim_signature = CharField(null = True)
    address = CharField()

    class Meta:
        database = db

# this class doesn't really do anything, but there for easy access.
class Validator(Model):
    address = CharField()
    staked_amount = FloatField()
    rewards = FloatField()

    class Meta:
        database = db

db.create_tables([State, Stake, Validator])

if State.select().count() == 0:
    State.create(ethereum_height=0, chainflip_height=0)
