#!/usr/bin/env python3
import argparse
import json
import socket
import sys
import time
from web3 import Web3, exceptions
from contract import pricefeed, wrb
from config import load_config

# Post a data request to the post_dr method of the WRB contract
def handle_requestUpdate(w3, pricefeedcontract, wrbcontract, account_addr, gas, gas_price):

    # Check that the accout has enough balance
    balance = w3.eth.getBalance(account_addr)
    if balance == 0:
        raise Exception("Account does not have any funds")

    print(f"Got {balance} wei")
    print(f"Gas price: {gas_price}")
    reward = wrbcontract.functions.estimateGasCost(gas_price).call()

    # Hardcoded gas since it does not estimate well
    try:
      dr_id = pricefeedcontract.functions.requestUpdate().transact({
        "from": account_addr,
        "gas": gas,
        "gasPrice": gas_price,
        "value": reward
      })
    except:
      print(f"Failed when calling to", account_addr, ".requestUpdate(). Retrying in next iteration.")
      return False

    try:     
      # Get receipt of the transaction   
      receipt = w3.eth.waitForTransactionReceipt(dr_id, 120, 5)

    except exceptions.TimeExhausted:
      print(
        f"Transaction timeout reached and dr post not included in the block. Retrying in next iteration."
      )
      return False

    # Check if transaction was succesful
    if receipt['status']: 
      print(
        f"Data request for contract {pricefeedcontract.address} posted successfully! Ethereum transaction hash:\n{dr_id.hex()}"
      )
    else:
      print(
        f"Data request for contract {pricefeedcontract.address} post transaction failed. Retrying in next iteration"
      )  
    return receipt['status']

def handle_read_data_request(w3, pricefeedcontract, account_addr, gas, gas_price):
    # We got a Read DR request!
    print(f"Got data complete request")

    # Check that the accout has enough balance
    balance = w3.eth.getBalance(account_addr)
    if balance == 0:
        raise Exception("Account does not have any funds")

    print(f"Got {balance} wei")
    print(F"Gas price: {gas_price}")
        
    # Hardcoded gas since it does not estimate well
    try:
      read_id = pricefeedcontract.functions.completeUpdate().transact({
        "from": account_addr,
        "gas": gas,
        "gasPrice": gas_price
      })
    except:
      print(f"Failed when calling to", account_addr, ".completeUpdate(). Retrying in next iteration.")
      return False

    try:     
      # Get receipt of the transaction
      receipt = w3.eth.waitForTransactionReceipt(read_id , 60, 5)
    except exceptions.TimeExhausted:
      print(
        f"Transaction timeout reached and result read not included in the block. Retrying in next iteration."
      )
      return False
    
    # Check if transaction was succesful
    if receipt['status']:
      try:
        price = pricefeedcontract.functions.lastPrice().call()
        print(f"Completed price update for contract {pricefeedcontract.address}. Latest price is {price}")
      except:
        # At this point we know the transaction ocurred but we could not get the latest state. Retry later.
        log_exception_state(pricefeedcontract.address)
        return True
    else:
      print(
        f"Read DR result failed. Retrying in next iteration."
      )  
    return receipt['status']

def log_exception_state(addr):
  # log the error and wait 5 seconds before next iteration
  print("Error getting the state of contract", addr, ". Re-trying in next iterations")
  time.sleep(1)


def log_loop(w3, wrbcontract, pricefeedcontracts, account, gas, gas_price, poll_interval):

    print("Checking status of contracts...")
    while True:
      contracts_information = []
      # Get current Id of the DR
      for feed in pricefeedcontracts:
        try:
          currentId = feed.functions.lastRequestId().call()
          contract_status = feed.functions.pending().call()
          contracts_information.append({
            "feed" : feed,
            "status" : contract_status,
            "currentId" : currentId
          })
          print("Current Id for contract %s is %d" % (feed.address, currentId))
        except:
          # Error calling the state of the contract. Wait and re-try
          log_exception_state(feed.address)
          continue

      # Check the state of the contracts
      for element in contracts_information:

        # Check if the result is ready
        if element["status"]:

          try:
            dr_tx_hash = wrbcontract.functions.readDrTxHash(element["currentId"]).call()
          except: 
            # Error calling the state of the contract. Wait and re-try
            log_exception_state(wrbcontract.address)
            continue

          if dr_tx_hash != 0:
            # Read the result
            success = handle_read_data_request(w3, element["feed"], account, gas, gas_price)
            if success:
              # Send  a new request
              handle_requestUpdate(w3, element["feed"], wrbcontract, account, gas, gas_price)
          else:
            # Result not ready. Wait for following group
            print("Waiting in contract %s for Result for DR %d" % (element["feed"].address, element["currentId"]))
        else:
          # Contract waiting for next request to be sent
          handle_requestUpdate(w3, element["feed"], wrbcontract, account, gas, gas_price)

      # Loop
      time.sleep(poll_interval)


def main(args):
    # Load the config from the config file:
    config = load_config(args.config_file)
    # Load providers:
    provider = args.provider if args.provider else  config['network']['provider']
    # Open web3 provider from the arguments provided:
    w3 = Web3(Web3.HTTPProvider(provider, request_kwargs={'timeout': 60}))
    # Load the pricefeed contract:
    pricefeedcontracts = pricefeed(w3, config)
    # Get account:
    account = config["account"]["address"]
    # Get gas limit, defaults to 4 million units:
    gas = config["network"].get("gas", 4000000)
    # Get gas price, defaults to 100 gwei:
    gas_price = config["network"].get("gas_price", 100000000000) 
    # Load the WRB contract:
    wrbcontract = wrb(w3, config)
    current_block = w3.eth.blockNumber
    print(f"Current block: {current_block}")

    # Call main loop
    log_loop(w3, wrbcontract, pricefeedcontracts, account, gas, gas_price, args.poll_interval)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Connect to an Ethereum provider.')
    parser.add_argument('--config_file', dest='config_file', action='store', required=True,
                    help='provide the config toml file with the contract and provider details')
    parser.add_argument('--poll_interval', dest='poll_interval', action='store', type=int, required=False, default=60, 
                    help='seconds after which the script triggers the state of the smart contract')
    parser.add_argument('--provider', dest='provider', action='store', required=False,
                    help='web3 provider to which the poller should connect. If not provided it reads from config')

    args = parser.parse_args()
    main(args)
