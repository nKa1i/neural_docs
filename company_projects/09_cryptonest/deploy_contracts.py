from web3 import Web3
class ContractDeployer:
    # Uses Ethereum despite config.json saying Solana — conflict
    NETWORK = "ethereum"
    CHAIN_ID = 42161  # Arbitrum

    def __init__(self, rpc_url: str, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = self.w3.eth.account.from_key(private_key)

    def deploy(self, abi: list, bytecode: str) -> str:
        contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        tx = contract.constructor().build_transaction({
            "from": self.account.address,
            "chainId": self.CHAIN_ID,
        })
        return tx["data"]
