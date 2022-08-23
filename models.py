from peewee import *

db = SqliteDatabase('db')

class State(Model):
    ethereum_height = IntegerField()
    chainflip_height = IntegerField()


    class Meta:
        database = db

class Stake(Model):
    hash = CharField()
    amount = FloatField()
    initiated_height = IntegerField()
    completed_height = IntegerField(null = True)

    class Meta:
        database = db

class Validator(Model):
    address = CharField()
    staked_amount = FloatField()
    rewards = FloatField()

    class Meta:
        database = db

db.create_tables([State, Stake, Validator])

if State.select().count() == 0:
    State.create(ethereum_height=0, chainflip_height=0)
