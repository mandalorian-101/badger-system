from assistant.subgraph.config import subgraph_config
from rich.console import Console
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from decimal import *
import json
getcontext().prec = 20
console = Console()

sett_prices_url = "https://laiv44udi0.execute-api.us-west-1.amazonaws.com/staging/v2/protocol/sett"
subgraph_url = subgraph_config["url"]
transport = AIOHTTPTransport(url=subgraph_url)
client = Client(transport=transport, fetch_schema_from_transport=True)


def fetch_sett_balances(settId, startBlock):
    console.print(
        "[bold green] Fetching sett balances {}[/bold green]".format(settId)
    )
    query = gql(
        """
        query balances_and_events($vaultID: Vault_filter, $blockHeight: Block_height,$lastBalanceId:AccountVaultBalance_filter) {
            vaults(block: $blockHeight, where: $vaultID) {
                balances(first:1000,where: $lastBalanceId) {
                    id
                    account {
                        id
                    }
                    shareBalanceRaw
                  }
                }
            }
        """
    )
    lastBalanceId = ""
    variables = {"blockHeight": {"number": startBlock}, "vaultID": {"id": settId}}
    balances = {}
    while True:
        variables["lastBalanceId"] = {
            "id_gt":lastBalanceId
        }
        results = client.execute(query, variable_values=variables)
        if len(results["vaults"]) == 0:
            return {}
        newBalances = {}
        balance_data = results["vaults"][0]["balances"]
        for result in balance_data:
            account = result["id"].split("-")[0]
            newBalances[account] = int(result["shareBalanceRaw"])

        if len(balance_data) == 0:
            break

        if len(balance_data) > 0:
            lastBalanceId = balance_data[-1]["id"]

        balances = {**newBalances,**balances}
    console.log("Processing {} balances".format(len(balances)))
    return balances


def fetch_geyser_events(geyserId, startBlock):
    console.print(
        "[bold green] Fetching Geyser Events {}[/bold green]".format(geyserId)
    )

    query = gql(
        """query($geyserID: Geyser_filter,$blockHeight: Block_height,$lastStakedId: StakedEvent_filter,$lastUnstakedId: UnstakedEvent_filter)
    {
      geysers(where: $geyserID,block: $blockHeight) {
          id
          totalStaked
          stakeEvents(first:1000,where: $lastStakedId) {
              id
              user,
              amount
              timestamp,
              total
          }
          unstakeEvents(first:1000,where: $lastUnstakedId) {
              id
              user,
              amount
              timestamp,
              total
          }
      }
    }
    """
    )

    stakes = []
    unstakes = []
    totalStaked = 0
    lastStakedId = ""
    lastUnstakedId = ""
    variables = {"geyserID": {"id": geyserId}, "blockHeight": {"number": startBlock}}
    while True:
        variables["lastStakedId"] = {
            "id_gt": lastStakedId
        }
        variables["lastUnstakedId"] = {
            "id_gt": lastUnstakedId
        }
        result = client.execute(query,variable_values=variables)

        if len(result["geysers"]) == 0:
            return {
                "stakes":[],
                "unstakes":[],
                "totalStaked":0
            }
        newStakes = result["geysers"][0]["stakeEvents"]
        newUnstakes = result["geysers"][0]["unstakeEvents"]
        if len(newStakes) == 0 and len(newUnstakes) == 0:
            break
        if len(newStakes) > 0:
            lastStakedId = newStakes[-1]["id"]
        if len(newUnstakes) > 0:
            lastUnstakedId = newUnstakes[-1]["id"]

        stakes.extend(newStakes)
        unstakes.extend(newUnstakes)
        totalStaked = result["geysers"][0]["unstakeEvents"]

    console.log("Processing {} stakes".format(len(stakes)))
    console.log("Processing {} unstakes".format(len(unstakes)))
    return {
        "stakes": stakes,
        "unstakes": unstakes,
        "totalStaked": totalStaked
    }


def fetch_sett_transfers(settID, startBlock, endBlock):
    console.print(
        "[bold green] Fetching Sett Deposits/Withdrawals {}[/bold green]".format(settID)
    )
    query = gql(
        """
        query sett_transfers($vaultID: Vault_filter, $blockHeight: Block_height) {
            vaults(block: $blockHeight, where: $vaultID) {
                deposits(first:1000) {
                    id
                    pricePerFullShare
                    account {
                     id
                    }
                    amount
                    transaction {
                        timestamp
                        blockNumber
                    }
                }
                withdrawals(first:1000) {
                    id
                    pricePerFullShare
                    account {
                     id
                    }
                    amount
                    transaction {
                        timestamp
                        blockNumber
                    }
                }
            }
        }
    """
    )
    variables = {"vaultID": {"id": settID}, "blockHeight": {"number": endBlock}}

    results = client.execute(query, variable_values=variables)

    def filter_by_startBlock(transfer):
        return int(transfer["transaction"]["blockNumber"]) > startBlock

    def convert_amount(transfer):
        ppfs = Decimal(transfer["pricePerFullShare"]) / Decimal(1e18)
        transfer["amount"] = round(Decimal(transfer["amount"]) / Decimal(ppfs))
        return transfer

    def negate_withdrawals(withdrawal):
        withdrawal["amount"] = -withdrawal["amount"]
        return withdrawal


    deposits = map(convert_amount, results["vaults"][0]["deposits"])
    withdrawals = map(
        negate_withdrawals,
        map(convert_amount, results["vaults"][0]["withdrawals"]),
    )

    deposits = list(filter(filter_by_startBlock, list(deposits)))
    withdrawals = list(filter(filter_by_startBlock, list(withdrawals)))
    console.log("Processing {} deposits".format(len(deposits)))
    console.log("Processing {} withdrawals".format(len((withdrawals))))

    return sorted(
        [*deposits, *withdrawals],
        key=lambda t: t["transaction"]["timestamp"],
    )

def fetch_farm_harvest_events():
    query = gql("""
        query fetch_harvest_events {
            farmHarvestEvents(first:1000,orderBy: blockNumber,orderDirection:asc) {
                id
                farmToRewards
                blockNumber
                totalFarmHarvested
                timestamp
            }
        }

    """)
    results = client.execute(query)
    for event in results["farmHarvestEvents"]:
        event["rewardAmount"] = event.pop("farmToRewards")

    return results["farmHarvestEvents"]

def fetch_sushi_harvest_events():
    query = gql("""
        query fetch_harvest_events {
            sushiHarvestEvents(first:1000,orderBy:blockNumber,orderDirection:asc) {
                id
                xSushiHarvested
                totalxSushi
                toStrategist
                toBadgerTree
                toGovernance
                timestamp
                blockNumber
            }
        }
    """)
    results = client.execute(query)
    wbtcEthEvents = []
    wbtcBadgerEvents = []
    wbtcDiggEvents = []
    for event in results["sushiHarvestEvents"]:
        event["rewardAmount"] = event.pop("toBadgerTree")
        strategy = event["id"].split("-")[0]
        if strategy == "0x7a56d65254705b4def63c68488c0182968c452ce":
            wbtcEthEvents.append(event)
        elif strategy == "0x3a494d79aa78118795daad8aeff5825c6c8df7f1":
            wbtcBadgerEvents.append(event)
        elif strategy == "0xaa8dddfe7dfa3c3269f1910d89e4413dd006d08a":
            wbtcDiggEvents.append(event)

    return {
        "wbtcEth":wbtcEthEvents,
        "wbtcBadger":wbtcBadgerEvents,
        "wbtcDigg":wbtcDiggEvents
    }

    cream_transport = AIOHTTPTransport(url=subgraph_config["cream_url"])
    cream_client = Client(transport=cream_transport, fetch_schema_from_transport=True)
    console.log("Fetching cream deposits...")
    increment = 1000

    query = gql("""
        query fetchCreambDeposits($firstAmount: Int, $lastID: ID,$symbol: String) {
            accountCTokens(first: $firstAmount,
                where: {
                    id_gt: $lastID
                    symbol: $symbol
                    enteredMarket: true
                }
            ) {
                id
                totalUnderlyingBorrowed
                totalUnderlyingSupplied
                account {
                    id
                }
            }
        markets(
            where:{
            symbol:$symbol
        }) {
            exchangeRate
        }
        }
    """)

    retVal = {}
    continueFetching = True
    lastID = "0x0000000000000000000000000000000000000000"

    while continueFetching:
        variables = {"firstAmount": increment, "lastID": lastID,"symbol": tokenSymbol}
        nextPage = cream_client.execute(query, variable_values=variables)
        if len(nextPage["accountCTokens"]) == 0:
            if len(nextPage["markets"]) == 0:
                return {}
            exchangeRate = nextPage["markets"][0]["exchangeRate"]
            ontinueFetching = False
        else:
            exchangeRate = nextPage["markets"][0]["exchangeRate"]
            lastID = nextPage["accountCTokens"][-1]["id"]
            for entry in nextPage["accountCTokens"]:
                retVal[entry["account"]["id"]] = float(entry["totalUnderlyingSupplied"]) * 1e18 / (1+float(exchangeRate))

    return retVal


def fetch_wallet_balances(badger_price,digg_price,digg):
    increment = 1000
    query = gql("""
        query fetchWalletBalance($firstAmount: Int, $lastID: ID) {
            tokenBalances(first: $firstAmount, where: { id_gt: $lastID  }) {
                id
                balance
                token {
                    symbol
                }
            }
        }
    """)

    ## Paginate this for more than 1000 balances
    continueFetching = True
    lastID = "0x0000000000000000000000000000000000000000"

    badger_balances = {}
    digg_balances = {}

    while continueFetching:
        variables = {"firstAmount": increment, "lastID": lastID}
        nextPage = client.execute(query, variable_values=variables)
        if len(nextPage["tokenBalances"]) == 0:
            continueFetching = False
        else:
            lastID = nextPage["tokenBalances"][-1]["id"]
            for entry in nextPage["tokenBalances"]:
                address = entry["id"].split("-")[0]
                if entry["token"]["symbol"] == "BADGER" and int(entry["balance"]) > 0:
                    badger_balances[address] = float(entry["balance"]) / 1e18 * badger_price
                if entry["token"]["symbol"] == "DIGG" and int(entry["balance"]) > 0:
                    # Convert
                    fragmentBalance = digg.logic.UFragments.sharesToFragments(entry["balance"])
                    digg_balances[address] = float(fragmentBalance) / 1e9 * digg_price

    return badger_balances, digg_balances

def fetch_cream_balances(tokenSymbol):
    cream_transport = AIOHTTPTransport(url=subgraph_config["cream_url"])
    cream_client = Client(transport=cream_transport, fetch_schema_from_transport=True)
    console.log("Fetching cream deposits...")
    increment = 1000

    query = gql("""
        query fetchCreambBadgerDeposits($firstAmount: Int, $lastID: ID, $symbol: String) {
            accountCTokens(first: $firstAmount,
                where: {
                    id_gt: $lastID
                    symbol: $symbol
                    enteredMarket: true
                }
            ) {
                id
                totalUnderlyingBorrowed
                totalUnderlyingSupplied
                account {
                    id
                }
            }
        markets(
            where:{
            symbol:$symbol
        }) {
            exchangeRate
        }
        }
    """)

    ## Paginate this for more than 1000 balances
    results = []
    continueFetching = True
    lastID = "0x0000000000000000000000000000000000000000"

    while continueFetching:
        variables = {"firstAmount": increment, "lastID": lastID,"symbol":tokenSymbol}
        nextPage = cream_client.execute(query, variable_values=variables)
        if len(nextPage["accountCTokens"]) == 0:
            if len(nextPage["markets"]) == 0:
                console.log("No Cream deposits found for {}".format(tokenSymbol))
                return {}
            exchangeRate = nextPage["markets"][0]["exchangeRate"]
            continueFetching = False
        else:
            lastID = nextPage["accountCTokens"][-1]["id"]
            results += nextPage["accountCTokens"]

    retVal = {}
    console.log("Queried {} cream balances".format(len(results)))
    for entry in results:
        retVal[entry["account"]["id"]] = float(entry["totalUnderlyingSupplied"]) * 1e18 / (1+float(exchangeRate))
    return retVal
