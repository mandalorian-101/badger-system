from helpers.time_utils import days
import json
import brownie
import pytest
from brownie import *
from helpers.constants import *
from helpers.registry import registry
from helpers.registry.artifacts import artifacts
from collections import namedtuple

with open("merkle/badger-bouncer.json") as f:
    yearnDistribution = json.load(f)

merkleRoot = yearnDistribution["merkleRoot"]

WITHDRAWAL_FEE = 50
DEVIATION_MAX = 50

@pytest.fixture(scope="module", autouse=True)
def setup(SimpleWrapperGatedUpgradeable, YearnRegistry, VipCappedGuestListWrapperUpgradeable):
    # Assign accounts
    deployer = accounts[0]
    affiliate = accounts[1]
    manager = accounts[2]
    guardian = accounts[3]
    randomUser1 = accounts[4]
    randomUser2 = accounts[5]
    randomUser3 = accounts[6]
    distributor = accounts[7]

    # Yearn governance account
    yearnGovernance = accounts.at('0xfeb4acf3df3cdea7399794d0869ef76a6efaff52', force=True)

    # WBTC owner account
    wbtcOwner = accounts.at('0xca06411bd7a7296d7dbdd0050dfc846e95febeb7', force=True)

    namedAccounts = {
        "deployer": deployer, 
        "affiliate": affiliate, 
        "manager": manager, 
        "guardian": guardian,
        "randomUser1": randomUser1,
        "randomUser2": randomUser2,
        "randomUser3": randomUser3,
        "distributor": distributor,
        "yearnGovernance": yearnGovernance,
        "wbtcOwner": wbtcOwner,
    }

    # WBTC
    abi = artifacts.wbtc["wbtc"]["abi"]
    wbtc = Contract.from_abi('WBTC', registry.tokens.wbtc, abi, wbtcOwner)
    print(wbtc.name() + ' fetched')

    assert wbtc.owner() == wbtcOwner.address

    # Deployer mints WBTC tokens for users
    wbtc.mint(randomUser1.address, 10e8)
    wbtc.mint(randomUser2.address, 20e8)
    wbtc.mint(randomUser3.address, 10e8)
    wbtc.mint(distributor.address, 1000e8)

    assert wbtc.balanceOf(randomUser1.address) == 10e8
    assert wbtc.balanceOf(randomUser2.address) == 20e8
    assert wbtc.balanceOf(randomUser3.address) == 10e8
    assert wbtc.balanceOf(distributor.address) == 1000e8

    # Yearn underlying vault (yvWBTC)
    yvwbtc = interface.VaultAPI('0xA696a63cc78DfFa1a63E9E50587C197387FF6C7E')
    print(yvwbtc.name() + ' fetched')

    # Yearn registry
    yearnRegistry = deployer.deploy(YearnRegistry)
    yearnRegistry.setGovernance(yearnGovernance.address)
    # No need to add vault since we will test in experimental mode

    # Deploy and initialize the wrapper contract (deployer -> affiliate)
    wrapper = deployer.deploy(SimpleWrapperGatedUpgradeable)
    wrapper.initialize(
        wbtc.address,
        yearnRegistry.address,
        "BadgerYearnWBTC",
        "byvwbtc",
        guardian.address,
        True,
        yvwbtc.address,
    )

    # Deploy the Guestlist contract (deployer -> bouncer)
    guestlist = deployer.deploy(VipCappedGuestListWrapperUpgradeable)
    guestlist.initialize(wrapper.address)

    # Add users to guestlist
    guestlist.setGuests([randomUser1.address, randomUser2.address], [True, True])
    # Set deposit cap to 15 tokens
    guestlist.setUserDepositCap(15e8)

    yield namedtuple(
        'setup', 
        'wbtc yvwbtc yearnRegistry wrapper guestlist namedAccounts'
    )(
        wbtc, 
        yvwbtc,
        yearnRegistry, 
        wrapper, 
        guestlist, 
        namedAccounts
    )

@pytest.fixture(autouse=True)
def isolation(fn_isolation):
    pass

#@pytest.mark.skip()
def test_permissions(setup):
    randomUser1 = setup.namedAccounts['randomUser1']
    randomUser2 = setup.namedAccounts['randomUser2']
    randomUser3 = setup.namedAccounts['randomUser3']
    deployer = setup.namedAccounts['deployer']
    guardian = setup.namedAccounts['guardian']
    manager = setup.namedAccounts['manager']

    # Adding users to guestlist from non-owner account reverts
    with brownie.reverts('Ownable: caller is not the owner'):
        setup.guestlist.setGuests([randomUser3.address], [True], {"from": randomUser2})

    # Setting deposit cap on guestlist from non-owner reverts
    with brownie.reverts('Ownable: caller is not the owner'):
        setup.guestlist.setUserDepositCap(15e8, {"from": randomUser2})

    # Setting guestRoot on guestlist from non-owner reverts
    with brownie.reverts('Ownable: caller is not the owner'):
        setup.guestlist.setGuestRoot('0x00000000000000000000000000000000', {"from": randomUser2})

    # Setting withrdawal fee by non-affiliate account reverts
    with brownie.reverts():
        setup.wrapper.setWithdrawalFee(50, {"from": randomUser2})

    # Setting withrdawal fee higher than allowed reverts
    with brownie.reverts('excessive-withdrawal-fee'):
        setup.wrapper.setWithdrawalFee(10001, {"from": deployer})

    # Setting _maxDeviationThreshold higher than allowed reverts
    with brownie.reverts('excessive-withdrawal-fee'):
        setup.wrapper.setWithdrawalFee(10001, {"from": deployer})

    # Set new affiliate from non-affiliate account reverts
    with brownie.reverts():
        setup.wrapper.setAffiliate(randomUser1.address, {"from": randomUser2})

    # Set new affiliate from affiliate account
    tx = setup.wrapper.setAffiliate(randomUser1.address, {"from": deployer})
    assert len(tx.events) == 1
    assert tx.events[0]['affiliate'] == randomUser1.address

    # Accepting affiliate role from non-pendingAffiliate account reverts
    with brownie.reverts():
        setup.wrapper.acceptAffiliate({"from": randomUser2})

    # Accepting affiliate role from pendingAffiliate account
    tx = setup.wrapper.acceptAffiliate({"from": randomUser1})
    assert len(tx.events) == 1
    assert tx.events[0]['affiliate'] == randomUser1.address

    # set Guardian from non-affiliate account reverts
    with brownie.reverts():
        setup.wrapper.setGuardian(guardian.address, {"from": randomUser2})

    # set Guardian from previous affiliate account reverts (check for affiliate rights revocation)
    with brownie.reverts():
        setup.wrapper.setGuardian(guardian.address, {"from": deployer})

    # set Guardian from new affiliate account
    tx = setup.wrapper.setGuardian(guardian.address, {"from": randomUser1})
    assert len(tx.events) == 1
    assert tx.events[0]['guardian'] == guardian.address

    # set Manager from non-affiliate account reverts
    with brownie.reverts():
        setup.wrapper.setManager(manager.address, {"from": randomUser2})

    # set Manager from new affiliate account
    tx = setup.wrapper.setManager(manager.address, {"from": randomUser1})
    assert len(tx.events) == 1
    assert tx.events[0]['manager'] == manager.address

    # set Guestlist from non-affiliate account reverts
    with brownie.reverts():
        setup.wrapper.setGuestList(setup.guestlist.address, {"from": randomUser2})

    # set Guestlist from new affiliate account
    tx = setup.wrapper.setGuestList(setup.guestlist.address, {"from": randomUser1})
    assert len(tx.events) == 1
    assert tx.events[0]['guestList'] == setup.guestlist.address

    # pausing contract with unauthorized account reverts
    with brownie.reverts():
        setup.wrapper.pause({"from": randomUser2})

    # pausing contract with guardian
    tx = setup.wrapper.pause({"from": guardian})
    assert len(tx.events) == 1
    assert tx.events[0]['account'] == guardian.address
    assert setup.wrapper.paused() == True

    chain.sleep(10000)
    chain.mine(1)

    # Permforming all write transactions on paused contract reverts
    if setup.wrapper.paused():

        # Approve wrapper as spender of wbtc
        setup.wbtc.approve(setup.wrapper.address, 10e8, {"from": randomUser2})

        # From any user
        with brownie.reverts():
            setup.wrapper.deposit([], {"from": randomUser2})

        with brownie.reverts():
            setup.wrapper.deposit(1e8, [], {"from": randomUser2})

        with brownie.reverts():
            setup.wrapper.withdraw({"from": randomUser2})

        with brownie.reverts():
            setup.wrapper.withdraw(1e8, {"from": randomUser2})

    else:
        pytest.fail("Wrapper not paused")
    

    # unpausing contract with manager
    tx = setup.wrapper.unpause({"from": manager})
    assert len(tx.events) == 1
    assert tx.events[0]['account'] == manager.address
    assert setup.wrapper.paused() == False

    # pausing contract with manager
    tx = setup.wrapper.pause({"from": manager})
    assert len(tx.events) == 1
    assert tx.events[0]['account'] == manager.address
    assert setup.wrapper.paused() == True
    
    # unpausing contract with affiliate
    tx = setup.wrapper.unpause({"from": randomUser1})
    assert len(tx.events) == 1
    assert tx.events[0]['account'] == randomUser1.address
    assert setup.wrapper.paused() == False

    # pausing contract with affiliate
    tx = setup.wrapper.pause({"from": randomUser1})
    assert len(tx.events) == 1
    assert tx.events[0]['account'] == randomUser1.address
    assert setup.wrapper.paused() == True

    # unpausing contract with guardian account reverts
    with brownie.reverts():
        setup.wrapper.unpause({"from": guardian})

    # unpausing contract with unauthorized account reverts
    with brownie.reverts():
        setup.wrapper.unpause({"from": randomUser2})

#@pytest.mark.skip()
def test_deposit_withdraw_flow(setup):
    randomUser1 = setup.namedAccounts['randomUser1']
    randomUser2 = setup.namedAccounts['randomUser2']
    randomUser3 = setup.namedAccounts['randomUser3']
    deployer = setup.namedAccounts['deployer']

    # Remove merkle proof verification from Gueslist
    setup.guestlist.setGuestRoot('0x0')

    # Link guestlist to wrapper
    setup.wrapper.setGuestList(setup.guestlist.address, {"from": deployer})
        
    # === Deposit flow === #
    
    # Approve wrapper as spender of wbtc for users
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser3})
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser2})
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser1})

    # total amount of tokens deposited through wrapper = 0
    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 0
    # total supply of wrapper shares = 0
    assert setup.wrapper.totalSupply() == 0

    # = User 2: Has 20 Tokens, deposits 1, on Guestlist = #
    # Random user (from guestlist) deposits 1 Token
    setup.wrapper.deposit(1e8, [], {"from": randomUser2})
    print("-- 1st User Deposits 1 --")
    print("Wrapper's PPS:", setup.wrapper.pricePerShare())
    print("yvwbtc's PPS:", setup.yvwbtc.pricePerShare())
    assert setup.wbtc.balanceOf(randomUser2.address) == 19e8

    # Check balance of user within wrapper
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 1e8

    # wbtc balance wrapper to deposited amount
    assert setup.wrapper.totalAssets() == 1e8

    # wrapper shares are minted for depositor and vault shares are 0 for depositor
    assert setup.yvwbtc.balanceOf(randomUser2.address) == 0
    assert setup.wrapper.balanceOf(randomUser2.address) == 1e8

    # Check balance of user within wrapper
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 1e8

    # Remaining deposit allowed for User 2: 15 - 1 = 14 wbtcs\
    # Gueslist not adapted to read wrapper usage data
    assert setup.guestlist.remainingUserDepositAllowed(randomUser2.address) == 14e8

    # Test pricePerShare to equal 1
    assert setup.wrapper.pricePerShare() == 1e8

    # = User 1: Has 10 Tokens, deposits 10, on Guestlist = #
    # Another random user (from guestlist) deposits all their Tokens (10)
    setup.wrapper.deposit([], {"from": randomUser1})
    print("-- 2nd User Deposits 10 --")
    print("Wrapper's PPS:", setup.wrapper.pricePerShare())
    print("yvwbtc's PPS:", setup.yvwbtc.pricePerShare())
    assert setup.wbtc.balanceOf(randomUser1.address) == 0

    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 11e8

    # wbtc balance of wrapper equals to net amount
    assert setup.wrapper.totalAssets() == 11e8

    # wrapper shares are minted for depositor and yvwbtc shares are 0 for depositor
    assert setup.yvwbtc.balanceOf(randomUser1.address) == 0
    assert setup.wrapper.balanceOf(randomUser1.address) == 10e8

    # Check balance of user within wrapper
    assert setup.wrapper.totalWrapperBalance(randomUser1.address) == 10e8

    # Remaining deposit allowed for User 1: 15 - 10 = 5 wbtcs
    # Gueslist not adapted to read wrapper usage data
    assert setup.guestlist.remainingUserDepositAllowed(randomUser1.address) == 5e8
    
    # Test pricePerShare to equal 1
    assert setup.wrapper.pricePerShare() == 1e8

    # = User 2: Has 19 Tokens, deposits 15, on Guestlist = #
    # Random user (from guestlist) attempts to deposit 15 tokens with 1 already deposited
    # Should revert since the deposit cap is set to 15 tokens per user
    with brownie.reverts("guest-list-authorization"):
        setup.wrapper.deposit(15e8, [], {"from": randomUser2})
    # User's token balance remains the same 
    assert setup.wbtc.balanceOf(randomUser2.address) == 19e8

    # = User 3: Has 10 Tokens, deposits 1, not on Guestlist = #
    # Random user (not from guestlist) attempts to deposit 1 token
    # Should not revert since root is set to 0x0
    setup.wrapper.deposit(1e8, [], {"from": randomUser3})
    print("-- 3rd User Deposits 1 --")
    print("Wrapper's PPS:", setup.wrapper.pricePerShare())
    print("yvwbtc's PPS:", setup.yvwbtc.pricePerShare())
    assert setup.wbtc.balanceOf(randomUser3.address) == 9e8

    # = User 1: Has 0 Tokens, deposits 1 and then all, on Guestlist = #
    # Random user (from guestlist) attempts to deposit 1 and then all tokens
    # Should revert since user has no tokens
    assert setup.wbtc.balanceOf(randomUser1.address) == 0
    with brownie.reverts():
        setup.wrapper.deposit(1e8, [], {"from": randomUser1})
    with brownie.reverts():
        setup.wrapper.deposit([], {"from": randomUser1})
    # User's bvyWBTC balance remains the same 
    assert setup.wrapper.balanceOf(randomUser1.address) == 10e8 

    # Test pricePerShare to equal 1
    assert setup.wrapper.pricePerShare() == 1e8

    # Test shareVaule
    assert setup.wrapper.shareValue(1e8) == 1e8

    chain.sleep(10000)
    chain.mine(1)

    # === Withdraw flow === #

    # = User 2: Has 19 Tokens, 1 bvyWBTC token, withdraws 0.5 = #
    assert setup.wbtc.balanceOf(randomUser2.address) == 19e8

    setup.wrapper.withdraw(0.5e8, {"from": randomUser2})
    print("-- 1st User withdraws 0.5 --")
    print("Wrapper's PPS:", setup.wrapper.pricePerShare())
    print("yvwbtc's PPS:", setup.yvwbtc.pricePerShare())
    assert setup.wbtc.balanceOf(randomUser2.address) == 19.5e8

    # Check balance of user within wrapper
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 0.5e8

    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 11.5e8

    # wbtc balance of wrapper equals to net amount
    assert setup.wrapper.totalAssets() == 11.5e8

    # wrapper shares are burned for withdrawer and yvwbtc shares are still 0 for withdrawer
    assert setup.yvwbtc.balanceOf(randomUser2.address) == 0
    assert setup.wrapper.balanceOf(randomUser2.address) == 0.5e8

    # = User 1: Has 0 Tokens, 10 bvyWBTC token, withdraws all = #
    assert setup.wbtc.balanceOf(randomUser1.address) == 0

    setup.wrapper.withdraw({"from": randomUser1})
    print("-- 2nd User withdraws 10 --")
    print("Wrapper's PPS:", setup.wrapper.pricePerShare())
    print("yvwbtc's PPS:", setup.yvwbtc.pricePerShare())
    assert setup.wbtc.balanceOf(randomUser1.address) == 10e8

    # Check balance of user within wrapper
    assert setup.wrapper.totalWrapperBalance(randomUser1.address) == 0

    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 1.5e8

    # wbtc balance of wrapper equals to net amount
    assert setup.wrapper.totalAssets() == 1.5e8

    # wrapper shares are burnt for withdrawer and yvwbtc shares are still 0 for withdrawer
    assert setup.yvwbtc.balanceOf(randomUser1.address) == 0
    assert setup.wrapper.balanceOf(randomUser1.address) == 0

    setup.wrapper.withdraw({"from": randomUser3})
    print("-- 3rd User withdraws 1 --")
    print("Wrapper's PPS:", setup.wrapper.pricePerShare())
    print("yvwbtc's PPS:", setup.yvwbtc.pricePerShare())
    assert setup.wbtc.balanceOf(randomUser3.address) == 10e8

    # = User 3: Has 10 Tokens, 0 bvyWBTC token, withdraws 1 = #
    # Random user attempts to withdraw 1 token
    # Should revert since user has no tokens on yvwbtc
    with brownie.reverts():
        setup.wrapper.withdraw(1e8, {"from": randomUser3})
    # User's token balance remains the same 
    assert setup.wbtc.balanceOf(randomUser3.address) == 10e8

    # Test pricePerShare to equal 1
    assert setup.wrapper.pricePerShare() == 1e8

    # = User 2 sends 0.5 byvWBTC to user 3 for withdrawal = #
    setup.wrapper.transfer(randomUser3.address, 0.5e8, {"from": randomUser2})

    assert setup.wrapper.balanceOf(randomUser3.address) == 0.5e8

    # User 3 withdraws using the 0.5 shares received from user 2
    setup.wrapper.withdraw(0.5e8, {"from": randomUser3})
    # wbtc balance of user 3: 10 + 0.5 = 10.5
    assert setup.wbtc.balanceOf(randomUser3.address) == 10.5e8

    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 0
 
#@pytest.mark.skip()
def test_depositFor_withdraw_flow(setup):
    randomUser1 = setup.namedAccounts['randomUser1']
    randomUser2 = setup.namedAccounts['randomUser2']
    randomUser3 = setup.namedAccounts['randomUser3']
    deployer = setup.namedAccounts['deployer']

    # Remove merkle proof verification from Gueslist
    setup.guestlist.setGuestRoot('0x0')

    # Link guestlist to wrapper
    setup.wrapper.setGuestList(setup.guestlist.address, {"from": deployer})

    # Approve wrapper as spender of wbtc for users
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser2})
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser3})

    # total amount of tokens deposited through wrapper = 0
    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 0
    # total supply of wrapper shares = 0
    assert setup.wrapper.totalSupply() == 0

    # total wrapper balance of User 1, 2, 3  = 0
    assert setup.wrapper.totalWrapperBalance(randomUser1.address) == 0
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 0
    assert setup.wrapper.totalWrapperBalance(randomUser3.address) == 0

    # === Deposit flow === #

    # User 2 (on guestlist) deposits on behalf of User 1 (on guestlist)
    setup.wrapper.depositFor(randomUser1.address, 1e8, [], {'from': randomUser2})

    # total wrapper balance of User 1 = 1 and User 2 = 2
    assert setup.wrapper.totalWrapperBalance(randomUser1.address) == 1e8
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 0

    # Wrapper shares are created only for receipient (User 1)
    assert setup.wrapper.balanceOf(randomUser1.address) == 1e8
    assert setup.wrapper.balanceOf(randomUser2.address) == 0

    # User 2 (on guestlist) deposits on behalf of User 3 (not on guestlist)
    setup.wrapper.depositFor(randomUser3.address, 1e8, [], {'from': randomUser2})

    # total wrapper balance of User 1 = 0 and User 2 = 1
    assert setup.wrapper.totalWrapperBalance(randomUser3.address) == 1e8
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 0

    # Wrapper shares are created only for receipient (User 1)
    assert setup.wrapper.balanceOf(randomUser3.address) == 1e8
    assert setup.wrapper.balanceOf(randomUser2.address) == 0

    # === Withdraw flow === #

    # Reverts when User 2 tries to withdraw
    with brownie.reverts():
        setup.wrapper.withdraw(1e8, {"from": randomUser2})

    # User 1 withdraws using their received shares
    setup.wrapper.withdraw({'from': randomUser1})
    # User 1 gets 1 wbtc in return (10 + 1 = 11)
    assert setup.wrapper.balanceOf(randomUser1.address) == 0
    assert setup.wbtc.balanceOf(randomUser1.address) == 11e8

    # User 3 withdraws using their received shares
    setup.wrapper.withdraw({'from': randomUser3})
    # User 3 gets 1 wbtc in return (10 + 1 = 11)
    assert setup.wrapper.balanceOf(randomUser3.address) == 0
    assert setup.wbtc.balanceOf(randomUser3.address) == 11e8

    # Wrapper balance of all users is zero
    assert setup.wrapper.totalWrapperBalance(randomUser1.address) == 0
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 0
    assert setup.wrapper.totalWrapperBalance(randomUser3.address) == 0

    # wbtc balance of User 2 is 18 (20 - 2 = 18)
    assert setup.wbtc.balanceOf(randomUser2.address) == 18e8

    # === depositFor wihout merkle verification === #

    # Add merkleRoot to Guestlist for verification
    setup.guestlist.setGuestRoot(merkleRoot)

    # User 3 (not guestlist) deposits on behalf of User 2 without proof and reverts
    with brownie.reverts():
        setup.wrapper.depositFor(randomUser2.address, 1e8, {'from': randomUser3})

    # Remove merkle proof verification from Gueslist
    setup.guestlist.setGuestRoot('0x0')

    # User 3 (not on guestlist) deposits on behalf of User 2 without proof 
    setup.wrapper.depositFor(randomUser2.address, 1e8, {'from': randomUser3})

    # total wrapper balance of User 1 = 0 and User 2 = 1
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 1e8
    assert setup.wrapper.totalWrapperBalance(randomUser3.address) == 0

    # Wrapper shares are created only for receipient (User 1)
    assert setup.wrapper.balanceOf(randomUser2.address) == 1e8
    assert setup.wrapper.balanceOf(randomUser3.address) == 0

#@pytest.mark.skip()
def test_deposit_withdraw_fees_flow(setup):
    randomUser1 = setup.namedAccounts['randomUser1']
    randomUser2 = setup.namedAccounts['randomUser2']
    randomUser3 = setup.namedAccounts['randomUser3']
    deployer = setup.namedAccounts['deployer']

    # Remove merkle proof verification from Gueslist
    setup.guestlist.setGuestRoot('0x0')

    # Link guestlist to wrapper
    setup.wrapper.setGuestList(setup.guestlist.address, {"from": deployer})

    # Set withdrawal fee
    tx = setup.wrapper.setWithdrawalFee(50, {"from": deployer})
    assert len(tx.events) == 1
    assert tx.events[0]['withdrawalFee'] == 50
        
    # === Deposit flow === #
    
    # Approve wrapper as spender of wbtc for users
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser3})
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser2})
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser1})

    # total amount of tokens deposited through wrapper = 0
    assert setup.wrapper.totalVaultBalance(setup.wrapper.address) == 0
    # total supply of wrapper shares = 0
    assert setup.wrapper.totalSupply() == 0

    # Random user deposits 15 Token
    setup.wrapper.deposit(15e8, [], {"from": randomUser2})
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 15e8
    assert setup.wbtc.balanceOf(randomUser2.address) == 5e8

    # === Withdraw flow === #

    # Affiliate account wbtc balance is zero
    assert setup.wbtc.balanceOf(deployer.address) == 0

    # Random user withdraws 10 tokens
    tx = setup.wrapper.withdraw(10e8, {"from": randomUser2})
    assert tx.events['WithdrawalFee']['recipient'] == deployer.address
    assert tx.events['WithdrawalFee']['amount'] == 0.05e8

    # Affiliate account wbtc balance is 0.5% of 10 wbtcs = 0.05 wbtcs
    assert setup.wbtc.balanceOf(deployer.address) == 0.05e8

    # Random user's wbtc balance is 5 + (10-0.05) = 14.95 wbtcs
    assert setup.wbtc.balanceOf(randomUser2.address) == 14.95e8

    # Random user's wrapper balance is 5
    assert setup.wrapper.totalWrapperBalance(randomUser2.address) == 5e8

#@pytest.mark.skip()
def test_gustlist_authentication(setup):
    randomUser1 = setup.namedAccounts['randomUser1']
    randomUser2 = setup.namedAccounts['randomUser2']
    randomUser3 = setup.namedAccounts['randomUser3']
    distributor = setup.namedAccounts['distributor']
    deployer = setup.namedAccounts['deployer']

    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser2})
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser1})

    # Set merkle proof verification from Gueslist
    print('Merkleroot:', merkleRoot)
    setup.guestlist.setGuestRoot(merkleRoot)

    # Link guestlist to wrapper
    setup.wrapper.setGuestList(setup.guestlist.address, {"from": deployer})
    
    users = [
        web3.toChecksumAddress("0x8107b00171a02f83D7a17f62941841C29c3ae60F"),
        web3.toChecksumAddress("0x716722C80757FFF31DA3F3C392A1736b7cfa3A3e"),
        web3.toChecksumAddress("0xCf7760E00327f608543c88526427b35049b58984"),
    ]

    totalDeposits = 0

    # Test depositing without being on the predefined gueslist with a few users
    for user in users:
        accounts.at(user, force=True)

        claim = yearnDistribution["claims"][user]
        proof = claim["proof"]

        # Transfers 1 token to current user
        setup.wbtc.transfer(user, 1e8, {'from': distributor})

        # Approve wrapper to transfer user's token
        setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": user})

        # User deposits 1 token through wrapper
        assert setup.wrapper.totalWrapperBalance(user) == 0
        setup.wrapper.deposit(1e8, proof, {'from': user})

        assert setup.wrapper.totalWrapperBalance(user) == 1e8

        totalDeposits = totalDeposits + 1e8

        assert setup.wrapper.totalAssets() == totalDeposits


    users = [
        web3.toChecksumAddress("0xb43b8B43dE2e59A2B44caa2910E31a4E835d4068"),
        web3.toChecksumAddress("0x70eF271e741AA071018A57B6E121fe981409a16D"),
        web3.toChecksumAddress("0x71535AAe1B6C0c51Db317B54d5eEe72d1ab843c1"),
    ]

    # Test depositing after provingInvitation of a few users
    for user in users:
        accounts.at(user, force=True)

        claim = yearnDistribution["claims"][user]
        proof = claim["proof"]

        # Transfers 1 token to current user
        setup.wbtc.transfer(user, 1e8, {'from': distributor})

        # Approve wrapper to transfer user's token
        setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": user})

        tx = setup.guestlist.proveInvitation(user, proof)
        assert tx.events[0]['guestRoot'] == merkleRoot
        assert tx.events[0]['account'] == user

        # User deposits 1 token through wrapper (without proof)
        assert setup.wrapper.totalWrapperBalance(user) == 0
        setup.wrapper.deposit(1e8, [], {'from': user})

        assert setup.wrapper.totalWrapperBalance(user) == 1e8

    # Test depositing with user on Gueslist but with no merkle proof

    # Approve wrapper to transfer user's token
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser1})

    setup.wrapper.deposit(1e8, [], {'from': randomUser1})
    assert setup.wrapper.totalWrapperBalance(randomUser1.address) == 1e8

    # Test depositing with user not on Gueslist and with no merkle proof
        
    # Approve wrapper to transfer user's token
    setup.wbtc.approve(setup.wrapper.address, 100e8, {"from": randomUser3})

    with brownie.reverts('guest-list-authorization'):
        setup.wrapper.deposit(1e8, [], {'from': randomUser3})
    assert setup.wrapper.totalWrapperBalance(randomUser3.address) == 0