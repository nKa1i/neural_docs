# Спецификация смарт-контрактов CryptoNest

## Контракты
- StakingPool.sol — стейкинг токенов CNT
- LendingVault.sol — лендинг под залог ETH
- GovernanceToken.sol — токен управления CNT

## Стандарты
- ERC-20 для CNT
- ERC-4626 для Vault

## Безопасность
- Reentrancy Guard на все внешние вызовы
- Timelock 48ч для административных действий
- Multi-sig 3-of-5 для treasury

## Риски
- Flash loan атаки на LendingVault
- Oracle manipulation (использовать Chainlink)
