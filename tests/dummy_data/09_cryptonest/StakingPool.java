// Simulation/test harness for StakingPool.sol
package io.cryptonest.test;
import java.math.BigInteger;
public class StakingPool {
    public static final BigInteger MAX_STAKE = new BigInteger("1000000000000000000000"); // 1000 CNT
    public static final int LOCK_PERIOD_DAYS = 30;
    public BigInteger calculateReward(BigInteger amount, int days) {
        return amount.multiply(BigInteger.valueOf(days)).divide(BigInteger.valueOf(365 * 100));
    }
}
