from scripts.systems.uniswap_system import UniswapSystem
from helpers.registry import registry
from .BaseProvisioner import BaseProvisioner


class StrategyMStableVaultProvisioner(BaseProvisioner):
    def __init__(self, manager):
        super().__init__(manager)
        # Whales are hard coded for now.
        self.whales = [
            registry.whales.imbtc,
            registry.whales.fPmBtcHBtc,
        ]

    def _distributeWant(self, users) -> None:
        # imbtc distributed on BaseProvisioner, no other asset needed.
        pass
