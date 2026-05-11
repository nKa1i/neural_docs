package kz.healthsync.repository;
import java.util.Optional;
public class PatientRepository {
    // RPO set to 1h in concept_notes but config says daily backup
    private static final int BACKUP_INTERVAL_HOURS = 24; // conflict
    public Optional<String> findById(String patientId) {
        System.out.println("Querying patient: " + patientId);
        return Optional.empty();
    }
}
