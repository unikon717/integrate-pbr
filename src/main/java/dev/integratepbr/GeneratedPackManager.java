package dev.integratepbr;

import com.mojang.logging.LogUtils;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.packs.resources.Resource;
import net.minecraft.server.packs.resources.ResourceManager;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.fml.loading.FMLPaths;
import net.neoforged.fml.ModList;
import org.slf4j.Logger;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;

/** Updates one optional folder resource pack when source textures or choices change. */
public final class GeneratedPackManager {
    private static final Logger LOGGER = LogUtils.getLogger();
    private static final Object UPDATE_LOCK = new Object();
    private static final AtomicLong REQUEST_ID = new AtomicLong();
    private static final java.util.concurrent.atomic.AtomicBoolean RELOAD_NEEDED = new java.util.concurrent.atomic.AtomicBoolean();
    private static final java.util.concurrent.ExecutorService GENERATOR = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "Integrate PBR generator");
        thread.setDaemon(true);
        return thread;
    });
    private static final String PACK_NAME = "IntegratePBR_Generated";
    private static final String CACHE_NAME = ".integratepbr-cache.properties";
    private static final String FORMAT_VERSION = "22";
    private static volatile List<String> reviewEntries = List.of();
    private static final int MAX_SOURCE_BYTES = 16_000_000;
    private static final long MAX_PIXELS = 4_194_304L;

    private GeneratedPackManager() {}

    public static List<String> reviewEntries() { return reviewEntries; }

    public static void updateAndReload() {
        Minecraft minecraft = Minecraft.getInstance();
        ResourceManager resources = minecraft.getResourceManager();
        long request = REQUEST_ID.incrementAndGet();
        CompletableFuture.runAsync(() -> update(resources, false), GENERATOR)
                .thenRun(() -> {
                    if (REQUEST_ID.get() == request) minecraft.execute(minecraft::reloadResourcePacks);
                });
    }

    public static void update(ResourceManager resources) {
        update(resources, true);
    }

    private static void update(ResourceManager resources, boolean reloadIfChanged) {
        Path root = FMLPaths.GAMEDIR.get().resolve("resourcepacks").resolve(PACK_NAME).toAbsolutePath().normalize();
        try {
            synchronized (UPDATE_LOCK) {
                if (updateChecked(resources, root) && reloadIfChanged) RELOAD_NEEDED.set(true);
            }
        } catch (Exception error) {
            LOGGER.error("Could not update generated PBR resource pack at {}", root, error);
        }
    }

    public static void onClientTick(ClientTickEvent.Post event) {
        if (!RELOAD_NEEDED.getAndSet(false)) return;
        Minecraft minecraft = Minecraft.getInstance();
        if (minecraft.options.resourcePacks.contains("file/" + PACK_NAME)) {
            LOGGER.info("Reloading resources to activate newly generated PBR maps");
            minecraft.reloadResourcePacks();
        }
    }

    private static boolean updateChecked(ResourceManager resources, Path root) throws IOException {
        Path marker = root.resolve(CACHE_NAME);
        if (Files.exists(root) && !Files.isRegularFile(marker)) {
            throw new IOException("Refusing to modify an existing pack without our ownership marker: " + root);
        }
        Files.createDirectories(root);
        Properties cache = new Properties();
        if (Files.isRegularFile(marker)) {
            try (var input = Files.newInputStream(marker)) { cache.load(input); }
            if (!"IntegratePBR".equals(cache.getProperty("generator"))) {
                throw new IOException("Invalid generated pack ownership marker: " + marker);
            }
        }
        boolean fresh = !Files.isRegularFile(marker);
        if (fresh) {
            cache.setProperty("generator", "IntegratePBR");
            saveCache(cache, marker);
        }
        Properties original = new Properties();
        original.putAll(cache);
        if (!Files.isRegularFile(root.resolve("pack.mcmeta"))) Files.writeString(root.resolve("pack.mcmeta"),
                "{\"pack\":{\"pack_format\":34,\"description\":\"Integrate PBR - generated labPBR maps\"}}\n",
                StandardCharsets.UTF_8);
        MaterialOverrides overrides = new MaterialOverrides(
                FMLPaths.CONFIGDIR.get().resolve("integratepbr-overrides.properties"));
        ModelTextureIndex.ScanResult scan = ModelTextureIndex.scan(resources);
        Map<ResourceLocation, Set<ModelTextureIndex.Owner>> textures = scan.textures();
        Files.writeString(root.resolve("COVERAGE.txt"), scan.coverage(), StandardCharsets.UTF_8);
        List<String> registeredNames = java.util.stream.Stream.concat(
                        BuiltInRegistries.ITEM.keySet().stream(), BuiltInRegistries.BLOCK.keySet().stream())
                .filter(id -> !id.getNamespace().equals("minecraft")
                        && !id.getNamespace().equals(IntegratePbr.MOD_ID)
                        && ModList.get().isLoaded(id.getNamespace()))
                .map(ResourceLocation::toString).distinct().toList();
        MaterialLexicon lexicon = MaterialLexicon.learn(registeredNames);
        Set<String> currentKeys = new HashSet<>();
        int updated = 0, reused = 0, skipped = 0;

        for (var entry : textures.entrySet()) {
            ResourceLocation base = entry.getKey();
            String key = "texture." + base;
            String reviewKey = "review." + base;
            currentKeys.add(key);
            var selected = chooseMaterial(entry.getValue(), overrides);
            String name = classificationName(base, entry.getValue());
            String metalHint = lexicon.matchingMetalTerm(base.getNamespace(), name);
            String woodHint = lexicon.matchingWoodTerm(base.getNamespace(), name);
            String stoneHint = lexicon.matchingStoneTerm(base.getNamespace(), name);
            boolean weaponHint = WeaponSignals.durableAttacker(entry.getValue());
            Path albedo = output(root, base);
            Path normal = output(root, companion(base, "_n"));
            Path specular = output(root, companion(base, "_s"));
            if (selected.disabled()) {
                deleteMap(albedo);
                deleteMap(normal);
                deleteMap(specular);
                cache.remove(key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            boolean needNormal = !hasExternalMap(resources, companion(base, "_n"));
            boolean needSpecular = !hasExternalMap(resources, companion(base, "_s"));
            if (!needNormal) deleteMap(normal);
            if (!needSpecular) deleteMap(specular);
            if (!needNormal && !needSpecular) {
                deleteMap(albedo);
                cache.remove(key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            var resource = sourceResource(resources, base);
            if (resource.isEmpty()) {
                discard(albedo, normal, specular, cache, key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            byte[] bytes;
            try (var input = resource.get().open()) {
                bytes = input.readNBytes(MAX_SOURCE_BYTES + 1);
            } catch (IOException error) {
                LOGGER.warn("Cannot read source texture {}; skipping it", base, error);
                discard(albedo, normal, specular, cache, key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            if (bytes.length > MAX_SOURCE_BYTES || !validPngSize(bytes)) {
                discard(albedo, normal, specular, cache, key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            byte[] metadata = null;
            var metadataResource = resources.getResource(ResourceLocation.fromNamespaceAndPath(
                    base.getNamespace(), base.getPath() + ".mcmeta"));
            if (metadataResource.isPresent()) {
                try (var input = metadataResource.get().open()) {
                    metadata = input.readNBytes(65_537);
                } catch (IOException error) {
                    LOGGER.warn("Cannot read texture metadata {}; skipping it", base, error);
                    discard(albedo, normal, specular, cache, key);
                    cache.remove(reviewKey);
                    skipped++;
                    continue;
                }
                if (metadata.length > 65_536) {
                    discard(albedo, normal, specular, cache, key);
                    cache.remove(reviewKey);
                    skipped++;
                    continue;
                }
            }
            int pngWidth = java.nio.ByteBuffer.wrap(bytes, 16, 4).getInt();
            int pngHeight = java.nio.ByteBuffer.wrap(bytes, 20, 4).getInt();
            boolean enhanceCandidate = metadata == null && needNormal && needSpecular
                    && SurfaceEnhancer.candidate(name, pngWidth, pngHeight,
                    base.getPath().startsWith("textures/block/"));
            if (!enhanceCandidate) deleteMap(albedo);
            String stamp = fingerprint(bytes, metadata, selected.material(), needNormal, needSpecular,
                    name, metalHint, woodHint, stoneHint, weaponHint);
            String cached = cache.getProperty(key);
            boolean cachedEnhanced = (stamp + ":enhanced").equals(cached);
            boolean cachedPlain = (stamp + ":plain").equals(cached);
            if ((cachedEnhanced || cachedPlain) && (!needNormal || Files.isRegularFile(normal))
                    && (!needSpecular || Files.isRegularFile(specular))
                    && (!cachedEnhanced || Files.isRegularFile(albedo))
                    && (metadata == null || (!needNormal || Files.isRegularFile(sidecar(normal)))
                    && (!needSpecular || Files.isRegularFile(sidecar(specular))))) {
                reused++;
                continue;
            }
            BufferedImage image;
            try {
                image = ImageIO.read(new ByteArrayInputStream(bytes));
            } catch (IOException | RuntimeException error) {
                LOGGER.warn("Cannot decode source texture {}; skipping it", base, error);
                discard(albedo, normal, specular, cache, key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            if (image == null) {
                discard(albedo, normal, specular, cache, key);
                cache.remove(reviewKey);
                skipped++;
                continue;
            }
            MaterialClassifier.Decision decision = selected.material() == null
                    ? MaterialClassifier.assess(image, name, metalHint, woodHint, stoneHint, weaponHint)
                    : new MaterialClassifier.Decision(selected.material(), null);
            MaterialType material = decision.material();
            if (decision.uncertain()) cache.setProperty(reviewKey,
                    material.name().toLowerCase(java.util.Locale.ROOT) + " | " + decision.reviewReason());
            else cache.remove(reviewKey);
            SurfaceEnhancer.Result enhanced = enhanceCandidate
                    ? SurfaceEnhancer.enhance(image, name, true) : null;
            if (enhanced == null) deleteMap(albedo);
            else writePng(enhanced.albedo(), albedo);
            BufferedImage painted = enhanced == null ? image : enhanced.albedo();
            LabPbrMaps.Pair maps = LabPbrMaps.generate(painted, material, name,
                    metadata == null && base.getPath().startsWith("textures/block/"),
                    enhanced == null ? null : enhanced.depth());
            if (needNormal) writeMap(maps.normal(), metadata, normal);
            if (needSpecular) writeMap(maps.specular(), metadata, specular);
            cache.setProperty(key, stamp + (enhanced == null ? ":plain" : ":enhanced"));
            updated++;
        }
        for (String key : Set.copyOf(cache.stringPropertyNames())) {
            if (!key.startsWith("texture.") || currentKeys.contains(key)) continue;
            try {
                ResourceLocation old = ResourceLocation.parse(key.substring("texture.".length()));
                deleteMap(output(root, old));
                deleteMap(output(root, companion(old, "_n")));
                deleteMap(output(root, companion(old, "_s")));
            } catch (RuntimeException error) { LOGGER.warn("Ignoring invalid cached texture {}", key); }
            cache.remove(key);
            cache.remove("review." + key.substring("texture.".length()));
        }
        List<String> reviews = cache.stringPropertyNames().stream()
                .filter(key -> key.startsWith("review."))
                .sorted(java.util.Comparator
                        .comparingInt((String key) -> reviewPriority(cache.getProperty(key)))
                        .thenComparing(key -> key))
                .map(key -> key.substring("review.".length()) + " | " + cache.getProperty(key))
                .toList();
        reviewEntries = reviews;
        Path report = root.resolve("REVIEW.txt");
        String reportText = "Integrate PBR uncertain classifications (" + reviews.size() + ")\n"
                + "These are automatic estimates, not confirmed materials.\n"
                + "Use /integratepbr review in game or set held/block type or disable.\n\n"
                + String.join("\n", reviews) + "\n";
        if (!Files.isRegularFile(report) || !Files.readString(report).equals(reportText))
            Files.writeString(report, reportText, StandardCharsets.UTF_8);
        cache.setProperty("generator", "IntegratePBR");
        cache.setProperty("version", FORMAT_VERSION);
        boolean changed = updated > 0 || !cache.equals(original);
        if (changed) saveCache(cache, marker);
        LOGGER.info("Integrate PBR pack: {} updated, {} reused, {} skipped; {} referenced textures, {} to review",
                updated, reused, skipped, textures.size(), reviews.size());
        return changed;
    }

    private record Selection(boolean disabled, MaterialType material) {}

    private static int reviewPriority(String result) {
        if (result.contains("equipment")) return 0;
        if (result.contains("material inferred")) return 1;
        return 2;
    }

    private static Selection chooseMaterial(Set<ModelTextureIndex.Owner> owners, MaterialOverrides overrides) {
        MaterialType chosen = null;
        for (var owner : owners) {
            MaterialOverrides.Choice choice = overrides.get(owner.kind(), owner.id());
            if (choice == null) continue;
            if (choice.disabled()) return new Selection(true, null);
            if (chosen != null && chosen != choice.material()) return new Selection(true, null);
            chosen = choice.material();
        }
        return new Selection(false, chosen);
    }

    private static String classificationName(ResourceLocation texture, Set<ModelTextureIndex.Owner> owners) {
        StringBuilder result = new StringBuilder(texture.getPath());
        owners.stream().map(owner -> owner.id().toString()).sorted()
                .forEach(id -> result.append('_').append(id));
        return result.toString();
    }

    private static boolean hasExternalMap(ResourceManager resources, ResourceLocation id) {
        return resources.getResourceStack(id).stream()
                .anyMatch(resource -> !resource.sourcePackId().contains(PACK_NAME));
    }

    private static Optional<Resource> sourceResource(ResourceManager resources, ResourceLocation id) {
        var stack = resources.getResourceStack(id);
        if (stack.isEmpty()) return Optional.empty();
        var top = resources.getResource(id);
        boolean firstIsTop = top.isPresent()
                && stack.get(0).sourcePackId().equals(top.get().sourcePackId());
        if (firstIsTop) {
            for (Resource resource : stack) if (!resource.sourcePackId().contains(PACK_NAME))
                return Optional.of(resource);
        } else {
            for (int i = stack.size() - 1; i >= 0; i--) {
                Resource resource = stack.get(i);
                if (!resource.sourcePackId().contains(PACK_NAME)) return Optional.of(resource);
            }
        }
        return Optional.empty();
    }

    private static void discard(Path albedo, Path normal, Path specular, Properties cache, String key) throws IOException {
        deleteMap(albedo);
        deleteMap(normal);
        deleteMap(specular);
        cache.remove(key);
    }

    private static Path sidecar(Path png) { return png.resolveSibling(png.getFileName() + ".mcmeta"); }

    private static void deleteMap(Path png) throws IOException {
        Files.deleteIfExists(png);
        Files.deleteIfExists(sidecar(png));
    }

    private static ResourceLocation companion(ResourceLocation base, String suffix) {
        String path = base.getPath();
        return ResourceLocation.fromNamespaceAndPath(base.getNamespace(),
                path.substring(0, path.length() - 4) + suffix + ".png");
    }

    private static Path output(Path root, ResourceLocation location) throws IOException {
        Path result = root.resolve("assets").resolve(location.getNamespace()).resolve(location.getPath()).normalize();
        if (!result.startsWith(root)) throw new IOException("Invalid resource path: " + location);
        return result;
    }

    private static boolean validPngSize(byte[] bytes) {
        if (bytes.length < 24 || bytes[0] != (byte) 137 || bytes[1] != 80 || bytes[2] != 78 || bytes[3] != 71) return false;
        int width = java.nio.ByteBuffer.wrap(bytes, 16, 4).getInt();
        int height = java.nio.ByteBuffer.wrap(bytes, 20, 4).getInt();
        return width > 0 && height > 0 && (long) width * height <= MAX_PIXELS;
    }

    private static String fingerprint(byte[] bytes, byte[] metadata, MaterialType material, boolean normal, boolean specular,
                                      String classificationName, String metalHint, String woodHint, String stoneHint,
                                      boolean weaponHint) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(FORMAT_VERSION.getBytes(StandardCharsets.UTF_8));
            digest.update((byte) (normal ? 1 : 0));
            digest.update((byte) (specular ? 1 : 0));
            digest.update((material == null ? "auto" : material.name()).getBytes(StandardCharsets.UTF_8));
            digest.update(classificationName.getBytes(StandardCharsets.UTF_8));
            digest.update((metalHint == null ? "" : metalHint).getBytes(StandardCharsets.UTF_8));
            digest.update((woodHint == null ? "" : woodHint).getBytes(StandardCharsets.UTF_8));
            digest.update((stoneHint == null ? "" : stoneHint).getBytes(StandardCharsets.UTF_8));
            digest.update((byte) (weaponHint ? 1 : 0));
            digest.update(bytes);
            if (metadata != null) digest.update(metadata);
            return java.util.HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    private static void writePng(BufferedImage image, Path target) throws IOException {
        Files.createDirectories(target.getParent());
        Path temporary = Files.createTempFile(target.getParent(), "integratepbr-", ".tmp");
        try {
            if (!ImageIO.write(image, "PNG", temporary.toFile())) throw new IOException("PNG writer unavailable");
            replace(temporary, target);
        } finally { Files.deleteIfExists(temporary); }
    }

    private static void writeMap(BufferedImage image, byte[] metadata, Path target) throws IOException {
        writePng(image, target);
        if (metadata == null) {
            Files.deleteIfExists(sidecar(target));
            return;
        }
        Path companion = sidecar(target);
        Path temporary = Files.createTempFile(target.getParent(), "integratepbr-meta-", ".tmp");
        try {
            Files.write(temporary, metadata);
            replace(temporary, companion);
        } finally { Files.deleteIfExists(temporary); }
    }

    private static void saveCache(Properties cache, Path target) throws IOException {
        Path temporary = Files.createTempFile(target.getParent(), "integratepbr-cache-", ".tmp");
        try {
            try (var output = Files.newOutputStream(temporary)) { cache.store(output, "Generated pack cache"); }
            replace(temporary, target);
        } finally { Files.deleteIfExists(temporary); }
    }

    private static void replace(Path from, Path to) throws IOException {
        try { Files.move(from, to, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
        catch (java.nio.file.AtomicMoveNotSupportedException error) {
            Files.move(from, to, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
