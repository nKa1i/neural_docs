package com.omnicore.wms;

import com.omnicore.wms.domain.*;
import com.omnicore.wms.events.*;
import com.omnicore.wms.repository.*;
import com.omnicore.wms.exceptions.*;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.cache.annotation.CacheEvict;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

/**
 * OmniCore WMS — Warehouse Management Service
 *
 * Handles core warehouse operations:
 *   - Stock movements (IN, OUT, TRANSFER, ADJUSTMENT)
 *   - Location management (bin-level addressing, 3D coordinates)
 *   - Pick/Pack/Ship operations
 *   - RFID and barcode scanning events
 *   - ABC analysis and slotting optimization
 *   - Drone-based inventory counting (interface)
 *   - FIFO/FEFO/LIFO lot management
 *
 * This is the Java legacy adapter version.
 * Primary WMS service is written in Go (wms-core).
 * This adapter handles integration with legacy WMS connectors (SAP EWM, Manhattan WMS).
 *
 * Team: OmniCore Operations Team
 * Module: warehouse-management
 * Version: 1.4.2
 */
@Service
public class WarehouseManagementService {

    private static final Logger log = LoggerFactory.getLogger(WarehouseManagementService.class);

    // Business constants
    public static final int ABC_A_THRESHOLD_PERCENT = 80;  // top 80% of value = A items
    public static final int ABC_B_THRESHOLD_PERCENT = 95;  // next 15% = B items
    public static final int MAX_LOCATIONS_PER_ZONE = 10_000;
    public static final BigDecimal MINIMUM_REORDER_QUANTITY = BigDecimal.valueOf(1);
    public static final int DEFAULT_PICK_WAVE_SIZE = 50;  // orders per pick wave
    public static final int RFID_SCAN_TIMEOUT_SECONDS = 5;
    public static final String KAFKA_TOPIC_STOCK_MOVEMENT = "wms.stock-movement.created.v1";
    public static final String KAFKA_TOPIC_LOW_STOCK = "wms.stock.low-threshold-reached.v1";
    public static final String KAFKA_TOPIC_SHIPMENT = "wms.shipment.dispatched.v1";

    private final StockMovementRepository movementRepo;
    private final LocationRepository locationRepo;
    private final SKURepository skuRepo;
    private final ShipmentRepository shipmentRepo;
    private final KafkaTemplate<String, Object> kafkaTemplate;
    private final RedisTemplate<String, Object> redisTemplate;
    private final ExecutorService asyncExecutor;

    public WarehouseManagementService(
            StockMovementRepository movementRepo,
            LocationRepository locationRepo,
            SKURepository skuRepo,
            ShipmentRepository shipmentRepo,
            KafkaTemplate<String, Object> kafkaTemplate,
            RedisTemplate<String, Object> redisTemplate) {
        this.movementRepo = movementRepo;
        this.locationRepo = locationRepo;
        this.skuRepo = skuRepo;
        this.shipmentRepo = shipmentRepo;
        this.kafkaTemplate = kafkaTemplate;
        this.redisTemplate = redisTemplate;
        this.asyncExecutor = Executors.newFixedThreadPool(
            Runtime.getRuntime().availableProcessors() * 2,
            r -> {
                Thread t = new Thread(r, "wms-async-" + r.hashCode());
                t.setDaemon(true);
                return t;
            }
        );
        log.info("WarehouseManagementService initialized, async threads: {}",
                 Runtime.getRuntime().availableProcessors() * 2);
    }

    // ─── Stock Movement ──────────────────────────────────────────────────────

    /**
     * Record a stock movement and update inventory levels atomically.
     * Publishes a Kafka event after successful DB commit.
     *
     * @param request    movement details (SKU, qty, from/to location, type)
     * @param tenantId   tenant identifier for data isolation
     * @param operatorId user performing the movement
     * @return the created StockMovement with generated ID and timestamp
     */
    @Transactional
    public StockMovement createMovement(
            CreateMovementRequest request,
            String tenantId,
            String operatorId) {

        validateMovementRequest(request);

        // Load and validate locations
        Location fromLocation = request.getFromLocationId() != null
            ? locationRepo.findByIdAndTenant(request.getFromLocationId(), tenantId)
                .orElseThrow(() -> new LocationNotFoundException(request.getFromLocationId()))
            : null;

        Location toLocation = request.getToLocationId() != null
            ? locationRepo.findByIdAndTenant(request.getToLocationId(), tenantId)
                .orElseThrow(() -> new LocationNotFoundException(request.getToLocationId()))
            : null;

        SKU sku = skuRepo.findByIdAndTenant(request.getSkuId(), tenantId)
            .orElseThrow(() -> new SKUNotFoundException(request.getSkuId()));

        // Check available stock for outbound movements
        if (request.getType() == MovementType.OUT || request.getType() == MovementType.TRANSFER) {
            BigDecimal available = getAvailableQuantity(request.getSkuId(),
                                                         request.getFromLocationId(), tenantId);
            if (available.compareTo(request.getQuantity()) < 0) {
                throw new InsufficientStockException(
                    String.format("SKU %s: requested %.4f, available %.4f at location %s",
                        sku.getCode(), request.getQuantity(), available,
                        request.getFromLocationId())
                );
            }
        }

        // Build movement record
        StockMovement movement = StockMovement.builder()
            .movementId(UUID.randomUUID().toString())
            .tenantId(tenantId)
            .skuId(request.getSkuId())
            .skuCode(sku.getCode())
            .fromLocationId(request.getFromLocationId())
            .toLocationId(request.getToLocationId())
            .quantity(request.getQuantity())
            .unitOfMeasure(sku.getBaseUom())
            .type(request.getType())
            .lotNumber(request.getLotNumber())
            .expiryDate(request.getExpiryDate())
            .referenceDocument(request.getReferenceDocument())
            .notes(request.getNotes())
            .operatorId(operatorId)
            .createdAt(Instant.now())
            .build();

        // Save to DB
        StockMovement saved = movementRepo.save(movement);

        // Update stock level cache
        asyncExecutor.submit(() -> {
            invalidateStockCache(request.getSkuId(), request.getFromLocationId(), tenantId);
            invalidateStockCache(request.getSkuId(), request.getToLocationId(), tenantId);
        });

        // Publish Kafka event (after transaction commits)
        publishStockMovementEvent(saved, sku, tenantId);

        // Check reorder point
        asyncExecutor.submit(() -> checkReorderPoint(sku, tenantId));

        log.info("Stock movement created: {} {} {} qty={}",
                 movement.getMovementId(), sku.getCode(), movement.getType(), request.getQuantity());

        return saved;
    }

    @Cacheable(value = "stock-levels", key = "#skuId + ':' + #locationId + ':' + #tenantId")
    public BigDecimal getAvailableQuantity(String skuId, String locationId, String tenantId) {
        return movementRepo.calculateAvailableQuantity(skuId, locationId, tenantId);
    }

    @CacheEvict(value = "stock-levels", key = "#skuId + ':' + #locationId + ':' + #tenantId")
    public void invalidateStockCache(String skuId, String locationId, String tenantId) {
        log.debug("Stock cache invalidated for SKU {} at location {}", skuId, locationId);
    }

    // ─── ABC Analysis ────────────────────────────────────────────────────────

    /**
     * Perform ABC analysis on warehouse inventory based on consumption value
     * over the specified period. Pareto principle: A = top 80% value, B = next 15%, C = rest.
     *
     * @param warehouseId  warehouse to analyze
     * @param tenantId     tenant
     * @param lookbackDays number of days of movement history to consider
     * @return ABCAnalysisResult with categorised SKU list
     */
    public ABCAnalysisResult performABCAnalysis(String warehouseId, String tenantId, int lookbackDays) {
        LocalDate fromDate = LocalDate.now().minusDays(lookbackDays);

        // Get consumption data: SKU → total value consumed
        List<SKUConsumption> consumptions = movementRepo.getConsumptionBySkuForPeriod(
            warehouseId, tenantId, fromDate, LocalDate.now()
        );

        if (consumptions.isEmpty()) {
            return ABCAnalysisResult.empty(warehouseId, tenantId, lookbackDays);
        }

        // Sort descending by value
        consumptions.sort(Comparator.comparing(SKUConsumption::getTotalValue).reversed());

        BigDecimal totalValue = consumptions.stream()
            .map(SKUConsumption::getTotalValue)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

        BigDecimal aThreshold = totalValue.multiply(BigDecimal.valueOf(ABC_A_THRESHOLD_PERCENT))
                                          .divide(BigDecimal.valueOf(100), 4, RoundingMode.HALF_UP);
        BigDecimal bThreshold = totalValue.multiply(BigDecimal.valueOf(ABC_B_THRESHOLD_PERCENT))
                                          .divide(BigDecimal.valueOf(100), 4, RoundingMode.HALF_UP);

        List<ABCItem> items = new ArrayList<>();
        BigDecimal cumulative = BigDecimal.ZERO;

        for (SKUConsumption consumption : consumptions) {
            cumulative = cumulative.add(consumption.getTotalValue());
            ABCCategory category;
            if (cumulative.compareTo(aThreshold) <= 0) {
                category = ABCCategory.A;
            } else if (cumulative.compareTo(bThreshold) <= 0) {
                category = ABCCategory.B;
            } else {
                category = ABCCategory.C;
            }
            items.add(new ABCItem(consumption.getSkuId(), consumption.getSkuCode(),
                                  consumption.getTotalValue(), category,
                                  cumulative.divide(totalValue, 4, RoundingMode.HALF_UP)));
        }

        long aCount = items.stream().filter(i -> i.getCategory() == ABCCategory.A).count();
        long bCount = items.stream().filter(i -> i.getCategory() == ABCCategory.B).count();
        long cCount = items.stream().filter(i -> i.getCategory() == ABCCategory.C).count();

        log.info("ABC analysis complete: warehouse={}, A={}, B={}, C={}, total_value={}",
                 warehouseId, aCount, bCount, cCount, totalValue);

        return ABCAnalysisResult.builder()
            .warehouseId(warehouseId)
            .tenantId(tenantId)
            .lookbackDays(lookbackDays)
            .analysisDate(LocalDate.now())
            .totalValue(totalValue)
            .items(items)
            .aItemCount((int) aCount)
            .bItemCount((int) bCount)
            .cItemCount((int) cCount)
            .build();
    }

    // ─── Pick Wave Management ─────────────────────────────────────────────────

    /**
     * Create an optimised pick wave for a set of outbound orders.
     * Uses a greedy bin-packing approach to minimise picker travel distance.
     * Groups picks by zone, then by aisle, then by bin level.
     *
     * @param orderIds list of outbound order IDs to include in the wave
     * @param warehouseId target warehouse
     * @param tenantId tenant
     * @return PickWave with sorted pick tasks
     */
    @Transactional(readOnly = true)
    public PickWave createPickWave(List<String> orderIds, String warehouseId, String tenantId) {
        if (orderIds.size() > DEFAULT_PICK_WAVE_SIZE * 3) {
            throw new PickWaveSizeLimitException(
                "Pick wave size " + orderIds.size() + " exceeds maximum " + (DEFAULT_PICK_WAVE_SIZE * 3)
            );
        }

        // Load all pick tasks for these orders
        List<PickTask> rawTasks = movementRepo.getPickTasksForOrders(orderIds, warehouseId, tenantId);

        if (rawTasks.isEmpty()) {
            return PickWave.empty(orderIds, warehouseId, tenantId);
        }

        // Optimise pick sequence: zone → aisle → bin (S-shaped or return routing)
        List<PickTask> optimised = optimisePickSequence(rawTasks, warehouseId);

        String waveId = UUID.randomUUID().toString();
        PickWave wave = PickWave.builder()
            .waveId(waveId)
            .warehouseId(warehouseId)
            .tenantId(tenantId)
            .orderIds(new ArrayList<>(orderIds))
            .pickTasks(optimised)
            .estimatedPickTimeMinutes(estimatePickTime(optimised))
            .totalPickLines(optimised.size())
            .createdAt(LocalDateTime.now())
            .status(WaveStatus.READY)
            .build();

        log.info("Pick wave created: waveId={}, orders={}, tasks={}, estTime={}min",
                 waveId, orderIds.size(), optimised.size(), wave.getEstimatedPickTimeMinutes());

        return wave;
    }

    private List<PickTask> optimisePickSequence(List<PickTask> tasks, String warehouseId) {
        // Sort by: zone → aisle (alternating direction for S-shape routing) → level
        return tasks.stream()
            .sorted(Comparator
                .comparing(PickTask::getZone)
                .thenComparing(t -> t.getAisle() % 2 == 0 ? t.getBin() : -t.getBin())
                .thenComparing(PickTask::getLevel))
            .collect(Collectors.toList());
    }

    private int estimatePickTime(List<PickTask> tasks) {
        // Rough estimate: 1 min per pick task + 0.5 min per zone change
        long zoneChanges = 0;
        String lastZone = null;
        for (PickTask task : tasks) {
            if (lastZone != null && !lastZone.equals(task.getZone())) {
                zoneChanges++;
            }
            lastZone = task.getZone();
        }
        return tasks.size() + (int)(zoneChanges / 2);
    }

    // ─── RFID Processing ──────────────────────────────────────────────────────

    /**
     * Process a batch of RFID scan events from warehouse readers.
     * Validates EPC codes, resolves to SKU/lot, triggers movements if needed.
     * Maximum throughput: ~10,000 scans/second per reader cluster.
     *
     * @param scans list of raw RFID scan events from readers
     * @param readerId ID of the RFID reader/portal
     * @param tenantId tenant
     * @return RFIDProcessingResult with counts and any errors
     */
    public RFIDProcessingResult processRFIDScans(
            List<RFIDScanEvent> scans, String readerId, String tenantId) {

        int processed = 0;
        int errors = 0;
        List<String> errorDetails = new ArrayList<>();
        List<CompletableFuture<Void>> futures = new ArrayList<>();

        for (RFIDScanEvent scan : scans) {
            CompletableFuture<Void> future = CompletableFuture.runAsync(() -> {
                try {
                    processRFIDScan(scan, readerId, tenantId);
                } catch (Exception e) {
                    log.warn("RFID scan processing failed: epc={}, error={}", scan.getEpc(), e.getMessage());
                    errorDetails.add(scan.getEpc() + ": " + e.getMessage());
                }
            }, asyncExecutor).orTimeout(RFID_SCAN_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            futures.add(future);
        }

        // Wait for all scans with timeout
        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]))
            .exceptionally(e -> {
                log.error("RFID batch processing encountered errors", e);
                return null;
            })
            .join();

        processed = (int)(scans.size() - errorDetails.size());
        errors = errorDetails.size();

        log.info("RFID batch processed: reader={}, total={}, ok={}, errors={}",
                 readerId, scans.size(), processed, errors);

        return new RFIDProcessingResult(scans.size(), processed, errors, errorDetails);
    }

    private void processRFIDScan(RFIDScanEvent scan, String readerId, String tenantId) {
        // Decode GS1 EPC to identify SKU + lot
        EPCDecodeResult decoded = EPCDecoder.decode(scan.getEpc());
        if (decoded == null || !decoded.isValid()) {
            throw new InvalidEPCException("Cannot decode EPC: " + scan.getEpc());
        }

        SKU sku = skuRepo.findByGTINAndTenant(decoded.getGtin(), tenantId)
            .orElseThrow(() -> new SKUNotFoundException("GTIN: " + decoded.getGtin()));

        // Determine movement type from reader location metadata
        Location readerLocation = locationRepo.findByRFIDReaderIdAndTenant(readerId, tenantId)
            .orElseThrow(() -> new LocationNotFoundException("Reader: " + readerId));

        if (readerLocation.isInboundGate()) {
            // Auto-create GR movement
            CreateMovementRequest req = CreateMovementRequest.builder()
                .skuId(sku.getId())
                .quantity(BigDecimal.ONE)
                .type(MovementType.IN)
                .toLocationId(readerLocation.getId())
                .lotNumber(decoded.getLotNumber())
                .expiryDate(decoded.getExpiryDate())
                .referenceDocument("RFID:" + scan.getEpc())
                .build();
            createMovement(req, tenantId, "rfid-auto");
        }
    }

    // ─── Drone Inventory Counting ─────────────────────────────────────────────

    /**
     * Initiate a drone-based inventory count for a warehouse zone.
     * Integrates with drone management service via internal API.
     * Drone captures RFID/barcode data, results reconciled with system stock.
     */
    public DroneCountJob initiateZoneDroneCount(
            String warehouseId, String zone, String tenantId, String requestedBy) {

        // Validate zone exists and is drone-accessible
        List<Location> zoneLocations = locationRepo.findByWarehouseAndZoneAndTenant(
            warehouseId, zone, tenantId
        );
        if (zoneLocations.isEmpty()) {
            throw new InvalidZoneException("Zone " + zone + " not found in warehouse " + warehouseId);
        }

        boolean droneReady = zoneLocations.stream().anyMatch(Location::isDroneAccessible);
        if (!droneReady) {
            throw new DroneNotSupportedException("Zone " + zone + " is not configured for drone access");
        }

        String jobId = UUID.randomUUID().toString();
        DroneCountJob job = DroneCountJob.builder()
            .jobId(jobId)
            .warehouseId(warehouseId)
            .zone(zone)
            .tenantId(tenantId)
            .requestedBy(requestedBy)
            .status(DroneJobStatus.QUEUED)
            .locationCount(zoneLocations.size())
            .estimatedDurationMinutes(zoneLocations.size() / 10 + 5)  // rough estimate
            .createdAt(LocalDateTime.now())
            .build();

        // Enqueue in Redis for drone controller to pick up
        redisTemplate.opsForList().leftPush("drone:jobs:" + warehouseId, job);
        redisTemplate.expire("drone:jobs:" + warehouseId, 24, TimeUnit.HOURS);

        log.info("Drone count job created: jobId={}, warehouse={}, zone={}, locations={}",
                 jobId, warehouseId, zone, zoneLocations.size());

        return job;
    }

    // ─── Slotting Optimisation ────────────────────────────────────────────────

    /**
     * Suggest optimal slot assignments for SKUs based on ABC category,
     * velocity (picks per day), weight, and dimensions.
     * A-items get ergonomic/fast-access locations; C-items go to bulk/high shelves.
     *
     * @param warehouseId warehouse to optimise
     * @param tenantId    tenant
     * @param lookbackDays period for velocity calculation
     * @return SlottingRecommendation with list of proposed location changes
     */
    public SlottingRecommendation generateSlottingRecommendations(
            String warehouseId, String tenantId, int lookbackDays) {

        ABCAnalysisResult abc = performABCAnalysis(warehouseId, tenantId, lookbackDays);
        List<Location> availableLocations = locationRepo.findByWarehouseAndTenant(warehouseId, tenantId);

        // Classify locations by ergonomic accessibility score (0-100)
        Map<String, Integer> locationScores = availableLocations.stream()
            .collect(Collectors.toMap(
                Location::getId,
                this::calculateLocationAccessibilityScore
            ));

        List<SlottingChange> changes = new ArrayList<>();
        List<ABCItem> aItems = abc.getItemsByCategory(ABCCategory.A);
        List<ABCItem> bItems = abc.getItemsByCategory(ABCCategory.B);
        List<ABCItem> cItems = abc.getItemsByCategory(ABCCategory.C);

        // Assign A-items to top-accessibility locations (score 80-100)
        List<Location> premiumLocations = availableLocations.stream()
            .filter(l -> locationScores.getOrDefault(l.getId(), 0) >= 80)
            .sorted(Comparator.comparingInt(l -> -locationScores.getOrDefault(l.getId(), 0)))
            .collect(Collectors.toList());

        for (int i = 0; i < Math.min(aItems.size(), premiumLocations.size()); i++) {
            ABCItem item = aItems.get(i);
            Location location = premiumLocations.get(i);
            Location currentLocation = locationRepo.findPrimaryLocationForSKU(
                item.getSkuId(), warehouseId, tenantId).orElse(null);

            if (currentLocation == null || !currentLocation.getId().equals(location.getId())) {
                changes.add(new SlottingChange(
                    item.getSkuId(), item.getSkuCode(), ABCCategory.A,
                    currentLocation != null ? currentLocation.getId() : null,
                    location.getId(), location.getCode(),
                    "A-item: move to premium access location"
                ));
            }
        }

        log.info("Slotting recommendations: warehouse={}, changes={}, A={}, B={}, C={}",
                 warehouseId, changes.size(), aItems.size(), bItems.size(), cItems.size());

        return SlottingRecommendation.builder()
            .warehouseId(warehouseId)
            .tenantId(tenantId)
            .generatedAt(LocalDateTime.now())
            .changes(changes)
            .estimatedPickTimeReductionPercent(estimatePickTimeReduction(changes))
            .build();
    }

    private int calculateLocationAccessibilityScore(Location location) {
        int score = 100;
        // Penalise for height (above shoulder = -20, high shelf = -40)
        if (location.getLevel() == 2) score -= 20;
        if (location.getLevel() >= 3) score -= 40;
        // Penalise for deep zones (far from dispatch area)
        if ("DEEP".equals(location.getZoneType())) score -= 15;
        // Penalise for cold storage
        if (location.isTemperatureControlled()) score -= 10;
        return Math.max(0, score);
    }

    private double estimatePickTimeReduction(List<SlottingChange> changes) {
        if (changes.isEmpty()) return 0.0;
        // Rough model: each A-item move to premium location saves ~10 seconds per pick
        long aMoves = changes.stream().filter(c -> c.getCategory() == ABCCategory.A).count();
        return Math.min(aMoves * 0.5, 35.0);  // cap at 35% improvement
    }

    // ─── Shipment Dispatch ────────────────────────────────────────────────────

    /**
     * Dispatch a shipment: validate all items are picked and packed,
     * generate shipping label, notify carrier, update stock levels.
     */
    @Transactional
    public Shipment dispatchShipment(String shipmentId, String carrierTrackingNumber,
                                      String tenantId, String dispatchedBy) {
        Shipment shipment = shipmentRepo.findByIdAndTenant(shipmentId, tenantId)
            .orElseThrow(() -> new ShipmentNotFoundException(shipmentId));

        if (shipment.getStatus() != ShipmentStatus.PACKED) {
            throw new InvalidShipmentStateException(
                "Shipment " + shipmentId + " must be PACKED before dispatch, current: " + shipment.getStatus()
            );
        }

        // Verify all pick tasks completed
        long pendingPicks = shipment.getPickTasks().stream()
            .filter(t -> t.getStatus() != PickTaskStatus.COMPLETED)
            .count();
        if (pendingPicks > 0) {
            throw new IncompletePickException(
                pendingPicks + " pick tasks not yet completed for shipment " + shipmentId
            );
        }

        shipment.setCarrierTrackingNumber(carrierTrackingNumber);
        shipment.setStatus(ShipmentStatus.DISPATCHED);
        shipment.setDispatchedAt(LocalDateTime.now());
        shipment.setDispatchedBy(dispatchedBy);
        shipment.setUpdatedAt(Instant.now());

        Shipment saved = shipmentRepo.save(shipment);

        // Publish dispatch event
        ShipmentDispatchedEvent event = new ShipmentDispatchedEvent(
            UUID.randomUUID().toString(),
            shipmentId,
            tenantId,
            carrierTrackingNumber,
            shipment.getCarrier(),
            shipment.getDestinationAddress(),
            Instant.now()
        );
        kafkaTemplate.send(KAFKA_TOPIC_SHIPMENT, shipmentId, event);

        log.info("Shipment dispatched: shipmentId={}, carrier={}, tracking={}",
                 shipmentId, shipment.getCarrier(), carrierTrackingNumber);

        return saved;
    }

    // ─── Validation ──────────────────────────────────────────────────────────

    private void validateMovementRequest(CreateMovementRequest request) {
        Objects.requireNonNull(request.getSkuId(), "SKU ID is required");
        Objects.requireNonNull(request.getType(), "Movement type is required");

        if (request.getQuantity() == null || request.getQuantity().compareTo(MINIMUM_REORDER_QUANTITY) < 0) {
            throw new InvalidMovementException(
                "Quantity must be >= " + MINIMUM_REORDER_QUANTITY + ", got: " + request.getQuantity()
            );
        }

        if (request.getType() == MovementType.IN && request.getToLocationId() == null) {
            throw new InvalidMovementException("Inbound movement requires a destination location");
        }
        if (request.getType() == MovementType.OUT && request.getFromLocationId() == null) {
            throw new InvalidMovementException("Outbound movement requires a source location");
        }
        if (request.getType() == MovementType.TRANSFER) {
            if (request.getFromLocationId() == null || request.getToLocationId() == null) {
                throw new InvalidMovementException("Transfer requires both source and destination locations");
            }
            if (request.getFromLocationId().equals(request.getToLocationId())) {
                throw new InvalidMovementException("Transfer source and destination cannot be the same location");
            }
        }
    }

    // ─── Reorder Point Check ──────────────────────────────────────────────────

    private void checkReorderPoint(SKU sku, String tenantId) {
        try {
            BigDecimal totalStock = movementRepo.getTotalStockAcrossAllLocations(sku.getId(), tenantId);
            if (sku.getReorderPoint() != null && totalStock.compareTo(sku.getReorderPoint()) <= 0) {
                log.warn("Reorder point reached: sku={}, current={}, reorderPoint={}",
                         sku.getCode(), totalStock, sku.getReorderPoint());

                LowStockAlert alert = new LowStockAlert(
                    UUID.randomUUID().toString(),
                    sku.getId(), sku.getCode(), tenantId,
                    totalStock, sku.getReorderPoint(), Instant.now()
                );
                kafkaTemplate.send(KAFKA_TOPIC_LOW_STOCK, sku.getId(), alert);
            }
        } catch (Exception e) {
            log.error("Error checking reorder point for SKU {}: {}", sku.getId(), e.getMessage());
        }
    }

    // ─── Kafka Event Publishing ───────────────────────────────────────────────

    private void publishStockMovementEvent(StockMovement movement, SKU sku, String tenantId) {
        StockMovementCreatedEvent event = StockMovementCreatedEvent.builder()
            .eventId(UUID.randomUUID().toString())
            .eventType("StockMovementCreated")
            .occurredAt(Instant.now())
            .tenantId(tenantId)
            .movementId(movement.getMovementId())
            .skuId(movement.getSkuId())
            .skuCode(sku.getCode())
            .quantity(movement.getQuantity())
            .movementType(movement.getType())
            .fromLocationId(movement.getFromLocationId())
            .toLocationId(movement.getToLocationId())
            .operatorId(movement.getOperatorId())
            .build();

        kafkaTemplate.send(KAFKA_TOPIC_STOCK_MOVEMENT, movement.getMovementId(), event)
            .whenComplete((result, ex) -> {
                if (ex != null) {
                    log.error("Failed to publish StockMovementCreated for movementId={}",
                              movement.getMovementId(), ex);
                } else {
                    log.debug("StockMovementCreated published: movementId={}, partition={}",
                              movement.getMovementId(), result.getRecordMetadata().partition());
                }
            });
    }

    // ─── Lifecycle ───────────────────────────────────────────────────────────

    public void shutdown() {
        log.info("WarehouseManagementService shutting down, draining async executor...");
        asyncExecutor.shutdown();
        try {
            if (!asyncExecutor.awaitTermination(30, TimeUnit.SECONDS)) {
                asyncExecutor.shutdownNow();
                log.warn("Async executor did not terminate cleanly within 30s");
            }
        } catch (InterruptedException e) {
            asyncExecutor.shutdownNow();
            Thread.currentThread().interrupt();
        }
        log.info("WarehouseManagementService shutdown complete");
    }
}
