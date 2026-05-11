package kz.swiftpay.service;
import java.math.BigDecimal;
public class TransactionService {
    private static final BigDecimal MAX_TX = new BigDecimal("5000000");
    private static final int TIMEOUT_MS = 3000;
    public boolean processTransfer(String from, String to, BigDecimal amount) {
        if (amount.compareTo(MAX_TX) > 0) return false;
        System.out.println("Transfer " + from + " -> " + to + " : " + amount);
        return true;
    }
}
