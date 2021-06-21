import random
import time
from enum import Enum

from brownie import accounts, web3
from helpers.sett.DiggSnapshotManager import DiggSnapshotManager
from helpers.sett.SnapshotManager import SnapshotManager
from hexbytes import HexBytes
from rich.console import Console
from scripts.systems.badger_system import BadgerSystem

from .actors import (
    ChainActor,
    DiggActor,
    SettKeeperActor,
    StrategyKeeperActor,
    UserActor,
)
from .provisioners import (
    BadgerLpMetaFarmProvisioner,
    BadgerRewardsProvisioner,
    BaseProvisioner,
    CurveGaugeProvisioner,
    DiggLpMetaFarmProvisioner,
    DiggRewardsProvisioner,
    HarvestMetaFarmProvisioner,
    PancakeBBadgerBtcbProvisioner,
    PancakeBDiggBtcbProvisioner,
    PancakeBnbBtcbProvisioner,
    SushiBadgerWbtcProvisioner,
    SushiClawUSDCProvisioner,
    SushiDiggWbtcLpOptimizerProvisioner,
    SushiLpOptimizerProvisioner,
    WbtcIbBtcLpProvisioner,
    ConvexProvisioner,
    HelperCvxProvisioner,
    HelperCvxCrvProvisioner
)

console = Console()

# Provision num users for sim.
NUM_USERS = 4


class SimulationManagerState(Enum):
    IDLE = 0
    PROVISIONED = 1
    RANDOMIZED = 2
    RUNNING = 3


# SimulationManager is meant to be initialized per test and run once.
class SimulationManager:
    def __init__(
        self,
        badger: BadgerSystem,
        snap: SnapshotManager,
        settId: str,
        seed: int = 0,  # Default seed is 0 or unset, will generate.
    ):
        self.accounts = accounts[9:]  # Use the 10th account onwards.
        # User accounts (need to be provisioned before running sim).
        self.users = []

        self.debug = True

        self.badger = badger
        self.snap = snap
        self.sett = badger.getSett(settId)
        self.strategy = badger.getStrategy(settId)
        self.want = badger.getStrategyWant(settId)
        self.settKeeper = accounts.at(self.sett.keeper(), force=True)
        self.strategyKeeper = accounts.at(self.strategy.keeper(), force=True)

        # Actors generate valid actions based on the actor type. For example,
        # user actors need to have deposited first before they can withdraw
        # (withdraw before deposit is an invalid action).
        self.actors = [
            SettKeeperActor(self, self.settKeeper),
            StrategyKeeperActor(self, self.strategyKeeper),
            ChainActor(),
        ]
        if isinstance(snap, DiggSnapshotManager):
            self.actors.append(DiggActor(self, self.badger.deployer))
        # Ordered valid actions generated by actors.
        self.actions = []

        self.state = SimulationManagerState.IDLE

        # Track seed so we can configure this value if we want to repro test failures.
        self.seed = seed
        if self.seed == 0:
            self.seed = int(time.time())
        console.print(f"initialized simulation manager with seed: {self.seed}")
        random.seed(self.seed)
        console.print("Random Seed")
        self.provisioner = self._initProvisioner(settId)
        console.print("initialization complete")

    def provision(self) -> None:
        if self.debug:
            console.print("provisioning")
        if self.state != SimulationManagerState.IDLE:
            raise Exception(f"invalid state: {self.state}")

        if self.debug:
            console.print(f"collecting {NUM_USERS} users")

        accountsUsed = set([])
        while len(self.users) < NUM_USERS:
            # if self.debug:
            #     console.print("processing user")
            idx = int(random.random() * len(self.accounts))
            if idx in accountsUsed:
                continue
            if web3.eth.getCode(self.accounts[idx].address) != HexBytes("0x"):
                continue

            self.users.append(self.accounts[idx])
            if self.debug:
                console.print(f"added user {idx}")
            accountsUsed.add(idx)

        if self.debug:
            console.print("distributing token")
        self.provisioner._distributeTokens(self.users)

        if self.debug:
            console.print("distributing want")
        self.provisioner._distributeWant(self.users)

        if self.debug:
            console.print("provisioning users")
        self._provisionUserActors()

        console.print(f"provisioned {len(self.users)} users {len(self.actors)} actors")

        self.state = SimulationManagerState.PROVISIONED

    def randomize(self, numActions: int) -> None:
        console.print(f"Randomizing {numActions} actions")
        if self.state != SimulationManagerState.PROVISIONED:
            raise Exception(f"invalid state: {self.state}")

        for i in range(0, numActions):
            # Pick a random actor and generate an action.
            idx = int(random.random() * len(self.actors))
            self.actions.append(self.actors[idx].generateAction())

        console.print(f"randomized {numActions} actions")

        self.state = SimulationManagerState.RANDOMIZED

    def run(self) -> None:
        if self.state != SimulationManagerState.RANDOMIZED:
            raise Exception(f"invalid state: {self.state}")
        self.state = SimulationManagerState.RUNNING

        console.print(f"running {len(self.actions)} actions")

        for action in self.actions:
            action.run()

    def _initProvisioner(self, settId) -> BaseProvisioner:
        if settId == "native.badger":
            return BadgerRewardsProvisioner(self)
        if settId == "native.digg":
            return DiggRewardsProvisioner(self)
        if settId == "native.uniDiggWbtc":
            return DiggLpMetaFarmProvisioner(self)
        if settId == "native.sushiDiggWbtc":
            return SushiDiggWbtcLpOptimizerProvisioner(self)
        if settId == "harvest.renCrv":
            return HarvestMetaFarmProvisioner(self)
        if settId == "native.sushiBadgerWbtc":
            return SushiBadgerWbtcProvisioner(self)
        if settId == "native.sushiWbtcEth":
            return SushiLpOptimizerProvisioner(self)
        if settId == "native.uniBadgerWbtc":
            return BadgerLpMetaFarmProvisioner(self)
        if settId in ["native.renCrv", "native.sbtcCrv", "native.tbtcCrv"]:
            return CurveGaugeProvisioner(self)
        if settId in ["native.sushiSClawUSDC", "native.sushiBClawUSDC"]:
            return SushiClawUSDCProvisioner(self)
        if settId == "native.pancakeBnbBtcb":
            return PancakeBnbBtcbProvisioner(self)
        if settId == "native.bBadgerBtcb":
            return PancakeBBadgerBtcbProvisioner(self)
        if settId == "native.bDiggBtcb":
            return PancakeBDiggBtcbProvisioner(self)
        if settId == "native.sushiWbtcIbBtc":
            return WbtcIbBtcLpProvisioner(self)
        if settId == "native.uniWbtcIbBtc":
            return WbtcIbBtcLpProvisioner(self, isUniswap=True)
        if settId in ["native.convexRenCrv", "native.convexSbtcCrv", "native.convexTbtcCrv"]:
            return ConvexProvisioner(self)
        if settId in ["native.hbtcCrv", "native.pbtcCrv", "native.obtcCrv", "native.bbtcCrv", "native.triCrypto"]: 
            return ConvexProvisioner(self)
        if settId == "helper.cvx":
            return HelperCvxProvisioner(self)
        if settId == "helper.cvxCrv" :
            return HelperCvxCrvProvisioner(self)
        raise Exception(f"invalid strategy settID (no provisioner): {settId}")

    def _provisionUserActors(self) -> None:
        # Add all users as actors the sim.
        for user in self.users:
            self.actors.append(UserActor(self, user))
